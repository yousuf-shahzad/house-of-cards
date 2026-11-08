"""A compressed private shared cache, with /tmp as a disposable local accelerator."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from hoc.core.cache import CacheEntry, DiskCache
from hoc.deployment.storage import BlobStore, ObjectStore, encode, is_storage_failure

log = logging.getLogger(__name__)


class BlobCache:
    _listings: ClassVar[dict[tuple, tuple[float, list[str]]]] = {}
    _listing_lock = threading.Lock()
    _outages: ClassVar[dict[str, float]] = {}

    def __init__(self, root: Path, store: ObjectStore | None = None) -> None:
        self.local = DiskCache(root, remote=False)
        self.store = store or BlobStore()
        self._pause_until = 0.0

    def _remote_call(self, method, *args):
        prefix = getattr(self.store, "prefix", None)
        paused = self._outages.get(prefix, 0) if prefix else self._pause_until
        if time.monotonic() < paused:
            return None
        try:
            return getattr(self.store, method)(*args)
        except Exception as exc:
            if not is_storage_failure(exc):
                raise
            # Shared caching is optional. A quota/access outage must not prevent
            # fetching real issuer data or using the writable local cache.
            until = time.monotonic() + 60
            if prefix:
                self._outages[prefix] = until
            self._pause_until = until
            log.warning("Shared cache unavailable (%s); using local cache for 60s.", type(exc).__name__)
            return None

    @staticmethod
    def _key(namespace: str, key: str) -> str:
        name = hashlib.sha256(key.encode()).hexdigest()
        return f"cache/{namespace}/{name}.json"

    def get(self, namespace: str, key: str) -> CacheEntry | None:
        cached = self.local.get(namespace, key)
        if cached is not None:
            return cached
        if namespace == "http/gemini" or (namespace == "http/tickerinside" and "/api/v1/sec/" in key):
            return None
        found = self._remote_call("get", self._key(namespace, key))
        if found is None:
            return None
        try:
            value = json.loads(found.body)
            if value["meta"].get("key") != key:
                return None
            datetime.fromisoformat(value["meta"]["fetched_at"])
            body = gzip.decompress(base64.b64decode(value["body"], validate=True))
            if not body:
                return None
            return self.local.put(namespace, key, body, value["meta"])
        except (OSError, EOFError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def put(self, namespace: str, key: str, body: bytes, meta: dict) -> CacheEntry:
        entry = self.local.put(namespace, key, body, meta)
        # Thousands of tiny per-security reference files would consume the free
        # upload allowance. Normalized ETFs and fund/global reference files are shared.
        if namespace == "http/gemini" or (namespace == "http/tickerinside" and "/api/v1/sec/" in key):
            return entry
        value = {"meta": entry.meta, "body": base64.b64encode(gzip.compress(body)).decode()}
        self._remote_call("put", self._key(namespace, key), encode(value))
        with self._listing_lock:
            self._listings.pop((getattr(self.store, "prefix", id(self.store)), namespace), None)
        return entry

    def iter_metadata(self, namespace: str):
        listing_key = (getattr(self.store, "prefix", id(self.store)), namespace)
        with self._listing_lock:
            cached = self._listings.get(listing_key)
        if cached is None or time.monotonic() - cached[0] > 5:
            keys = self._remote_call("keys", f"cache/{namespace}/") or []
            with self._listing_lock:
                self._listings[listing_key] = (time.monotonic(), keys)
        else:
            keys = cached[1]
        seen = set()
        for key in keys:
            found = self._remote_call("get", key)
            if found is None:
                continue
            try:
                value = json.loads(found.body)
                meta = value["meta"]
                if meta["key"] in seen:
                    continue
                if self._key(namespace, meta["key"]) != key:
                    continue
                datetime.fromisoformat(meta["fetched_at"])
                body = gzip.decompress(base64.b64decode(value["body"], validate=True))
                if not body:
                    continue
                # Hydrate the ordinary reader so it validates verified edges and dates.
                self.local.put(namespace, meta["key"], body, meta)
            except (OSError, EOFError, ValueError, KeyError, TypeError, AttributeError):
                continue
            seen.add(meta["key"])
            yield meta
        for meta in self.local.iter_metadata(namespace):
            if (
                isinstance(meta, dict)
                and isinstance(meta.get("key"), str)
                and meta["key"] not in seen
                and self.local.get(namespace, meta["key"]) is not None
            ):
                yield meta
