"""A compressed private shared cache, with /tmp as a disposable local accelerator."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import threading
import time
from pathlib import Path
from typing import ClassVar

from hoc.core.cache import CacheEntry, DiskCache
from hoc.deployment.storage import BlobStore, ObjectStore, encode


class BlobCache:
    _listings: ClassVar[dict[tuple, tuple[float, list[str]]]] = {}
    _listing_lock = threading.Lock()

    def __init__(self, root: Path, store: ObjectStore | None = None) -> None:
        self.local = DiskCache(root, remote=False)
        self.store = store or BlobStore()

    @staticmethod
    def _key(namespace: str, key: str) -> str:
        name = hashlib.sha256(key.encode()).hexdigest()
        return f"cache/{namespace}/{name}.json"

    def get(self, namespace: str, key: str) -> CacheEntry | None:
        cached = self.local.get(namespace, key)
        if cached is not None:
            return cached
        found = self.store.get(self._key(namespace, key))
        if found is None:
            return None
        try:
            value = json.loads(found.body)
            if value["meta"].get("key") != key:
                return None
            body = gzip.decompress(base64.b64decode(value["body"]))
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
        self.store.put(self._key(namespace, key), encode(value))
        with self._listing_lock:
            self._listings.pop((getattr(self.store, "prefix", id(self.store)), namespace), None)
        return entry

    def iter_metadata(self, namespace: str):
        listing_key = (getattr(self.store, "prefix", id(self.store)), namespace)
        with self._listing_lock:
            cached = self._listings.get(listing_key)
        if cached is None or time.monotonic() - cached[0] > 5:
            keys = self.store.keys(f"cache/{namespace}/")
            with self._listing_lock:
                self._listings[listing_key] = (time.monotonic(), keys)
        else:
            keys = cached[1]
        for key in keys:
            found = self.store.get(key)
            if found is None:
                continue
            try:
                value = json.loads(found.body)
                meta = value["meta"]
                if self._key(namespace, meta["key"]) != key:
                    continue
                # Hydrate the ordinary reader so it validates verified edges and dates.
                self.local.put(namespace, meta["key"], gzip.decompress(base64.b64decode(value["body"])), meta)
            except (OSError, EOFError, ValueError, KeyError, TypeError, AttributeError):
                continue
            yield meta
