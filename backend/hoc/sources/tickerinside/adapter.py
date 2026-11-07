"""TickerInside (https://tickerinside.com/api/v1/). Owner: package a (Gawyn's Gemini).

Facts verified 2026-11-07 (see docs/hoc/PLAN.md):
- fund/{ticker.lower()}.json (uppercase paths 301): holdings = {symbol: percent}, holdings_as_of is the
  DISCLOSURE date (as_of is the build date), source_layer issuer|sec_nport, filing_url (sec_nport only),
  cite_as + license on every file, breakdown.sectors_pct. Unknown fund -> 404.
- Derivatives can appear inside holdings (XLK had a futures line): classify them, don't drop silently.
- CC BY 4.0: carry cite_as into RawEtfHoldings.attribution and licence="CC BY 4.0".
- They ask for an app-identifying User-Agent and at most one fetch per nightly build: ttl >= 24h.
- Never use their /overlap or /lookthrough endpoints in the app: our maths must be our own.
"""

from __future__ import annotations

from typing import ClassVar

from hoc.contract import RawEtfHoldings, SourceName

BASE_URL = "https://tickerinside.com/api/v1"


class TickerInsideAdapter:
    name: ClassVar[SourceName] = "tickerinside"

    def __init__(self, http, settings) -> None:
        self.http = http
        self.settings = settings

    def supports(self, ticker: str) -> bool:
        """Until package a lands, decline everything so the registry falls through (flip to True)."""
        return False

    def fetch(self, ticker: str) -> RawEtfHoldings:
        raise NotImplementedError("package a: TickerInsideAdapter.fetch")
