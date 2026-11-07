"""Package a: TickerInside adapter + reference over SYNTHETIC answers (FakeHttpClient, no network).

Shapes copy the real files read on 2026-11-07; every ticker, name and number here is invented.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from hoc.config import Settings
from hoc.contract import SourceParseError, SourceUnavailable, TickerNotFound
from hoc.core.http import FakeHttpClient
from hoc.identity.resolver import Aliases
from hoc.normalise.pipeline import normalise_etf
from hoc.sources.tickerinside.adapter import TickerInsideAdapter
from hoc.sources.tickerinside.reference import TickerInsideReference

BASE = "https://tickerinside.com/api/v1"
CITE = "TickerInside, SYNTHETIC Fund (ZZTI), holdings from the issuer's file of 2026-11-05, CC BY 4.0"

FUND = {
    "ticker": "ZZTI", "name": "SYNTHETIC Fund", "page_url": "https://example.invalid/etf/zzti/",
    "cite_as": CITE, "license": "CC BY 4.0", "source_layer": "issuer",
    "as_of": "2026-11-06", "holdings_as_of": "2026-11-05",
    "breakdown": {"sectors_pct": {"technology": 60.0, "financials": 39.9}},
    "holdings": {"ZZALP": 40.0, "ZZBET.A": 20.0, "ZZBET.B": 20.0, "9999.TW": 15.0, "ZZFND": 4.9, "ZZXZ6": 0.1},
}
SECURITIES = {"securities": [
    ["ZZALP", 3, 40.0, "ZZ Alpha Corp", 1, 1], ["ZZBET.A", 2, 20.0, "ZZ Beta Class A", 1, 1],
    ["ZZBET.B", 2, 20.0, "ZZ Beta Class B", 1, 1], ["9999.TW", 1, 15.0, "ZZ Epsilon Semi", 0, 0],
    ["ZZXZ6", 1, 0.1, "ZZ Index Dec26", 0, 0],
]}
FIELDS = ["ticker", "name", "asset_type", "exchange", "composite_figi", "share_class_figi", "cik", "series_id", "class_id"]
IDENTIFIERS = {"fields": FIELDS, "securities": [
    ["ZZALP", "ZZ Alpha Corp", "stock", "Nasdaq", "ZZFIGI1", "ZZSCF1", "9990000001", None, None],
    ["ZZBET.A", "ZZ Beta Class A", "stock", "NYSE", "ZZFIGI2", "ZZSCF2", "9990000002", None, None],
    ["ZZBET.B", "ZZ Beta Class B", "stock", "NYSE", "ZZFIGI3", "ZZSCF3", "9990000002", None, None],
    ["ZZFND", "ZZ Inner Fund", "etf", "NYSE Arca", "ZZFIGI4", "ZZSCF4", "9990000009", "S9", "C9"],
]}


def client(fund=FUND, refs=True) -> FakeHttpClient:
    http = FakeHttpClient()
    http.add(f"{BASE}/fund/zzti.json", json.dumps(fund), content_type="application/json")
    if refs:
        http.add(f"{BASE}/securities.json", json.dumps(SECURITIES), content_type="application/json")
        http.add(f"{BASE}/identifiers.json", json.dumps(IDENTIFIERS), content_type="application/json")
    return http


def test_fetch_parses_fund_file():
    raw = TickerInsideAdapter(client(), Settings()).fetch("zzti")
    assert (raw.etf_ticker, raw.source, raw.source_layer) == ("ZZTI", "tickerinside", "issuer")
    assert raw.as_of == date(2026, 11, 5)  # holdings_as_of, not the build date
    assert raw.attribution == CITE and raw.licence == "CC BY 4.0"
    lines = {h.source_symbol: h for h in raw.holdings}
    assert lines["ZZALP"].weight == pytest.approx(0.40)
    assert lines["ZZALP"].name == "ZZ Alpha Corp" and lines["ZZALP"].cik == "9990000001"
    assert lines["ZZXZ6"].asset_class == "derivative"
    assert lines["ZZFND"].asset_class == "fund"
    assert lines["9999.TW"].country == "TW" and lines["ZZBET.B"].country is None
    assert raw.reported_sector_weights == pytest.approx({"technology": 0.60, "financials": 0.399})
    assert raw.warnings == []


def test_unknown_fund_and_errors():
    http = client()
    http.add(f"{BASE}/fund/zznope.json", "Not found", status=404)
    adapter = TickerInsideAdapter(http, Settings())
    with pytest.raises(TickerNotFound):
        adapter.fetch("ZZNOPE")
    http = FakeHttpClient()
    http.add(f"{BASE}/fund/zzti.json", "oops", status=503)
    with pytest.raises(SourceUnavailable):
        TickerInsideAdapter(http, Settings()).fetch("ZZTI")
    http = FakeHttpClient()
    http.add(f"{BASE}/fund/zzti.json", "<html>not json</html>", content_type="text/html")
    with pytest.raises(SourceParseError):
        TickerInsideAdapter(http, Settings()).fetch("ZZTI")
    with pytest.raises(SourceParseError):
        TickerInsideAdapter(client({**FUND, "holdings": {}}), Settings()).fetch("ZZTI")


def test_missing_reference_files_still_return_holdings():
    raw = TickerInsideAdapter(client(refs=False), Settings()).fetch("ZZTI")
    assert len(raw.holdings) == 6 and raw.holdings[0].name is None
    assert any("reference files unavailable" in w for w in raw.warnings)
    assert TickerInsideReference(client(refs=False), Settings()).lookup_symbols(["ZZALP"]) == {}


def test_reference_lookup():
    ref = TickerInsideReference(client(), Settings())
    found = ref.lookup_symbols(["ZZALP", "9999.TW", "ZZNONE"])
    assert set(found) == {"ZZALP", "9999.TW"}
    assert (found["ZZALP"].cik, found["ZZALP"].figi, found["ZZALP"].exchange) == ("9990000001", "ZZFIGI1", "Nasdaq")
    assert found["9999.TW"].country == "TW" and found["9999.TW"].cik is None
    assert ref.lookup_isins(["ZZ0000000001"]) == {}


def test_through_normaliser_merges_share_classes_by_cik():
    http, settings = client(), Settings()
    etf = normalise_etf(TickerInsideAdapter(http, settings).fetch("ZZTI"), TickerInsideReference(http, settings),
                        Aliases())
    keys = {h.symbol: h.company_key for h in etf.holdings}
    assert keys["ZZBET.A"] == keys["ZZBET.B"] == "CIK:9990000002"
    assert etf.excluded_weight == pytest.approx(0.001)
    assert etf.sector_basis == "fund_reported"


@pytest.mark.live
def test_live_xlk(tmp_path):
    from hoc.core.cache import DiskCache
    from hoc.core.http import CachedHttpClient

    settings = Settings(cache_dir=tmp_path)
    http = CachedHttpClient(settings, DiskCache(tmp_path))
    raw = TickerInsideAdapter(http, settings).fetch("XLK")
    assert raw.attribution and len(raw.holdings) > 50
    assert sum(h.weight for h in raw.holdings) == pytest.approx(1, abs=0.02)
    etf = normalise_etf(raw, TickerInsideReference(http, settings), Aliases())
    assert etf.holdings_weight > 0.95


def test_stock_sectors_fetched_for_heaviest_symbols(monkeypatch):
    import hoc.sources.tickerinside.reference as reference_module

    monkeypatch.setattr(reference_module, "SECTOR_LOOKUP_LIMIT", 2)
    http = client()
    http.add(f"{BASE}/sec/zzalp.json", json.dumps({"sector": "Information Technology"}), content_type="application/json")
    http.add(f"{BASE}/sec/zzbet.a.json", json.dumps({"sector": "Financials"}), content_type="application/json")
    http.add(f"{BASE}/sec/zzbet.b.json", "missing", status=404)
    settings = Settings()
    ref = TickerInsideReference(http, settings)
    etf = normalise_etf(TickerInsideAdapter(http, settings).fetch("ZZTI"), ref, Aliases())
    sectors = {h.symbol: (h.sector, h.sector_source) for h in etf.holdings}
    assert sectors["ZZALP"] == ("information_technology", "reference")
    assert sectors["ZZBET.A"] == ("financials", "reference")  # 2nd heaviest (tie with ZZBET.B, by symbol)
    assert sectors["ZZBET.B"] == ("unknown", "none")  # beyond the limit: never requested
    assert not any("zzbet.b" in url or "9999.tw" in url for _, url in http.requests)
    calls = len(http.requests)
    ref.lookup_symbols(["ZZALP"])
    assert len(http.requests) == calls  # memoised per stock


@pytest.mark.parametrize("breakdown", [{"sectors_pct": {"tech": "unavailable"}}, "temporarily unavailable",
                                       {"sectors_pct": ["tech"]}, {"sectors_pct": {"tech": "nan"}}])
def test_malformed_sector_breakdown_is_dropped_with_a_warning(breakdown):
    raw = TickerInsideAdapter(client({**FUND, "breakdown": breakdown}), Settings()).fetch("ZZTI")
    assert raw.reported_sector_weights is None and len(raw.holdings) == 6
    assert any("sector breakdown is malformed" in w for w in raw.warnings)


@pytest.mark.parametrize("fund", [{**FUND, "holdings": {"ZZALP": "nan"}}, {**FUND, "cite_as": ["not", "text"]},
                                  [1, 2, 3], {**FUND, "holdings_as_of": None}])
def test_malformed_fund_files_raise_parse_error(fund):
    with pytest.raises(SourceParseError):
        TickerInsideAdapter(client(fund), Settings()).fetch("ZZTI")
