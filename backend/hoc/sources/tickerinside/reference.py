"""TickerInside reference data: securities.json (names), identifiers.json (CIK, FIGI, exchange).

Owner: package a (Kendrick's Claude). Implements hoc.sources.base.ReferenceProvider. The two bulk files
are cached for 24h. Sectors come from per-stock sec/{t}.json files (7-day cache), fetched only for the
first SECTOR_LOOKUP_LIMIT symbols of each call: normalise_etf passes symbols heaviest first, so these are
the ETF's largest holdings. Only symbols that securities.json says have a stock file are requested.
Stock files are fetched by one shared pool (at most SECTOR_WORKERS in flight across all ETFs), and each
symbol is fetched once per reference instance, however many ETFs hold it.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta

from hoc.contract import SecurityInfo, SourceError

from .files import ReferenceFiles, country_of, get_json
from .files import longest as _longest

SECTOR_LOOKUP_LIMIT = 150
SECTOR_TTL = timedelta(days=7)
SECTOR_WORKERS = 4
SECTOR_REQUEST_SPACING = 0.1
"""Seconds each worker waits after a live (uncached) sec/{t} request, to stay polite to TickerInside."""


class TickerInsideReference:
    def __init__(self, http, settings) -> None:
        self.http = http
        self.settings = settings
        self.files = ReferenceFiles(http, settings)
        self._sectors: dict[str, Future] = {}
        self._sector_lock = threading.Lock()
        self._pool: ThreadPoolExecutor | None = None

    def _fetch_sector(self, symbol: str) -> str | None:
        try:
            data, response = get_json(self.http, self.settings, f"sec/{symbol.lower()}.json", ttl=SECTOR_TTL)
        except SourceError:
            return None  # no sector for this stock; the ETF falls back to its fund-reported breakdown
        if not response.from_cache:
            time.sleep(SECTOR_REQUEST_SPACING)
        sector = data.get("sector") if isinstance(data, dict) else None
        return sector if isinstance(sector, str) and sector else None

    def _sector_futures(self, symbols: list[str]) -> dict[str, Future]:
        """Start (or reuse) one fetch per symbol on the shared pool; ETFs loading in parallel share it."""
        with self._sector_lock:
            for symbol in symbols:
                if symbol not in self._sectors:
                    self._pool = self._pool or ThreadPoolExecutor(SECTOR_WORKERS, thread_name_prefix="ti-sector")
                    self._sectors[symbol] = self._pool.submit(self._fetch_sector, symbol)
            return {symbol: self._sectors[symbol] for symbol in symbols}

    def lookup_symbols(self, symbols: Sequence[str]) -> dict[str, SecurityInfo]:
        try:
            names, ids = self.files.securities(), self.files.identifiers()
        except SourceError:  # the adapter already warns; lines keep the CIK/FIGI it embedded
            return {}
        wanted = [s.upper() for s in symbols[:SECTOR_LOOKUP_LIMIT]
                  if (row := names.get(s.upper())) and len(row) > 5 and row[5] == 1]
        sectors = self._sector_futures(wanted)
        found = {}
        for symbol in symbols:
            key = symbol.upper()
            row, ident = names.get(key), ids.get(key)
            if row is None and ident is None:
                continue
            ident = ident or {}
            found[symbol] = SecurityInfo(
                symbol=key, name=_longest(row[3] if row and len(row) > 3 else None, ident.get("name")),
                cik=ident.get("cik"), figi=ident.get("composite_figi"),
                share_class_figi=ident.get("share_class_figi"), exchange=ident.get("exchange"),
                country=country_of(key, ident, row[3] if row and len(row) > 3 else None),
                sector_label=sectors[key].result() if key in sectors else None,
            )
        return found

    def lookup_isins(self, isins: Sequence[str]) -> dict[str, SecurityInfo]:
        return {}
