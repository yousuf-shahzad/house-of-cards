"""SEC EDGAR N-PORT-P (public domain). Owner: package b (Kendrick's Gemini).

Facts verified 2026-11-07:
- ticker -> CIK/series/class via https://www.sec.gov/files/company_tickers_mf.json (SPY is absent:
  CIK 884394). Latest NPORT-P from data.sec.gov/submissions/CIK##########.json, newest by repPdDate.
- primary_doc.xml: seriesId, repPdDate, invstOrSec{name, lei, title, cusip, isin, balance, valUSD,
  pctVal (percent -> fraction), assetCat}. Parse with defusedxml. ~60-day lag; no sector.
- A User-Agent with contact (settings.sec_contact) is REQUIRED; stay under 10 requests/s.
  Filings are immutable: cache by accession with ttl=None.
"""

from __future__ import annotations

from typing import ClassVar

from hoc.contract import RawEtfHoldings, SourceName


class SecNportAdapter:
    name: ClassVar[SourceName] = "sec_nport"

    def __init__(self, http, settings) -> None:
        self.http = http
        self.settings = settings

    def supports(self, ticker: str) -> bool:
        """Until package b lands, decline everything so the registry falls through (flip to True)."""
        return False

    def fetch(self, ticker: str) -> RawEtfHoldings:
        raise NotImplementedError("package b: SecNportAdapter.fetch")
