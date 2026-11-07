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

import re
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any, ClassVar
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as DefusedET

from hoc.contract import (
     AssetClass,
    RawEtfHoldings,
    RawHolding,
    SecurityInfo,
    SourceName,
    SourceParseError,
    SourceUnavailable,
    TickerNotFound,
    wsum,
)
from hoc.contract.units import RAW_WEIGHT_SUM_MAX

MF_TICKERS_URL = "https://www.sec.gov/files/company_tickers_mf.json"
SUBMISSIONS_URL_TPL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SERIES_ATOM_URL_TPL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={series_id}&type=NPORT-P&count=5&output=atom"
)
ARCHIVE_XML_URL_TPL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{doc}"
ARCHIVE_INDEX_URL_TPL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{acc}-index.htm"
OPENFIGI_MAPPING_URL = "https://api.openfigi.com/v3/mapping"

TTL_METADATA = timedelta(hours=24)
DEFAULT_SEC_CONTACT = "contact@agentverse-hackathon.org"

# Unit Investment Trusts (UITs) that file NPORT-P under their CIK without a seriesId in company_tickers_mf.json.
KNOWN_UIT_CIKS: dict[str, tuple[int, str]] = {
    "SPY": (884394, "SPDR S&P 500 ETF Trust"),
    "DIA": (1041130, "SPDR Dow Jones Industrial Average ETF Trust"),
    "MDY": (936958, "SPDR S&P MidCap 400 ETF Trust"),
}

_ASSET_CAT_MAP: dict[str, AssetClass] = {
    "EC": "equity",
    "EP": "preferred",
    "STIV": "cash",
    "DE": "derivative",
    "DIR": "derivative",
    "DCR": "derivative",
    "DCO": "derivative",
    "OTH": "derivative",
    "DFE": "fx",
    "DBT": "fixed_income",
    "ABS": "fixed_income",
    "AGCY": "fixed_income",
    "MBS": "fixed_income",
    "UST": "fixed_income",
    "MUNI": "fixed_income",
    "LON": "fixed_income",
    "RF": "fund",
    "RA": "other",
    "RE": "other",
}


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _clean_str(value: str | None) -> str | None:
    if value is None:
        return None
    s = value.strip()
    if not s or s.upper() in {"N/A", "NONE", "NULL", "-"}:
        return None
    return s


def _child_text(elem: Element, name: str) -> str | None:
    for child in elem:
        if _local_name(child.tag) == name:
            return _clean_str(child.text)
    return None


def _find_first(elem: Element, name: str) -> Element | None:
    for node in elem.iter():
        if _local_name(node.tag) == name:
            return node
    return None


def _classify_asset_class(inv: Element) -> AssetClass:
    asset_cat = _child_text(inv, "assetCat")
    issuer_cat = _child_text(inv, "issuerCat")
    if asset_cat:
        code = asset_cat.upper()
        if code in _ASSET_CAT_MAP:
            return _ASSET_CAT_MAP[code]
        if code.startswith("D"):
            return "derivative"

    for child in inv:
        if _local_name(child.tag) == "assetConditional":
            cond_cat = _clean_str(child.attrib.get("assetCat"))
            desc = (_clean_str(child.attrib.get("desc")) or "").lower()
            if cond_cat and cond_cat.upper() in _ASSET_CAT_MAP:
                return _ASSET_CAT_MAP[cond_cat.upper()]
            if any(k in desc for k in ("adr", "gdr", "nvdr", "equity", "common", "ordinary", "stock", "share")):
                return "equity"
            if "prefer" in desc:
                return "preferred"
            if any(k in desc for k in ("currency", "cash", "money market", "deposit")):
                return "cash"
            if any(k in desc for k in ("fx", "foreign exchange", "forward")):
                return "fx"
            if any(k in desc for k in ("future", "swap", "option", "warrant", "derivative", "right")):
                return "derivative"
            if any(k in desc for k in ("bond", "note", "debt", "treasury", "bill")):
                return "fixed_income"
            if any(k in desc for k in ("fund", "etf", "trust", "reit")):
                return "fund" if "reit" not in desc else "equity"
            return "other"

    if issuer_cat and issuer_cat.upper() == "RF":
        return "fund"
    return "equity"


