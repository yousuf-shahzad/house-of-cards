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
    VerifiedEdge,
)
from hoc.contract.dependencies import FilingRef, Insights, JobStatus, MetricFact

log = logging.getLogger("hoc.jobs")

WORKERS = 4
"""Per-company work in flight across all jobs (matches G-AI's Gemini concurrency cap)."""
JOB_RETENTION_SECONDS = 3600
"""Finished jobs are forgotten after an hour; their per-company results stay in the disk caches."""
SUBMIT_WAIT_SECONDS = 1.5
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
                          cached=found.cached)

    def insights(self, analysis, edges, *, cache_only):
        return self.orchestrator.insights(analysis, edges, cache_only=cache_only)

    def reverse(self, company: CompanyExposure, *, cache_only: bool) -> Extraction:
        """Who names this company: other filers' latest 10-K/20-F (at most reverse_limit), kept only when the edge's target
        resolves to this very company. Uses the company's display name; its own CIK is excluded."""
        if self.reverse_limit <= 0:
            return Extraction(edges=[])
        own_cik = company.company_key.removeprefix("CIK:") if company.company_key.startswith("CIK:") else None
        filings = self.fetcher.names_in_other_filings(company.company_name, exclude_cik=own_cik,
                                                      limit=self.reverse_limit)
        found = self.extractor.extract_reverse(company, filings, cache_only=cache_only,
                                               top_n_company_keys={company.company_key},
                                               resolve_target_key=self.resolver_for([company]))
        return Extraction(edges=list(found.edges), rejected=found.rejected, cached=found.cached)

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
    """sha256 of the top-N company keys, allocations, prompt version and top_n: the same click twice is
    the same job (no double spend). Filing accessions are resolved inside the job; the per-company
    extraction caches key on them, so a new filing still re-extracts."""
    payload = {
        "companies": [c.company_key for c in companies],
        "allocations": sorted((h.ticker, round(h.allocation, 10)) for h in request.holdings),
        "prompt_version": prompt_version,
        "top_n": request.top_n,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _resolve_and_flag(analysis: AnalysisResponse, edges: list[VerifiedEdge],
                      resolve: Callable[[str], str | None] | None = None) -> list[VerifiedEdge]:
    """Against this job's own portfolio (extractions are cached across portfolios): fill a missing company
    target_key with the deterministic resolver, then set source/target_in_portfolio. The LLM never picks a key."""
    keys = {c.company_key for c in analysis.exposures}
    flagged = []
    for edge in edges:
        target_key = edge.target_key
        if target_key is None and resolve is not None and edge.target_kind == "company":
            target_key = resolve(edge.target_name)
        flagged.append(edge.model_copy(update={
            "target_key": target_key,
            "source_in_portfolio": edge.source_company_key in keys,
            "target_in_portfolio": target_key is not None and target_key in keys,
        }))
    return flagged


@dataclass
class _Job:
    job_id: str
    request: DependencyRequest
    analysis: AnalysisResponse
    top: list[CompanyExposure]
    companies: list[CompanyRunStatus]
    cache_only: bool
    status: JobStatus = "queued"
    result: DependencyResult | None = None
    error: ErrorBody | None = None
    finished_at: float | None = None
    future: Future | None = field(default=None, repr=False)


class DependencyJobs:
    def __init__(self, analyse: Callable[[PortfolioRequest], AnalysisResponse], pipeline: DependencyPipeline, *,
                 runner: Executor | None = None, workers: Executor | None = None) -> None:
        self._analyse = analyse
        self.pipeline = pipeline
        self._runner = runner or ThreadPoolExecutor(2, thread_name_prefix="hoc-deps-job")
        self._workers = workers or ThreadPoolExecutor(WORKERS, thread_name_prefix="hoc-deps")
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
            )

    # ---------- internals ----------

    @staticmethod
    def _replace(job: _Job, cache_only: bool) -> bool:
        """Rerun a failed job, and let a real click upgrade a finished cache-only (warm-up) replay that
        missed some companies."""
        if job.status == "error":
            return True
        return (job.cache_only and not cache_only and job.status == "done"
                and any(c.status not in ("cached", "done") for c in job.companies))

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

    def _set_company(self, job: _Job, index: int, **changes) -> None:
        with self._lock:
            job.companies[index] = job.companies[index].model_copy(update=changes)

    def _run(self, job: _Job) -> None:
        self._set(job, status="running")
        try:
            started = time.monotonic()
            forwards = [f.result() for f in [self._workers.submit(self._forward, job, i, c)
                                             for i, c in enumerate(job.top)]]
            reverses = [f.result() for f in [self._workers.submit(self._reverse, job, i, c, started)
                                             for i, c in enumerate(job.top)]]
            extractions = [self._finish(job, i, fwd, rev)
                           for i, (fwd, rev) in enumerate(zip(forwards, reverses, strict=True))]
            resolver_for = getattr(self.pipeline, "resolver_for", None)
            edges = _resolve_and_flag(job.analysis,
                                      list({e.edge_id: e for x in extractions if x for e in x.edges}.values()),
                                      resolver_for(job.analysis.exposures) if resolver_for else None)
            metrics, insights = self.pipeline.insights(job.analysis, edges, cache_only=job.cache_only)
            with self._lock:
                companies = list(job.companies)
            analysed = sum(c.status in ("cached", "done") for c in companies)
            result = DependencyResult(
                as_of_date=job.analysis.as_of_date, request=job.request, companies=companies, edges=edges, metrics=metrics, insights=insights,
                counts=DependencyCounts(
                    companies_requested=len(companies), companies_analysed=analysed,
                    companies_skipped=len(companies) - analysed, verified_edges=len(edges),
                    rejected_edges=sum(c.rejected_edges for c in companies),
                    unresolved_counterparties=len({e.target_name.casefold() for e in edges
                                                   if e.target_key is None and e.target_kind == "company"}),
                ),
            )
            self._set(job, status="done", result=result)
        except Exception as exc:  # the job fails visibly (status error), never the server
            log.exception("dependency job %s failed", job.job_id)
            self._set(job, status="error", error=ErrorBody(
                code="INTERNAL_ERROR", message="Dependency analysis failed", details={"type": type(exc).__name__}))

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
        if time.monotonic() - started > REVERSE_BUDGET_SECONDS:
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
        if forward is None and reverse and reverse.edges:
            message = f"{message or ''} {len(reverse.edges)} link(s) found in other companies' filings.".strip()
        if note:
            message = f"{message or ''} {note}".strip()
        self._set_company(job, index, status=status, message=message, verified_edges=len(edges),
                          rejected_edges=rejected, extraction_quality=forward.quality if forward else None)
        if forward is None and not edges:
            return None
        return Extraction(edges=edges, rejected=rejected, quality=forward.quality if forward else None,
                          cached=bool(forward and forward.cached))
