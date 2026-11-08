"""Wires sources -> normalisation -> maths. Owner: package f (Bekarys's Claude). Signatures fixed by W0-B.

EtfService keeps an in-memory memo of EtfHoldings per (ticker, source), so changing allocations
never refetches; fetch several ETFs in parallel (a small thread pool). The API layer only calls
these methods.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from hoc import __version__
from hoc.contract import (
    AnalysisResponse,
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
    SourceError,
    SourceName,
    SourcesUnavailableError,
    TickerNotFound,
    UnknownTickerError,
    ValuationRequest,
    ValuationResponse,
)
from hoc.examples import EXAMPLES
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
from hoc.portfolio.validation import validate_request
from hoc.portfolio.valuation import value_portfolio

MAX_WORKERS = 8
MEMO_TTL_SECONDS = 24 * 3600
"""How long a loaded ETF is reused in memory: the source TTL, so a long-running API picks up new disclosures."""
log = logging.getLogger("hoc.service")


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

    @classmethod
    def from_settings(cls, settings) -> EtfService:
        """Production wiring: DiskCache + CachedHttpClient + build_registry + TickerInsideReference."""
        from hoc.core.cache import DiskCache
        from hoc.core.http import CachedHttpClient
        from hoc.identity.resolver import load_aliases
        from hoc.sources.registry import build_registry
        from hoc.sources.tickerinside.adapter import TickerInsideAdapter
        from hoc.sources.tickerinside.reference import TickerInsideReference

        http = CachedHttpClient(settings, DiskCache(settings.cache_dir))
        service = cls(build_registry(settings, http), TickerInsideReference(http, settings), load_aliases(), settings)
        service.quotes = TickerInsideAdapter(http, settings)
        service.dependency_pipeline = LivePipeline.from_settings(http, settings)
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

    def compare(self, request: CompareRequest) -> CompareResponse:
        """Before/after comparison (X-API). Synchronous and cache-only: it runs both analyses, reads the
        verified extractions already cached for either side's top-N companies, and never fetches a filing
        or calls Gemini. Analysis errors (422/503) pass through."""
        from hoc.ai import PROMPT_VERSION
        from hoc.config import DEFAULT_EXTRACTOR_MODEL, DEFAULT_ORCHESTRATOR_MODEL

        baseline = self.analyse(PortfolioRequest(holdings=request.baseline))
        candidate = self.analyse(PortfolioRequest(holdings=request.candidate))
        top = request.top_n
        keys = {c.company_key for c in baseline.exposures[:top]} | {c.company_key for c in candidate.exposures[:top]}
        models = tuple(dict.fromkeys((self.settings.gemini_extractor_model, DEFAULT_EXTRACTOR_MODEL,
                                      DEFAULT_ORCHESTRATOR_MODEL)))
        cached = read_cached_extractions(self.settings.cache_dir, keys, models=models, prompt_version=PROMPT_VERSION)
        return compare_portfolios(request, baseline, candidate, cached, aliases=self.aliases)

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
