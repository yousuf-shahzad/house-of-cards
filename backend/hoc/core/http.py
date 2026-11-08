"""Cached HTTP for every source. Owner: Bekarys's Claude (core/ handed over from d). Signatures fixed by W0-B.

All network access in the backend goes through an HttpClient, so caching, User-Agent, per-host
rate limits, retries, offline mode (HOC_OFFLINE=1) and stale-if-error behave the same everywhere.
Adapter tests use FakeHttpClient (below), never the network.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

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


GEMINI_HOST = "generativelanguage.googleapis.com"

MIN_INTERVAL_SECONDS = {
    "sec.gov": 0.12,  # SEC fair access: at most 10 requests per second
    "api.openfigi.com": 2.5,  # keyless OpenFIGI: 25 requests per minute
    GEMINI_HOST: 1.0,  # event key; Argon's limits are only visible in AI Studio
}
"""Per-host spacing between requests. A key matches the host and its subdomains (www.sec.gov)."""
RETRY_DELAYS = (1.0, 3.0)
"""Seconds to wait before each retry of a network error, 429 or 5xx. Retry-After is honoured up to 30 s."""
TIMEOUT_SECONDS = 30.0

# Per-host overrides (same host/subdomain matching as MIN_INTERVAL_SECONDS).
TIMEOUT_BY_HOST = {GEMINI_HOST: 900.0}
"""Long thinking calls on Argon can take minutes (R5). A timeout this long is never retried."""
RETRY_DELAYS_BY_HOST = {GEMINI_HOST: (5.0, 20.0)}
"""Gemini answers 429 (quota) and 503 ("model overloaded") often; back off harder."""
RETRY_AFTER_CAP_BY_HOST = {GEMINI_HOST: 60.0}
UNCACHED_ERROR_HOSTS = frozenset({GEMINI_HOST})
"""Hosts whose non-2xx answers are never cached (a 400 from a bad prompt must not stick)."""
SECRET_QUERY_PARAMS = frozenset({"key", "api_key", "apikey"})
"""Never allowed in a URL: URLs are written to cache meta. Keys go in headers (x-goog-api-key)."""


def _for_host(table: Mapping[str, Any], host: str, default):
    return next((v for h, v in table.items() if host == h or host.endswith("." + h)), default)


def _now() -> datetime:
    return datetime.now(UTC)


class CachedHttpClient:
    """Production client: httpx + DiskCache.

    Fresh cache entry -> served without a request. Offline -> any cached entry (stale=True if expired),
    else SourceUnavailable. Live request failing (network error, 429/5xx after retries) -> the expired
    entry if there is one (stale-if-error), else SourceUnavailable. Every response below 500 except 429
    is cached, so a 404 is not refetched within its TTL.
    """

    def __init__(self, settings, cache) -> None:
        self.settings = settings
        self.cache = cache
        self._client = httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True)
        self._host_locks: dict[str, threading.Lock] = {}
        self._last_request: dict[str, float] = {}
        self._locks_guard = threading.Lock()

    def get(self, url, *, source, ttl, headers=None, params=None) -> CachedResponse:
        if params:
            url = f"{url}{'&' if '?' in url else '?'}{urlencode(sorted(params.items()))}"
        return self._fetch("GET", url, url, source=source, ttl=ttl, headers=headers)

    def post_json(self, url, payload, *, source, ttl, headers=None) -> CachedResponse:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        key = f"POST {url} {hashlib.sha256(body.encode('utf-8')).hexdigest()}"
        return self._fetch("POST", url, key, source=source, ttl=ttl, headers=headers, payload=payload)

    # ---------- internals ----------

    def _fetch(self, method, url, key, *, source, ttl, headers, payload=None) -> CachedResponse:
        parts = urlsplit(url)
        if any(name.lower() in SECRET_QUERY_PARAMS for name, _ in parse_qsl(parts.query)):
            raise ValueError(f"API keys must go in a header, never in the URL ({parts.hostname})")
        namespace = f"http/{source}"
        entry = self.cache.get(namespace, key)
        if entry is not None and (ttl is None or _now() - entry.fetched_at < ttl):
            return self._from_entry(url, entry, stale=False)
        if self.settings.offline:
            if entry is not None:
                return self._from_entry(url, entry, stale=True)
            raise SourceUnavailable(f"offline (HOC_OFFLINE=1) and {source} has no cached copy of this file")
        try:
            response = self._request(method, url, headers, payload)
        except SourceUnavailable:
            if entry is not None:
                return self._from_entry(url, entry, stale=True)
            raise
        fetched_at = _now()
        content_type = response.headers.get("content-type")
        # 429 and 5xx never get here (_request retries, then raises), so this caches only real answers;
        # some hosts (Gemini) also keep their 4xx out of the cache. Headers are never stored.
        if 200 <= response.status_code < 300 or parts.hostname not in UNCACHED_ERROR_HOSTS:
            self.cache.put(namespace, key, response.content, {
                "url": url, "status": response.status_code, "content_type": content_type, "fetched_at": fetched_at,
            })
        return CachedResponse(url=url, status=response.status_code, content_type=content_type,
                              body=response.content, fetched_at=fetched_at)

    def _request(self, method, url, headers, payload) -> httpx.Response:
        merged = {"User-Agent": self.settings.user_agent, **(headers or {})}
        host = urlsplit(url).hostname or ""
        delays = _for_host(RETRY_DELAYS_BY_HOST, host, RETRY_DELAYS)
        timeout = _for_host(TIMEOUT_BY_HOST, host, TIMEOUT_SECONDS)
        retry_after_cap = _for_host(RETRY_AFTER_CAP_BY_HOST, host, 30.0)
        last_error = "no attempt"
        attempts = 0
        for attempt in range(len(delays) + 1):
            self._wait_for_host(host)
            attempts += 1
            delay = delays[attempt] if attempt < len(delays) else None
            try:
                response = self._client.request(method, url, headers=merged, json=payload, timeout=timeout)
            except httpx.HTTPError as exc:  # message never includes headers, so no key leaks here
                last_error = type(exc).__name__
                if isinstance(exc, httpx.TimeoutException) and timeout > TIMEOUT_SECONDS:
                    break  # a long call that timed out is not worth repeating
            else:
                if response.status_code != 429 and response.status_code < 500:
                    return response
                last_error = f"HTTP {response.status_code}"
                retry_after = response.headers.get("retry-after", "")
                if delay is not None and retry_after.isdigit():
                    delay = min(max(delay, float(retry_after)), retry_after_cap)
            if delay is None:
                break
            time.sleep(delay)
        raise SourceUnavailable(f"{host} unavailable after {attempts} attempt(s) ({last_error})")

    def _wait_for_host(self, host: str) -> None:
        interval = next((s for h, s in MIN_INTERVAL_SECONDS.items() if host == h or host.endswith("." + h)), 0)
        if not interval:
            return
        with self._locks_guard:
            lock = self._host_locks.setdefault(host, threading.Lock())
        with lock:
            wait = self._last_request.get(host, 0.0) + interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request[host] = time.monotonic()

    @staticmethod
    def _from_entry(url: str, entry, *, stale: bool) -> CachedResponse:
        return CachedResponse(url=entry.meta.get("url", url), status=entry.meta.get("status", 200),
                              content_type=entry.meta.get("content_type"), body=entry.body,
                              fetched_at=entry.fetched_at, from_cache=True, stale=stale)


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
