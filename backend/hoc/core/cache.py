"""On-disk cache (default backend/.cache/, gitignored). Owner: package d. Signatures fixed by W0-B.

Writes are atomic (temp file + os.replace) and every entry has a JSON meta sidecar
(url, status, content_type, fetched_at). Raw issuer files live only here and are never committed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CacheEntry:
    body: bytes
    meta: dict[str, Any]
    fetched_at: datetime


class DiskCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get(self, namespace: str, key: str) -> CacheEntry | None:
        """Return the entry regardless of age (callers decide freshness), or None."""
        raise NotImplementedError("package d: DiskCache.get")

    def put(self, namespace: str, key: str, body: bytes, meta: dict[str, Any]) -> CacheEntry:
        raise NotImplementedError("package d: DiskCache.put")
