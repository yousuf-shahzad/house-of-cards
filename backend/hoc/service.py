"""Wires sources -> normalisation -> maths. Owner: package f (Bekarys's Claude). Signatures fixed by W0-B.

EtfService keeps an in-memory memo of EtfHoldings per (ticker, source), so changing allocations
never refetches; fetch several ETFs in parallel (a small thread pool). The API layer only calls
these methods.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from hoc import __version__
from hoc.contract import (
    AnalysisResponse,
    ChangeIdeasRequest,
    ChangeIdeasResponse,
    CompareRequest,
    CompareResponse,
    DependencyJob,
    DependencyRequest,
    EtfFailure,
    EtfHoldings,
    EtfNotFoundError,
    EtfSummary,
    ExampleEtf,
    ExamplePortfolio,
    ExamplesResponse,
    HealthResponse,
    PortfolioRequest,
    PriceQuote,
    ResearchJob,
    ResearchRequest,
    ShockBasis,
    ShockSpec,
    SourceError,
    SourceName,
    SourcesUnavailableError,
    StressRequest,
    StressResponse,
    TickerNotFound,
    UnknownTickerError,
    ValuationRequest,
    ValuationResponse,
    VerifiedEdge,
)
from hoc.contract.stress import DEFAULT_SHOCK_DROP
from hoc.examples import EXAMPLES
from hoc.history import HistoricalShocks, YahooHistory, historical_shock, simulated_basis
from hoc.jobs import (
    SUBMIT_WAIT_SECONDS,
    DependencyJobs,
    LivePipeline,
    NotWiredPipeline,
    NotWiredResearch,
    ResearchJobs,
)
from hoc.normalise.pipeline import normalise_etf
from hoc.portfolio.analyse import analyse
from hoc.portfolio.compare import compare_portfolios, read_cached_extractions
from hoc.portfolio.ideas import (
    IDEA_TICKERS,
    baseline_idea_metrics,
    build_idea_scenarios,
    build_proposal_scenarios,
    rank_change_ideas,
    verify_change_ideas,
)
from hoc.portfolio.stress import simulate_failure
from hoc.portfolio.validation import validate_request
from hoc.portfolio.valuation import value_portfolio

MAX_WORKERS = 8
MEMO_TTL_SECONDS = 24 * 3600
"""How long a loaded ETF is reused in memory: the source TTL, so a long-running API picks up new disclosures."""
log = logging.getLogger("hoc.service")
IDEAS_WAIT_SECONDS = 9.0
IDEAS_TTL_SECONDS = 60.0
IDEAS_MAX_KEYS = 32
IDEAS_AI_TIMEOUT_SECONDS = 90.0

@dataclass
class _IdeaContext:
    baseline: AnalysisResponse
    loaded: dict[str, EtfHoldings]
    cached: dict[str, list[VerifiedEdge]]


def _clock() -> float:
    return time.monotonic()


def _attempts(failures: Sequence[EtfFailure]) -> dict[str, list[dict]]:
    return {f.etf_ticker: [a.model_dump(mode="json") for a in f.attempts] for f in failures}


class EtfService:
    def __init__(self, registry, reference, aliases, settings) -> None:
        self.registry = registry
        self.reference = reference
        self.aliases = aliases
        self.settings = settings
        self._memo: dict[tuple[str, str | None], tuple[float, EtfHoldings]] = {}
        """(loaded at, holdings); reused for MEMO_TTL_SECONDS, then reloaded through the cached HTTP layer."""
        self._locks: dict[tuple[str, str | None], threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self.quotes = None
        """Cheap price source with quote(ticker) -> PriceQuote | None (TickerInside, from its cached fund file)."""
        self.dependency_pipeline = NotWiredPipeline()
        """G-DOC + G-AI + G-ORCH behind hoc.jobs.DependencyPipeline; set before the first dependency request."""
        self._jobs: DependencyJobs | None = None
        self.research_runner = NotWiredResearch()
        """A-RES behind hoc.jobs.ResearchRunner; set before the first research request."""
        self._research: ResearchJobs | None = None
        self._ideas_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hoc-ideas")
        self._ideas: dict[tuple, tuple[float, Future]] = {}
        self._idea_contexts: dict[tuple, _IdeaContext] = {}
        self._idea_ai_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="hoc-idea-proposals")
        self._idea_ai_jobs: dict[tuple, tuple[float, Future]] = {}
        self.idea_proposer = None
        """Lazy proposer, replaceable in tests. It never uses dependency jobs or the research runner."""
        self.history = HistoricalShocks(None)
        """FIX-63: where a shock's historical drop comes from. Production: HistoricalShocks(YahooHistory(http));
        without a provider every shock is the simulated DEFAULT_SHOCK_DROP (20%) fall, so tests never touch the network."""

    @classmethod
    def from_settings(cls, settings) -> EtfService:
        """Production wiring: DiskCache + CachedHttpClient + build_registry + TickerInsideReference."""
        from hoc.core.cache import DiskCache
        from hoc.core.http import CachedHttpClient
        from hoc.graph.idea_proposer import IdeaProposer
        from hoc.identity.resolver import load_aliases
        from hoc.research import AgenticResearchRunner
        from hoc.sources.registry import build_registry
        from hoc.sources.tickerinside.adapter import TickerInsideAdapter
        from hoc.sources.tickerinside.reference import TickerInsideReference

        http = CachedHttpClient(settings, DiskCache(settings.cache_dir))
        service = cls(build_registry(settings, http), TickerInsideReference(http, settings), load_aliases(), settings)
        service.idea_proposer = IdeaProposer(http, settings)
        service.history = HistoricalShocks(YahooHistory(http))
        service.quotes = TickerInsideAdapter(http, settings)
        service.dependency_pipeline = LivePipeline.from_settings(http, settings)
        service.research_runner = AgenticResearchRunner.from_settings(http, settings)
        service.dependency_pipeline.researcher = service.research_runner  # v3.1: per-company agents in the job
        return service

    def valuation(self, request: ValuationRequest) -> ValuationResponse:
        """Shares -> allocations (hoc.portfolio.valuation). Prices come from memoised holdings, else a quote
        from the cached fund file: valuing never runs normalisation or sector loading."""
        tickers = list(dict.fromkeys(row.ticker for row in request.rows))
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(tickers))) as pool:
            prices = dict(zip(tickers, pool.map(self._price, tickers), strict=True))
        quotes = {t: p for t, p in prices.items() if p != "unavailable"}
        unavailable = [t for t, p in prices.items() if p == "unavailable"]
        return value_portfolio(request, quotes, unavailable, today=datetime.now(UTC).date())

    def _price(self, ticker: str) -> PriceQuote | None | str:
        """A PriceQuote, None (no published price), or "unavailable" (the price source failed)."""
        memo = self._memo.get((ticker, None))
        if memo is not None and _clock() - memo[0] < MEMO_TTL_SECONDS and memo[1].price is not None:
            return memo[1].price
        if self.quotes is None:
            return None
        try:
            return self.quotes.quote(ticker)
        except TickerNotFound:
            return "unavailable"  # not at the price source: pin it, or analysis reports UNKNOWN_TICKER
        except Exception:  # SourceUnavailable, SourceParseError or a bug: this row only, never a 500
            log.exception("price lookup failed for %s", ticker)
            return "unavailable"

    def stress(self, request: StressRequest) -> StressResponse:
        """FIX-63 failure simulator: what one industry, country or supplier failing does to each portfolio.
        Synchronous; analysis errors (422/503) pass through like /api/compare. No filing fetch, no model call."""
        baseline = self.analyse(PortfolioRequest(holdings=request.baseline))
        candidate = self.analyse(PortfolioRequest(holdings=request.candidate)) if request.candidate else None
        return simulate_failure(request, baseline, candidate, self._shock_basis(request.shock))

    def _shock_basis(self, shock: ShockSpec) -> ShockBasis:
        """The fall each affected company takes: the user's override, else history (hoc.history), else a
        simulated DEFAULT_SHOCK_DROP (20%). A supplier never has its own history, so it never asks the provider."""
        if shock.drop is not None:
            return simulated_basis(f"You chose a {shock.drop:.0%} fall.", drop=shock.drop)
        if shock.kind == "supplier":
            return historical_shock("supplier", shock.key, None, label=shock.label)
        try:
            return self.history.historical_shock(shock.kind, shock.key, label=shock.label)
        except Exception:  # hoc.history never raises; an injected provider might: simulate, never a 500
            log.exception("history provider failed for %s %s", shock.kind, shock.key)
            return simulated_basis(f"Price history isn't available right now, so we simulated a "
                                   f"{DEFAULT_SHOCK_DROP:.0%} fall.")

    def compare(self, request: CompareRequest) -> CompareResponse:
        """Before/after comparison (X-API). Synchronous and cache-only: it runs both analyses, reads the
        verified extractions already cached for either side's top-N companies, and never fetches a filing
        or calls Gemini. Analysis errors (422/503) pass through."""
        baseline = self.analyse(PortfolioRequest(holdings=request.baseline))
        candidate = self.analyse(PortfolioRequest(holdings=request.candidate))
        cached = self._comparison_cache((baseline, candidate), request.top_n)
        return compare_portfolios(request, baseline, candidate, cached, aliases=self.aliases)

    def _comparison_cache(self, analyses: Sequence[AnalysisResponse], top_n: int) -> dict[str, list[VerifiedEdge]]:
        """Shared cache-only reader for compare and change ideas; one snapshot per operation."""
        from hoc.ai import PROMPT_VERSION
        from hoc.config import DEFAULT_EXTRACTOR_MODEL, DEFAULT_ORCHESTRATOR_MODEL

        keys = {c.company_key for analysis in analyses for c in analysis.exposures[:top_n]}
        models = tuple(dict.fromkeys((self.settings.gemini_extractor_model, DEFAULT_EXTRACTOR_MODEL,
                                      DEFAULT_ORCHESTRATOR_MODEL)))
        return read_cached_extractions(self.settings.cache_dir, keys, models=models, prompt_version=PROMPT_VERSION)

    def change_ideas(self, request: ChangeIdeasRequest) -> ChangeIdeasResponse:
        """Bound the HTTP wait, share in-flight work and cache each holdings key for one minute.

        Loading source holdings may outlast the wait; a later call reuses that work.
        The fixed shortlist and two-worker pool bound concurrent idea computations.
        No dependency job, filing fetch, researcher or model client is invoked.
        """
        validate_request(PortfolioRequest(holdings=request.holdings))
        key = (tuple(sorted((h.ticker, h.allocation) for h in request.holdings)), request.top_n)
        with self._locks_guard:
            now = _clock()
            self._ideas = {k: v for k, v in self._ideas.items()
                           if not v[1].done() or now - v[0] < IDEAS_TTL_SECONDS}
            self._idea_contexts = {k: v for k, v in self._idea_contexts.items() if k in self._ideas}
            entry = self._ideas.get(key)
            if entry is None:
                # Never let many distinct cold portfolios create an unbounded queue.
                if len(self._ideas) >= IDEAS_MAX_KEYS:
                    return ChangeIdeasResponse(status="partial", notes=[
                        "Change ideas are busy; try again shortly. Skipped candidates: " + ", ".join(IDEA_TICKERS)])
                future = self._ideas_pool.submit(self._compute_change_ideas, request.model_copy(deep=True))
                self._ideas[key] = (now, future)
            else:
                future = entry[1]
        try:
            rules = future.result(timeout=IDEAS_WAIT_SECONDS).model_copy(deep=True)
        except TimeoutError:
            return ChangeIdeasResponse(status="partial", notes=[
                "ETF data is still loading; try again shortly. Skipped candidates for this response: "
                + ", ".join(IDEA_TICKERS)])
        except Exception:
            with self._locks_guard:
                self._ideas.pop(key, None)
            raise
        return self._with_ai_ideas(request, rules)

    def _compute_change_ideas(self, request: ChangeIdeasRequest) -> ChangeIdeasResponse:
        baseline = self.analyse(PortfolioRequest(holdings=request.holdings))
        current = {h.ticker for h in request.holdings}
        # No candidate fetches when the current portfolio is incomplete or already full.
        from hoc.contract import MAX_ETFS

        candidates = ([t for t in IDEA_TICKERS if t not in current]
                      if len(current) < MAX_ETFS and baseline.coverage.missing_allocation == 0 else [])
        results = self._load_many([*current, *candidates])
        loaded = {t: r for t, r in results.items() if isinstance(r, EtfHoldings)}
        notes = []
        for ticker in candidates:
            etf = results[ticker]
            if isinstance(etf, EtfFailure):
                notes.append(f"Skipped {ticker}: {etf.message}")
            elif etf.holdings_weight < 0.95:
                notes.append(f"Skipped {ticker}: less than 95% of the fund has usable company holdings.")
        scenarios = build_idea_scenarios(request, baseline, loaded, candidates)
        cached = self._comparison_cache([baseline, *(s.analysis for s in scenarios)], request.top_n)
        key = (tuple(sorted((h.ticker, h.allocation) for h in request.holdings)), request.top_n)
        with self._locks_guard:
            self._idea_contexts[key] = _IdeaContext(baseline, loaded, cached)
        return rank_change_ideas(request, baseline, scenarios, cached, aliases=self.aliases, notes=notes)

    def _with_ai_ideas(self, request: ChangeIdeasRequest, rules: ChangeIdeasResponse) -> ChangeIdeasResponse:
        """Return rules immediately while one separately bounded proposal job runs."""
        from hoc.graph.idea_proposer import IdeaProposer, build_portfolio_issues

        holdings_key = (tuple(sorted((h.ticker, h.allocation) for h in request.holdings)), request.top_n)
        with self._locks_guard:
            context = self._idea_contexts.get(holdings_key)
            if self.idea_proposer is None:
                self.idea_proposer = IdeaProposer(settings=self.settings)
            proposer = self.idea_proposer
        if context is None or context.baseline.coverage.missing_allocation > 0:
            return rules
        facts = baseline_idea_metrics(request, context.baseline, context.cached, aliases=self.aliases)
        issues = build_portfolio_issues(context.baseline, facts)
        # Issue facts include values: a refreshed extraction snapshot cannot share stale work.
        key = (holdings_key, tuple((i.issue_id, i.metric_id, i.value) for i in issues),
               self.settings.gemini_orchestrator_model, proposer.prompt_version)
        with self._locks_guard:
            now = _clock()
            self._idea_ai_jobs = {k: v for k, v in self._idea_ai_jobs.items()
                                 if not v[1].done() or now - v[0] < IDEAS_TTL_SECONDS}
            entry = self._idea_ai_jobs.get(key)
        if entry is None:
            universe = self._read_idea_universe(proposer)
            cached_result = proposer.read_cached(request.holdings, issues, universe=universe,
                                                 analysis=context.baseline,
                                                 edges=[e for edges in context.cached.values() for e in edges])
            if cached_result is None and (not self.settings.gemini_api_key or self.settings.offline):
                rules.ai_status = "missing_api_key" if not self.settings.gemini_api_key else "not_used"
                return rules
            rules.model = self.settings.gemini_orchestrator_model
            rules.prompt_version = proposer.prompt_version
            with self._locks_guard:
                entry = self._idea_ai_jobs.get(key)
                if entry is None:
                    if len(self._idea_ai_jobs) >= IDEAS_MAX_KEYS:
                        rules.ai_status = "not_used"
                        rules.notes.append("AI ideas are busy; showing checked rules ideas.")
                        return rules
                    job = self._idea_ai_pool.submit(self._run_ai_ideas, key, request.model_copy(deep=True),
                                                   context, rules.model_copy(deep=True), issues, cached_result)
                    entry = (now, job)
                    self._idea_ai_jobs[key] = entry
        rules.model = self.settings.gemini_orchestrator_model
        rules.prompt_version = proposer.prompt_version
        future = entry[1]
        if not future.done():
            rules.ai_status = "pending"
            return rules
        try:
            return future.result().model_copy(deep=True)
        except Exception:
            # Keep the completed failed entry for the memo interval; polling cannot
            # trigger a retry storm. No raw provider exception/key goes into the API.
            log.warning("AI change idea verification failed", exc_info=True)
            rules.ai_status = "failed"
            return rules

    def _run_ai_ideas(self, key, *args):
        try:
            return self._compute_ai_ideas(*args)
        finally:
            # A slow Argon call gets the whole memo interval after it finishes.
            # Submission holds this lock until its future is stored, so even an
            # immediately completed task can safely update the matching entry.
            with self._locks_guard:
                entry = self._idea_ai_jobs.get(key)
                if entry is not None:
                    self._idea_ai_jobs[key] = (_clock(), entry[1])

    def _compute_ai_ideas(self, request, context, rules, issues, cached_result):
        """Load the universe and propose off the HTTP path, then measure on cached edges."""
        from hoc.graph.idea_proposer import PINNED_ETF_UNIVERSE, enrich_universe_from_loaded

        proposer = self.idea_proposer
        # Cache hits only need their proposed funds. Cold proposals see the entire
        # successfully loaded, Python-enriched universe, never invented source data.
        wanted = ([p.ticker for p in cached_result.proposals] if cached_result is not None
                  else [entry.ticker for entry in PINNED_ETF_UNIVERSE])
        results = self._load_many(sorted(set(wanted) | {h.ticker for h in request.holdings}))
        loaded = {**context.loaded, **{t: r for t, r in results.items() if isinstance(r, EtfHoldings)}}
        notes = [f"Skipped {t}: {r.message}" for t, r in results.items() if isinstance(r, EtfFailure)]
        universe = (self._read_idea_universe(proposer) if cached_result is not None
                    else enrich_universe_from_loaded(loaded, PINNED_ETF_UNIVERSE, notes=notes))
        if cached_result is None:
            self._write_idea_universe(proposer, universe)
        proposal_result = cached_result or proposer.propose(
            request.holdings, issues, universe=universe, analysis=context.baseline,
            edges=[e for edges in context.cached.values() for e in edges],
            timeout_s=IDEAS_AI_TIMEOUT_SECONDS,
        )
        scenarios, _ = build_proposal_scenarios(request, context.baseline, loaded,
                                               proposal_result.proposals, PINNED_ETF_UNIVERSE)
        cached = (self._comparison_cache([context.baseline, *(s.analysis for s in scenarios)], request.top_n)
                  if scenarios else context.cached)
        response = verify_change_ideas(request, context.baseline, loaded, cached, proposal_result,
                                       PINNED_ETF_UNIVERSE, fallback=rules, aliases=self.aliases)
        response.notes.extend(notes)
        if notes:
            response.status = "partial"
        return response

    def _read_idea_universe(self, proposer):
        """Reuse the exact Python-enriched prompt metadata across process restarts."""
        from hoc.core.cache import DiskCache
        from hoc.graph.idea_proposer import PINNED_ETF_UNIVERSE, EtfUniverseEntry

        entry = DiskCache(self.settings.cache_dir).get("idea_universe", proposer.prompt_version)
        if entry is not None:
            try:
                rows = [EtfUniverseEntry(**row) for row in json.loads(entry.body)]
                allowed = {u.ticker for u in PINNED_ETF_UNIVERSE}
                if rows and all(row.ticker in allowed for row in rows):
                    return rows
            except (ValueError, TypeError, KeyError):
                pass
        return PINNED_ETF_UNIVERSE

    def _write_idea_universe(self, proposer, universe):
        from hoc.core.cache import DiskCache

        try:
            DiskCache(self.settings.cache_dir).put("idea_universe", proposer.prompt_version,
                                                   json.dumps([asdict(u) for u in universe]).encode(),
                                                   {"status": 200, "content_type": "application/json"})
        except OSError:
            log.warning("Could not cache ETF idea universe metadata")

    @property
    def dependency_jobs(self) -> DependencyJobs:
        with self._locks_guard:
            if self._jobs is None:
                self._jobs = DependencyJobs(self.analyse, self.dependency_pipeline)
            return self._jobs

    def submit_dependencies(self, request: DependencyRequest, *, cache_only: bool = False,
                            wait: float = SUBMIT_WAIT_SECONDS) -> DependencyJob:
        """Start or reuse the dependency job for these allocations; analysis errors (422/503) pass through."""
        return self.dependency_jobs.submit(request, cache_only=cache_only, wait=wait)

    def dependency_job(self, job_id: str) -> DependencyJob:
        """Raises JobNotFoundError (404)."""
        return self.dependency_jobs.get(job_id)

    @property
    def research_jobs(self) -> ResearchJobs:
        jobs = self.dependency_jobs
        with self._locks_guard:
            if self._research is None:
                self._research = ResearchJobs(jobs, self.research_runner)
            return self._research

    def submit_research(self, dependency_job_id: str, request: ResearchRequest, *,
                        wait: float = SUBMIT_WAIT_SECONDS) -> ResearchJob:
        """Start or join research on a finished dependency job. Raises JobNotFoundError (404) or
        PortfolioValidationError (422 while the dependency job is unfinished)."""
        return self.research_jobs.submit(dependency_job_id, request, wait=wait)

    def research_job(self, research_id: str) -> ResearchJob:
        """Raises ResearchNotFoundError (404)."""
        return self.research_jobs.get(research_id)

    def health(self) -> HealthResponse:
        return HealthResponse(version=__version__, offline=self.settings.offline, sources=self.registry.names)

    def load_etf(self, ticker: str, source: SourceName | None = None) -> EtfHoldings | EtfFailure:
        """Successes are memoised; failures are not (an outage should not stick). Concurrent loads of the
        same ETF (the startup warm-up and a first request) wait for one fetch instead of doing two."""
        ticker = ticker.upper()
        key = (ticker, source)
        with self._locks_guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            memo = self._memo.get(key)
            if memo is not None and _clock() - memo[0] < MEMO_TTL_SECONDS:
                return memo[1]
            loaded = self._load_uncached(ticker, source)
            if isinstance(loaded, EtfHoldings):
                self._memo[key] = (_clock(), loaded)
            elif memo is not None and loaded.status == "unavailable":
                return memo[1]  # refresh failed: yesterday's holdings beat a gap (they keep their own as_of)
            return loaded

    def _load_uncached(self, ticker: str, source: SourceName | None) -> EtfHoldings | EtfFailure:
        try:
            result = self.registry.fetch_with_fallback(ticker, only=source)
        except Exception as exc:  # an adapter bug must cost this ETF, never the whole analysis (no 500)
            log.exception("unexpected error fetching %s", ticker)
            return EtfFailure(etf_ticker=ticker, status="unavailable",
                              message=f"Could not load {ticker}: a data source failed unexpectedly "
                                      f"({type(exc).__name__})")
        if result.raw is None:
            status = "not_found" if result.status == "not_found" else "unavailable"
            message = (f"No data source has {ticker}" if status == "not_found"
                       else f"Could not load {ticker}: data sources unavailable")
            return EtfFailure(etf_ticker=ticker, status=status, attempts=result.attempts, message=message)
        try:
            holdings = normalise_etf(result.raw, self.reference, self.aliases)
        except (SourceError, ValueError) as exc:
            return EtfFailure(etf_ticker=ticker, status="unavailable", attempts=result.attempts,
                              message=f"Could not use {result.raw.source} data for {ticker}: {exc}")
        except Exception as exc:
            log.exception("unexpected error normalising %s from %s", ticker, result.raw.source)
            return EtfFailure(etf_ticker=ticker, status="unavailable", attempts=result.attempts,
                              message=f"Could not use {result.raw.source} data for {ticker} "
                                      f"({type(exc).__name__})")
        return holdings.model_copy(update={"attempts": result.attempts})

    def _load_many(self, tickers: Sequence[str]) -> dict[str, EtfHoldings | EtfFailure]:
        tickers = list(dict.fromkeys(t.upper() for t in tickers))
        if not tickers:
            return {}
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(tickers))) as pool:
            return dict(zip(tickers, pool.map(self.load_etf, tickers), strict=True))

    def etf_summary(self, ticker: str, *, include_holdings: bool = False,
                    source: SourceName | None = None) -> EtfSummary:
        """Raises EtfNotFoundError / SourcesUnavailableError."""
        etf = self.load_etf(ticker, source)
        if isinstance(etf, EtfFailure):
            details = {"ticker": etf.etf_ticker, "attempts": _attempts([etf])[etf.etf_ticker]}
            if etf.status == "not_found":
                raise EtfNotFoundError(etf.message, details)
            raise SourcesUnavailableError(etf.message, details)
        return EtfSummary(
            ticker=etf.etf_ticker,
            name=etf.etf_name,
            status="warning" if etf.warnings else "ok",
            source=etf.source,
            source_layer=etf.source_layer,
            source_url=etf.source_url,
            filing_url=etf.filing_url,
            attribution=etf.attribution,
            licence=etf.licence,
            as_of=etf.as_of,
            retrieved_at=etf.retrieved_at,
            holdings_count=len(etf.holdings),
            company_count=len({h.company_key for h in etf.holdings}),
            reported_weight=etf.reported_weight,
            holdings_weight=etf.holdings_weight,
            excluded_weight=etf.excluded_weight,
            unmatched_weight=etf.unmatched_weight,
            sector_basis=etf.sector_basis,
            sector_weights=etf.sector_weights,
            warnings=etf.warnings,
            attempts=etf.attempts,
            holdings=etf.holdings if include_holdings else None,
        )

    def analyse(self, request: PortfolioRequest) -> AnalysisResponse:
        """validate_request -> load every ETF -> analyse(). Raises PortfolioValidationError,
        UnknownTickerError (any ticker not_found everywhere) or SourcesUnavailableError (nothing loaded)."""
        notices = validate_request(request)
        results = self._load_many([item.ticker for item in request.holdings])
        loaded = {t: r for t, r in results.items() if isinstance(r, EtfHoldings)}
        failures = {t: r for t, r in results.items() if isinstance(r, EtfFailure)}
        unknown = [f for f in failures.values() if f.status == "not_found"]
        if unknown:
            tickers = [f.etf_ticker for f in unknown]
            raise UnknownTickerError(f"No data source has {', '.join(tickers)}",
                                     {"tickers": tickers, "attempts": _attempts(unknown)})
        if not loaded:
            raise SourcesUnavailableError("No ETF could be loaded: data sources unavailable",
                                          {"attempts": _attempts(list(failures.values()))})
        now = datetime.now(UTC)
        response = analyse(request, loaded, failures, today=now.date(), generated_at=now)
        extra = [n for n in notices if n not in response.warnings]
        return response.model_copy(update={"warnings": [*extra, *response.warnings]}) if extra else response

    def examples(self) -> ExamplesResponse:
        results = self._load_many([ticker for ex in EXAMPLES for ticker, _ in ex.holdings])
        portfolios = []
        for ex in EXAMPLES:
            etfs = []
            for ticker, allocation in ex.holdings:
                etf = results[ticker.upper()]
                ok = isinstance(etf, EtfHoldings)
                etfs.append(ExampleEtf(ticker=ticker.upper(), allocation=allocation, verified=ok,
                                       source=etf.source if ok else None, as_of=etf.as_of if ok else None))
            portfolios.append(ExamplePortfolio(id=ex.id, name=ex.name, description=ex.description,
                                               holdings=etfs, verified=all(e.verified for e in etfs)))
        return ExamplesResponse(examples=portfolios)
