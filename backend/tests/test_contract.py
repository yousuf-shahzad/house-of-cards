"""The frozen contract itself: units, models, fixtures and the frontend mock stay consistent."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from hoc.contract import (
    AnalysisResponse,
    PortfolioItem,
    PortfolioRequest,
    PortfolioValidationError,
    RawEtfHoldings,
    Weight,
    wsum,
)

FRONTEND_FIXTURE = Path(__file__).resolve().parents[2] / "frontend" / "api" / "__fixtures__" / "synthetic-analysis.json"


def test_offline_tests_cannot_open_network_connections():
    import socket

    with pytest.raises(RuntimeError, match="Network access in an offline test"):
        socket.create_connection(("example.com", 443), timeout=1)


def test_weight_serialises_to_ten_decimals():
    assert TypeAdapter(Weight).dump_python(0.1 + 0.2, mode="json") == 0.3
    assert TypeAdapter(Weight).dump_python(0.012345678912345, mode="json") == 0.0123456789


def test_wsum_is_order_independent():
    values = [0.1] * 10 + [1e-12, 0.3333333333, 0.6666666667]
    shuffled = values[:]
    random.Random(7).shuffle(shuffled)
    assert wsum(values) == wsum(shuffled) == math.fsum(values)


def test_portfolio_item_uppercases_and_checks_ticker():
    assert PortfolioItem(ticker="ivv", allocation=0.4).ticker == "IVV"
    assert PortfolioItem(ticker="brk.b", allocation=0.1).ticker == "BRK.B"
    for bad in ["", "IVV QQQ", "A" * 13, "IVV;DROP"]:
        with pytest.raises(ValidationError):
            PortfolioItem(ticker=bad, allocation=0.5)


@pytest.mark.parametrize("allocation", [-0.01, 1.01])
def test_portfolio_item_allocation_is_a_fraction(allocation):
    with pytest.raises(ValidationError):
        PortfolioItem(ticker="IVV", allocation=allocation)


def test_portfolio_request_schema_is_lenient_business_rules_are_not():
    # Sum/duplicate/count rules are hoc.portfolio.validation's job (own error codes), not schema errors.
    PortfolioRequest(holdings=[PortfolioItem(ticker="IVV", allocation=0.3)] * 2)
    with pytest.raises(ValidationError):
        PortfolioRequest(holdings=[])


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        PortfolioRequest.model_validate({"holdings": [{"ticker": "IVV", "allocation": 1}], "x": 1})


def test_error_response_shape():
    err = PortfolioValidationError("ALLOCATION_SUM_INVALID", "Allocations total 90%", {"total": 0.9})
    assert err.status == 422
    assert err.to_response().model_dump() == {
        "error": {"code": "ALLOCATION_SUM_INVALID", "message": "Allocations total 90%", "details": {"total": 0.9}}
    }


def test_synthetic_raw_fixtures_validate(synthetic_dir):
    files = sorted((synthetic_dir / "raw").glob("*.json"))
    assert files, "no synthetic raw fixtures"
    for path in files:
        raw = RawEtfHoldings.model_validate_json(path.read_text(encoding="utf-8"))
        assert raw.source == "fake" and raw.etf_ticker.startswith("ZZ")
        assert 0.5 < wsum(h.weight for h in raw.holdings) <= 1.5


def _frontend_fixture() -> AnalysisResponse:
    data = json.loads(FRONTEND_FIXTURE.read_text(encoding="utf-8"))
    data.pop("_comment", None)
    return AnalysisResponse.model_validate(data)


def test_frontend_mock_fixture_matches_contract_and_reconciles():
    """frontend/api/__fixtures__/synthetic-analysis.json must stay a valid, internally consistent response."""
    r = _frontend_fixture()
    assert all(e.source == "fake" for e in r.etfs), "mock fixture must be labelled synthetic"
    close = lambda a, b: math.isclose(a, b, abs_tol=1e-9)
    c = r.coverage
    assert close(c.covered_weight + c.excluded_weight + c.missing_allocation + c.unexplained_weight,
                 c.total_allocation)
    assert close(wsum(x.exposure for x in r.exposures) + r.other_exposure, c.covered_weight)
    assert close(wsum(s.weight for s in r.sectors), c.covered_weight)
    for x in r.exposures:
        assert close(wsum(k.contribution for k in x.contributions), x.exposure)
        assert close(wsum(s.exposure for s in x.securities), x.exposure)
    assert [x.rank for x in r.exposures] == list(range(1, len(r.exposures) + 1))
    assert [x.exposure for x in r.exposures] == sorted((x.exposure for x in r.exposures), reverse=True)
    m = r.overlap.matrix
    assert all(m[i][j] == m[j][i] for i in range(len(m)) for j in range(len(m)))
    assert r.concentration.distinct_securities >= r.concentration.distinct_companies