def _is_cash_collateral(inv: Element) -> bool:
    for child in inv:
        if _local_name(child.tag) == "securityLending":
            for sub in child:
                lname = _local_name(sub.tag)
                if lname == "isCashCollateral" and (_clean_str(sub.text) or "").upper() == "Y":
                    return True
                if lname == "cashCollateralCondition" and (_clean_str(sub.attrib.get("isCashCollateral")) or "").upper() == "Y":
                    return True
    return False


def _format_openfigi_symbol(ticker: str | None, country: str | None, exch_code: str | None = None) -> str | None:
    t = _clean_str(ticker)
    if not t:
        return None
    c = (_clean_str(country) or "").upper()
    exch = (_clean_str(exch_code) or "").upper()
    if c in {"", "US"} or exch in {"US", "UN", "UW", "UA", "UQ", "UR", "UP"}:
        return t.replace("/", ".").upper()
    base = t.split(".")[0].replace("/", ".").upper()
    return f"{base}.{c}"


def parse_nport_xml(
    xml_bytes: bytes,
    *,
    etf_ticker: str,
    retrieved_at: datetime,
    source_url: str,
    filing_url: str | None = None,
    accession_number: str | None = None,
    fallback_as_of: date | None = None,
    fallback_name: str | None = None,
) -> tuple[RawEtfHoldings, str | None]:
    """Parse an SEC Form N-PORT XML payload into (RawEtfHoldings, xml_series_id)."""
    try:
        root = DefusedET.fromstring(xml_bytes)
    except Exception as exc:
        raise SourceParseError(f"Invalid N-PORT XML for {etf_ticker}: {exc}") from exc

    root_name = _local_name(root.tag).lower()
    if root_name == "html" or (root_name != "edgarsubmission" and _find_first(root, "invstOrSecs") is None):
        raise SourceParseError(f"Unexpected N-PORT XML root <{_local_name(root.tag)}> for {etf_ticker}")

    gen_info = _find_first(root, "genInfo")
    fund_info = _find_first(root, "fundInfo")

    xml_series_id: str | None = None
    if gen_info is not None:
        xml_series_id = _child_text(gen_info, "seriesId")
    if not xml_series_id:
        sc_info = _find_first(root, "seriesClassInfo")
        if sc_info is not None:
            xml_series_id = _child_text(sc_info, "seriesId")

    etf_name: str | None = None
    if gen_info is not None:
        etf_name = _child_text(gen_info, "seriesName") or _child_text(gen_info, "regName")
    etf_name = etf_name or fallback_name

    rep_date_str: str | None = None
    if gen_info is not None:
        rep_date_str = _child_text(gen_info, "repPdDate") or _child_text(gen_info, "repPdEnd")
    as_of: date | None = None
    if rep_date_str:
        try:
            as_of = date.fromisoformat(rep_date_str[:10])
        except ValueError as exc:
            raise SourceParseError(f"Invalid repPdDate {rep_date_str!r} in N-PORT for {etf_ticker}") from exc
    else:
        as_of = fallback_as_of
    if as_of is None:
        raise SourceParseError(f"Missing repPdDate in N-PORT XML for {etf_ticker}")

    net_assets: float | None = None
    if fund_info is not None:
        na_str = _child_text(fund_info, "netAssets")
        if na_str:
            try:
                net_assets = float(na_str)
            except ValueError:
                net_assets = None

    inv_container = _find_first(root, "invstOrSecs")
    inv_nodes = (
        [c for c in inv_container if _local_name(c.tag) == "invstOrSec"]
        if inv_container is not None
        else [n for n in root.iter() if _local_name(n.tag) == "invstOrSec"]
    )
    if not inv_nodes:
        raise SourceParseError(f"N-PORT XML for {etf_ticker} contains no <invstOrSec> entries")

    holdings: list[RawHolding] = []
    warnings: list[str] = []
    skipped_collateral = 0

    for inv in inv_nodes:
        if _is_cash_collateral(inv):
            skipped_collateral += 1
            continue

        name = _child_text(inv, "name") or _child_text(inv, "title")
        lei = _child_text(inv, "lei")
        cusip = _child_text(inv, "cusip")
        if cusip and len(cusip) < 6:
            cusip = None

        isin: str | None = None
        source_symbol: str | None = None
        for child in inv:
            if _local_name(child.tag) == "identifiers":
                for id_node in child:
                    id_tag = _local_name(id_node.tag)
                    if id_tag == "isin":
                        isin = _clean_str(id_node.attrib.get("value")) or _clean_str(id_node.text) or isin
                    elif id_tag == "ticker":
                        source_symbol = (
                            _clean_str(id_node.attrib.get("value")) or _clean_str(id_node.text) or source_symbol
                        )

        val_usd: float | None = None
        val_str = _child_text(inv, "valUSD")
        if val_str:
            try:
                val_usd = float(val_str)
            except ValueError as exc:
                raise SourceParseError(f"Invalid valUSD {val_str!r} in N-PORT for {etf_ticker}") from exc

        pct_str = _child_text(inv, "pctVal")
        weight: float | None = None
        if pct_str is not None:
            try:
                weight = float(pct_str) / 100.0
            except ValueError as exc:
                raise SourceParseError(f"Invalid pctVal {pct_str!r} in N-PORT for {etf_ticker}") from exc
        elif val_usd is not None and net_assets and net_assets > 0:
            weight = val_usd / net_assets
        else:
            raise SourceParseError(f"Missing pctVal and netAssets in N-PORT holding for {etf_ticker}")

        payoff = (_child_text(inv, "payoffProfile") or "").lower()
        if payoff == "short" and weight > 0:
            weight = -weight

        currency = _child_text(inv, "curCd")
        if not currency:
            for child in inv:
                if _local_name(child.tag) == "currencyConditional":
                    currency = _clean_str(child.attrib.get("curCd"))
                    if currency:
                        break

        country = _child_text(inv, "invCountry")
        if country and len(country) != 2:
            country = None

        asset_class = _classify_asset_class(inv)
        if source_symbol:
            source_symbol = _format_openfigi_symbol(source_symbol, country)

        holdings.append(
            RawHolding(
                source_symbol=source_symbol,
                name=name,
                weight=weight,
                asset_class=asset_class,
                country=country,
                currency=currency,
                isin=isin,
                cusip=cusip,
                lei=lei,
                market_value_usd=val_usd,
            )
        )

    if skipped_collateral:
        warnings.append(f"Skipped {skipped_collateral} securities-lending cash collateral line(s)")

    if not holdings:
        raise SourceParseError(f"No usable holdings found in N-PORT XML for {etf_ticker}")

    total_weight = wsum(h.weight for h in holdings)
    if total_weight > RAW_WEIGHT_SUM_MAX:
        raise SourceParseError(
            f"N-PORT weights for {etf_ticker} sum to {total_weight:.4f} (> {RAW_WEIGHT_SUM_MAX})"
        )

    acc_label = f" ({accession_number})" if accession_number else ""
    raw = RawEtfHoldings(
        etf_ticker=etf_ticker.upper(),
        etf_name=etf_name,
        source="sec_nport",
        source_layer="sec_nport",
        as_of=as_of,
        retrieved_at=retrieved_at,
        source_url=source_url,
        filing_url=filing_url,
        attribution=f"SEC EDGAR Form N-PORT{acc_label}, period ended {as_of.isoformat()}",
        licence="Public domain (SEC EDGAR)",
        reported_sector_weights=None,
        holdings=holdings,
        warnings=warnings,
    )
    return raw, xml_series_id


