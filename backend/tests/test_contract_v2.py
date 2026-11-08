"""v2 contract: prices, valuation and dependency models, plus the frontend mock fixtures stay consistent."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from hoc.config import Settings
from hoc.contract import (
    DependencyJob,
    DependencyRequest,
    PriceQuote,
    ValuationResponse,
    ValuationRow,
    wsum,
)

FIXTURES = Path(__file__).resolve().parents[2] / "frontend" / "api" / "__fixtures__"


def _load(name: str) -> dict:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    data.pop("_comment", None)
    return data


@pytest.mark.parametrize("bad", [0, -1, math.nan, math.inf])
def test_price_quote_rejects_non_positive_or_non_finite(bad):
    with pytest.raises(ValidationError):
        PriceQuote(price=bad, currency="USD", as_of="2026-11-06", source="tickerinside")


def test_price_quote_currency_is_iso_4217():
    with pytest.raises(ValidationError):
        PriceQuote(price=1.0, currency="usd", as_of="2026-11-06", source="tickerinside")


def test_valuation_row_rules():
    row = ValuationRow(ticker="ivv", shares=12.5)
    assert row.ticker == "IVV" and row.allocation_override is None
    for bad in [{"shares": -1}, {"shares": math.inf}, {"allocation_override": 1.2}, {"allocation_override": -0.1}]:
        with pytest.raises(ValidationError):
            ValuationRow(ticker="IVV", **bad)


def test_dependency_request_top_n_bounds():
    with pytest.raises(ValidationError):
        DependencyRequest(holdings=[{"ticker": "IVV", "allocation": 1}], top_n=31)
    assert DependencyRequest(holdings=[{"ticker": "IVV", "allocation": 1}]).top_n == 15


def test_valuation_fixture_reconciles():
    v = ValuationResponse.model_validate(_load("synthetic-valuation.json"))
    assert v.status == "usable" and all(r.allocation is not None for r in v.rows)
    assert math.isclose(wsum(r.allocation for r in v.rows), 1.0, abs_tol=1e-9)
    assert math.isclose(v.pinned_total, wsum(r.allocation for r in v.rows if r.pinned), abs_tol=1e-9)
    unpinned = [r for r in v.rows if not r.pinned]
    assert math.isclose(v.total_value, wsum(r.value for r in unpinned), abs_tol=1e-6)
    for r in unpinned:  # allocation_i = (1 - P) * V_i / sum(V)
        assert math.isclose(r.allocation, (1 - v.pinned_total) * r.value / v.total_value, abs_tol=1e-9)
        assert math.isclose(r.value, r.shares * r.price.price, abs_tol=1e-6)
    assert all(r.price.source == "fake" for r in unpinned), "mock fixture must be labelled synthetic"


def test_dependencies_fixture_is_internally_consistent():
    job = DependencyJob.model_validate(_load("synthetic-dependencies.json"))
    r = job.result
    assert job.status == "done" and r is not None
    edge_ids = {e.edge_id for e in r.edges}
    metric_ids = {m.metric_id for m in r.metrics}
    assert len(edge_ids) == len(r.edges), "edge ids must be unique"
    assert all(set(m.supporting_edge_ids) <= edge_ids for m in r.metrics)
    for claim in r.insights.flaws + r.insights.suggestions:
        assert set(claim.cited_metric_ids) <= metric_ids and set(claim.cited_edge_ids) <= edge_ids
    assert r.counts.verified_edges == len(r.edges)
    assert all(e.evidence_quote.strip() for e in r.edges)
    assert all(e.filing.url.startswith("https://example.invalid/") for e in r.edges), "synthetic only"


def test_gemini_key_is_read_from_env_and_never_shown():
    s = Settings.from_env({"GEMINI_API_KEY": "sk-test-not-real", "HOC_DEPS_TOP_N": "99"})
    assert s.gemini_api_key == "sk-test-not-real"
    assert "sk-test-not-real" not in repr(s)
    assert s.deps_top_n == 15 and s.gemini_extractor_model == "gemini-3.8-flash"
    assert Settings.from_env({}).gemini_api_key is None
