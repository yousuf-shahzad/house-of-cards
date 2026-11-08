"""Valuation checks use the labelled synthetic ZZ valuation fixture, never live prices."""

import json
import math
from datetime import date, timedelta
from itertools import permutations
from pathlib import Path

import pytest

from hoc.contract import (
    PortfolioRequest,
    PriceQuote,
    ValuationRequest,
    ValuationResponse,
    ValuationRow,
)
from hoc.portfolio.validation import validate_request
from hoc.portfolio.valuation import value_portfolio

TODAY = date(2026, 11, 8)


@pytest.fixture
def example():
    path = Path(__file__).resolve().parents[3] / "frontend/api/__fixtures__/synthetic-valuation.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("_comment")
    response = ValuationResponse.model_validate(data)
    request = ValuationRequest(
        rows=[
            ValuationRow(
                ticker=row.ticker,
                shares=row.shares,
                allocation_override=row.allocation if row.pinned else None,
            )
            for row in response.rows
        ]
    )
    quotes = {row.ticker: row.price for row in response.rows}
    return request, quotes, response


def codes(response):
    return {item.code for item in response.issues if item.severity == "blocking"}


def test_fixture_values_and_attribution(example):
    request, quotes, expected = example
    result = value_portfolio(request, quotes, [], today=TODAY)
    assert result.model_dump() == expected.model_dump()
    validate_request(
        PortfolioRequest(
            holdings=[{"ticker": row.ticker, "allocation": row.allocation} for row in result.rows]
        )
    )


def test_fractional_shares_and_pin_rescaling(example):
    request, quotes, _ = example
    request.rows[0].shares = 0.5
    request.rows[1].shares = 0.2
    result = value_portfolio(request, quotes, [], today=TODAY)
    assert result.status == "usable"
    assert result.total_value == 50
    assert [row.allocation for row in result.rows] == pytest.approx([0.4, 0.4, 0.2])
    request.rows[2].allocation_override = 0.6
    result = value_portfolio(request, quotes, [], today=TODAY)
    assert [row.allocation for row in result.rows] == pytest.approx([0.2, 0.2, 0.6])


@pytest.mark.parametrize("age,stale", [(0, False), (2, False), (4, False), (5, True)])
def test_staleness_calendar_boundary(example, age, stale):
    request, quotes, _ = example
    quote = quotes["ZZAAA"].model_copy(update={"as_of": TODAY - timedelta(days=age)})
    result = value_portfolio(ValuationRequest(rows=[request.rows[0]]), {"ZZAAA": quote}, [], today=TODAY)
    assert result.status == "usable"
    assert result.rows[0].price_age_days == age
    assert result.rows[0].price_stale is stale
    assert [issue.code for issue in result.issues] == (["stale_price"] if stale else [])


@pytest.mark.parametrize(
    "mode,code",
    [
        ("absent", "no_price"),
        ("none", "no_price"),
        ("unavailable", "price_unavailable"),
        ("currency", "non_usd_price"),
        ("missing_shares", "missing_shares"),
    ],
)
def test_unpriced_row_blocks_and_pinning_recovers(example, mode, code):
    request, quotes, _ = example
    if mode == "absent":
        quotes.pop("ZZAAA")
    elif mode == "none":
        quotes["ZZAAA"] = None
    elif mode == "currency":
        quotes["ZZAAA"] = quotes["ZZAAA"].model_copy(update={"currency": "GBP"})
    elif mode == "missing_shares":
        request.rows[0].shares = None
    unavailable = ["zzaaa"] if mode == "unavailable" else []
    result = value_portfolio(request, quotes, unavailable, today=TODAY)
    assert result.status == "blocked"
    assert code in codes(result)
    assert result.rows[0].allocation is None
    assert result.rows[1].allocation is None
    assert result.rows[2].allocation == 0.2
    row_issue = next(item for item in result.rows[0].issues if item.code == code)
    assert row_issue.ticker == "ZZAAA"
    assert row_issue in result.issues
    request.rows[0].allocation_override = 0.3
    result = value_portfolio(request, quotes, unavailable, today=TODAY)
    assert result.status == "usable"
    assert [row.allocation for row in result.rows] == pytest.approx([0.3, 0.5, 0.2])


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ([0.4, 0.6], set()),
        ([0.4, 0.5], {"allocation_sum_invalid"}),
        ([0.6, 0.5], {"pinned_over_100"}),
        ([0.0, 1.0], set()),
        ([0.4, 0.599999], {"allocation_sum_invalid"}),
    ],
)
def test_all_pinned_without_quotes(overrides, expected):
    request = ValuationRequest(
        rows=[
            {"ticker": ticker, "allocation_override": allocation}
            for ticker, allocation in zip(["ZZAAA", "ZZBBB"], overrides)
        ]
    )
    result = value_portfolio(request, {}, ["ZZAAA", "ZZBBB"], today=TODAY)
    assert codes(result) == expected
    assert result.status == ("blocked" if expected else "usable")
    assert result.total_value == 0
    assert [row.allocation for row in result.rows] == overrides


