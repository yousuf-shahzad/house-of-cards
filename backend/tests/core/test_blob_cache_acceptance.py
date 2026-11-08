"""Independent #262 acceptance checks, using fake storage and HTTP only."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import sys
import types
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from hoc.ai.cache import EXTRACTION_CACHE_NAMESPACE, ExtractionCache, make_extraction_cache_key
from hoc.config import Settings
from hoc.core.cache import DiskCache
from hoc.core.http import CachedHttpClient
from hoc.deployment import cache as blob_module
from hoc.deployment.cache import BlobCache
from hoc.deployment.storage import BlobStore, Stored, encode
from hoc.portfolio.compare import read_cached_extractions

OLD = datetime(2020, 1, 1, tzinfo=UTC)
URL = "https://example.invalid/fund.json"


class MemoryObjects:
    def __init__(self):
        self.entries = {}
        self.list_calls = []

    def get(self, key):
        return self.entries.get(key)

    def put(self, key, body, *, overwrite=True):
        if key in self.entries and not overwrite:
            return False
        self.entries[key] = Stored(body, str(len(self.entries)))
        return True

    def keys(self, prefix):
        self.list_calls.append(prefix)
        return sorted(key for key in self.entries if key.startswith(prefix))


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    monkeypatch.delenv("HOC_CACHE_BACKEND", raising=False)
    blob_module.BlobCache._listings.clear()
    monkeypatch.setattr("hoc.core.http.RETRY_DELAYS", ())
    monkeypatch.setattr("hoc.core.http.MIN_INTERVAL_SECONDS", {})


def http_client(root, objects, transport, *, offline=False):
    client = CachedHttpClient(Settings(cache_dir=root, offline=offline), BlobCache(root, objects))
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(transport))
    return client


def test_default_disk_bytes_and_opt_out_are_unchanged(tmp_path, monkeypatch):
    disk = DiskCache(tmp_path)
    disk.put("http/x", URL, b"issuer bytes", {"fetched_at": OLD, "status": 200})
    digest = hashlib.sha256(URL.encode()).hexdigest()
    assert (tmp_path / "http/x" / f"{digest}.body").read_bytes() == b"issuer bytes"
    expected = {"fetched_at": OLD.isoformat(), "status": 200, "key": URL}
    assert (tmp_path / "http/x" / f"{digest}.json").read_bytes() == json.dumps(
        expected, sort_keys=True
    ).encode()
    monkeypatch.setenv("HOC_CACHE_BACKEND", "vercel")
    assert DiskCache(tmp_path, remote=False).get("http/x", URL).body == b"issuer bytes"


def test_remote_factory_and_fresh_replay_between_cold_instances(tmp_path, monkeypatch):
    objects = MemoryObjects()
    original = BlobCache
    monkeypatch.setattr(blob_module, "BlobCache", lambda root: original(root, objects))
    monkeypatch.setenv("HOC_CACHE_BACKEND", "vercel")
    first = DiskCache(tmp_path / "first")
    entry = first.put("ai/extractions", "company|filing|model|v1", b"verified", {"fetched_at": OLD})
    cold = DiskCache(tmp_path / "cold").get("ai/extractions", "company|filing|model|v1")
    assert cold == entry
    assert cold.fetched_at == OLD


def test_http_fresh_ttl_expiry_and_offline_preserve_original_timestamp(tmp_path):
    objects = MemoryObjects()
    initial = BlobCache(tmp_path / "first", objects)
    initial.put("http/issuer", URL, b"old", {"fetched_at": OLD, "status": 200})
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(200, content=b"new")

    offline = http_client(tmp_path / "offline", objects, reply, offline=True)
    stale = offline.get(URL, source="issuer", ttl=timedelta(hours=24))
    assert stale.body == b"old" and stale.stale and stale.from_cache
    assert stale.fetched_at == OLD and requests == []
    online = http_client(tmp_path / "online", objects, reply)
    assert online.get(URL, source="issuer", ttl=timedelta(hours=24)).body == b"new"
    cold = http_client(tmp_path / "cold", objects, reply)
    assert cold.get(URL, source="issuer", ttl=timedelta(hours=24)).from_cache
    assert len(requests) == 1


@pytest.mark.parametrize("failure", ["network", "503", "429"])
def test_http_stale_if_error_works_from_shared_cache(tmp_path, failure):
    objects = MemoryObjects()
    BlobCache(tmp_path / "writer", objects).put(
        "http/issuer", URL, b"stale issuer", {"fetched_at": OLD, "status": 200}
    )

    def fail(request):
        if failure == "network":
            raise httpx.ConnectError("down")
        return httpx.Response(int(failure), content=b"error")

    client = http_client(tmp_path / "cold", objects, fail)
    result = client.get(URL, source="issuer", ttl=timedelta(seconds=1))
    assert result.from_cache and result.stale and result.body == b"stale issuer"
    assert len(objects.entries) == 1


@pytest.mark.parametrize("source", ["gemini", "gemini-alternate"])
def test_gemini_errors_and_credentials_never_enter_blob_or_local_cache(tmp_path, source):
    objects = MemoryObjects()
    secret = "synthetic-acceptance-key"
    url = "https://generativelanguage.googleapis.com/v1beta/interactions"
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(400 if len(requests) == 1 else 200, json={"output": "safe"})

    client = http_client(tmp_path, objects, reply)
    for expected in (400, 200):
        assert client.post_json(url, {"input": "synthetic"}, source=source, ttl=None,
                                headers={"x-goog-api-key": secret}).status == expected
    assert requests[0].headers["x-goog-api-key"] == secret
    assert client.post_json(url, {"input": "synthetic"}, source=source, ttl=None).from_cache
    with pytest.raises(ValueError, match="header"):
        client.get(url + "?key=" + secret, source=source, ttl=None)
    stored = b"".join(entry.body for entry in objects.entries.values())
    for entry in objects.entries.values():
        value = json.loads(entry.body)
        assert "headers" not in value["meta"]
        stored += gzip.decompress(base64.b64decode(value["body"]))
    stored += b"".join(path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
    assert secret.encode() not in stored
    assert len(requests) == 2


def test_listing_ttl_reuses_across_instances_and_invalidates_after_put(tmp_path, monkeypatch):
    objects = MemoryObjects()
    clock = [100.0]
    monkeypatch.setattr(blob_module.time, "monotonic", lambda: clock[0])
    first = BlobCache(tmp_path / "one", objects)
    second = BlobCache(tmp_path / "two", objects)
    first.put("ai/extractions", "one", b"{}", {})
    assert [m["key"] for m in first.iter_metadata("ai/extractions")] == ["one"]
    assert [m["key"] for m in second.iter_metadata("ai/extractions")] == ["one"]
    assert len(objects.list_calls) == 1
    clock[0] += 6
    assert list(second.iter_metadata("ai/extractions"))
    assert len(objects.list_calls) == 2
    first.put("ai/extractions", "two", b"{}", {})
    assert {m["key"] for m in second.iter_metadata("ai/extractions")} == {"one", "two"}
    assert len(objects.list_calls) == 3


@pytest.mark.parametrize("bad", [b"{", b"[]", b'{"meta":null}', b'{"meta":{"key":"wanted"},"body":"!"}'])
def test_corrupt_blob_is_a_miss_like_disk_cache(tmp_path, bad):
    objects = MemoryObjects()
    objects.put(BlobCache._key("ai/extractions", "wanted"), bad)
    assert BlobCache(tmp_path, objects).get("ai/extractions", "wanted") is None


def test_bad_listing_entry_does_not_hide_valid_extraction(tmp_path):
    objects = MemoryObjects()
    cache = BlobCache(tmp_path / "writer", objects)
    cache.put("ai/extractions", "good", b"verified", {"status": 200})
    objects.put("cache/ai/extractions/000-broken.json", b"{")
    assert [m["key"] for m in BlobCache(tmp_path / "cold", objects).iter_metadata("ai/extractions")] == ["good"]


@pytest.mark.parametrize("timestamp", [None, "not-a-date"])
def test_blob_never_refreshes_age_for_missing_or_invalid_timestamp(tmp_path, timestamp):
    objects = MemoryObjects()
    meta = {"key": "wanted"}
    if timestamp is not None:
        meta["fetched_at"] = timestamp
    value = {"meta": meta, "body": base64.b64encode(gzip.compress(b"old")).decode()}
    objects.put(BlobCache._key("http/issuer", "wanted"), encode(value))
    assert BlobCache(tmp_path, objects).get("http/issuer", "wanted") is None


def test_cold_compare_replays_only_verified_matching_extractions(tmp_path, monkeypatch):
    objects = MemoryObjects()
    original = BlobCache
    monkeypatch.setattr(blob_module, "BlobCache", lambda root: original(root, objects))
    monkeypatch.setenv("HOC_CACHE_BACKEND", "vercel")
    writer = DiskCache(tmp_path / "writer")
    source = "CIK:9990000001"
    accession = "9990000001-26-000001"
    edge = {
        "edge_id": "synthetic-edge", "source_company_key": source,
        "source_company_name": "ZZ Synthetic", "source_in_portfolio": False,
        "edge_type": "supplier", "target_name": "ZZ Supplier", "target_kind": "company",
        "target_key": None, "target_in_portfolio": False,
        "evidence_quote": "We rely on ZZ Supplier.", "section": "Item 1",
        "filing": {"company_key": source, "form": "10-K", "accession": accession,
                   "filed": "2026-10-30", "url": "https://example.invalid/filing"},
    }
    payload = {"company_key": source, "accession": accession, "model": "synthetic-model",
               "prompt_version": "synthetic-v1", "filed": "2026-10-30", "edges": [edge]}
    ExtractionCache(writer).put(source, accession, model="synthetic-model", prompt_version="synthetic-v1",
                                payload=payload)
    # A newer, unverified raw prediction must not displace the older verified result.
    newer = "9990000001-26-000002"
    raw = {**payload, "accession": newer, "filed": "2026-11-01", "edges": [{"prediction": "raw"}]}
    ExtractionCache(writer).put(source, newer, model="synthetic-model", prompt_version="synthetic-v1",
                                payload=raw)
    # Nor may a payload whose metadata and body identify different companies.
    wrong = "CIK:9990000002"
    key = make_extraction_cache_key(wrong, accession, "synthetic-model", "synthetic-v1")
    writer.put(EXTRACTION_CACHE_NAMESPACE, key, encode(payload), {"status": 200})
    result = read_cached_extractions(tmp_path / "cold", [source, wrong], models=["synthetic-model"],
                                     prompt_version="synthetic-v1")
    assert list(result) == [source]
    assert [found.edge_id for found in result[source]] == ["synthetic-edge"]


def test_service_injected_http_preserves_history_and_existing_providers(tmp_path):
    from hoc.core.http import FakeHttpClient
    from hoc.service import EtfService

    supplied = FakeHttpClient()
    service = EtfService.from_settings(Settings(cache_dir=tmp_path), http=supplied)
    assert service.reference.http is supplied
    assert service.quotes.http is supplied
    assert service.history.provider.http is supplied
    assert service.dependency_pipeline.fetcher.http is supplied
    assert service.idea_proposer._http_client is supplied
    assert service.dependency_pipeline.researcher is service.research_runner


def test_hash_collision_guard_does_not_hydrate_wrong_key(tmp_path):
    objects = MemoryObjects()
    value = {"meta": {"key": "different", "fetched_at": OLD.isoformat()},
             "body": base64.b64encode(gzip.compress(b"wrong")).decode()}
    objects.put(BlobCache._key("ai/extractions", "wanted"), encode(value))
    assert BlobCache(tmp_path, objects).get("ai/extractions", "wanted") is None
    assert not list(tmp_path.rglob("*.json"))


def test_blob_sdk_calls_explicitly_use_private_access(tmp_path, monkeypatch):
    calls = []
    sdk = types.ModuleType("vercel.blob")
    sdk.BlobNotFoundError = type("BlobNotFoundError", (Exception,), {})
    sdk.BlobError = type("BlobError", (Exception,), {})

    def put(path, body, **kwargs):
        calls.append(("put", path, kwargs))

    def get(path, **kwargs):
        calls.append(("get", path, kwargs))
        return types.SimpleNamespace(body=b"private", metadata=types.SimpleNamespace(etag="etag"))

    sdk.sync = types.SimpleNamespace(put_blob=put, get_blob=get)
    package = types.ModuleType("vercel")
    package.blob = sdk
    monkeypatch.setitem(sys.modules, "vercel", package)
    monkeypatch.setitem(sys.modules, "vercel.blob", sdk)
    monkeypatch.setenv("VERCEL_ENV", "preview")
    store = BlobStore("synthetic")
    assert store.put("cache/x", b"private")
    assert store.get("cache/x").body == b"private"
    assert all(path == "synthetic/preview/cache/x" for _, path, _ in calls)
    assert all(kwargs["access"] == "private" for _, _, kwargs in calls)
    assert calls[0][2]["add_random_suffix"] is False
