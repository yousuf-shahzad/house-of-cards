"""Shared TickerInside file access: one cached GET per file per 24 h (their terms)."""

from __future__ import annotations

import re
import threading
from datetime import timedelta
from functools import lru_cache
from typing import Any

from hoc.contract import SourceParseError, SourceUnavailable, TickerNotFound
from hoc.identity.resolver import DEPOSITARY_RECEIPT_SYMBOLS, load_aliases

BASE_URL = "https://tickerinside.com/api/v1"
TTL = timedelta(hours=24)
LICENCE = "CC BY 4.0"
SOURCE = "tickerinside"


def get_json(http, settings, path: str, ttl: timedelta = TTL) -> tuple[Any, Any]:
    """GET {BASE_URL}/{path} -> (parsed JSON, CachedResponse). 404 -> TickerNotFound."""
    response = http.get(f"{BASE_URL}/{path}", source=SOURCE, ttl=ttl,
                        headers={"User-Agent": settings.user_agent})
    if response.status == 404:
        raise TickerNotFound(f"TickerInside has no {path}")
    if not 200 <= response.status < 300:
        raise SourceUnavailable(f"TickerInside returned HTTP {response.status} for {path}")
    try:
        return response.json(), response
    except ValueError as exc:  # HTML error page or truncated body
        raise SourceParseError(f"TickerInside {path} is not JSON") from exc


def longest(*names: str | None) -> str | None:
    """securities.json truncates long names ('Taiwan Semiconductor Manufac'); prefer the fuller one."""
    return max((n for n in names if n), key=len, default=None)


@lru_cache(maxsize=1)
def _cross_listed_identifiers() -> frozenset[str]:
    """Curated aliases with an overseas listing must never default to US."""
    aliases = load_aliases().by_identifier
    overseas = {alias[0] for identifier, alias in aliases.items()
                if re.fullmatch(r"[^.]+\.[A-Z]{2}", identifier)}
    return frozenset(identifier for identifier, alias in aliases.items() if alias[0] in overseas)


def country_of(symbol: str, identifiers: dict | None = None, name: str | None = None) -> str | None:
    """Listing-country fallback; US needs exchange evidence and must not be a receipt.

    Names and curated overseas aliases catch ADRs even when asset_type is merely 'stock'
    (e.g. TSM), and foreign registry shares such as ASML. A CIK or US ISIN isn't US evidence.
    """
    match = re.fullmatch(r"[^.]+\.([A-Z]{2})", symbol)
    if match:
        return match.group(1)
    identifiers = identifiers or {}
    description = " ".join(str(value or "") for value in
                           (name, identifiers.get("name"), identifiers.get("asset_type")))
    if symbol in DEPOSITARY_RECEIPT_SYMBOLS or symbol in _cross_listed_identifiers() or re.search(
        r"\b(?:ADR|ADS|GDR|deposit[ao]ry|registry shares)\b", description, re.IGNORECASE
    ):
        return None
    exchange = str(identifiers.get("exchange") or "").strip().casefold()
    if exchange in {"nasdaq", "nyse", "nyse arca", "nyse american", "cboe bzx", "txse"}:
        return "US"
    return None


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
