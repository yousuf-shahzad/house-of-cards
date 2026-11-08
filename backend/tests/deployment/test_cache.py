"""Private storage and disposable local cache behavior, with a fake remote backend."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from hoc.deployment.cache import BlobCache
from hoc.deployment.runtime import _DeadlineClient
from hoc.deployment.storage import BlobStore

from .test_jobs import MemoryStore


def test_cache_survives_a_new_local_directory_and_preserves_bytes(tmp_path):
    objects = MemoryStore()
    now = datetime(2026, 11, 8, tzinfo=UTC)
    first = BlobCache(tmp_path / "first", objects)
    payload = b"\x00binary fixture\xff" * 100
    original = first.put("filings", "synthetic-key", payload, {"fetched_at": now, "status": 200})
    second = BlobCache(tmp_path / "second", objects)
    restored = second.get("filings", "synthetic-key")
    assert restored.body == payload and restored.meta == original.meta and restored.fetched_at == now


def test_listing_has_a_ttl_and_new_writes_invalidate_it(tmp_path):
    objects = MemoryStore()
    cache = BlobCache(tmp_path, objects)
    cache.put("ai/extractions", "first", b"{}", {"status": 200})
    assert len(list(cache.iter_metadata("ai/extractions"))) == 1
    assert len(list(cache.iter_metadata("ai/extractions"))) == 1
    assert objects.list_calls == 1
    cache.put("ai/extractions", "second", b"{}", {"status": 200})
    assert len(list(cache.iter_metadata("ai/extractions"))) == 2 and objects.list_calls == 2


def test_blob_requests_are_private_and_do_not_cache_mutable_progress(monkeypatch):
    blob = pytest.importorskip("vercel.blob.sync")

    calls = []
    monkeypatch.setattr(blob, "put_blob", lambda path, body, **kw: calls.append((path, kw)))
    monkeypatch.setattr(
        blob,
        "get_blob",
        lambda path, **kw: (
            calls.append((path, kw)) or SimpleNamespace(body=b"{}", metadata=SimpleNamespace(etag="v1"))
        ),
    )
    store = BlobStore("synthetic")
    store.put("jobs/1.json", b"{}", overwrite=False)
    assert store.get("jobs/1.json").etag == "v1"
    assert all(kw["access"] == "private" for _, kw in calls)
    assert calls[0][1]["allow_overwrite"] is False and calls[0][1]["cache_control_max_age"] == 0


def test_expired_request_budget_prevents_another_provider_call():
    import httpx

    client = _DeadlineClient(SimpleNamespace(request=lambda *a, **kw: pytest.fail("unexpected request")), 1)
    client.deadline = 0
    with pytest.raises(httpx.ReadTimeout):
        client.request("GET", "https://example.invalid")


@pytest.mark.parametrize("delivery_etag", ['"version-1"', 'W/"version-1"'])
def test_conditional_delete_accepts_cdn_etag_without_losing_version_check(monkeypatch, delivery_etag):
    blob = pytest.importorskip("vercel.blob.sync")
    deleted, heads = [], []
    monkeypatch.setattr(blob, "head_blob", lambda path: heads.append(path) or SimpleNamespace(etag='"version-1"'))

    def delete(path, *, if_match):
        # The write API requires a strong ETag; private downloads may supply W/.
        assert if_match == '"version-1"'
        deleted.append(path)

    monkeypatch.setattr(blob, "delete_blob", delete)
    store = BlobStore("synthetic")
    store.delete("jobs/expired.json", etag=delivery_etag)
    assert deleted == [store._path("jobs/expired.json")]
    assert len(heads) == (1 if delivery_etag.startswith("W/") else 0)


def test_conditional_delete_does_not_remove_a_newer_scan(monkeypatch):
    blob = pytest.importorskip("vercel.blob.sync")
    from vercel.blob import BlobPreconditionFailedError

    monkeypatch.setattr(blob, "head_blob", lambda path: SimpleNamespace(etag='"version-2"'))
    monkeypatch.setattr(blob, "delete_blob", lambda *a, **kw: pytest.fail("must preserve newer scan"))
    with pytest.raises(BlobPreconditionFailedError):
        BlobStore("synthetic").delete("jobs/expired.json", etag='W/"version-1"')


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        b"{}",
        b'{"meta":{"key":"other"}}',
        b'{"meta":{"key":"wanted","fetched_at":"bad"},"body":""}',
    ],
)
def test_corrupt_shared_entries_are_cache_misses(tmp_path, payload):
    objects = MemoryStore()
    cache = BlobCache(tmp_path, objects)
    objects.put(cache._key("synthetic", "wanted"), payload)
    assert cache.get("synthetic", "wanted") is None


def test_local_only_http_namespaces_do_not_spend_shared_read_quota(tmp_path, monkeypatch):
    objects = MemoryStore()
    monkeypatch.setattr(objects, "get", lambda key: pytest.fail("unnecessary shared lookup"))
    cache = BlobCache(tmp_path, objects)
    assert cache.get("http/gemini", "synthetic") is None
    assert cache.get("http/tickerinside", "https://tickerinside.com/api/v1/sec/zz.json") is None


def test_suspended_cache_does_not_block_real_http_or_local_reuse(tmp_path, monkeypatch):
    import httpx
    from datetime import timedelta
    from hoc.config import Settings
    from hoc.core.http import CachedHttpClient

    objects, remote_calls, upstream = MemoryStore(), [], []

    def unavailable(key):
        remote_calls.append(key)
        raise PermissionError("synthetic suspended storage")

    monkeypatch.setattr(objects, "get", unavailable)
    monkeypatch.setattr(objects, "put", lambda *a, **kw: pytest.fail("remote cache should be paused"))
    cache = BlobCache(tmp_path, objects)
    http = CachedHttpClient(Settings(cache_dir=tmp_path), cache)
    http._client = httpx.Client(transport=httpx.MockTransport(
        lambda req: upstream.append(req.url) or httpx.Response(200, content=b"real source bytes")
    ))
    first = http.get("https://example.invalid/fund", source="synthetic", ttl=timedelta(hours=1))
    second = http.get("https://example.invalid/fund", source="synthetic", ttl=timedelta(hours=1))
    assert first.body == second.body == b"real source bytes"
    assert len(upstream) == len(remote_calls) == 1


def test_failed_cache_write_preserves_local_entry_and_metadata(tmp_path, monkeypatch):
    objects = MemoryStore()

    def unavailable(*args, **kwargs):
        raise PermissionError("synthetic suspended storage")

    monkeypatch.setattr(objects, "put", unavailable)
    monkeypatch.setattr(objects, "keys", lambda *a: pytest.fail("remote cache should be paused"))
    cache = BlobCache(tmp_path, objects)
    entry = cache.put("ai/extractions", "verified", b"verified bytes", {"status": 200})
    assert cache.get("ai/extractions", "verified").body == entry.body
    assert list(cache.iter_metadata("ai/extractions")) == [entry.meta]