class OpenFigiReference:
    """ReferenceProvider backed by OpenFIGI v3 mapping API (ISIN -> symbol, FIGI, exchange, sector)."""

    def __init__(self, http, settings, *, batch_size: int | None = None) -> None:
        self.http = http
        self.settings = settings
        self.batch_size = batch_size

    def lookup_symbols(self, symbols: Sequence[str]) -> dict[str, SecurityInfo]:
        return {}

    def lookup_isins(self, isins: Sequence[str]) -> dict[str, SecurityInfo]:
        unique_isins = list(dict.fromkeys(i.strip().upper() for i in isins if i and i.strip()))
        if not unique_isins:
            return {}

        api_key = getattr(self.settings, "openfigi_key", None)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["X-OPENFIGI-APIKEY"] = api_key

        max_batch = self.batch_size or (100 if api_key else 10)
        result: dict[str, SecurityInfo] = {}

        for idx in range(0, len(unique_isins), max_batch):
            chunk = unique_isins[idx : idx + max_batch]
            payload = [{"idType": "ID_ISIN", "idValue": isin} for isin in chunk]
            try:
                resp = self.http.post_json(
                    OPENFIGI_MAPPING_URL,
                    payload,
                    source="sec_nport",
                    ttl=TTL_METADATA,
                    headers=headers,
                )
            except SourceUnavailable:
                break

            if resp.status != 200:
                break
            try:
                items = resp.json()
            except (ValueError, TypeError):
                break
            if not isinstance(items, list):
                break

            for isin, entry in zip(chunk, items):
                if not isinstance(entry, dict):
                    continue
                matches = entry.get("data")
                if not isinstance(matches, list) or not matches:
                    continue
                best = matches[0]
                if not isinstance(best, dict):
                    continue
                country = isin[:2] if len(isin) == 12 and isin[:2].isalpha() else None
                exch = _clean_str(best.get("exchCode"))
                symbol = _format_openfigi_symbol(best.get("ticker"), country, exch)
                result[isin] = SecurityInfo(
                    symbol=symbol,
                    name=_clean_str(best.get("name")),
                    figi=_clean_str(best.get("figi")),
                    share_class_figi=_clean_str(best.get("shareClassFIGI")),
                    exchange=exch,
                    country=country,
                    sector_label=_clean_str(best.get("marketSector")),
                )

        return result


