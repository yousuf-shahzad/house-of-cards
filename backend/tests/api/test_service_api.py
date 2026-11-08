"""Package f: EtfService wiring, HTTP routes and the CLI, over SYNTHETIC fixtures (no network)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hoc import cli
from hoc.api.app import create_app
from hoc.config import Settings
from hoc.contract import AnalysisResponse, EtfFailure, EtfHoldings, PortfolioValidationError
from hoc.examples import ExampleDefinition


def client(service) -> TestClient:
    return TestClient(create_app(lambda: service, Settings()))


@pytest.fixture
def no_validation(monkeypatch):
    monkeypatch.setattr("hoc.service.validate_request", lambda request: [])


# ---------- load_etf / memo ----------


def test_success_is_memoised_and_records_attempts(make_service):
    service, source = make_service()
    first = service.load_etf("zzaaa")
    assert isinstance(first, EtfHoldings) and first.etf_ticker == "ZZAAA"
    assert [(a.source, a.outcome) for a in first.attempts] == [("fake", "ok")]
    assert service.load_etf("ZZAAA") is first
    assert source.calls == ["ZZAAA"]


def test_failures_are_not_memoised(make_service):
    service, source = make_service()
    assert service.load_etf("ZZNOPE").status == "not_found"
    assert service.load_etf("ZZNOPE").status == "not_found"
    assert source.calls == ["ZZNOPE", "ZZNOPE"]
    down, _ = make_service(unavailable=["ZZAAA"])
    failure = down.load_etf("ZZAAA")
    assert isinstance(failure, EtfFailure) and failure.status == "unavailable"


def test_normaliser_rejection_becomes_unavailable(make_service, monkeypatch):
    service, _ = make_service()

    def reject(*args):
        raise ValueError("raw weights look like percent")

    monkeypatch.setattr("hoc.service.normalise_etf", reject)
    failure = service.load_etf("ZZAAA")
    assert failure.status == "unavailable" and "percent" in failure.message


# ---------- GET /api/etfs/{ticker} ----------


def test_etf_summary_route(make_service):
    service, _ = make_service()
    body = client(service).get("/api/etfs/zzaaa").json()
    assert body["ticker"] == "ZZAAA" and body["source"] == "fake" and body["holdings"] is None
    assert body["holdings_count"] == 5 and body["company_count"] == 5
    assert body["excluded_weight"] == pytest.approx(0.05)
    with_lines = client(service).get("/api/etfs/ZZAAA?holdings=true").json()
    assert len(with_lines["holdings"]) == 5


def test_etf_errors_map_to_404_and_503(make_service):
    service, _ = make_service(unavailable=["ZZAAA"])
    missing = client(service).get("/api/etfs/ZZNOPE")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "ETF_NOT_FOUND"
    assert missing.json()["error"]["details"]["attempts"][0]["outcome"] == "not_found"
    down = client(service).get("/api/etfs/ZZAAA")
    assert down.status_code == 503 and down.json()["error"]["code"] == "SOURCES_UNAVAILABLE"


# ---------- POST /api/analysis ----------


def test_unknown_ticker_is_422(make_service, no_validation):
    service, _ = make_service()
    response = client(service).post("/api/analysis", json={"holdings": [
        {"ticker": "ZZAAA", "allocation": 0.5}, {"ticker": "ZZNOPE", "allocation": 0.5}]})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "UNKNOWN_TICKER" and error["details"]["tickers"] == ["ZZNOPE"]
    assert error["details"]["attempts"]["ZZNOPE"][0]["outcome"] == "not_found"


def test_nothing_loaded_is_503(make_service, no_validation):
    service, _ = make_service(unavailable=["ZZAAA", "ZZBBB"])
    response = client(service).post("/api/analysis", json={"holdings": [
        {"ticker": "ZZAAA", "allocation": 0.5}, {"ticker": "ZZBBB", "allocation": 0.5}]})
    assert response.status_code == 503 and response.json()["error"]["code"] == "SOURCES_UNAVAILABLE"


def test_partial_outage_reaches_analyse_with_failures(make_service, no_validation, monkeypatch):
    service, _ = make_service(unavailable=["ZZBBB"])
    seen = {}

    def record(request, loaded, failures, *, today, generated_at):
        seen.update(loaded=set(loaded), failures=set(failures), aware=generated_at.tzinfo is not None)
        raise PortfolioValidationError("TOO_MANY_ETFS", "stop here")  # analyse() is package e's

    monkeypatch.setattr("hoc.service.analyse", record)
    response = client(service).post("/api/analysis", json={"holdings": [
        {"ticker": "ZZAAA", "allocation": 0.5}, {"ticker": "ZZBBB", "allocation": 0.5}]})
    assert response.status_code == 422
    assert seen == {"loaded": {"ZZAAA"}, "failures": {"ZZBBB"}, "aware": True}


def test_analysis_route_with_real_maths(make_service):
    service, _ = make_service(unavailable=["ZZCCC"])
    response = client(service).post("/api/analysis", json={"holdings": [
        {"ticker": "ZZAAA", "allocation": 0.5}, {"ticker": "ZZBBB", "allocation": 0.3},
        {"ticker": "ZZCCC", "allocation": 0.2}]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert {e["ticker"]: e["status"] for e in body["etfs"]}["ZZCCC"] == "unavailable"
    assert body["coverage"]["missing_allocation"] == pytest.approx(0.2)
    assert "Coverage: covered" in cli.summary(AnalysisResponse.model_validate(body))


def test_validation_runs_before_any_fetch(make_service, monkeypatch):
    service, source = make_service()

    def invalid(request):
        raise PortfolioValidationError("ALLOCATION_SUM_INVALID", "Allocations total 90%", {"total": 0.9})

    monkeypatch.setattr("hoc.service.validate_request", invalid)
    response = client(service).post("/api/analysis", json={"holdings": [{"ticker": "ZZAAA", "allocation": 0.9}]})
    assert response.json()["error"]["code"] == "ALLOCATION_SUM_INVALID"
    assert source.calls == []


def test_unexpected_errors_keep_the_error_shape(make_service, monkeypatch):
    service, _ = make_service()
    monkeypatch.setattr("hoc.service.validate_request", lambda request: 1 / 0)
    response = TestClient(create_app(lambda: service, Settings()), raise_server_exceptions=False).post(
        "/api/analysis", json={"holdings": [{"ticker": "ZZAAA", "allocation": 1}]})
    assert response.status_code == 500 and response.json()["error"]["code"] == "INTERNAL_ERROR"


# ---------- GET /api/examples ----------


def test_examples_verified_only_when_every_etf_loads(make_service, monkeypatch):
    monkeypatch.setattr("hoc.service.EXAMPLES", (
        ExampleDefinition("good", "Good", "synthetic", (("ZZAAA", 0.6), ("ZZBBB", 0.4))),
        ExampleDefinition("bad", "Bad", "synthetic", (("ZZAAA", 0.5), ("ZZNOPE", 0.5))),
    ))
    service, source = make_service()
    examples = {e["id"]: e for e in client(service).get("/api/examples").json()["examples"]}
    assert examples["good"]["verified"] is True
    assert examples["good"]["holdings"][0] == {"ticker": "ZZAAA", "allocation": 0.6, "verified": True,
                                               "source": "fake", "as_of": "2026-11-05"}
    assert examples["bad"]["verified"] is False and examples["bad"]["holdings"][1]["verified"] is False
    assert source.calls.count("ZZAAA") == 1  # shared tickers fetched once


# ---------- CLI ----------


def test_cli_builds_requests_from_pairs_and_examples():
    request = cli.build_request(None, ["ivv=40", "QQQ=60"])
    assert [(h.ticker, h.allocation) for h in request.holdings] == [("IVV", 0.4), ("QQQ", 0.6)]
    assert len(cli.build_request("us-core-tilt", []).holdings) == 4
    for example, pairs in ((None, []), ("us-core-tilt", ["IVV=100"]), (None, ["IVV"]), (None, ["=40"]),
                           (None, ["IVV=abc"]), ("nope", [])):
        with pytest.raises(ValueError):
            cli.build_request(example, pairs)


def test_cli_warm_reports_each_etf(make_service, monkeypatch, capsys):
    monkeypatch.setattr("hoc.cli.EXAMPLES", (
        ExampleDefinition("zz", "ZZ", "synthetic", (("ZZAAA", 0.5), ("ZZNOPE", 0.5))),))
    service, _ = make_service()
    monkeypatch.setattr("hoc.cli.EtfService.from_settings", classmethod(lambda cls, settings: service))
    assert cli.main(["warm", "--example", "zz"]) == 1
    out = capsys.readouterr().out
    assert "ZZAAA    ok" in out and "ZZNOPE   not_found" in out


def test_cli_analyse_reports_errors(make_service, no_validation, monkeypatch, capsys):
    service, _ = make_service()
    monkeypatch.setattr("hoc.cli.EtfService.from_settings", classmethod(lambda cls, settings: service))
    assert cli.main(["analyse", "ZZNOPE=100"]) == 1
    assert "UNKNOWN_TICKER" in capsys.readouterr().err


# ---------- end to end with the real normaliser and maths (activates when packages d and e land) ----------


def test_end_to_end_with_real_packages(fake_source, fake_reference):
    from hoc.identity.resolver import load_aliases
    from hoc.normalise.pipeline import normalise_etf
    from hoc.portfolio.analyse import analyse  # noqa: F401
    from hoc.service import EtfService
    from hoc.sources.registry import SourceRegistry

    try:
        aliases = load_aliases()
        normalise_etf(fake_source.fetch("ZZAAA"), fake_reference, aliases)
        service = EtfService(SourceRegistry([fake_source]), fake_reference, aliases, Settings())
        response = client(service).post("/api/analysis", json={"holdings": [
            {"ticker": "ZZAAA", "allocation": 0.6}, {"ticker": "ZZBBB", "allocation": 0.4}]})
    except NotImplementedError as exc:
        pytest.skip(f"waiting for {exc}")
    assert response.status_code == 200, response.text
    body = response.json()
    exposure = sum(e["exposure"] for e in body["exposures"]) + body["other_exposure"]
    assert exposure == pytest.approx(body["coverage"]["covered_weight"], abs=1e-9)
    assert [e["ticker"] for e in body["etfs"]] == ["ZZAAA", "ZZBBB"]
    assert "Coverage: covered" in cli.summary(AnalysisResponse.model_validate(body))


# ---------- startup warm-up and robustness ----------


def test_startup_warm_up_preloads_examples_without_blocking(make_service, monkeypatch):
    monkeypatch.setattr("hoc.service.EXAMPLES", (
        ExampleDefinition("zz", "ZZ", "synthetic", (("ZZAAA", 0.6), ("ZZBBB", 0.4))),))
    monkeypatch.setattr("hoc.service.IDEA_TICKERS", ("ZZCCC",))  # FIX-17: the idea shortlist is warmed too
    service, source = make_service()
    app = create_app(lambda: service, Settings(), warm=True)
    with TestClient(app) as warmed:  # entering runs the lifespan, which starts the thread
        app.state.warm_up_thread.join(timeout=10)
        assert sorted(source.calls) == ["ZZAAA", "ZZBBB", "ZZCCC"]
        response = warmed.post("/api/analysis", json={"holdings": [
            {"ticker": "ZZAAA", "allocation": 0.6}, {"ticker": "ZZBBB", "allocation": 0.4}]})
    assert response.status_code == 200
    assert sorted(source.calls) == ["ZZAAA", "ZZBBB", "ZZCCC"]  # the first analysis was served from the memo


def test_failed_warm_up_still_serves(make_service, monkeypatch):
    service, _ = make_service()
    monkeypatch.setattr(service, "examples", lambda: 1 / 0)
    app = create_app(lambda: service, Settings(), warm=True)
    with TestClient(app) as warmed:
        app.state.warm_up_thread.join(timeout=10)
        assert warmed.get("/api/health").status_code == 200


def test_apps_do_not_warm_up_unless_asked(make_service):
    service, source = make_service()
    app = create_app(lambda: service, Settings())
    with TestClient(app):
        assert app.state.warm_up_thread is None and source.calls == []


def test_adapter_bug_costs_one_etf_not_a_500(make_service, monkeypatch):
    service, source = make_service()
    real_fetch = source.fetch

    def buggy(ticker):
        if ticker == "ZZBBB":
            raise AttributeError("'str' object has no attribute 'get'")  # e.g. a malformed upstream field
        return real_fetch(ticker)

    monkeypatch.setattr(source, "fetch", buggy)
    response = client(service).post("/api/analysis", json={"holdings": [
        {"ticker": "ZZAAA", "allocation": 0.5}, {"ticker": "ZZBBB", "allocation": 0.5}]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert {e["ticker"]: e["status"] for e in body["etfs"]}["ZZBBB"] == "unavailable"
    assert body["coverage"]["missing_allocation"] == pytest.approx(0.5)


def test_concurrent_loads_of_one_etf_fetch_once(make_service, monkeypatch):
    import threading
    import time

    service, source = make_service()
    real_fetch = source.fetch

    def slow(ticker):
        time.sleep(0.2)
        return real_fetch(ticker)

    monkeypatch.setattr(source, "fetch", slow)
    threads = [threading.Thread(target=service.load_etf, args=("ZZAAA",)) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert source.calls == ["ZZAAA"]


def test_memo_reuses_within_ttl_and_refreshes_after(make_service, monkeypatch):
    """Codex audit (f): an always-running API must pick up a newer disclosure once the memo TTL passes."""
    from datetime import date

    import hoc.service as service_module

    service, source = make_service()
    now = [1000.0]
    monkeypatch.setattr(service_module, "_clock", lambda: now[0])
    disclosed = [date(2026, 11, 5)]
    real_fetch = source.fetch
    monkeypatch.setattr(source, "fetch", lambda t: real_fetch(t).model_copy(update={"as_of": disclosed[0]}))

    assert service.load_etf("ZZAAA").as_of == date(2026, 11, 5)
    disclosed[0] = date(2026, 11, 6)
    now[0] += service_module.MEMO_TTL_SECONDS - 1  # allocation changes within the TTL: memo hits
    for _ in range(3):
        assert service.load_etf("ZZAAA").as_of == date(2026, 11, 5)
    assert source.calls == ["ZZAAA"]
    now[0] += 2  # past the TTL: reload, new disclosure
    assert service.load_etf("ZZAAA").as_of == date(2026, 11, 6)
    assert source.calls == ["ZZAAA", "ZZAAA"]


def test_expired_memo_survives_a_failed_refresh(make_service, monkeypatch):
    import hoc.service as service_module

    service, source = make_service()
    now = [1000.0]
    monkeypatch.setattr(service_module, "_clock", lambda: now[0])
    first = service.load_etf("ZZAAA")
    source.unavailable.add("ZZAAA")
    now[0] += service_module.MEMO_TTL_SECONDS + 1
    assert service.load_etf("ZZAAA") is first  # stale holdings, still dated by their own as_of
    assert source.calls == ["ZZAAA", "ZZAAA"]


# ---------- FIX-57: every error uses the one envelope ----------


def test_unknown_route_and_wrong_method_use_the_error_envelope(make_service):
    service, _ = make_service()
    api = client(service)
    missing = api.get("/api/nope")
    assert missing.status_code == 404
    assert missing.json() == {"error": {"code": "NOT_FOUND", "message": "There is no such API route.",
                                        "details": {"path": "/api/nope", "method": "GET"}}}
    wrong = api.get("/api/analysis")
    assert wrong.status_code == 405
    assert wrong.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert "POST" in wrong.headers["allow"]
    assert api.get("/api/dependencies/nope").json()["error"]["code"] == "JOB_NOT_FOUND"  # route 404s keep theirs


# ---------- FIX-63: price history warm-up ----------


class _RecordingShocks:
    def __init__(self):
        self.calls = []

    def historical_shock(self, kind, key, label=None):
        from hoc.contract import ShockBasis

        self.calls.append((kind, key))
        return ShockBasis(source="historical", drop=0.2, proxy="X", description="synthetic")


def test_history_warm_up_fetches_each_proxy_once(make_service):
    from hoc.api.app import warm_history
    from hoc.history import COUNTRY_PROXIES, SECTOR_PROXIES

    service, _ = make_service()
    service.history = _RecordingShocks()
    warm_history(service)
    proxies = [SECTOR_PROXIES[k] if kind == "sector" else COUNTRY_PROXIES[k] for kind, k in service.history.calls]
    assert len(proxies) == len(set(proxies)) == len(set(SECTOR_PROXIES.values()) | set(COUNTRY_PROXIES.values()))
    assert ("sector", "information_technology") in service.history.calls and ("country", "TW") in service.history.calls


def test_history_warm_up_is_skipped_offline(make_service):
    import dataclasses

    from hoc.api.app import warm_history

    service, _ = make_service()
    service.history = _RecordingShocks()
    service.settings = dataclasses.replace(service.settings, offline=True)
    warm_history(service)
    assert service.history.calls == []
