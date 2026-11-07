"""Wires sources -> normalisation -> maths. Owner: package f (Bekarys's Claude). Signatures fixed by W0-B.

EtfService keeps an in-memory memo of EtfHoldings per (ticker, source), so changing allocations
never refetches; fetch several ETFs in parallel (a small thread pool). The API layer only calls
these methods.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from hoc import __version__
from hoc.contract import (
    AnalysisResponse,
    EtfFailure,
    EtfHoldings,
    EtfNotFoundError,
    EtfSummary,
    ExampleEtf,
    ExamplePortfolio,
    ExamplesResponse,
    HealthResponse,
    PortfolioRequest,
    SourceError,
    SourceName,
    SourcesUnavailableError,
    UnknownTickerError,
)
from hoc.examples import EXAMPLES
from hoc.normalise.pipeline import normalise_etf
from hoc.portfolio.analyse import analyse
from hoc.portfolio.validation import validate_request

MAX_WORKERS = 8
log = logging.getLogger("hoc.service")


def _attempts(failures: Sequence[EtfFailure]) -> dict[str, list[dict]]:
    return {f.etf_ticker: [a.model_dump(mode="json") for a in f.attempts] for f in failures}


class EtfService:
    def __init__(self, registry, reference, aliases, settings) -> None:
        self.registry = registry
        self.reference = reference
        self.aliases = aliases
        self.settings = settings
        # ponytail: memo lives as long as the process (the disk cache holds the 24 h TTL); restart to refresh.
        self._memo: dict[tuple[str, str | None], EtfHoldings] = {}
        self._locks: dict[tuple[str, str | None], threading.Lock] = {}
        self._locks_guard = threading.Lock()

    @classmethod
    def from_settings(cls, settings) -> EtfService:
        """Production wiring: DiskCache + CachedHttpClient + build_registry + TickerInsideReference."""
        from hoc.core.cache import DiskCache
        from hoc.core.http import CachedHttpClient
        from hoc.identity.resolver import load_aliases
        from hoc.sources.registry import build_registry
        from hoc.sources.tickerinside.reference import TickerInsideReference

        http = CachedHttpClient(settings, DiskCache(settings.cache_dir))
        return cls(build_registry(settings, http), TickerInsideReference(http, settings), load_aliases(), settings)

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
            if key in self._memo:
                return self._memo[key]
            loaded = self._load_uncached(ticker, source)
            if isinstance(loaded, EtfHoldings):
                self._memo[key] = loaded
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
