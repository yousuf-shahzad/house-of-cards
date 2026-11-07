"""Shared TickerInside file access: one cached GET per file per 24 h (their terms)."""

from __future__ import annotations

import re
import threading
from datetime import timedelta
from typing import Any

from hoc.contract import SourceParseError, SourceUnavailable, TickerNotFound

BASE_URL = "https://tickerinside.com/api/v1"
TTL = timedelta(hours=24)
LICENCE = "CC BY 4.0"
SOURCE = "tickerinside"


def get_json(http, settings, path: str) -> tuple[Any, Any]:
    """GET {BASE_URL}/{path} -> (parsed JSON, CachedResponse). 404 -> TickerNotFound."""
    response = http.get(f"{BASE_URL}/{path}", source=SOURCE, ttl=TTL,
                        headers={"User-Agent": settings.user_agent})
    if response.status == 404:
        raise TickerNotFound(f"TickerInside has no {path}")
    if not 200 <= response.status < 300:
        raise SourceUnavailable(f"TickerInside returned HTTP {response.status} for {path}")
    try:
        return response.json(), response
    except ValueError as exc:  # HTML error page or truncated body
        raise SourceParseError(f"TickerInside {path} is not JSON") from exc


def country_of(symbol: str) -> str | None:
    """'2330.TW' -> 'TW'. US class suffixes are one letter ('BRK.B'), so they never match."""
    match = re.fullmatch(r"[^.]+\.([A-Z]{2})", symbol)
    return match.group(1) if match else None


class ReferenceFiles:
    """securities.json (names) and identifiers.json (CIK, FIGI, exchange, asset type), parsed once."""

    def __init__(self, http, settings) -> None:
        self.http, self.settings = http, settings
        self._lock = threading.Lock()
        self._securities: dict[str, list] | None = None
        self._identifiers: dict[str, dict] | None = None

    def securities(self) -> dict[str, list]:
        """symbol -> [ticker, holder count, max weight, name, has page, has stock file]."""
        with self._lock:
            if self._securities is None:
                data, _ = get_json(self.http, self.settings, "securities.json")
                rows = data.get("securities") if isinstance(data, dict) else None
                if not isinstance(rows, list):
                    raise SourceParseError("TickerInside securities.json has no securities list")
                self._securities = {r[0].upper(): r for r in rows if isinstance(r, list) and r}
            return self._securities

    def identifiers(self) -> dict[str, dict]:
        """symbol -> {field: value} using the file's own `fields` order."""
        with self._lock:
            if self._identifiers is None:
                data, _ = get_json(self.http, self.settings, "identifiers.json")
                fields, rows = (data.get("fields"), data.get("securities")) if isinstance(data, dict) else (None, None)
                if not isinstance(fields, list) or not isinstance(rows, list):
                    raise SourceParseError("TickerInside identifiers.json has no fields/securities")
                self._identifiers = {r[0].upper(): dict(zip(fields, r, strict=False))
                                     for r in rows if isinstance(r, list) and r}
            return self._identifiers
