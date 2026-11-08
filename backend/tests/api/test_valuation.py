"""I-API: POST /api/valuation wiring (prices -> hoc.portfolio.valuation), over SYNTHETIC tickers and prices."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import hoc.service as service_module
from hoc.api.app import create_app
from hoc.config import Settings
from hoc.contract import PriceQuote, SourceUnavailable, TickerNotFound


def quote(price: float, days_old: int = 1, currency: str = "USD") -> PriceQuote:
    return PriceQuote(price=price, currency=currency, source="fake", attribution="SYNTHETIC price",
                      as_of=datetime.now(UTC).date() - timedelta(days=days_old))


class FakeQuotes:
    def __init__(self, answers):
        self.answers = answers
        self.calls: list[str] = []

    def quote(self, ticker):
        self.calls.append(ticker)
        answer = self.answers.get(ticker)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def valued(make_service):
    def make(answers):
        service, _ = make_service()
        service.quotes = FakeQuotes(answers)
        return TestClient(create_app(lambda: service, Settings())), service

    return make


def test_shares_become_allocations(valued):
    client, service = valued({"ZZAAA": quote(100.0), "ZZBBB": quote(50.0)})
    body = client.post("/api/valuation", json={"rows": [
        {"ticker": "zzaaa", "shares": 3}, {"ticker": "ZZBBB", "shares": 4}]}).json()
    assert body["status"] == "usable" and body["total_value"] == pytest.approx(500.0)
    assert [r["allocation"] for r in body["rows"]] == pytest.approx([0.6, 0.4])
    assert sorted(service.quotes.calls) == ["ZZAAA", "ZZBBB"]


def test_a_memoised_price_is_used_without_a_lookup(valued):
    client, service = valued({"ZZBBB": quote(50.0)})
    loaded = service.load_etf("ZZAAA")
    service._memo[("ZZAAA", None)] = (service_module._clock(), loaded.model_copy(update={"price": quote(100.0)}))
    body = client.post("/api/valuation", json={"rows": [
        {"ticker": "ZZAAA", "shares": 1}, {"ticker": "ZZBBB", "shares": 2}]}).json()
    assert body["status"] == "usable" and service.quotes.calls == ["ZZBBB"]


def test_price_failures_block_only_their_row_and_never_500(valued):
    client, _ = valued({"ZZAAA": quote(100.0), "ZZBBB": SourceUnavailable("down"), "ZZCCC": TickerNotFound("no"),
                        "ZZDDD": None})
    rows = [{"ticker": t, "shares": 1} for t in ("ZZAAA", "ZZBBB", "ZZCCC", "ZZDDD")]
    response = client.post("/api/valuation", json={"rows": rows})
    assert response.status_code == 200
    body = response.json()
    codes = {r["ticker"]: [i["code"] for i in r["issues"]] for r in body["rows"]}
    assert body["status"] == "blocked"
    assert codes["ZZBBB"] == ["price_unavailable"] and codes["ZZCCC"] == ["price_unavailable"]
    assert codes["ZZDDD"] == ["no_price"] and codes["ZZAAA"] == []


def test_pinning_the_unpriced_rows_unblocks(valued):
    client, _ = valued({"ZZAAA": quote(100.0, days_old=10), "ZZBBB": SourceUnavailable("down")})
    body = client.post("/api/valuation", json={"rows": [
        {"ticker": "ZZAAA", "shares": 2}, {"ticker": "ZZBBB", "allocation_override": 0.25}]}).json()
    assert body["status"] == "usable"
    assert [r["allocation"] for r in body["rows"]] == pytest.approx([0.75, 0.25])
    assert body["rows"][0]["price_stale"] is True  # 10 days old: a warning, not a block


def test_schema_errors_use_the_error_shape(valued):
    client, _ = valued({})
    response = client.post("/api/valuation", json={"rows": [{"ticker": "ZZAAA", "shares": -1}]})
    assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"
