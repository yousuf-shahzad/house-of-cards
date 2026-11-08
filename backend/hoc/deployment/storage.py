"""Private Blob objects behind a small injectable interface, without credentials in payloads."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Stored:
    body: bytes
    etag: str


class ObjectStore(Protocol):
    def get(self, key: str) -> Stored | None: ...
    def put(self, key: str, body: bytes, *, overwrite: bool = True) -> bool: ...
    def delete(self, key: str, *, etag: str) -> None: ...
    def keys(self, prefix: str) -> list[str]: ...


def encode(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def read_json(store: ObjectStore, key: str) -> dict | None:
    entry = store.get(key)
    return json.loads(entry.body) if entry else None


class BlobStore:
    def __init__(self, prefix: str | None = None) -> None:
        # Separate preview data from production. No user input becomes a Blob path.
        self.prefix = (prefix or os.getenv("HOC_BLOB_PREFIX", "house-of-cards")).strip("/")
        self.prefix += "/" + os.getenv("VERCEL_ENV", "development")

    def _path(self, key: str) -> str:
        if ".." in key.split("/") or key.startswith("/"):
            raise ValueError("Invalid storage key")
        return f"{self.prefix}/{key}"

    def get(self, key: str) -> Stored | None:
        from vercel.blob import BlobNotFoundError
        from vercel.blob import sync as blob

        try:
            found = blob.get_blob(self._path(key), access="private")
        except BlobNotFoundError:
            return None
        return Stored(found.body, found.metadata.etag or "")

    def put(self, key: str, body: bytes, *, overwrite: bool = True) -> bool:
        from vercel.blob import BlobError
        from vercel.blob import sync as blob

        try:
            blob.put_blob(
                self._path(key),
                body,
                access="private",
                add_random_suffix=False,
                allow_overwrite=overwrite,
                content_type="application/octet-stream",
                cache_control_max_age=0,
            )
        except BlobError:
            # A create conflict is expected when two browsers submit the same job.
            # Permissions, quota and network failures must still surface.
            if not overwrite and self.get(key) is not None:
                return False
            raise
        return True

    def delete(self, key: str, *, etag: str) -> None:
        from vercel.blob import sync as blob

        blob.delete_blob(self._path(key), if_match=etag)

    def keys(self, prefix: str) -> list[str]:
        from vercel.blob import sync as blob

        base = self.prefix + "/"
        return [entry.pathname.removeprefix(base) for entry in blob.query_blobs(prefix=self._path(prefix))]
