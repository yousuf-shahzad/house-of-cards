"""Cached HTTP for every source. Owner: package d (Kendrick's Claude). Signatures fixed by W0-B.

All network access in the backend goes through an HttpClient, so caching, User-Agent, per-host
rate limits, retries, offline mode (HOC_OFFLINE=1) and stale-if-error behave the same everywhere.
Adapter tests use FakeHttpClient (below), never the network.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from hoc.contract import SourceUnavailable


@dataclass(frozen=True)
class CachedResponse:
    url: str
    status: int
    content_type: str | None
    body: bytes
    fetched_at: datetime
    from_cache: bool = False
    stale: bool = False
    """True when served from an expired cache entry (offline or the live request failed)."""

    def text(self) -> str:
        return self.body.decode("utf-8")

    def json(self) -> Any:
        return json.loads(self.body)


class HttpClient(Protocol):
    def get(
        self,
        url: str,
        *,
        source: str,
        ttl: timedelta | None,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> CachedResponse:
        """GET with caching under cache/http/<source>/. ttl=None means never expires.

        Raises SourceUnavailable on network failure with no usable cache entry. Returns non-2xx
        responses (adapters decide, e.g. 404 -> TickerNotFound); never caches 5xx.
        """
        ...

    def post_json(
        self,
        url: str,
        payload: Any,
        *,
        source: str,
        ttl: timedelta | None,
        headers: Mapping[str, str] | None = None,
    ) -> CachedResponse:
        """POST JSON, cached by a hash of url + body (used for OpenFIGI)."""
        ...


class CachedHttpClient:
    """Production client: httpx + DiskCache. Implemented by package d."""

    def __init__(self, settings, cache) -> None:
        self.settings = settings
        self.cache = cache

    def get(self, url, *, source, ttl, headers=None, params=None) -> CachedResponse:
        raise NotImplementedError("package d: CachedHttpClient.get")

    def post_json(self, url, payload, *, source, ttl, headers=None) -> CachedResponse:
        raise NotImplementedError("package d: CachedHttpClient.post_json")


class FakeHttpClient:
    """Test double: serves fixed bytes per URL. Unknown URLs raise SourceUnavailable."""

    def __init__(self, routes: Mapping[str, tuple[int, str | None, bytes]] | None = None) -> None:
        self.routes = dict(routes or {})
        self.requests: list[tuple[str, str]] = []

    def add(self, url: str, body: bytes | str, *, status: int = 200, content_type: str | None = None) -> None:
        self.routes[url] = (status, content_type, body.encode("utf-8") if isinstance(body, str) else body)

    def _serve(self, method: str, url: str) -> CachedResponse:
        self.requests.append((method, url))
        if url not in self.routes:
            raise SourceUnavailable(f"FakeHttpClient has no route for {url}")
        status, content_type, body = self.routes[url]
        return CachedResponse(url=url, status=status, content_type=content_type, body=body,
                              fetched_at=datetime.now(UTC))

    def get(self, url, *, source, ttl, headers=None, params=None) -> CachedResponse:
        if params:
            url = url + ("&" if "?" in url else "?") + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return self._serve("GET", url)

    def post_json(self, url, payload, *, source, ttl, headers=None) -> CachedResponse:
        return self._serve("POST", url)
