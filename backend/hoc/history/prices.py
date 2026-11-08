"""Daily closes for a proxy fund (FIX-63). Yahoo Finance's public chart endpoint, through the shared
cached HTTP client (24-hour cache; offline or failing -> the cached copy, else SourceUnavailable)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from urllib.parse import quote

from hoc.core.http import HttpClient

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HISTORY_TTL = timedelta(hours=24)
# A generic client name: this request goes to a third party, so never the SEC contact User-Agent.
GENERIC_USER_AGENT = "Mozilla/5.0 (compatible; HouseOfCards-PoC/0.1)"


@dataclass(frozen=True)
class DailyCloses:
    symbol: str
    dates: tuple[date, ...]
    closes: tuple[float, ...]
    """Adjusted closes (dividends and splits) when the source has them, else plain closes; oldest first."""


class HistoryProvider(Protocol):
    def daily_closes(self, symbol: str) -> DailyCloses | None:
        """About 5 years of daily closes, or None when the source has nothing usable for this symbol.
        May raise (e.g. SourceUnavailable); callers fall back to a simulated drop."""
        ...


class YahooHistory:
    def __init__(self, http: HttpClient, *, range_: str = "5y") -> None:
        self.http = http
        self.range = range_

    def daily_closes(self, symbol: str) -> DailyCloses | None:
        response = self.http.get(
            YAHOO_CHART_URL.format(symbol=quote(symbol.upper(), safe="")),
            source="yahoo_chart",
            ttl=HISTORY_TTL,
            headers={"User-Agent": GENERIC_USER_AGENT, "Accept": "application/json"},
            params={"range": self.range, "interval": "1d", "events": "div,split"},
        )
        if response.status != 200:
            return None
        return parse_chart(symbol.upper(), response.json())


def parse_chart(symbol: str, payload: dict) -> DailyCloses | None:
    """Yahoo v8 chart JSON -> DailyCloses. Skips days with a missing close; None if nothing usable."""
    try:
        result = (payload.get("chart") or {}).get("result") or []
        if not result:
            return None
        first = result[0]
        stamps = first.get("timestamp") or []
        indicators = first.get("indicators") or {}
        adj = ((indicators.get("adjclose") or [{}])[0] or {}).get("adjclose")
        raw = ((indicators.get("quote") or [{}])[0] or {}).get("close")
        series = adj if adj and len(adj) == len(stamps) else raw
        if not series or len(series) != len(stamps):
            return None
    except (AttributeError, IndexError, TypeError):
        return None
    pairs: dict[date, float] = {}
    for stamp, close in zip(stamps, series):
        if close is None or not isinstance(stamp, (int, float)):
            continue
        value = float(close)
        if value <= 0:
            continue
        pairs[datetime.fromtimestamp(stamp, tz=UTC).date()] = value
    if not pairs:
        return None
    days = sorted(pairs)
    return DailyCloses(symbol=symbol, dates=tuple(days), closes=tuple(pairs[d] for d in days))
