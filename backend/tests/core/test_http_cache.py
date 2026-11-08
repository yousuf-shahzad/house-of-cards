"""hoc.core: DiskCache and CachedHttpClient (TTL, offline, stale-if-error, retries, rate limits).

httpx.MockTransport stands in for the network, so nothing leaves the process.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from hoc.config import Settings
from hoc.contract import SourceUnavailable
from hoc.core import http as http_module
from hoc.core.cache import DiskCache
from hoc.core.http import CachedHttpClient

URL = "https://example.invalid/fund.json"
DAY = timedelta(hours=24)
OLD = datetime(2020, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(http_module, "RETRY_DELAYS", (0.0, 0.0))
    monkeypatch.setattr(http_module.time, "sleep", lambda seconds: None)


class Server:
    """Scripted responses per call; records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


def make(tmp_path, *responses, offline=False):
    server = Server(*responses)
    cache = DiskCache(tmp_path / "cache")
    client = CachedHttpClient(Settings(cache_dir=tmp_path / "cache", offline=offline), cache)
    client._client = httpx.Client(transport=httpx.MockTransport(server), follow_redirects=True)
    return client, cache, server


def ok(body="fresh", status=200, **headers):
    return httpx.Response(status, content=body.encode(), headers={"content-type": "application/json", **headers})


# ---------- DiskCache ----------


def test_disk_cache_round_trip_and_misses(tmp_path):
    cache = DiskCache(tmp_path)
    assert cache.get("http/x", URL) is None
    entry = cache.put("http/x", URL, b"abc", {"status": 200, "fetched_at": OLD})
    again = cache.get("http/x", URL)
    assert again.body == b"abc" and again.fetched_at == OLD == entry.fetched_at
    assert again.meta["status"] == 200 and again.meta["key"] == URL
    assert not list(tmp_path.rglob("*.tmp"))  # atomic writes leave no temp files


def test_disk_cache_ignores_corrupt_entries_and_stays_inside_root(tmp_path):
    cache = DiskCache(tmp_path / "root")
    cache.put("../../escape", URL, b"x", {})
    assert all((tmp_path / "root") in p.parents for p in tmp_path.rglob("*.json"))
    meta = next((tmp_path / "root").rglob("*.json"))
    meta.write_text("{not json", encoding="utf-8")
    assert cache.get("../../escape", URL) is None


# ---------- CachedHttpClient ----------


def test_fresh_entry_is_served_without_a_request(tmp_path):
    client, _, server = make(tmp_path, ok("one"))
    first = client.get(URL, source="ti", ttl=DAY)
    second = client.get(URL, source="ti", ttl=DAY)
    assert first.body == second.body == b"one" and not first.from_cache and second.from_cache
    assert second.status == 200 and second.content_type == "application/json" and not second.stale
    assert len(server.requests) == 1


def test_expired_entry_is_refetched_but_ttl_none_never_expires(tmp_path):
    client, cache, server = make(tmp_path, ok("new"))
    cache.put("http/ti", URL, b"old", {"status": 200, "fetched_at": OLD})
    assert client.get(URL, source="ti", ttl=DAY).body == b"new"
    cache.put("http/sec", URL, b"filing", {"status": 200, "fetched_at": OLD})
    assert client.get(URL, source="sec", ttl=None).body == b"filing"
    assert len(server.requests) == 1


def test_offline_serves_any_cached_copy_and_never_requests(tmp_path):
    client, cache, server = make(tmp_path, ok(), offline=True)
    cache.put("http/ti", URL, b"old", {"status": 200, "fetched_at": OLD})
    response = client.get(URL, source="ti", ttl=DAY)
    assert response.body == b"old" and response.stale and response.from_cache
    with pytest.raises(SourceUnavailable, match="offline"):
        client.get("https://example.invalid/other.json", source="ti", ttl=DAY)
    assert server.requests == []


def test_network_failure_falls_back_to_stale_or_raises(tmp_path):
    client, cache, server = make(tmp_path, httpx.ConnectError("down"))
    with pytest.raises(SourceUnavailable, match="3 attempt"):
        client.get(URL, source="ti", ttl=DAY)
    assert len(server.requests) == 3
    cache.put("http/ti", URL, b"old", {"status": 200, "fetched_at": OLD})
    response = client.get(URL, source="ti", ttl=DAY)
    assert response.body == b"old" and response.stale


def test_5xx_and_429_are_retried_and_never_cached(tmp_path):
    client, _, server = make(tmp_path, ok("busy", 503), ok("slow", 429), ok("finally"))
    assert client.get(URL, source="ti", ttl=DAY).body == b"finally"
    assert len(server.requests) == 3
    client2, cache2, _ = make(tmp_path / "b", ok("busy", 503))
    with pytest.raises(SourceUnavailable, match="HTTP 503"):
        client2.get(URL, source="ti", ttl=DAY)
    assert cache2.get("http/ti", URL) is None


def test_404_is_returned_and_cached(tmp_path):
    client, _, server = make(tmp_path, ok("missing", 404))
    assert client.get(URL, source="ti", ttl=DAY).status == 404
    assert client.get(URL, source="ti", ttl=DAY).status == 404
    assert len(server.requests) == 1


