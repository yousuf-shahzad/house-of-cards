"""FIX-67: synthetic weights with real listing metadata; no network requests."""

import json
from datetime import UTC, datetime

import pytest

from hoc.config import Settings
from hoc.contract import PortfolioRequest, ShockBasis, StressRequest
from hoc.core.http import FakeHttpClient
from hoc.identity.resolver import load_aliases
from hoc.normalise.pipeline import normalise_etf
from hoc.portfolio.analyse import analyse
from hoc.portfolio.stress import simulate_failure
from hoc.sources.tickerinside.adapter import TickerInsideAdapter
from hoc.sources.tickerinside.files import country_of
from hoc.sources.tickerinside.reference import TickerInsideReference

BASE = "https://tickerinside.com/api/v1"
NOW = datetime(2026, 11, 8, tzinfo=UTC)


@pytest.mark.parametrize(("symbol", "exchange", "name", "asset_type", "expected"), [
    ("AAPL", "Nasdaq", "Apple Inc.", "stock", "US"),
    ("NVDA", "Nasdaq", "Nvidia", "stock", "US"),
    ("MSFT", "Nasdaq", "Microsoft", "stock", "US"),
    ("BRK.B", "NYSE", "Berkshire Hathaway", "stock", "US"),
    ("ZZ", "NYSE American", "ZZ Inc.", "stock", "US"),
    ("ZZ", "Cboe BZX", "ZZ Inc.", "stock", "US"),
    ("ZZ", "TXSE", "ZZ Inc.", "stock", "US"),
    ("2330.TW", None, "Taiwan Semiconductor", "stock", "TW"),
    ("TSM", "NYSE", "Taiwan Semiconductor Manufacturing Company Ltd.", "stock", None),
    ("ASML", "Nasdaq", "ASML Holding N.V.", "stock", None),
    ("ARM", "Nasdaq", "Arm Holdings plc - American Depositary Shares", "stock", None),
    ("ARM", "Nasdaq", "Arm Holdings plc", "stock", None),
    ("PDD", "Nasdaq", "PDD Holdings Inc.", "stock", None),
    ("ZZADR", "NYSE", "ZZ Sponsored ADR", "stock", None),
    ("ZZADR", "NYSE", "ZZ Inc.", "adr", None),
    ("ZZADR", "Nasdaq", "ZZ American Depository Shares", "stock", None),
    ("ZZREG", "Nasdaq", "ZZ - New York Registry Shares", "stock", None),
    ("ZZ", None, "ZZ Inc.", "stock", None),
    ("ZZ", "Unknown exchange", "ZZ Inc.", "stock", None),
    ("ZZ", "Nasdaq OMX Helsinki", "ZZ Inc.", "stock", None),
])
def test_country_requires_exchange_and_excludes_receipts(symbol, exchange, name, asset_type, expected):
    assert country_of(symbol, {"exchange": exchange, "name": name, "asset_type": asset_type}) == expected


@pytest.fixture
def country_fund():
    # Invented allocations, with TSM's deliberately unmarked name and ARM marked only in securities.json.
    names = {"AAPL": "Apple Inc.", "TSM": "Taiwan Semiconductor Manufacturing Company Ltd.",
             "2330.TW": "Taiwan Semiconductor", "ASML": "ASML Holding N.V.",
             "ARM": "Arm Holdings plc American Depositary Shares"}
    http = FakeHttpClient()
    http.add(f"{BASE}/fund/zzcountry.json", json.dumps({
        "holdings_as_of": "2026-11-05",
        "holdings": {"AAPL": 40, "TSM": 20, "2330.TW": 20, "ASML": 10, "ARM": 10},
    }))
    http.add(f"{BASE}/securities.json", json.dumps({
        "securities": [[s, 1, 1, name, 0, 0] for s, name in names.items()],
    }))
    http.add(f"{BASE}/identifiers.json", json.dumps({
        "fields": ["ticker", "name", "asset_type", "exchange"],
        "securities": [[s, s, "stock", "NYSE" if s == "TSM" else "Nasdaq"]
                       for s in names if s != "2330.TW"],
    }))
    settings = Settings()
    raw = TickerInsideAdapter(http, settings).fetch("ZZCOUNTRY")
    reference = TickerInsideReference(http, settings)
    return raw, reference


def test_adapter_reference_normalisation_and_company_countries(country_fund):
    raw, reference = country_fund
    expected = {"AAPL": "US", "TSM": None, "2330.TW": "TW", "ASML": None, "ARM": None}
    assert {h.source_symbol: h.country for h in raw.holdings} == expected
    assert {s: h.country for s, h in reference.lookup_symbols(list(expected)).items()} == expected
    etf = normalise_etf(raw, reference, load_aliases())
    request = PortfolioRequest(holdings=[{"ticker": "ZZCOUNTRY", "allocation": 1}])
    result = analyse(request, {"ZZCOUNTRY": etf}, {}, today=NOW.date(), generated_at=NOW)
    companies = {c.company_key: c for c in result.exposures}
    assert companies["SYM:AAPL"].country == "US"
    assert companies["ALIAS:TSMC"].country == "TW"
    assert companies["ALIAS:TSMC"].exposure == pytest.approx(0.4)
    assert companies["ALIAS:ASML"].country is None
    assert companies["SYM:ARM"].country is None
    stress = simulate_failure(
        StressRequest(baseline=request.holdings, shock={"kind": "country", "key": "US"}),
        result, None, ShockBasis(source="simulated", drop=0.2, description="Synthetic test fall"),
    )
    assert stress.baseline.affected_weight == pytest.approx(0.4)
    assert stress.baseline.loss_fraction == pytest.approx(0.08)
    assert any("20.00%" in note and "don't know the country" in note for note in stress.notes)


def test_adr_only_portfolio_is_not_us(country_fund):
    raw, reference = country_fund
    adr = next(h for h in raw.holdings if h.source_symbol == "TSM").model_copy(update={"weight": 1})
    etf = normalise_etf(raw.model_copy(update={"holdings": [adr]}), reference, load_aliases())
    request = PortfolioRequest(holdings=[{"ticker": "ZZCOUNTRY", "allocation": 1}])
    result = analyse(request, {"ZZCOUNTRY": etf}, {}, today=NOW.date(), generated_at=NOW)
    assert result.exposures[0].country is None


@pytest.mark.parametrize(("reported", "expected"), [(None, "NL"), ("NL", "NL"), ("US", "US")])
@pytest.mark.parametrize("inferred", [None, "US"])
def test_company_country_prefers_reported_then_overseas_listing(country_fund, reported, expected, inferred):
    raw, reference = country_fund
    etf = normalise_etf(raw, reference, load_aliases())
    # ASML sorts before ASML.NL: a US fallback must not hide the local security's country.
    base = next(h for h in etf.holdings if h.symbol == "ASML")
    us = base.model_copy(update={"country": inferred, "weight": 0.5})
    local = base.model_copy(update={"symbol": "ASML.NL", "security_key": "SYM:ASML.NL",
                                    "country": "NL", "weight": 0.5})
    lines = [us, local]
    if reported:
        lines[0] = us.model_copy(update={"country": reported, "source": "ishares"})
    etf = etf.model_copy(update={"holdings": lines})
    request = PortfolioRequest(holdings=[{"ticker": "ZZCOUNTRY", "allocation": 1}])
    for order in (lines, lines[::-1]):
        result = analyse(request, {"ZZCOUNTRY": etf.model_copy(update={"holdings": order})}, {},
                         today=NOW.date(), generated_at=NOW)
        assert result.exposures[0].country == expected
        assert result.exposures[0].exposure == pytest.approx(1)
