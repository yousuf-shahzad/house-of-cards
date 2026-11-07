"""TickerInside reference data: securities.json (names), identifiers.json (CIK, FIGI, exchange).

Owner: package a (Kendrick's Claude). Implements hoc.sources.base.ReferenceProvider. The two bulk files
are cached for 24h. Sectors come from per-stock sec/{t}.json files (7-day cache), fetched only for the
first SECTOR_LOOKUP_LIMIT symbols of each call: normalise_etf passes symbols heaviest first, so these are
the ETF's largest holdings. Only symbols that securities.json says have a stock file are requested.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from datetime import timedelta

from hoc.contract import SecurityInfo, SourceError

from .files import ReferenceFiles, country_of, get_json
from .files import longest as _longest

SECTOR_LOOKUP_LIMIT = 150
SECTOR_TTL = timedelta(days=7)
SECTOR_REQUEST_SPACING = 0.1
"""Seconds to wait after each live (uncached) sec/{t} request, to stay polite to TickerInside."""


class TickerInsideReference:
    def __init__(self, http, settings) -> None:
        self.http = http
        self.settings = settings
        self.files = ReferenceFiles(http, settings)
        self._sectors: dict[str, str | None] = {}
        self._sector_lock = threading.Lock()  # ETFs load in parallel; fetch each stock file once

    def _sector(self, symbol: str) -> str | None:
        with self._sector_lock:
            if symbol not in self._sectors:
                sector = None
                try:
                    data, response = get_json(self.http, self.settings, f"sec/{symbol.lower()}.json", ttl=SECTOR_TTL)
                    sector = data.get("sector") if isinstance(data, dict) else None
                    if not response.from_cache:
                        time.sleep(SECTOR_REQUEST_SPACING)
                except SourceError:
                    pass  # no sector for this stock; the ETF falls back to its fund-reported breakdown
                self._sectors[symbol] = sector if isinstance(sector, str) and sector else None
            return self._sectors[symbol]

    def lookup_symbols(self, symbols: Sequence[str]) -> dict[str, SecurityInfo]:
        try:
            names, ids = self.files.securities(), self.files.identifiers()
        except SourceError:  # the adapter already warns; lines keep the CIK/FIGI it embedded
            return {}
        found = {}
        for index, symbol in enumerate(symbols):
            key = symbol.upper()
            row, ident = names.get(key), ids.get(key)
            if row is None and ident is None:
                continue
            ident = ident or {}
            found[symbol] = SecurityInfo(
                symbol=key, name=_longest(row[3] if row and len(row) > 3 else None, ident.get("name")),
                cik=ident.get("cik"), figi=ident.get("composite_figi"),
                share_class_figi=ident.get("share_class_figi"), exchange=ident.get("exchange"),
                country=country_of(key),
                sector_label=(self._sector(key) if index < SECTOR_LOOKUP_LIMIT and row and len(row) > 5 and row[5] == 1
                              else None),
            )
        return found

    def lookup_isins(self, isins: Sequence[str]) -> dict[str, SecurityInfo]:
        return {}
