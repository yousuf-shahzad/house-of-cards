"""FIX-17: real service/route with synthetic sources, forbidden AI, deadline and memo checks."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from hoc.api.app import create_app
from hoc.config import Settings
from hoc.contract import ChangeIdeasRequest

BASELINE = [{"ticker": "ZZAAA", "allocation": .6}, {"ticker": "ZZBBB", "allocation": .4}]


class ForbiddenPipeline:
    def __getattr__(self, name):
        raise AssertionError(f"change ideas touched the dependency pipeline: {name}")


@pytest.fixture
def ideas_service(make_service, monkeypatch):
    service, source = make_service()
    service.dependency_pipeline = ForbiddenPipeline()
    service.research_runner = ForbiddenPipeline()
    monkeypatch.setattr("hoc.service.IDEA_TICKERS", ("ZZCCC", "ZZMISSING"))
    reads = []

    def cached(cache_dir, keys, **kwargs):
        reads.append(set(keys))
        return {}

    monkeypatch.setattr("hoc.service.read_cached_extractions", cached)
    return service, source, reads


def test_route_is_cache_only_returns_partial_skips_unavailable_and_memoises(ideas_service):
    service, _, reads = ideas_service
    client = TestClient(create_app(lambda: service, Settings()))
    first = client.post("/api/change-ideas", json={"holdings": BASELINE})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "partial" and len(body["ideas"]) == 1
    assert body["ideas"][0]["ticker"] == "ZZCCC"
    assert any("Skipped ZZMISSING" in note for note in body["notes"])
    assert reads and len(reads) == 1  # shared snapshot, not one disk scan per candidate/fraction
    second = client.post("/api/change-ideas", json={"holdings": list(reversed(BASELINE))})
    assert second.json() == body and len(reads) == 1


def test_invalid_current_portfolios_keep_analysis_error_codes(ideas_service):
    service, _, reads = ideas_service
    client = TestClient(create_app(lambda: service, Settings()))
    for holdings, code in (([{"ticker": "ZZAAA", "allocation": .2}], "ALLOCATION_SUM_INVALID"),
                           ([{"ticker": "ZZNOPE", "allocation": 1}], "UNKNOWN_TICKER")):
        response = client.post("/api/change-ideas", json={"holdings": holdings})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == code
    assert reads == []


def test_cold_slow_load_is_bounded_and_retry_reuses_inflight_result(ideas_service, monkeypatch):
    service, _, reads = ideas_service
    entered, release = threading.Event(), threading.Event()
    real = service.analyse

    def slow(request):
        entered.set()
        assert release.wait(2)
        return real(request)

    monkeypatch.setattr(service, "analyse", slow)
    monkeypatch.setattr("hoc.service.IDEAS_WAIT_SECONDS", .02)
    request = ChangeIdeasRequest(holdings=BASELINE)
    try:
        first = service.change_ideas(request)
        assert entered.is_set()
        assert first.status == "partial" and first.ideas == []
        assert "ZZCCC, ZZMISSING" in first.notes[0]
        assert len(service._ideas) == 1
    finally:
        release.set()
    monkeypatch.setattr("hoc.service.IDEAS_WAIT_SECONDS", 2)
    assert service.change_ideas(request).ideas
    assert len(reads) == 1


def test_concurrent_requests_share_one_computation(ideas_service):
    service, _, reads = ideas_service
    request = ChangeIdeasRequest(holdings=BASELINE)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.change_ideas(request), range(4)))
    assert all(result == results[0] for result in results)
    assert len(reads) == 1


def test_memo_expiry_refreshes_dependency_snapshot(ideas_service, monkeypatch):
    service, _, reads = ideas_service
    clock = [100.0]
    monkeypatch.setattr("hoc.service._clock", lambda: clock[0])
    request = ChangeIdeasRequest(holdings=BASELINE)
    service.change_ideas(request)
    service.change_ideas(request)
    assert len(reads) == 1
    clock[0] += 61
    service.change_ideas(request)
    assert len(reads) == 2


def test_current_sources_unavailable_is_503_and_incomplete_baseline_has_no_ideas(make_service, monkeypatch):
    monkeypatch.setattr("hoc.service.IDEA_TICKERS", ("ZZCCC",))
    monkeypatch.setattr("hoc.service.read_cached_extractions", lambda *a, **k: {})
    service, _ = make_service(unavailable=["ZZAAA", "ZZBBB"])
    client = TestClient(create_app(lambda: service, Settings()))
    response = client.post("/api/change-ideas", json={"holdings": BASELINE})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SOURCES_UNAVAILABLE"
    service, _ = make_service(unavailable=["ZZBBB"])
    requested = []
    original = service._load_many

    def load(tickers):
        requested.extend(tickers)
        return original(tickers)

    monkeypatch.setattr(service, "_load_many", load)
    response = service.change_ideas(ChangeIdeasRequest(holdings=BASELINE))
    assert response.status == "partial" and response.ideas == []
    assert "ZZCCC" not in requested
