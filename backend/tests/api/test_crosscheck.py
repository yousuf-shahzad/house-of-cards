"""V1: scripts/crosscheck_tickerinside.py over SYNTHETIC fixtures and invented TickerInside answers."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

import hoc.service
from hoc.contract import PortfolioItem, PortfolioRequest
from hoc.core.http import FakeHttpClient

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "crosscheck_tickerinside.py"
BASE = "https://tickerinside.com/api/v1"


def load_script():
    spec = importlib.util.spec_from_file_location("crosscheck_tickerinside", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve string annotations through sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def service(make_service, monkeypatch):
    """Fake-backed service whose stand-in normaliser merges ZZBET.A/ZZBET.B into one company."""
    service, _ = make_service()
    base = hoc.service.normalise_etf

    def merging(raw, reference, aliases):
        etf = base(raw, reference, aliases)
        holdings = [h.model_copy(update={"company_key": "SYM:ZZBET"}) if (h.symbol or "").startswith("ZZBET.")
                    else h for h in etf.holdings]
        return etf.model_copy(update={"holdings": holdings})

    monkeypatch.setattr("hoc.service.normalise_etf", merging)
    return service


def fake_tickerinside() -> FakeHttpClient:
    http = FakeHttpClient()
    http.add(f"{BASE}/lookthrough?portfolio=ZZAAA:50,ZZBBB:30,ZZCCC:20&top=50", json.dumps(
        {"error": "bad_request", "reason": "too_large", "limit": {"chars": 300},
         "files": {"ZZAAA": 100, "ZZBBB": 100, "ZZCCC": 500}}), status=400)
    http.add(f"{BASE}/lookthrough?portfolio=ZZAAA:50,ZZBBB:30&top=50", json.dumps({
        "portfolio_value": 80, "looked_through_pct": 100, "distinct_companies": 6, "top_10_weight_pct": 99.0,
        "holdings_as_of": {"ZZAAA": "2026-11-05", "ZZBBB": "2026-06-30"},
        "companies": [
            {"ticker": "ZZALP", "weight_pct": 33.75},   # 27% of the portfolio: matches ours
            {"ticker": "ZZBET.B", "weight_pct": 17.5},  # 14%: ours is 19% because we merge ZZBET.A into it
            {"ticker": "ZZNOPE", "weight_pct": 1.0},    # a ticker we do not have
        ]}))
    http.add(f"{BASE}/overlap?funds=ZZAAA,ZZBBB,ZZCCC", json.dumps({
        "kind": "matrix",
        "holdings_as_of": {"ZZAAA": "2026-11-05", "ZZBBB": "2026-06-30", "ZZCCC": "2026-10-30"},
        "pairs": [{"pair": ["ZZAAA", "ZZBBB"], "by_weight": 50.0, "companies_in_both": 2},
                  {"pair": ["ZZAAA", "ZZCCC"], "by_weight": 25.0, "companies_in_both": 1}]}))
    return http


REQUEST = PortfolioRequest(holdings=[PortfolioItem(ticker="ZZAAA", allocation=0.5),
                                     PortfolioItem(ticker="ZZBBB", allocation=0.3),
                                     PortfolioItem(ticker="ZZCCC", allocation=0.2)])


def test_too_large_lookthrough_drops_the_largest_file_once():
    script, http = load_script(), fake_tickerinside()
    answer, skipped = script.fetch_lookthrough(http, {"ZZAAA": 0.5, "ZZBBB": 0.3, "ZZCCC": 0.2})
    assert skipped == ["ZZCCC"] and answer["portfolio_value"] == 80
    assert len(http.requests) == 2


def test_compare_explains_each_difference(service):
    script, http = load_script(), fake_tickerinside()
    lookthrough, skipped = script.fetch_lookthrough(http, {"ZZAAA": 0.5, "ZZBBB": 0.3, "ZZCCC": 0.2})
    overlap = script._get(http, "overlap", {"funds": "ZZAAA,ZZBBB,ZZCCC"})[1]
    report = script.compare(service.analyse(REQUEST), lookthrough, skipped, overlap, "zz")
    rows = {r.label: r for r in report.exposures}
    assert rows["ZZALP"].theirs == pytest.approx(27) and rows["ZZALP"].diff == pytest.approx(0, abs=1e-9)
    assert rows["ZZALP"].note == "rounding"
    assert rows["ZZBET.B"].diff == pytest.approx(5) and "merge ZZBET.A+ZZBET.B" in rows["ZZBET.B"].note
    assert rows["ZZNOPE"].ours is None
    pairs = {r.label: r for r in report.overlap}
    assert pairs["ZZAAA / ZZBBB"].diff == pytest.approx(0, abs=1e-9)
    assert "holdings dates differ" in pairs["ZZAAA / ZZCCC"].note  # ours 2026-10-31, theirs 2026-10-30
    assert report.skipped_funds == ["ZZCCC"] and report.lookthrough_funds == ["ZZAAA", "ZZBBB"]


def test_run_renders_markdown_with_three_fetches(service):
    script, http = load_script(), fake_tickerinside()
    text = script.run(service, http, REQUEST, "zz")
    assert "| ZZBET.B | 14.0000 | 19.0000 | 5.0000 |" in text
    assert "left out: ZZCCC" in text and "CC BY 4.0" in text
    assert len(http.requests) == 3