def test_params_user_agent_and_redirects(tmp_path):
    client, _, server = make(tmp_path, httpx.Response(301, headers={"location": "https://example.invalid/b"}),
                             ok("moved"))
    response = client.get(URL, source="ti", ttl=DAY, params={"top": "50", "portfolio": "IVV:40,QQQ:60"})
    assert response.body == b"moved"
    first = server.requests[0]
    assert first.url.params["portfolio"] == "IVV:40,QQQ:60" and list(first.url.params) == ["portfolio", "top"]
    assert first.headers["user-agent"] == Settings().user_agent
    client.get(URL + "?x=1", source="ti", ttl=DAY, headers={"User-Agent": "Adapter/1 (me@example.invalid)"})
    assert server.requests[-1].headers["user-agent"] == "Adapter/1 (me@example.invalid)"


def test_post_json_is_cached_by_body(tmp_path):
    client, _, server = make(tmp_path, ok("[]"))
    url = "https://api.openfigi.com/v3/mapping"
    client.post_json(url, [{"idType": "ID_ISIN", "idValue": "A"}], source="sec", ttl=DAY)
    client.post_json(url, [{"idValue": "A", "idType": "ID_ISIN"}], source="sec", ttl=DAY)  # same body
    client.post_json(url, [{"idType": "ID_ISIN", "idValue": "B"}], source="sec", ttl=DAY)
    assert len(server.requests) == 2
    assert json.loads(server.requests[0].content) == [{"idType": "ID_ISIN", "idValue": "A"}]


def test_sec_requests_are_spaced(tmp_path, monkeypatch):
    waits = []
    monkeypatch.setattr(http_module.time, "sleep", waits.append)
    monkeypatch.setattr(http_module.time, "monotonic", lambda: 1000.0)  # frozen: a slow machine can't skip the wait
    client, _, _ = make(tmp_path, ok())
    client.get("https://www.sec.gov/a", source="sec", ttl=DAY)
    client.get("https://www.sec.gov/b", source="sec", ttl=DAY)
    client.get("https://example.invalid/c", source="ti", ttl=DAY)
    client.get("https://example.invalid/d", source="ti", ttl=DAY)
    assert waits == [pytest.approx(http_module.MIN_INTERVAL_SECONDS["sec.gov"])]


# ---------- Gemini host rules (PLAN-v2 I-API) ----------

GEMINI = "https://generativelanguage.googleapis.com/v1beta/interactions"
SECRET = "TEST-ONLY-NOT-A-REAL-KEY-7f3a9"


def test_gemini_errors_are_not_cached_but_answers_are(tmp_path):
    client, _, server = make(tmp_path, ok('{"error":"bad schema"}', 400), ok('{"output_text":"{}"}'))
    payload = {"model": "gemini-3.8-flash", "input": "x"}
    assert client.post_json(GEMINI, payload, source="gemini", ttl=None).status == 400
    assert client.post_json(GEMINI, payload, source="gemini", ttl=None).status == 200  # 400 did not stick
    assert client.post_json(GEMINI, payload, source="gemini", ttl=None).from_cache
    assert len(server.requests) == 2


def test_api_key_stays_in_the_header_and_off_disk(tmp_path):
    client, _, server = make(tmp_path, ok("{}"), ok("busy", 503))
    client.post_json(GEMINI, {"input": "x"}, source="gemini", ttl=None, headers={"x-goog-api-key": SECRET})
    assert server.requests[0].headers["x-goog-api-key"] == SECRET and SECRET not in str(server.requests[0].url)
    with pytest.raises(SourceUnavailable) as failure:
        client.post_json(GEMINI, {"input": "y"}, source="gemini", ttl=None, headers={"x-goog-api-key": SECRET})
    assert SECRET not in str(failure.value)
    stored = b"".join(p.read_bytes() for p in (tmp_path / "cache").rglob("*") if p.is_file())
    assert stored and SECRET.encode() not in stored


def test_keys_in_urls_are_refused(tmp_path):
    client, _, server = make(tmp_path, ok())
    for url in (f"{GEMINI}?key={SECRET}", f"https://example.invalid/x?api_key={SECRET}"):
        with pytest.raises(ValueError, match="header"):
            client.get(url, source="gemini", ttl=DAY)
    assert server.requests == []


def test_gemini_gets_a_long_timeout_spacing_and_a_capped_retry_after(tmp_path, monkeypatch):
    waits = []
    monkeypatch.setattr(http_module.time, "sleep", waits.append)
    client, _, server = make(tmp_path, ok("slow down", 429, **{"retry-after": "120"}), ok("{}"))
    client.post_json(GEMINI, {"input": "x"}, source="gemini", ttl=None)
    assert server.requests[0].extensions["timeout"]["read"] == http_module.TIMEOUT_BY_HOST[http_module.GEMINI_HOST]
    assert 60.0 in waits  # Retry-After 120 capped at 60 s
    client.get("https://example.invalid/fund.json", source="ti", ttl=DAY)
    assert server.requests[-1].extensions["timeout"]["read"] == http_module.TIMEOUT_SECONDS


def test_a_timed_out_gemini_call_is_not_repeated(tmp_path):
    client, _, server = make(tmp_path, httpx.ReadTimeout("thinking too long"))
    with pytest.raises(SourceUnavailable, match="1 attempt"):
        client.post_json(GEMINI, {"input": "x"}, source="gemini", ttl=None)
    assert len(server.requests) == 1