def test_zero_shares_and_nothing_to_rescale(example):
    request, quotes, _ = example
    request.rows[0].shares = 0
    result = value_portfolio(request, quotes, [], today=TODAY)
    assert result.status == "usable"
    assert result.rows[0].value == result.rows[0].allocation == 0
    request.rows[1].shares = 0
    result = value_portfolio(request, quotes, [], today=TODAY)
    assert codes(result) == {"nothing_to_rescale"}
    request.rows[2].allocation_override = 1
    result = value_portfolio(request, quotes, [], today=TODAY)
    assert result.status == "usable"
    assert [row.allocation for row in result.rows] == [0, 0, 1]


def test_unpinned_still_requires_price_when_pinned_total_is_one(example):
    request, quotes, _ = example
    request.rows[2].allocation_override = 1
    quotes["ZZAAA"] = None
    result = value_portfolio(request, quotes, [], today=TODAY)
    assert codes(result) == {"no_price"}


def test_business_validation_and_issue_order(example):
    request, quotes, _ = example
    request.rows.append(request.rows[1].model_copy(update={"ticker": "zzbbb"}))
    result = value_portfolio(request, quotes, [], today=TODAY)
    assert codes(result) == {"duplicate_ticker"}
    assert result.issues[0].severity == "blocking"
    request = ValuationRequest(
        rows=[{"ticker": f"ZZ{index}", "allocation_override": 0.1} for index in range(11)]
    )
    result = value_portfolio(request, {}, [], today=TODAY)
    assert codes(result) == {"too_many_etfs", "pinned_over_100"}


def test_order_case_precision_and_no_input_mutation(example):
    request, quotes, _ = example
    request.rows[0].shares = 1 / 3
    before = request.model_dump_json()
    original_quotes = dict(quotes)
    baseline = value_portfolio(request, quotes, [], today=TODAY)
    assert baseline.rows[0].value == request.rows[0].shares * quotes["ZZAAA"].price
    for ordering in permutations(request.rows):
        result = value_portfolio(
            ValuationRequest(rows=list(ordering)),
            {ticker.lower(): quote for ticker, quote in reversed(list(quotes.items()))},
            [],
            today=TODAY,
        )
        assert [row.ticker for row in result.rows] == [row.ticker for row in ordering]
        assert {row.ticker: row.allocation for row in result.rows} == {
            row.ticker: row.allocation for row in baseline.rows
        }
        assert math.fsum(row.allocation for row in result.rows) == pytest.approx(1)
        assert result.attributions == baseline.attributions
    assert request.model_dump_json() == before
    assert quotes == original_quotes


@pytest.mark.parametrize("shares,price", [(1e308, 50), (1e-308, 1e-308), (1_000_000_001, 50)])
def test_unrepresentable_share_values_block(example, shares, price):
    request, quotes, _ = example
    request.rows[0].shares = shares
    quotes["ZZAAA"] = quotes["ZZAAA"].model_copy(update={"price": price})
    result = value_portfolio(request, quotes, [], today=TODAY)
    assert "invalid_price" in codes(result)
    assert result.rows[0].value is None
    assert math.isfinite(result.total_value)
    result.model_dump_json()


def test_total_value_overflow_blocks(example):
    request, quotes, _ = example
    for row in request.rows[:2]:
        row.shares = 1e308
        quotes[row.ticker] = quotes[row.ticker].model_copy(update={"price": 1.0})
    result = value_portfolio(request, quotes, [], today=TODAY)
    assert result.status == "blocked"
    assert "invalid_price" in codes(result)
    assert math.isfinite(result.total_value)
    assert all(row.allocation is None for row in result.rows[:2])


def test_invalid_quote_values_cannot_enter_contract(example):
    _, quotes, _ = example
    for price in (0, -1, float("inf"), float("nan")):
        data = quotes["ZZAAA"].model_dump()
        data["price"] = price
        with pytest.raises(ValueError):
            PriceQuote.model_validate(data)
