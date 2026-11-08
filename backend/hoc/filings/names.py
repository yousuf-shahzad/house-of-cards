"""Counterparty name -> company_key, deterministically. Owner: G-DOC (Kendrick's Claude).

The LLM never picks a key. A name extracted from a filing resolves only by EXACT match of its name key
(lower case, share-class/listing suffixes and legal forms removed, punctuation dropped) against:
  1. the portfolio's own companies (company_name and symbols) -> their company_key;
  2. aliases.json company names -> ALIAS:{id};
  3. SEC company_tickers titles (optional) -> CIK:{10 digits};
after a short manual list maps well-known short names onto a fuller one (Foxconn -> Hon Hai Precision Industry).
A name that matches two different keys, or nothing, stays unresolved (None): never a fuzzy merge.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from hoc.identity.resolver import Aliases, clean_company_name

LEGAL_FORMS = frozenset({
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "llc", "lp",
    "nv", "ag", "se", "sa", "spa", "asa", "ab", "oyj", "kk", "bhd", "tbk", "pte", "the",
})
MANUAL = {
    "foxconn": "Hon Hai Precision Industry",
    "hon hai": "Hon Hai Precision Industry",
    "hon hai precision": "Hon Hai Precision Industry",
    "tsmc": "Taiwan Semiconductor Manufacturing",
    "samsung": "Samsung Electronics",
    "sk hynix": "SK Hynix",
    "hynix": "SK Hynix",
    "umc": "United Microelectronics",
    "google": "Alphabet",
}
"""Short or brand names seen in filings -> the name a portfolio/alias/SEC entry carries. Keep it short."""


def name_key(name: str) -> str:
    """'Taiwan Semiconductor Manufacturing Co., Ltd.' -> 'taiwan semiconductor manufacturing'."""
    words = re.sub(r"[^a-z0-9 ]+", " ", clean_company_name(name).casefold().replace("&", " and ")).split()
    while words and words[-1] in LEGAL_FORMS:
        words.pop()
    if words and words[0] == "the":
        words.pop(0)
    return " ".join(words)


class NameResolver:
    def __init__(self, companies: Iterable, aliases: Aliases | None = None,
                 sec_titles: Mapping[str, str] | None = None) -> None:
        """companies: CompanyExposure-like objects (company_key, company_name, symbols).
        sec_titles: SEC company title -> 10-digit CIK (from company_tickers.json), optional."""
        index: dict[str, set[str]] = {}

        def add(name: str | None, key: str, layer: dict[str, set[str]]) -> None:
            if name and (k := name_key(name)):
                layer.setdefault(k, set()).add(key)

        self._layers: list[dict[str, set[str]]] = []
        for company in companies:
            add(company.company_name, company.company_key, index)
            for symbol in company.symbols:
                add(symbol, company.company_key, index)
        self._layers.append(index)
        alias_layer: dict[str, set[str]] = {}
        for alias_id, display in set((aliases or Aliases()).by_identifier.values()):
            add(display, f"ALIAS:{alias_id}", alias_layer)
        self._layers.append(alias_layer)
        sec_layer: dict[str, set[str]] = {}
        for title, cik in (sec_titles or {}).items():
            add(title, f"CIK:{str(cik).zfill(10)}", sec_layer)
        self._layers.append(sec_layer)

    def resolve(self, name: str) -> str | None:
        """The company_key for an extracted counterparty name, or None if unknown or ambiguous."""
        key = name_key(name)
        key = name_key(MANUAL.get(key, key))
        for layer in self._layers:  # portfolio first, then aliases, then SEC titles
            keys = layer.get(key)
            if keys:
                return next(iter(keys)) if len(keys) == 1 else None
        return None
