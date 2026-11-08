"""FIX-63: POST /api/stress wiring (service + route). SYNTHETIC fixtures; the history provider is injected, so
no test touches the network. The loss maths itself is tested with hoc.portfolio.stress."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hoc.api.app import create_app
from hoc.config import Settings
from hoc.contract import ShockBasis
from hoc.contract.stress import DEFAULT_SHOCK_DROP

BASELINE = [{"ticker": "ZZAAA", "allocation": 0.6}, {"ticker": "ZZBBB", "allocation": 0.4}]


class RecordingHistory:
    def __init__(self, basis=None, error=None):
        self.calls: list[tuple[str, str]] = []
        self.basis = basis
        self.error = error

    def historical_shock(self, kind, key, label=None):
        self.calls.append((kind, key))
        if self.error:
            raise self.error
        return self.basis


HISTORICAL = ShockBasis(source="historical", drop=0.193, proxy="XLK",
                        description="XLK's worst month in the last 5 years: -19.3%.")


@pytest.fixture
def api(make_service):
    def make(history=None, unavailable=()):
        service, _ = make_service(unavailable=unavailable)
        if history is not None:
            service.history = history
        return service, TestClient(create_app(lambda: service, Settings()))

    return make


def post(client, shock, **extra):
    return client.post("/api/stress", json={"baseline": BASELINE, "shock": shock, **extra})


def test_sector_shock_uses_the_history_provider_and_echoes_the_shock(api):
    history = RecordingHistory(HISTORICAL)
    _, client = api(history)
    response = post(client, {"kind": "sector", "key": "information_technology", "label": "Technology"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert history.calls == [("sector", "information_technology")]
    assert body["basis"] == HISTORICAL.model_dump(mode="json")
    assert body["shock"]["label"] == "Technology"
    assert body["candidate"] is None  # no candidate sent


def test_candidate_side_is_returned_when_sent(api):
    _, client = api(RecordingHistory(HISTORICAL))
    response = post(client, {"kind": "country", "key": "US"}, candidate=[{"ticker": "ZZAAA", "allocation": 1.0}])
    assert response.status_code == 200, response.text
    assert response.json()["candidate"] is not None


def test_supplier_and_override_never_ask_history(api):
    history = RecordingHistory(HISTORICAL)
    _, client = api(history)
    supplier = post(client, {"kind": "supplier", "key": "ALIAS:TSMC"}, company_keys=["CIK:1", "CIK:2"]).json()
    assert supplier["basis"]["source"] == "simulated" and supplier["basis"]["drop"] == DEFAULT_SHOCK_DROP
    assert "supplier" in supplier["basis"]["description"]
    override = post(client, {"kind": "sector", "key": "energy", "drop": 0.25}).json()
    assert override["basis"] == {"source": "simulated", "drop": 0.25, "proxy": None, "window_start": None,
                                 "window_end": None, "description": "You chose a 25% fall."}
    assert history.calls == []


def test_a_failing_history_provider_falls_back_to_the_simulated_drop(api):
    _, client = api(RecordingHistory(error=RuntimeError("yahoo down")))
    body = post(client, {"kind": "sector", "key": "energy"}).json()
    assert body["basis"]["source"] == "simulated" and body["basis"]["drop"] == DEFAULT_SHOCK_DROP


def test_without_a_price_provider_shocks_are_simulated(api):
    _, client = api()
    body = post(client, {"kind": "country", "key": "TW"}).json()
    assert body["basis"]["source"] == "simulated"


def test_errors_match_compare(api):
    _, client = api(RecordingHistory(HISTORICAL))
    bad_sum = client.post("/api/stress", json={"baseline": [{"ticker": "ZZAAA", "allocation": 0.5}],
                                               "shock": {"kind": "sector", "key": "energy"}})
    assert bad_sum.status_code == 422 and bad_sum.json()["error"]["code"] == "ALLOCATION_SUM_INVALID"
    unknown = client.post("/api/stress", json={"baseline": [{"ticker": "ZZNOPE", "allocation": 1}],
                                               "shock": {"kind": "sector", "key": "energy"}})
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "UNKNOWN_TICKER"
    bad_kind = client.post("/api/stress", json={"baseline": BASELINE, "shock": {"kind": "planet", "key": "x"}})
    assert bad_kind.status_code == 422 and bad_kind.json()["error"]["code"] == "VALIDATION_ERROR"
    _, down = api(RecordingHistory(HISTORICAL), unavailable=["ZZAAA", "ZZBBB"])
    unavailable = post(down, {"kind": "sector", "key": "energy"})
    assert unavailable.status_code == 503 and unavailable.json()["error"]["code"] == "SOURCES_UNAVAILABLE"


def test_losses_are_computed_by_simulate_failure(api):
    """Wired to hoc.portfolio.stress: each side loses affected_weight x drop (no stub note any more)."""
    _, client = api(RecordingHistory(HISTORICAL))
    analysis = client.post("/api/analysis", json={"holdings": BASELINE}).json()
    sector = next(c["sector"] for c in analysis["exposures"] if c.get("sector"))
    body = post(client, {"kind": "sector", "key": sector, "drop": 0.25},
                candidate=[{"ticker": "ZZAAA", "allocation": 1.0}]).json()
    for side in (body["baseline"], body["candidate"]):
        assert side["affected_weight"] > 0
        assert side["loss_fraction"] == pytest.approx(side["affected_weight"] * 0.25)
        assert side["affected"] and len(side["affected"]) <= 10
    assert not any("still being connected" in note for note in body["notes"])
