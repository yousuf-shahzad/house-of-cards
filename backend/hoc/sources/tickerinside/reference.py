"""TickerInside reference data: securities.json (names), identifiers.json (CIK, FIGI, exchange).

Owner: package a (Kendrick's Claude). Implements hoc.sources.base.ReferenceProvider. The two bulk files
are cached for 24h. shortcut: no per-stock sec/{t}.json sector lookups (one request per stock is too
many); sectors come from the fund's own breakdown (fund_reported basis). Add if holdings-basis sectors matter.
"""

from __future__ import annotations

from collections.abc import Sequence

from hoc.contract import SecurityInfo, SourceError

from .files import ReferenceFiles, country_of


class TickerInsideReference:
    def __init__(self, http, settings) -> None:
        self.http = http
        self.settings = settings
        self.files = ReferenceFiles(http, settings)

    def lookup_symbols(self, symbols: Sequence[str]) -> dict[str, SecurityInfo]:
        try:
            names, ids = self.files.securities(), self.files.identifiers()
        except SourceError:  # the adapter already warns; lines keep the CIK/FIGI it embedded
            return {}
        found = {}
        for symbol in symbols:
            key = symbol.upper()
            row, ident = names.get(key), ids.get(key)
            if row is None and ident is None:
                continue
            ident = ident or {}
            found[symbol] = SecurityInfo(
                symbol=key, name=(row[3] if row and len(row) > 3 else None) or ident.get("name"),
                cik=ident.get("cik"), figi=ident.get("composite_figi"),
                share_class_figi=ident.get("share_class_figi"), exchange=ident.get("exchange"),
                country=country_of(key),
            )
        return found

    def lookup_isins(self, isins: Sequence[str]) -> dict[str, SecurityInfo]:
        return {}
