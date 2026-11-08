"""v2 dependency jobs: job table, bounded executors and the pipeline seam. Owner: I-API (Bekarys's Claude).

POST /api/dependencies -> DependencyJobs.submit; GET /api/dependencies/{job_id} -> DependencyJobs.get.
Request threads only submit work and read snapshots. The work runs on two small pools (job runners, and
per-company workers capped at WORKERS), so a cold run of ~15 Gemini calls plus an orchestrator call never
ties up the server's request threads. A job makes at most one extraction per company plus one insights call.

The pipeline (G-DOC filing fetch, G-AI extraction, G-ORCH metrics + insights) is reached only through
DependencyPipeline, so it can be swapped for a fake in tests. Until those packages land the service uses
NotWiredPipeline, which reports every company honestly instead of failing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Literal, Protocol

from hoc.contract import (
    AnalysisResponse,
    CompanyExposure,
    CompanyRunStatus,
    CompanyUnavailable,
    DependencyCounts,
    DependencyJob,
    DependencyRequest,
    DependencyResult,
    ErrorBody,
    JobNotFoundError,
    PortfolioRequest,
    PortfolioValidationError,
    ResearchFinding,
    ResearchJob,
    ResearchNotFoundError,
    ResearchRequest,
    SourceError,
    VerifiedEdge,
)
from hoc.contract.dependencies import FilingRef, Insights, JobStatus, MetricFact
from hoc.research.loop import RESEARCH_DEPTH_PRESETS

log = logging.getLogger("hoc.jobs")

WORKERS = 4
"""Per-company work in flight across all jobs (matches G-AI's Gemini concurrency cap)."""
RESEARCH_WORKERS = 8
"""Per-company research agents in flight across all jobs (FIX-22)."""
JOB_RETENTION_SECONDS = 3600
"""Finished jobs are forgotten after an hour; their per-company results stay in the disk caches."""
SUBMIT_WAIT_SECONDS = 1.5
RESEARCH_BUDGET_SECONDS = {"light": 50.0, "thorough": 95.0}
"""v3.1 A2: a company's research agent not started this long after reading ended is skipped (it says so).
Reading (fetch + extract + reverse links) is never cut; an agent that has started finishes its own steps."""
RESEARCH_STEPS_ESTIMATE = {depth: items * steps for depth, (items, steps) in RESEARCH_DEPTH_PRESETS.items()}
"""FIX-18: agent steps reserved per company when the job starts (the depth's items x steps), so steps_total
starts at its full estimate and only ever falls; an agent reporting fewer lowers its share, never more."""
REVERSE_BUDGET_SECONDS = 100.0
"""Reverse-link steps not started this long after the job began are skipped (the company says so), so a
cold click still finishes in about 2 minutes. Forward extraction always runs first and is never cut."""
"""POST waits this long, so an all-cached run comes back finished (HTTP 200) instead of 202."""
FINISHED = frozenset({"cached", "done", "no_sec_filing", "unsupported_form", "sec_contact_missing",
                      "missing_api_key", "error"})


@dataclass(frozen=True)
class Extraction:
    edges: list[VerifiedEdge]
    """Only edges whose evidence quote Python verified against the filing."""
    rejected: int = 0
    interpretation_rejected: int = 0
    """V-INT: quotes that verified but whose meaning did not (competitor, negated...); already removed."""
    quality: Literal["sections", "fallback"] | None = None
    cached: bool = False
    """True when served from the extraction cache (no Gemini call)."""


class DependencyPipeline(Protocol):
    prompt_version: str

    def filing(self, company: CompanyExposure) -> FilingRef:
        """Latest 10-K/20-F. Raises CompanyUnavailable(no_sec_filing | unsupported_form | sec_contact_missing)."""
        ...

    def extract(self, company: CompanyExposure, filing: FilingRef, *, cache_only: bool) -> Extraction:
        """Verified edges for one filing. Raises CompanyUnavailable("missing_api_key") when it would need
        Gemini but has no key, or cache_only is set and nothing is cached."""
        ...

    def insights(self, analysis: AnalysisResponse, edges: list[VerifiedEdge], *,
                 cache_only: bool) -> tuple[list[MetricFact], Insights]:
        """Python metrics + orchestrator insights. Reports metrics_only / no_verified_edges / missing_api_key
        through Insights.status; never raises for those."""
        ...

    # Optional: resolver_for(portfolio: Sequence[CompanyExposure]) -> Callable[[str], str | None], the
    # deterministic name -> company_key resolver for one job's portfolio (G-DOC). Without it keys stay None.
    # Optional (v3.1 A2): research_company(company, filing: FilingRef, edges, *, depth, cache_only, progress, analysis)
    # -> object with .findings (ResearchFinding), .edges (the company's final set: kept + revised + new, all verified),
    # .rejected_edge_ids, .cached. Raises CompanyUnavailable('missing_api_key') when it would need Gemini.
    # Optional: reverse(company, *, cache_only) -> Extraction, verified edges from OTHER filers' documents
    # whose target resolves to this company (EDGAR full-text search + G-AI extract_reverse).


class NotWiredPipeline:
    """Stand-in until G-DOC, G-AI and G-ORCH merge: every company is reported, nothing is invented."""

    prompt_version = "not-wired"
    MESSAGE = "Dependency analysis is not wired in yet (waiting for the filings, extractor and orchestrator)."

    def filing(self, company: CompanyExposure) -> FilingRef:
        raise CompanyUnavailable("error", self.MESSAGE)

    def extract(self, company, filing, *, cache_only):
        raise CompanyUnavailable("error", self.MESSAGE)

    def insights(self, analysis, edges, *, cache_only):
        return [], Insights(status="no_verified_edges")


class LivePipeline:
    """The real pipeline: G-DOC filing fetch -> G-AI extraction (Gemini Flash) -> G-ORCH metrics + insights.

    One instance per service, so the fetcher's per-accession memo and the extraction/orchestrator disk caches
    are shared by every job."""

    def __init__(self, fetcher, extractor, orchestrator, *, resolve_target_key=None,
                 reverse_limit: int = 3) -> None:
        self.fetcher = fetcher
        self.extractor = extractor
        self.orchestrator = orchestrator
        self.resolve_target_key = resolve_target_key
        self.reverse_limit = reverse_limit
        self._titles_by_cik: dict[str, str] | None = None
        self.researcher = None
        """v3.1 A2: the research runner (hoc.research.ResearchLoop); its research_company is A1's per-company agent."""
        """Other filers' documents searched per company (HOC_DEPS_REVERSE_LIMIT; 0 = reverse links off)."""
        self.prompt_version = f"{extractor.prompt_version}+{orchestrator.prompt_version}"
        self._filings: dict[str, object] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, http, settings) -> LivePipeline:
        from hoc.ai import DependencyExtractor, ExtractionCache, GeminiClient
        from hoc.core.cache import DiskCache
        from hoc.filings.fetch import FilingFetcher
        from hoc.graph import DependencyOrchestrator

        extractor = DependencyExtractor(GeminiClient(http, settings), ExtractionCache(DiskCache(settings.cache_dir)))
        return cls(FilingFetcher(http, settings), extractor, DependencyOrchestrator(http=http, settings=settings),
                   reverse_limit=settings.deps_reverse_limit)

    def filing(self, company: CompanyExposure) -> FilingRef:
        filing = self.fetcher.for_company(company)  # raises FilingUnavailable, a CompanyUnavailable
        with self._lock:
            self._filings[filing.accession] = filing
        return FilingRef(company_key=company.company_key, form=filing.form, accession=filing.accession,
                         filed=filing.filed, url=filing.url)

    def extract(self, company: CompanyExposure, filing: FilingRef, *, cache_only: bool) -> Extraction:
        with self._lock:
            document = self._filings.get(filing.accession)
        found = self.extractor.extract(company, document or filing, cache_only=cache_only,
                                       resolve_target_key=self.resolve_target_key)
        return Extraction(edges=list(found.edges), rejected=found.rejected, quality=found.quality,
                          cached=found.cached,
                          interpretation_rejected=getattr(found, "interpretation_rejected", 0))

    def insights(self, analysis, edges, *, cache_only):
        return self.orchestrator.insights(analysis, edges, cache_only=cache_only)

    def reverse(self, company: CompanyExposure, *, cache_only: bool) -> Extraction:
        """Who names this company: other filers' latest 10-K/20-F (at most reverse_limit), kept only when the edge's target
        resolves to this very company. Uses the company's display name; its own CIK is excluded."""
        if self.reverse_limit <= 0:
            return Extraction(edges=[])
        own_cik = company.company_key.removeprefix("CIK:") if company.company_key.startswith("CIK:") else None
        filings = self.fetcher.names_in_other_filings(search_name(company.company_name), exclude_cik=own_cik,
                                                      limit=self.reverse_limit)
        titles = self._filer_titles()
        hits = []
        for filing in filings:
            cik = str(filing.cik).zfill(10)
            hits.append((f"CIK:{cik}", titles.get(cik) or f"CIK:{cik}", filing))  # job swaps in portfolio names
        found = self.extractor.extract_reverse(company, hits, cache_only=cache_only,
                                               top_n_company_keys={company.company_key},
                                               resolve_target_key=self.resolver_for([company]))
        return Extraction(edges=list(found.edges), rejected=found.rejected, cached=found.cached,
                          interpretation_rejected=getattr(found, "interpretation_rejected", 0))

    def _filer_titles(self) -> dict[str, str]:
        """10-digit CIK -> SEC company title (one cached SEC request per process); {} if unavailable."""
        with self._lock:
            if self._titles_by_cik is None:
                try:
                    titles = self.fetcher.sec_titles()
                except (CompanyUnavailable, SourceError, ValueError):  # cosmetic: fall back to the CIK
                    log.warning("SEC titles unavailable; reverse-link filers show their CIK")
                    titles = {}
                self._titles_by_cik = {}
                for title, cik in titles.items():
                    self._titles_by_cik.setdefault(cik, title)
            return self._titles_by_cik

    @property
    def research_company(self):
        """A1's per-company agent wired to this job's resolver, or None while the runner has no such entry point
        (the job then skips the research phase exactly as in v3)."""
        agent = getattr(self.researcher, "research_company", None)
        if agent is None:
            return None

        def run(company, filing, edges, *, depth, cache_only, progress, analysis):
            return agent(company, filing, edges, depth=depth, cache_only=cache_only, progress=progress,
                         analysis=analysis, resolve_target_key=self.resolver_for(analysis.exposures))

        return run

    def resolver_for(self, portfolio: Sequence[CompanyExposure]) -> Callable[[str], str | None]:
        """G-DOC's deterministic name -> company_key resolver for one job's portfolio (exact match only)."""
        from hoc.filings.names import NameResolver
        from hoc.identity.resolver import load_aliases

        return NameResolver(portfolio, load_aliases()).resolve


