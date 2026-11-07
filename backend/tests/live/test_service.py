"""The documented example through production service wiring, with real holdings."""
from __future__ import annotations

import math

import pytest

from hoc.contract import PortfolioItem, PortfolioRequest
from hoc.examples import EXAMPLES
from hoc.service import EtfService

pytestmark = pytest.mark.live


def test_example_portfolio(live_settings):
    definition = next(example for example in EXAMPLES if example.id == "us-core-tilt")
    request = PortfolioRequest(holdings=[
        PortfolioItem(ticker=ticker, allocation=allocation)
        for ticker, allocation in definition.holdings
    ])
    result = EtfService.from_settings(live_settings).analyse(request)
    assert {etf.ticker for etf in result.etfs} == {ticker for ticker, _ in definition.holdings}
    assert all(etf.status in {"ok", "warning"} for etf in result.etfs)
    assert all(etf.holdings_count > 0 and etf.as_of is not None for etf in result.etfs)
    coverage = result.coverage
    assert coverage.loaded_allocation == pytest.approx(1.0)
    assert coverage.missing_allocation == pytest.approx(0.0)
    assert 0.90 < coverage.covered_weight <= 1.05
    assert math.fsum([
        coverage.covered_weight, coverage.excluded_weight,
        coverage.missing_allocation, coverage.unexplained_weight,
    ]) == pytest.approx(1.0, abs=1e-8)
    assert len(result.exposures) > 100
    assert math.fsum(company.exposure for company in result.exposures) + result.other_exposure == (
        pytest.approx(coverage.covered_weight, abs=1e-8)
    )
    assert all(etf.source != "fake" for etf in result.etfs)
