"""On-disk cache (default backend/.cache/, gitignored). Owner: Bekarys's Claude (core/ handed over from d).

Writes are atomic (temp file + os.replace) and every entry has a JSON meta sidecar
(url, status, content_type, fetched_at). Raw issuer files live only here and are never committed.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CacheEntry:
    body: bytes
    meta: dict[str, Any]
    fetched_at: datetime


def _write_atomic(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class DiskCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _paths(self, namespace: str, key: str) -> tuple[Path, Path]:
        folder = self.root.joinpath(*(part for part in namespace.split("/") if part not in ("", ".", "..")))
        name = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return folder / f"{name}.body", folder / f"{name}.json"

    def get(self, namespace: str, key: str) -> CacheEntry | None:
        """Return the entry regardless of age (callers decide freshness), or None."""
        body_path, meta_path = self._paths(namespace, key)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            body = body_path.read_bytes()
            fetched_at = datetime.fromisoformat(meta["fetched_at"])
        except (OSError, ValueError, KeyError):
            return None  # missing or half-written entry: treat as a miss
        if meta.get("key") != key:
            return None  # hash collision guard
        return CacheEntry(body=body, meta=meta, fetched_at=fetched_at)

    def put(self, namespace: str, key: str, body: bytes, meta: dict[str, Any]) -> CacheEntry:
        """meta may carry an aware `fetched_at` (datetime or ISO string); otherwise now (UTC)."""
        body_path, meta_path = self._paths(namespace, key)
        body_path.parent.mkdir(parents=True, exist_ok=True)
        fetched = meta.get("fetched_at") or datetime.now(UTC)
        fetched_at = datetime.fromisoformat(fetched) if isinstance(fetched, str) else fetched
        meta = {**meta, "key": key, "fetched_at": fetched_at.isoformat()}
        # Body first, then meta: a reader that sees the new meta always finds a complete body.
        _write_atomic(body_path, body)
        _write_atomic(meta_path, json.dumps(meta, sort_keys=True).encode("utf-8"))
        return CacheEntry(body=body, meta=meta, fetched_at=fetched_at)
