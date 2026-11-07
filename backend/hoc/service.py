"""Wires sources -> normalisation -> maths. Owner: package f (Bekarys's Claude). Signatures fixed by W0-B.

EtfService keeps an in-memory memo of EtfHoldings per (ticker, source), so changing allocations
never refetches; fetch several ETFs in parallel (a small thread pool). The API layer only calls
these methods.
"""

from __future__ import annotations

from hoc import __version__
from hoc.contract import (
    AnalysisResponse,
    EtfFailure,
    EtfHoldings,
    EtfSummary,
    ExamplesResponse,
    HealthResponse,
    PortfolioRequest,
    SourceName,
)


class EtfService:
    def __init__(self, registry, reference, aliases, settings) -> None:
        self.registry = registry
        self.reference = reference
        self.aliases = aliases
        self.settings = settings

    @classmethod
    def from_settings(cls, settings) -> EtfService:
        """Production wiring: DiskCache + CachedHttpClient + build_registry + TickerInsideReference."""
        raise NotImplementedError("package f: EtfService.from_settings")

    def health(self) -> HealthResponse:
        return HealthResponse(version=__version__, offline=self.settings.offline, sources=self.registry.names)

    def load_etf(self, ticker: str, source: SourceName | None = None) -> EtfHoldings | EtfFailure:
        raise NotImplementedError("package f: EtfService.load_etf")

    def etf_summary(self, ticker: str, *, include_holdings: bool = False,
                    source: SourceName | None = None) -> EtfSummary:
        """Raises EtfNotFoundError / SourcesUnavailableError."""
        raise NotImplementedError("package f: EtfService.etf_summary")

    def analyse(self, request: PortfolioRequest) -> AnalysisResponse:
        """validate_request -> load every ETF -> analyse(). Raises PortfolioValidationError,
        UnknownTickerError (any ticker not_found everywhere) or SourcesUnavailableError (nothing loaded)."""
        raise NotImplementedError("package f: EtfService.analyse")

    def examples(self) -> ExamplesResponse:
        raise NotImplementedError("package f: EtfService.examples")