class InlineExecutor(Executor):
    """Runs each task immediately in the caller's thread: deterministic jobs for tests."""

    def submit(self, fn, /, *args, **kwargs):
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001 (handed to the caller through the future, like a real executor)
            future.set_exception(exc)
        return future


def job_id_for(request: DependencyRequest, companies: Sequence[CompanyExposure], prompt_version: str) -> str:
    """sha256 of the top-N company keys, allocations, prompt version, top_n and depth: the same click twice is
    the same job (no double spend). Filing accessions are resolved inside the job; the per-company
    extraction caches key on them, so a new filing still re-extracts."""
    payload = {
        "companies": [c.company_key for c in companies],
        "allocations": sorted((h.ticker, round(h.allocation, 10)) for h in request.holdings),
        "prompt_version": prompt_version,
        "top_n": request.top_n,
        "depth": request.depth,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def search_name(name: str) -> str:
    """The phrase to search other filings for: the display name without trailing legal forms, original wording
    kept ('Taiwan Semiconductor Manufacturing Co., Ltd.' -> 'Taiwan Semiconductor Manufacturing', 'AT&T Inc.' ->
    'AT&T'). Annual reports rarely repeat the suffix, so the exact phrase with it finds almost nothing."""
    from hoc.filings.names import LEGAL_FORMS
    from hoc.identity.resolver import clean_company_name

    words = clean_company_name(name).split()
    while len(words) > 1 and words[-1].strip(".,").casefold() in LEGAL_FORMS:
        words.pop()
    return " ".join(words).rstrip(",") or name


def _resolve_and_flag(analysis: AnalysisResponse, edges: list[VerifiedEdge],
                      resolve: Callable[[str], str | None] | None = None) -> list[VerifiedEdge]:
    """Against this job's own portfolio (extractions are cached across portfolios): fill a missing company
    target_key with the deterministic resolver, then set source/target_in_portfolio. The LLM never picks a key."""
    names = {c.company_key: c.company_name for c in analysis.exposures}
    keys = set(names)
    flagged = []
    for edge in edges:
        target_key = edge.target_key
        if target_key is None and resolve is not None and edge.target_kind == "company":
            target_key = resolve(edge.target_name)
        flagged.append(edge.model_copy(update={
            "target_key": target_key,
            "source_company_name": names.get(edge.source_company_key, edge.source_company_name),
            "source_in_portfolio": edge.source_company_key in keys,
            "target_in_portfolio": target_key is not None and target_key in keys,
        }))
    return flagged


def _with_importance(edges: list[VerifiedEdge]) -> list[VerifiedEdge]:
    """R-IMP: every edge in the result carries its deterministic importance (score, tier, reasons), capped at
    medium when V-INT flagged it. A scoring bug leaves importance None (metrics still score on the fly)."""
    from hoc.graph import attach_edge_importance

    try:
        return attach_edge_importance(edges)
    except Exception:
        log.exception("importance scoring failed; edges keep importance=None")
        return edges


def _coverage(analysis: AnalysisResponse, companies: list[CompanyRunStatus], edges: list[VerifiedEdge]):
    """C-COV: what share of the portfolio the run actually covers. Optional: a failure leaves it None, never
    the job."""
    from hoc.graph import compute_coverage_report

    try:
        return compute_coverage_report(analysis, companies, edges, as_of_date=analysis.as_of_date)
    except Exception:
        log.exception("coverage report failed; result.coverage stays None")
        return None


@dataclass
class _Job:
    job_id: str
    request: DependencyRequest
    analysis: AnalysisResponse
    top: list[CompanyExposure]
    companies: list[CompanyRunStatus]
    cache_only: bool
    status: JobStatus = "queued"
    phase: str = "queued"
    steps: dict[str, tuple[int, int]] = field(default_factory=dict)
    """v3.1 progress parts: 'read' (companies read, of N), 'research:<key>' (agent steps), 'synth' (0/1 or 1/1)."""
    research: list[ResearchFinding] = field(default_factory=list)
    """FIX-11: each company's findings, added as soon as its agent finishes (shown while the job runs)."""
    result: DependencyResult | None = None
    error: ErrorBody | None = None
    finished_at: float | None = None
    future: Future | None = field(default=None, repr=False)


class DependencyJobs:
    def __init__(self, analyse: Callable[[PortfolioRequest], AnalysisResponse], pipeline: DependencyPipeline, *,
                 runner: Executor | None = None, workers: Executor | None = None,
                 research_workers: Executor | None = None) -> None:
        self._analyse = analyse
        self.pipeline = pipeline
        self._runner = runner or ThreadPoolExecutor(2, thread_name_prefix="hoc-deps-job")
        self._workers = workers or ThreadPoolExecutor(WORKERS, thread_name_prefix="hoc-deps")
        self._research_workers = research_workers or workers or ThreadPoolExecutor(
            RESEARCH_WORKERS, thread_name_prefix="hoc-deps-research"
        )
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()

    # ---------- public ----------

    def submit(self, request: DependencyRequest, *, cache_only: bool = False,
               wait: float = SUBMIT_WAIT_SECONDS) -> DependencyJob:
        """Start (or reuse) the job for this request. Raises the analysis errors (422/503) unchanged."""
        analysis = self._analyse(PortfolioRequest(holdings=request.holdings))
        top = [c for c in analysis.exposures if c.exposure > 0][: request.top_n]
        job_id = job_id_for(request, top, self.pipeline.prompt_version)
        with self._lock:
            self._evict()
            job = self._jobs.get(job_id)
            start = job is None or self._replace(job, cache_only)
            if not start and job.cache_only and not cache_only and job.status in ("queued", "running"):
                job.cache_only = False  # a real click joined the warm-up replay: finish it live
            if start:
                job = _Job(job_id=job_id, request=request, analysis=analysis, top=top, cache_only=cache_only,
                           companies=[CompanyRunStatus(company_key=c.company_key, company_name=c.company_name,
                                                       exposure=c.exposure, status="queued") for c in top])
                self._jobs[job_id] = job
        if start:  # outside the lock: an inline runner executes _run right here
            job.future = self._runner.submit(self._run, job)
        future = job.future
        if wait > 0 and future is not None:
            try:
                future.result(timeout=wait)
            except FutureTimeout:
                pass
        return self.get(job_id)

    def get(self, job_id: str) -> DependencyJob:
        with self._lock:
            self._evict()
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(f"No dependency job {job_id} (unknown, or finished over an hour ago)",
                                       {"job_id": job_id})
            return DependencyJob(
                job_id=job.job_id, status=job.status, companies=list(job.companies),
                progress_done=sum(c.status in FINISHED for c in job.companies),
                progress_total=len(job.companies), result=job.result, error=job.error,
                phase=job.phase, steps_done=sum(d for d, _ in job.steps.values()),
                steps_total=sum(n for _, n in job.steps.values()), research=list(job.research),
            )

    # ---------- internals ----------

    @staticmethod
    def _replace(job: _Job, cache_only: bool) -> bool:
        """Rerun a failed job, and let a real click upgrade a finished cache-only (warm-up) replay that missed
        some companies OR has no live insights (metrics_only / missing_api_key: e.g. every company was cached
        but the orchestrator cache missed after a metrics or prompt change). Cached companies replay fast."""
        if job.status == "error":
            return True
        if not (job.cache_only and not cache_only and job.status == "done"):
            return False
        missed = any(c.status not in ("cached", "done") for c in job.companies)
        no_live_insights = job.result is not None and job.result.insights.status in ("metrics_only",
                                                                                      "missing_api_key")
        return missed or no_live_insights

    def finished(self, job_id: str) -> tuple[AnalysisResponse, DependencyResult]:
        """The analysis and result of a finished job, for the research loop. Raises JobNotFoundError (404), or
        PortfolioValidationError (422) while the job is still running or if it failed."""
        with self._lock:
            self._evict()
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(f"No dependency job {job_id} (unknown, or finished over an hour ago)",
                                       {"job_id": job_id})
            if job.status != "done" or job.result is None:
                raise PortfolioValidationError(
                    "VALIDATION_ERROR", "Research starts once Find dependencies has finished for this portfolio.",
                    {"job_id": job_id, "status": job.status})
            return job.analysis, job.result

    def _evict(self) -> None:
        cutoff = time.monotonic() - JOB_RETENTION_SECONDS
        for job_id in [j for j, job in self._jobs.items() if job.finished_at and job.finished_at < cutoff]:
            del self._jobs[job_id]

    def _set(self, job: _Job, **changes) -> None:
        with self._lock:
            for name, value in changes.items():
                setattr(job, name, value)
            if job.status in ("done", "error"):
                job.finished_at = time.monotonic()

    def _step(self, job: _Job, part: str, done: int, total: int) -> None:
        """FIX-18: the bar never goes back. A part's total only falls from its first value, and done only rises."""
        with self._lock:
            prev_done, cap = job.steps.get(part, (0, total))
            total = min(total, cap)
            job.steps[part] = (min(max(done, prev_done), total), total)

    def _set_company(self, job: _Job, index: int, **changes) -> None:
        with self._lock:
            job.companies[index] = job.companies[index].model_copy(update=changes)

    def _run(self, job: _Job) -> None:
        self._set(job, status="running", phase="reading")
        self._step(job, "read", 0, len(job.top))
        if getattr(self.pipeline, "research_company", None):  # reserve every agent's steps up front (FIX-18)
            for company in job.top:
                self._step(job, f"research:{company.company_key}", 0,
                           RESEARCH_STEPS_ESTIMATE.get(job.request.depth, 0))
        self._step(job, "synth", 0, 1)
        try:
            started = time.monotonic()
            forwards = [f.result() for f in [self._workers.submit(self._forward, job, i, c)
                                             for i, c in enumerate(job.top)]]
            reverses = [f.result() for f in [self._workers.submit(self._reverse, job, i, c, started)
                                             for i, c in enumerate(job.top)]]
            extractions = [self._finish(job, i, fwd, rev)
                           for i, (fwd, rev) in enumerate(zip(forwards, reverses, strict=True))]
            self._step(job, "read", len(job.top), len(job.top))
            extractions, findings, researched = self._research_phase(job, forwards, extractions)
            self._set(job, phase="synthesising")
            resolver_for = getattr(self.pipeline, "resolver_for", None)
            edges = _resolve_and_flag(job.analysis,
                                      list({e.edge_id: e for x in extractions if x for e in x.edges}.values()),
                                      resolver_for(job.analysis.exposures) if resolver_for else None)
            edges = _with_importance(edges)
            metrics, insights = self.pipeline.insights(job.analysis, edges, cache_only=job.cache_only)
            with self._lock:
                companies = list(job.companies)
            analysed = sum(c.status in ("cached", "done") for c in companies)
            coverage = _coverage(job.analysis, companies, edges)
            result = DependencyResult(
                as_of_date=job.analysis.as_of_date, request=job.request, companies=companies, edges=edges, metrics=metrics, insights=insights,
                counts=DependencyCounts(
                    companies_requested=len(companies), companies_analysed=analysed,
                    companies_skipped=len(companies) - analysed, verified_edges=len(edges),
                    rejected_edges=sum(c.rejected_edges for c in companies),
                    interpretation_rejected=sum(x.interpretation_rejected for x in extractions if x),
                    unresolved_counterparties=len({e.target_name.casefold() for e in edges
                                                   if e.target_key is None and e.target_kind == "company"}),
                ),
                coverage=coverage,
                research=findings,
                research_depth=job.request.depth if researched else "none",
            )
            self._step(job, "synth", 1, 1)
            self._set(job, status="done", phase="done", result=result)
        except Exception as exc:  # the job fails visibly (status error), never the server
            log.exception("dependency job %s failed", job.job_id)
            self._set(job, status="error", error=ErrorBody(
                code="INTERNAL_ERROR", message="Dependency analysis failed", details={"type": type(exc).__name__}))

    def _research_phase(self, job: _Job, forwards, extractions):
        """v3.1 A2: each company read from its own filing gets its agent (pipeline.research_company), in parallel on
        the bounded workers, within the depth's budget. Returns (extractions with each company's final edges,
        findings, whether any agent actually ran). Without the optional hook it is a no-op."""
        research = getattr(self.pipeline, "research_company", None)
        targets = [i for i, (fwd, _, _) in enumerate(forwards) if research and fwd is not None and extractions[i]]
        for i, company in enumerate(job.top):  # companies with no agent give back their reserved steps
            if i not in targets:
                self._step(job, f"research:{company.company_key}", 0, 0)
        if not targets:
            return extractions, [], False
        self._set(job, phase="researching")
        deadline = time.monotonic() + RESEARCH_BUDGET_SECONDS[job.request.depth]
        futures = {i: self._research_workers.submit(self._research, job, i, job.top[i], extractions[i], deadline)
                   for i in targets}
        findings, ran = [], False
        extractions = list(extractions)
        for i, future in futures.items():
            outcome = future.result()
            if outcome is None:
                continue
            ran = True
            company_findings, edges, rejected, misread = outcome
            findings.extend(company_findings)
            before = extractions[i]
            extractions[i] = Extraction(edges=edges, rejected=before.rejected + rejected, quality=before.quality,
                                        cached=before.cached,
                                        interpretation_rejected=before.interpretation_rejected + misread)
            with self._lock:
                current = job.companies[i]
            self._set_company(job, i, verified_edges=len(edges), rejected_edges=current.rejected_edges + rejected)
        return extractions, findings, ran

    def _research(self, job: _Job, index: int, company: CompanyExposure, extraction: Extraction, deadline: float):
        """One company's agent. Returns (findings, final edges, rejected, interpretation-rejected) or None when it
        was skipped. Never raises, and never downgrades the company: its status (done/cached) and edges stay as
        read; a skip only adds a plain note to its message and completes its share of the progress bar."""
        with self._lock:
            current = job.companies[index]
        part = f"research:{company.company_key}"
        note, found = None, None
        if time.monotonic() > deadline and not job.cache_only:
            note = "Double-check skipped: the run's time budget was used up."
        else:
            self._set_company(job, index, status="researching")
            try:
                found = self.pipeline.research_company(
                    company, current.filing, list(extraction.edges), depth=job.request.depth,
                    cache_only=job.cache_only, progress=lambda done, total: self._step(job, part, done, total),
                    analysis=job.analysis)
            except CompanyUnavailable as exc:
                log.info("research skipped for %s: %s", company.company_key, exc.message)
                note = ("Double-check skipped: no AI key." if not job.cache_only and exc.status == "missing_api_key"
                        else "Double-check skipped: not run yet for this portfolio.")
            except Exception:
                log.exception("research failed for %s", company.company_key)
                note = "Double-check skipped: it failed for this company."
        with self._lock:
            _, total = job.steps.get(part, (0, 0))
            job.steps[part] = (total, total)  # finished or skipped: its share is complete
        changes = {"status": current.status}
        if note:
            changes["message"] = f"{current.message or ''} {note}".strip()
        self._set_company(job, index, **changes)
        if found is None:
            return None
        with self._lock:  # FIX-11: visible to pollers now, not only when the whole job ends
            job.research.extend(found.findings)
        rejected = set(found.rejected_edge_ids)
        edges = [e for e in found.edges if e.edge_id not in rejected]
        return list(found.findings), edges, len(rejected), getattr(found, "interpretation_rejected", 0)

    def _forward(self, job: _Job, index: int, company: CompanyExposure):
        """The company's own filing. Returns (Extraction | None, status, message); never raises."""
        try:
            self._set_company(job, index, status="fetching")
            filing = self.pipeline.filing(company)
            self._set_company(job, index, status="extracting", filing=filing)
            forward = self.pipeline.extract(company, filing, cache_only=job.cache_only)
        except CompanyUnavailable as exc:
            return None, exc.status, exc.message
        except Exception as exc:  # one company's failure never sinks the others
            log.exception("dependency step failed for %s", company.company_key)
            return None, "error", f"Unexpected error ({type(exc).__name__})"
        return forward, "cached" if forward.cached else "done", None

    def _reverse(self, job: _Job, index: int, company: CompanyExposure, started: float):
        """Other filers naming this company (optional pipeline step), once every forward step has finished.
        Returns (Extraction | None, note | None). Its failures never change the company's status."""
        reverse = getattr(self.pipeline, "reverse", None)
        if reverse is None:
            return None, None
        # The budget caps Gemini spend on a live click; a cache-only replay spends nothing, so it always runs.
        if not job.cache_only and time.monotonic() - started > REVERSE_BUDGET_SECONDS:
            return None, "Reverse links skipped: the run's time budget was used up."
        self._set_company(job, index, status="extracting")
        try:
            return reverse(company, cache_only=job.cache_only), None
        except CompanyUnavailable as exc:
            log.info("reverse links skipped for %s: %s", company.company_key, exc.message)
        except Exception:
            log.exception("reverse links failed for %s", company.company_key)
        return None, None

    def _finish(self, job: _Job, index: int, forward_step, reverse_step) -> Extraction | None:
        """Merge both steps and set the company's final status once (so progress never runs ahead)."""
        forward, status, message = forward_step
        reverse, note = reverse_step
        edges = [*(forward.edges if forward else []), *(reverse.edges if reverse else [])]
        rejected = (forward.rejected if forward else 0) + (reverse.rejected if reverse else 0)
        misread = (forward.interpretation_rejected if forward else 0) + (reverse.interpretation_rejected if reverse else 0)
        if forward is None and reverse and reverse.edges:
            message = f"{message or ''} {len(reverse.edges)} link(s) found in other companies' filings.".strip()
        if note:
            message = f"{message or ''} {note}".strip()
        self._set_company(job, index, status=status, message=message, verified_edges=len(edges),
                          rejected_edges=rejected, extraction_quality=forward.quality if forward else None)
        if forward is None and not edges and not misread:
            return None
        return Extraction(edges=edges, rejected=rejected, quality=forward.quality if forward else None,
                          cached=bool(forward and forward.cached), interpretation_rejected=misread)


# ---------- v3 A-RES: research jobs (I-API) ----------


class ResearchRunner(Protocol):
    """A-RES (hoc.research) behind one seam. `run` investigates up to `max_items` uncertain findings of a finished
    dependency result and returns the findings plus the result with them merged in (metrics and insights
    recomputed). It reports progress through `progress(done, total, findings_so_far)`; an item that fails becomes
    an 'unresolved' finding rather than an exception."""

    prompt_version: str

    def run(self, result: DependencyResult, analysis: AnalysisResponse, *, max_items: int, cache_only: bool,
            progress: Callable[[int, int, list[ResearchFinding]], None]
            ) -> tuple[list[ResearchFinding], DependencyResult]: ...


class NotWiredResearch:
    """Until A-RES is wired in: every research job ends as an error with a clear message (never a 500)."""

    prompt_version = "not-wired"

    def run(self, result, analysis, *, max_items, cache_only, progress):
        raise RuntimeError("The research loop is not available on this server yet.")


def research_id_for(dependency_job_id: str, request: ResearchRequest, prompt_version: str) -> str:
    """Idempotent: researching the same dependency result twice joins one job (no double Gemini spend)."""
    payload = json.dumps({"job": dependency_job_id, "max_items": request.max_items, "prompt": prompt_version},
                         sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass
class _Research:
    research_id: str
    dependency_job_id: str
    status: JobStatus = "queued"
    progress_done: int = 0
    progress_total: int = 0
    findings: list[ResearchFinding] = field(default_factory=list)
    result: DependencyResult | None = None
    error: ErrorBody | None = None
    finished_at: float | None = None
    future: Future | None = field(default=None, repr=False)


class ResearchJobs:
    def __init__(self, dependency_jobs: DependencyJobs, runner: ResearchRunner, *,
                 executor: Executor | None = None) -> None:
        self.dependency_jobs = dependency_jobs
        self.runner = runner
        self._executor = executor or ThreadPoolExecutor(1, thread_name_prefix="hoc-research")
        self._jobs: dict[str, _Research] = {}
        self._lock = threading.Lock()

    def submit(self, dependency_job_id: str, request: ResearchRequest, *, cache_only: bool = False,
               wait: float = SUBMIT_WAIT_SECONDS) -> ResearchJob:
        """Start (or join) research on a finished dependency job. Raises JobNotFoundError (404) or
        PortfolioValidationError (422, the dependency job hasn't finished)."""
        analysis, result = self.dependency_jobs.finished(dependency_job_id)
        research_id = research_id_for(dependency_job_id, request, self.runner.prompt_version)
        with self._lock:
            self._evict()
            job = self._jobs.get(research_id)
            start = job is None or job.status == "error"  # a failed run may be retried
            if start:
                job = _Research(research_id=research_id, dependency_job_id=dependency_job_id)
                self._jobs[research_id] = job
        if start:  # outside the lock: an inline executor runs _run right here
            job.future = self._executor.submit(self._run, job, analysis, result, request, cache_only)
        if wait > 0 and job.future is not None:
            try:
                job.future.result(timeout=wait)
            except FutureTimeout:
                pass
        return self.get(research_id)

    def get(self, research_id: str) -> ResearchJob:
        with self._lock:
            self._evict()
            job = self._jobs.get(research_id)
            if job is None:
                raise ResearchNotFoundError(f"No research job {research_id} (unknown, or finished over an hour ago)",
                                            {"research_id": research_id})
            return ResearchJob(research_id=job.research_id, dependency_job_id=job.dependency_job_id,
                               status=job.status, progress_done=job.progress_done,
                               progress_total=job.progress_total, findings=list(job.findings),
                               result=job.result, error=job.error)

    def _run(self, job: _Research, analysis: AnalysisResponse, result: DependencyResult,
             request: ResearchRequest, cache_only: bool) -> None:
        def progress(done: int, total: int, findings: list[ResearchFinding]) -> None:
            with self._lock:
                job.progress_done, job.progress_total, job.findings = done, total, list(findings)

        with self._lock:
            job.status = "running"
        try:
            findings, merged = self.runner.run(result, analysis, max_items=request.max_items,
                                               cache_only=cache_only, progress=progress)
            with self._lock:
                job.findings, job.result, job.status = list(findings), merged, "done"
                job.progress_done = job.progress_total = max(job.progress_total, len(findings))
        except Exception as exc:  # the research job fails visibly (status error), never the server
            log.exception("research job %s failed", job.research_id)
            with self._lock:
                job.status = "error"
                job.error = ErrorBody(code="INTERNAL_ERROR", message=str(exc) or "Research failed",
                                      details={"type": type(exc).__name__})
        finally:
            with self._lock:
                job.finished_at = time.monotonic()

    def _evict(self) -> None:
        cutoff = time.monotonic() - JOB_RETENTION_SECONDS
        for research_id in [r for r, job in self._jobs.items() if job.finished_at and job.finished_at < cutoff]:
            del self._jobs[research_id]
