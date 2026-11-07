"""Source fallback: try adapters in order, first success wins, record every attempt."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from hoc.contract import (
    RawEtfHoldings,
    SourceAttempt,
    SourceParseError,
    SourceUnavailable,
    TickerNotFound,
)

from .base import SourceAdapter

FetchStatus = Literal["ok", "not_found", "unavailable"]


@dataclass
class FetchResult:
    ticker: str
    raw: RawEtfHoldings | None
    attempts: list[SourceAttempt] = field(default_factory=list)

    @property
    def status(self) -> FetchStatus:
        """ok if any source succeeded; not_found if every attempted source said not_found; else unavailable."""
        if self.raw is not None:
            return "ok"
        tried = [a for a in self.attempts if a.outcome != "skipped"]
        if tried and all(a.outcome == "not_found" for a in tried):
            return "not_found"
        return "unavailable" if tried else "not_found"


class SourceRegistry:
    def __init__(self, adapters: Sequence[SourceAdapter], order: Sequence[str] | None = None) -> None:
        by_name = {adapter.name: adapter for adapter in adapters}
        if len(by_name) != len(adapters):
            raise ValueError("Two adapters share a name")
        names = list(order) if order else [adapter.name for adapter in adapters]
        unknown = [name for name in names if name not in by_name]
        if unknown:
            raise ValueError(f"Unknown sources in order: {unknown}")
        self._adapters = [by_name[name] for name in names]

    @property
    def names(self) -> list[str]:
        return [adapter.name for adapter in self._adapters]

    def fetch_with_fallback(self, ticker: str, only: str | None = None) -> FetchResult:
        ticker = ticker.upper()
        result = FetchResult(ticker=ticker, raw=None)
        for adapter in self._adapters:
            if only is not None and adapter.name != only:
                continue
            if not adapter.supports(ticker):
                result.attempts.append(SourceAttempt(source=adapter.name, outcome="skipped"))
                continue
            try:
                raw = adapter.fetch(ticker)
            except TickerNotFound as exc:
                result.attempts.append(SourceAttempt(source=adapter.name, outcome="not_found", message=str(exc)))
            except SourceUnavailable as exc:
                result.attempts.append(SourceAttempt(source=adapter.name, outcome="unavailable", message=str(exc)))
            except SourceParseError as exc:
                result.attempts.append(SourceAttempt(source=adapter.name, outcome="parse_error", message=str(exc)))
            else:
                result.attempts.append(SourceAttempt(source=adapter.name, outcome="ok"))
                result.raw = raw
                return result
        return result


def build_registry(settings, http) -> SourceRegistry:
    """The production registry, in settings.source_order. Adapters are imported lazily."""
    from hoc.sources.ishares.adapter import ISharesAdapter
    from hoc.sources.sec_nport.adapter import SecNportAdapter
    from hoc.sources.tickerinside.adapter import TickerInsideAdapter

    adapters = [
        TickerInsideAdapter(http, settings),
        ISharesAdapter(http, settings),
        SecNportAdapter(http, settings),
    ]
    return SourceRegistry(adapters, order=settings.source_order)
