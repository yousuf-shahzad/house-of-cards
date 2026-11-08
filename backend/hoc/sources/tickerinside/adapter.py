"""TickerInside (https://tickerinside.com/api/v1/). Owner: package a (Kendrick's Claude).

Facts verified 2026-11-07 (see docs/hoc/PLAN.md):
- fund/{ticker.lower()}.json (uppercase paths 301): holdings = {symbol: percent}, holdings_as_of is the
  DISCLOSURE date (as_of is the build date), source_layer issuer|sec_nport, filing_url (sec_nport only),
  cite_as + license on every file, breakdown.sectors_pct. Unknown fund -> 404.
- Derivatives can appear inside holdings (XLK had a futures line 'IXTZ6'): classify them, don't drop silently.
- CC BY 4.0: carry cite_as into RawEtfHoldings.attribution and licence="CC BY 4.0".
- They ask for an app-identifying User-Agent and at most one fetch per nightly build: ttl >= 24h.
- Never use their /overlap or /lookthrough endpoints in the app: our maths must be our own.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import ClassVar

from hoc.contract import (
    PriceQuote,
    RawEtfHoldings,
    RawHolding,
    SourceError,
    SourceName,
    SourceParseError,
    TickerNotFound,
)

from .files import BASE_URL, LICENCE, ReferenceFiles, country_of, get_json
from .files import longest as _longest

TICKER = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,11}")
FUTURES_SYMBOL = re.compile(r"[A-Z]{1,5}[FGHJKMNQUVXZ]\d{1,2}")
"""Futures contract codes: root + month letter + year digit(s), e.g. IXTZ6 (Dec 2026). No dot, unlike non-US listings."""


class TickerInsideAdapter:
    name: ClassVar[SourceName] = "tickerinside"

    def __init__(self, http, settings) -> None:
        self.http = http
        self.settings = settings
        self.files = ReferenceFiles(http, settings)

    def supports(self, ticker: str) -> bool:
        return bool(TICKER.fullmatch(ticker.upper()))

    def _fund(self, ticker: str):
        """(TICKER, path, parsed fund JSON, response); the fund file is cached 24 h by core/http."""
        ticker = ticker.upper()
        if not self.supports(ticker):
            raise TickerNotFound(f"{ticker} is not a valid ticker")
        path = f"fund/{ticker.lower()}.json"
        data, response = get_json(self.http, self.settings, path)
        if not isinstance(data, dict):
            raise SourceParseError(f"TickerInside {path} is not a fund file")
        return ticker, path, data, response

    def quote(self, ticker: str) -> PriceQuote | None:
        """The ETF's latest exchange close from the same cached fund file, without loading holdings.

        None when the file has no usable price. Raises TickerNotFound / SourceUnavailable / SourceParseError.
        """
        return _price(self._fund(ticker)[2])

    def fetch(self, ticker: str) -> RawEtfHoldings:
        ticker, path, data, response = self._fund(ticker)
        try:
            holdings = data["holdings"]
            as_of = date.fromisoformat(data["holdings_as_of"])
            if not isinstance(holdings, dict) or not holdings:
                raise ValueError("empty holdings")
            pct = {str(s).upper(): float(w) for s, w in holdings.items()}
            if not all(math.isfinite(w) for w in pct.values()):
                raise ValueError("non-finite weight")
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceParseError(f"TickerInside {path} is not a fund holdings file ({exc})") from exc

        warnings = []
        try:  # names and asset types are optional extras: the holdings stand without them
            names, ids = self.files.securities(), self.files.identifiers()
        except SourceError as exc:
            names, ids = {}, {}
            warnings.append(f"TickerInside reference files unavailable, holdings have no names: {exc}")
        if response.stale:
            warnings.append("TickerInside fund file served from an expired cache entry")

        lines = []
        for symbol, weight in pct.items():
            ident = ids.get(symbol, {})
            if FUTURES_SYMBOL.fullmatch(symbol) and symbol not in ids:
                asset_class = "derivative"
            elif ident.get("asset_type") in ("etf", "etn"):
                asset_class = "fund"
            else:
                asset_class = "equity"
            row = names.get(symbol)
            lines.append(RawHolding(
                source_symbol=symbol, name=_longest(row[3] if row and len(row) > 3 else None, ident.get("name")),
                weight=weight / 100, asset_class=asset_class, exchange=ident.get("exchange"),
                country=country_of(symbol, ident, row[3] if row and len(row) > 3 else None),
                cik=ident.get("cik"), figi=ident.get("composite_figi"),
            ))

        price = _price(data)
        if price is None and data.get("last_close") is not None:
            warnings.append("TickerInside price data is malformed and was ignored")
        sectors = _sector_weights(data.get("breakdown"))
        if sectors is _MALFORMED:
            sectors = None
            warnings.append("TickerInside sector breakdown is malformed and was ignored")
        try:
            return RawEtfHoldings(
                etf_ticker=ticker, etf_name=data.get("name"), source="tickerinside",
                source_layer=data.get("source_layer"), as_of=as_of, retrieved_at=response.fetched_at,
                source_url=data.get("page_url") or f"{BASE_URL}/{path}", filing_url=data.get("filing_url"),
                attribution=data.get("cite_as"), licence=data.get("license") or LICENCE,
                reported_sector_weights=sectors, holdings=lines, warnings=warnings, price=price,
            )
        except ValueError as exc:  # pydantic ValidationError: a field had the wrong type upstream
            raise SourceParseError(f"TickerInside {path} has malformed fields") from exc


def _price(data: dict) -> PriceQuote | None:
    """last_close / last_close_date / currency -> PriceQuote (an exchange close, not NAV); None if unusable."""
    try:
        return PriceQuote(price=float(data["last_close"]), currency=str(data["currency"]).upper(),
                          as_of=date.fromisoformat(data["last_close_date"]), kind="close", source="tickerinside",
                          attribution=data.get("cite_as"))
    except (KeyError, TypeError, ValueError):  # missing, non-numeric, non-positive, NaN, bad date, no currency
        return None


_MALFORMED = object()


def _sector_weights(breakdown):
    """breakdown.sectors_pct (percent) -> fractions; None if absent, _MALFORMED if unusable."""
    if breakdown is None:
        return None
    try:
        sectors = breakdown.get("sectors_pct")
        if not sectors:
            return None
        weights = {str(k): float(v) / 100 for k, v in sectors.items()}
    except (AttributeError, TypeError, ValueError):
        return _MALFORMED
    return weights if all(math.isfinite(w) for w in weights.values()) else _MALFORMED