class SecNportAdapter:
    name: ClassVar[SourceName] = "sec_nport"

    def __init__(self, http, settings, *, use_openfigi: bool | None = None) -> None:
        self.http = http
        self.settings = settings
        self.use_openfigi = use_openfigi

    def supports(self, ticker: str) -> bool:
        return bool(ticker and ticker.strip())

    def _sec_headers(self) -> dict[str, str]:
        ua = getattr(self.settings, "user_agent", "") or "HouseOfCards-PoC/0.1"
        contact = getattr(self.settings, "sec_contact", None)
        if contact and contact not in ua:
            ua = f"{ua} ({contact})"
        elif "@" not in ua:
            ua = f"{ua} ({DEFAULT_SEC_CONTACT})"
        return {"User-Agent": ua, "Accept": "*/*"}

    def _lookup_ticker_identity(self, ticker: str) -> tuple[int, str | None, str | None, str | None]:
        """Return (cik, series_id, class_id, fallback_name) for ticker."""
        resp = self.http.get(
            MF_TICKERS_URL,
            source=self.name,
            ttl=TTL_METADATA,
            headers=self._sec_headers(),
        )
        if resp.status == 404:
            raise TickerNotFound(f"SEC mutual fund ticker index returned 404 for {ticker}")
        if resp.status >= 400:
            raise SourceUnavailable(f"SEC ticker index failed with HTTP {resp.status}")

        try:
            data = resp.json()
        except Exception as exc:
            raise SourceParseError(f"Malformed SEC company_tickers_mf.json: {exc}") from exc

        if isinstance(data, dict) and "fields" in data and "data" in data:
            fields = data["fields"]
            rows = data["data"]
            if not isinstance(fields, list) or not isinstance(rows, list):
                raise SourceParseError("Invalid structure in SEC company_tickers_mf.json")
            try:
                idx_sym = fields.index("symbol")
                idx_cik = fields.index("cik")
                idx_series = fields.index("seriesId") if "seriesId" in fields else -1
                idx_class = fields.index("classId") if "classId" in fields else -1
            except ValueError as exc:
                raise SourceParseError(f"Missing required fields in company_tickers_mf.json: {exc}") from exc

            for row in rows:
                if not isinstance(row, (list, tuple)) or len(row) <= max(idx_sym, idx_cik):
                    continue
                sym = str(row[idx_sym] or "").strip().upper()
                if sym == ticker:
                    cik = int(row[idx_cik])
                    series_id = _clean_str(str(row[idx_series])) if idx_series >= 0 and len(row) > idx_series else None
                    class_id = _clean_str(str(row[idx_class])) if idx_class >= 0 and len(row) > idx_class else None
                    return cik, series_id, class_id, None
        elif isinstance(data, dict):
            for entry in data.values():
                if isinstance(entry, dict) and str(entry.get("symbol") or entry.get("ticker") or "").strip().upper() == ticker:
                    cik = int(entry.get("cik") or entry.get("cik_str"))
                    return cik, _clean_str(entry.get("seriesId")), _clean_str(entry.get("classId")), _clean_str(entry.get("title"))
        else:
            raise SourceParseError("Unexpected root JSON type in SEC company_tickers_mf.json")

        if ticker in KNOWN_UIT_CIKS:
            cik, name = KNOWN_UIT_CIKS[ticker]
            return cik, None, None, name

        raise TickerNotFound(f"Ticker {ticker} not found in SEC company_tickers_mf.json")

    def _extract_submission_candidates(self, sub_data: Any, ticker: str) -> list[tuple[str, str, str, str]]:
        """Return list of (report_date, filing_date, accession_number, primary_doc) sorted newest first."""
        if not isinstance(sub_data, dict):
            raise SourceParseError(f"Malformed SEC submissions JSON for {ticker}")
        filings = sub_data.get("filings")
        recent = filings.get("recent") if isinstance(filings, dict) else None
        if not isinstance(recent, dict):
            raise SourceParseError(f"Missing filings.recent in SEC submissions JSON for {ticker}")

        forms = recent.get("form")
        accs = recent.get("accessionNumber")
        f_dates = recent.get("filingDate")
        r_dates = recent.get("reportDate")
        docs = recent.get("primaryDocument")

        if not isinstance(forms, list) or not isinstance(accs, list):
            raise SourceParseError(f"Invalid filings.recent arrays in SEC submissions JSON for {ticker}")

        candidates: list[tuple[str, str, str, str]] = []
        for i, form in enumerate(forms):
            form_str = str(form or "").strip().upper()
            if form_str not in {"NPORT-P", "NPORT-P/A"}:
                continue
            acc = str(accs[i] if i < len(accs) else "").strip()
            if not acc:
                continue
            f_date = str(f_dates[i] if isinstance(f_dates, list) and i < len(f_dates) else "").strip()
            r_date = str(r_dates[i] if isinstance(r_dates, list) and i < len(r_dates) else "").strip()
            doc = str(docs[i] if isinstance(docs, list) and i < len(docs) else "primary_doc.xml").strip() or "primary_doc.xml"
            candidates.append((r_date, f_date, acc, doc))

        candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return candidates

    def _fetch_filing_xml(self, cik: int, acc: str, primary_doc: str):
        acc_nodash = acc.replace("-", "")
        raw_doc = primary_doc.rsplit("/", 1)[-1] if "/" in primary_doc else primary_doc
        urls = [ARCHIVE_XML_URL_TPL.format(cik_int=int(cik), acc_nodash=acc_nodash, doc=raw_doc)]
        if primary_doc != raw_doc:
            urls.append(ARCHIVE_XML_URL_TPL.format(cik_int=int(cik), acc_nodash=acc_nodash, doc=primary_doc))
        if raw_doc != "primary_doc.xml":
            urls.append(ARCHIVE_XML_URL_TPL.format(cik_int=int(cik), acc_nodash=acc_nodash, doc="primary_doc.xml"))

        last_err: Exception | None = None
        for url in dict.fromkeys(urls):
            try:
                resp = self.http.get(url, source=self.name, ttl=None, headers=self._sec_headers())
            except SourceUnavailable as exc:
                last_err = exc
                continue
            if resp.status == 404:
                last_err = TickerNotFound(f"N-PORT XML not found at {url}")
                continue
            if resp.status >= 400:
                raise SourceUnavailable(f"SEC Archive returned HTTP {resp.status} for {url}")
            return resp

        if isinstance(last_err, TickerNotFound):
            raise last_err
        raise SourceUnavailable(f"Unable to fetch N-PORT XML for accession {acc}: {last_err}")

    def _lookup_series_atom_accession(self, series_id: str) -> str | None:
        url = SERIES_ATOM_URL_TPL.format(series_id=series_id)
        try:
            resp = self.http.get(url, source=self.name, ttl=TTL_METADATA, headers=self._sec_headers())
        except SourceUnavailable:
            return None
        if resp.status != 200:
            return None
        txt = resp.text()
        m = re.search(r"<accession-number>\s*([0-9-]+)\s*</accession-number>", txt)
        return m.group(1).strip() if m else None

    def _maybe_enrich_openfigi(self, raw: RawEtfHoldings) -> RawEtfHoldings:
        should_run = self.use_openfigi if self.use_openfigi is not None else bool(getattr(self.settings, "openfigi_key", None))
        if not should_run:
            return raw

        need_isins = [h.isin for h in raw.holdings if h.isin and not h.source_symbol]
        if not need_isins:
            return raw

        ref = OpenFigiReference(self.http, self.settings)
        mapped = ref.lookup_isins(need_isins)
        if not mapped:
            return raw

        updated: list[RawHolding] = []
        for h in raw.holdings:
            info = mapped.get(h.isin) if h.isin else None
            if info is not None:
                updated.append(
                    h.model_copy(
                        update={
                            "source_symbol": h.source_symbol or info.symbol,
                            "figi": h.figi or info.share_class_figi or info.figi,
                            "exchange": h.exchange or info.exchange,
                        }
                    )
                )
            else:
                updated.append(h)
        return raw.model_copy(update={"holdings": updated})

    def fetch(self, ticker: str) -> RawEtfHoldings:
        clean_ticker = (ticker or "").strip().upper()
        if not clean_ticker:
            raise TickerNotFound("Empty ticker")

        cik, series_id, _class_id, fallback_name = self._lookup_ticker_identity(clean_ticker)

        sub_url = SUBMISSIONS_URL_TPL.format(cik=int(cik))
        sub_resp = self.http.get(
            sub_url,
            source=self.name,
            ttl=TTL_METADATA,
            headers=self._sec_headers(),
        )
        if sub_resp.status == 404:
            raise TickerNotFound(f"No SEC submissions found for {clean_ticker} (CIK {cik:010d})")
        if sub_resp.status >= 400:
            raise SourceUnavailable(f"SEC submissions failed with HTTP {sub_resp.status} for {clean_ticker}")

        try:
            sub_json = sub_resp.json()
        except Exception as exc:
            raise SourceParseError(f"Malformed SEC submissions JSON for {clean_ticker}: {exc}") from exc

        sub_entity_name = _clean_str(sub_json.get("name")) if isinstance(sub_json, dict) else None
        candidates = self._extract_submission_candidates(sub_json, clean_ticker)
        if not candidates:
            raise TickerNotFound(f"No NPORT-P filings found in SEC submissions for {clean_ticker}")

        for idx, (r_date, _f_date, acc, doc) in enumerate(candidates[:10]):
            xml_resp = self._fetch_filing_xml(cik, acc, doc)
            fallback_date: date | None = None
            if r_date:
                try:
                    fallback_date = date.fromisoformat(r_date[:10])
                except ValueError:
                    fallback_date = None

            acc_nodash = acc.replace("-", "")
            filing_url = ARCHIVE_INDEX_URL_TPL.format(cik_int=int(cik), acc_nodash=acc_nodash, acc=acc)
            raw, xml_series_id = parse_nport_xml(
                xml_resp.body,
                etf_ticker=clean_ticker,
                retrieved_at=xml_resp.fetched_at,
                source_url=xml_resp.url,
                filing_url=filing_url,
                accession_number=acc,
                fallback_as_of=fallback_date,
                fallback_name=fallback_name or sub_entity_name,
            )

            if series_id is None or xml_series_id is None or xml_series_id.upper() == series_id.upper():
                return self._maybe_enrich_openfigi(raw)

            # Multi-series trust mismatch on the first candidate: check if EDGAR series Atom feed is available.
            if idx == 0:
                atom_acc = self._lookup_series_atom_accession(series_id)
                if atom_acc and atom_acc != acc:
                    atom_xml_resp = self._fetch_filing_xml(cik, atom_acc, "primary_doc.xml")
                    atom_nodash = atom_acc.replace("-", "")
                    atom_filing_url = ARCHIVE_INDEX_URL_TPL.format(
                        cik_int=int(cik), acc_nodash=atom_nodash, acc=atom_acc
                    )
                    atom_raw, atom_series_id = parse_nport_xml(
                        atom_xml_resp.body,
                        etf_ticker=clean_ticker,
                        retrieved_at=atom_xml_resp.fetched_at,
                        source_url=atom_xml_resp.url,
                        filing_url=atom_filing_url,
                        accession_number=atom_acc,
                        fallback_as_of=fallback_date,
                        fallback_name=fallback_name or sub_entity_name,
                    )
                    if atom_series_id is None or atom_series_id.upper() == series_id.upper():
                        return self._maybe_enrich_openfigi(atom_raw)

        raise TickerNotFound(f"No NPORT-P filing matching series {series_id} found for {clean_ticker}")
