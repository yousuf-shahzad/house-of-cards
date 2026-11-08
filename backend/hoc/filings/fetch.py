"""Latest 10-K / 20-F for a company, as canonical text with section offsets. Owner: G-DOC (Kendrick's Claude).

- company_key 'CIK:##########' gives the CIK directly; otherwise a US symbol is looked up in SEC
  company_tickers.json. Samsung, SK Hynix and other non-SEC issuers have no CIK: status no_sec_filing.
- data.sec.gov/submissions/CIK##########.json -> the newest exact '10-K' or '20-F' in filings.recent
  (amendments skipped). Filers with only 40-F/6-K etc.: unsupported_form.
- SEC requires a User-Agent with contact details (HOC_SEC_CONTACT). Without it nothing is fetched:
  status sec_contact_missing. Requests go through core/http (sec.gov spacing <= 10/s); filing documents
  are immutable, so they are cached forever (ttl=None).
"""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from hoc.contract import SourceError

from .sections import section_map
from .text import html_to_text, normalise

FilingStatus = Literal["no_sec_filing", "unsupported_form", "sec_contact_missing", "error"]
ANNUAL_FORMS = ("10-K", "20-F")
OTHER_ANNUAL_FORMS = ("40-F", "10-KT", "20-FR")
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"
METADATA_TTL = timedelta(hours=24)
SOURCE = "sec_filings"


class FilingUnavailable(Exception):
    def __init__(self, status: FilingStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Filing:
    cik: str
    form: str
    accession: str
    filed: date
    url: str
    text: str
    """normalise(html_to_text(document)): the exact text every evidence quote is verified against."""
    sha256: str
    sections: dict[str, tuple[int, int]]
    """'1', '1A', '2' (10-K) or '3', '3D', '4', '5' (20-F), 'concentration_N', or 'document' on fallback."""
    quality: Literal["sections", "fallback"]

    def section_texts(self) -> dict[str, str]:
        return {name: self.text[start:end] for name, (start, end) in sorted(self.sections.items(), key=lambda kv: kv[1])}


class FilingFetcher:
    def __init__(self, http, settings) -> None:
        self.http = http
        self.settings = settings
        self._memo: dict[str, Filing] = {}  # accession -> Filing (filings are immutable)
        self._lock = threading.Lock()

    def for_company(self, company) -> Filing:
        """Latest 10-K/20-F for a CompanyExposure-like object (company_key, symbols). Raises FilingUnavailable."""
        return self.latest(self.cik_for(company.company_key, tuple(company.symbols)))

    def _headers(self) -> dict[str, str]:
        contact = (self.settings.sec_contact or "").strip()
        if not contact:
            raise FilingUnavailable("sec_contact_missing", "Set HOC_SEC_CONTACT (SEC requires contact details).")
        return {"User-Agent": f"{self.settings.user_agent} ({contact})", "Accept": "*/*"}

    def _get(self, url: str, ttl: timedelta | None):
        try:
            response = self.http.get(url, source=SOURCE, ttl=ttl, headers=self._headers())
        except SourceError as exc:
            raise FilingUnavailable("error", f"SEC request failed: {exc}") from exc
        return response

    def cik_for(self, company_key: str, symbols: list[str] | tuple[str, ...] = ()) -> str:
        """10-digit CIK for a portfolio company, or FilingUnavailable('no_sec_filing')."""
        if company_key.startswith("CIK:") and company_key[4:].isdigit():
            return company_key[4:].zfill(10)
        us_symbols = [s.upper() for s in symbols if "." not in s or re.fullmatch(r"[A-Z]+\.[A-Z]", s.upper())]
        if us_symbols:
            response = self._get(TICKERS_URL, METADATA_TTL)
            if response.status == 200:
                try:
                    rows = response.json().values()
                    by_ticker = {str(r["ticker"]).upper().replace("-", "."): int(r["cik_str"]) for r in rows}
                except (AttributeError, KeyError, TypeError, ValueError) as exc:
                    raise FilingUnavailable("error", "SEC company_tickers.json is malformed") from exc
                for symbol in us_symbols:
                    if symbol in by_ticker:
                        return str(by_ticker[symbol]).zfill(10)
        raise FilingUnavailable("no_sec_filing", f"No SEC filer found for {company_key}")

    def latest(self, cik: str) -> Filing:
        cik = cik.zfill(10)
        response = self._get(SUBMISSIONS_URL.format(cik=cik), METADATA_TTL)
        if response.status == 404:
            raise FilingUnavailable("no_sec_filing", f"SEC has no submissions for CIK {cik}")
        if response.status != 200:
            raise FilingUnavailable("error", f"SEC submissions returned HTTP {response.status}")
        try:
            recent = response.json()["filings"]["recent"]
            rows = list(zip(recent["form"], recent["accessionNumber"], recent["filingDate"],
                            recent["primaryDocument"], strict=True))
        except (KeyError, TypeError, ValueError) as exc:
            raise FilingUnavailable("error", f"SEC submissions for CIK {cik} are malformed") from exc
        annual = [row for row in rows if row[0] in ANNUAL_FORMS]
        if not annual:
            other = sorted({row[0] for row in rows if row[0] in OTHER_ANNUAL_FORMS})
            status: FilingStatus = "unsupported_form" if other else "no_sec_filing"
            raise FilingUnavailable(status, f"No 10-K or 20-F for CIK {cik}" + (f" (files {', '.join(other)})" if other else ""))
        form, accession, filed, document = max(annual, key=lambda row: (row[2], row[1]))  # newest filing date
        with self._lock:
            if accession in self._memo:
                return self._memo[accession]
        url = ARCHIVE_URL.format(cik=int(cik), accession=accession.replace("-", ""), document=document)
        doc = self._get(url, None)
        if doc.status != 200:
            raise FilingUnavailable("error", f"SEC filing document returned HTTP {doc.status}")
        body = doc.body.decode("utf-8", errors="replace")
        text = normalise(body) if document.lower().endswith(".txt") else html_to_text(body)
        sections, quality = section_map(text, form)
        filing = Filing(cik=cik, form=form, accession=accession, filed=date.fromisoformat(filed), url=url, text=text,
                        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), sections=sections, quality=quality)
        with self._lock:
            return self._memo.setdefault(accession, filing)
