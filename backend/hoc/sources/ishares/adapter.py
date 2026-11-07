"""iShares (BlackRock) holdings CSV. Owner: package c (Kendrick's Gemini, after b).

Facts verified 2026-11-07:
- The old ...ajax?fileType=csv URL returns the HTML product page with Content-Type text/csv:
  ALWAYS validate the body. Use /us/products/{id}/{slug}/latest-holdings.csv, whose URL is in the
  product page JSON-LD (contentUrl).
- Preamble includes 'Fund Holdings as of,"Nov 05, 2026"' (UK site: '"05/Nov/2026"'); then a header row
  whose columns VARY by fund (map by name: Ticker, Name, Sector, Asset Class, Weight (%) or Market
  Weight, Location, Exchange, Currency...). No ISIN/CUSIP; foreign tickers are bare local codes.
- Filter cash, futures, FX and collateral rows into asset_class cash/derivative/fx.
- Site terms restrict redistribution: never commit downloaded files.
"""

from __future__ import annotations

from typing import ClassVar

from hoc.contract import RawEtfHoldings, SourceName


class ISharesAdapter:
    name: ClassVar[SourceName] = "ishares"

    def __init__(self, http, settings) -> None:
        self.http = http
        self.settings = settings

    def supports(self, ticker: str) -> bool:
        """Until c lands, decline everything so the registry falls through to the next source."""
        return False

    def fetch(self, ticker: str) -> RawEtfHoldings:
        raise NotImplementedError("package c: ISharesAdapter.fetch")
