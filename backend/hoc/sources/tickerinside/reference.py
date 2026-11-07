"""TickerInside reference data: securities.json (names), identifiers.json (CIK, FIGI), sec/{t}.json (sector).

Owner: package a. Implements hoc.sources.base.ReferenceProvider. Cache the two bulk files for 24h.
"""

from __future__ import annotations

from collections.abc import Sequence

from hoc.contract import SecurityInfo


class TickerInsideReference:
    def __init__(self, http, settings) -> None:
        self.http = http
        self.settings = settings

    def lookup_symbols(self, symbols: Sequence[str]) -> dict[str, SecurityInfo]:
        raise NotImplementedError("package a: TickerInsideReference.lookup_symbols")

    def lookup_isins(self, isins: Sequence[str]) -> dict[str, SecurityInfo]:
        return {}
