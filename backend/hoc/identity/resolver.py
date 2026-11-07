"""Security and company identity. Owner: package d (Kendrick's Claude). Signatures fixed by W0-B.

security_key (listing level, drives "shared securities"), first match wins:
  SYM:{symbol} in the TickerInside convention (US 'BRK.B'; elsewhere '{local}.{ISO2}', e.g. '2330.TW'),
  then ISIN:, CUSIP:, NAME:{normalised name}.
company_key (drives exposures), first match wins:
  ALIAS:{id} (aliases.json) > CIK:{10 digits} > LEI: > ISSUER:{isin[:8]} (US/CA ISINs only)
  > SYM: (identity_status 'partial') > NAME: ('unmatched').
FIGI is never a company key (it is security level: GOOG and GOOGL differ). Unmatched lines are kept.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from hoc.contract import RawHolding, SecurityInfo

ALIASES_PATH = Path(__file__).with_name("aliases.json")
MAX_ALIASES = 50


@dataclass(frozen=True)
class Aliases:
    """security identifier (symbol or ISIN) -> (alias id, display company name)."""

    by_identifier: dict[str, tuple[str, str]] = field(default_factory=dict)


def aliases_from_entries(entries: list[dict]) -> Aliases:
    """Build Aliases from aliases.json-style entries: {id, company_name, identifiers, note}."""
    if len(entries) > MAX_ALIASES:
        raise ValueError(f"aliases.json has {len(entries)} entries; the limit is {MAX_ALIASES}")
    by_identifier: dict[str, tuple[str, str]] = {}
    for entry in entries:
        alias_id, name = entry["id"], entry["company_name"]
        if not entry.get("note"):
            raise ValueError(f"alias {alias_id} has no source note")
        for identifier in entry["identifiers"]:
            key = identifier.strip().upper()
            if key in by_identifier and by_identifier[key][0] != alias_id:
                raise ValueError(f"identifier {identifier} is in two aliases: {by_identifier[key][0]}, {alias_id}")
            by_identifier[key] = (alias_id, name)
    return Aliases(by_identifier)


def load_aliases(path: Path = ALIASES_PATH) -> Aliases:
    return aliases_from_entries(json.loads(path.read_text(encoding="utf-8")).get("aliases", []))


def normalise_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().upper()


def normalise_cik(cik: str | None) -> str | None:
    digits = re.sub(r"\D", "", cik or "")
    return digits.zfill(10) if digits and int(digits) else None


@dataclass(frozen=True)
class Identity:
    security_key: str
    security_id: str
    security_id_type: str
    symbol: str | None
    company_key: str
    company_key_basis: str
    identity_status: str
    alias_name: str | None


def listing_symbol(line: RawHolding, source: str) -> str | None:
    """The line's symbol in the TickerInside convention."""
    symbol = (line.source_symbol or "").strip().upper() or None
    # shortcut: iShares US class shares come as 'BRKB' (no dot) and stay unmerged with 'BRK.B' at
    # security level (CIK still merges the company); upgrade if shared-security counts matter.
    if symbol and source == "ishares" and line.country and line.country.upper() != "US" and "." not in symbol:
        symbol = f"{symbol}.{line.country.upper()}"
    return symbol


def resolve(line: RawHolding, symbol: str | None, info: SecurityInfo | None, aliases: Aliases,
            display_name: str) -> Identity:
    info = info or SecurityInfo()
    isin = (line.isin or "").strip().upper() or None
    cusip = (line.cusip or "").strip().upper() or None
    figi = line.figi or info.figi

    if symbol:
        security_key = f"SYM:{symbol}"
    elif isin:
        security_key = f"ISIN:{isin}"
    elif cusip:
        security_key = f"CUSIP:{cusip}"
    else:
        security_key = f"NAME:{normalise_name(display_name)}"

    for id_type, value in (("isin", isin), ("figi", figi), ("cusip", cusip), ("symbol", symbol)):
        if value:
            security_id, security_id_type = value, id_type
            break
    else:
        security_id, security_id_type = display_name, "name"

    alias = next((aliases.by_identifier[k] for k in (symbol, isin) if k and k in aliases.by_identifier), None)
    cik = normalise_cik(line.cik) or normalise_cik(info.cik)
    lei = (line.lei or info.lei or "").strip().upper() or None
    if alias:
        company = (f"ALIAS:{alias[0]}", "alias", "resolved")
    elif cik:
        company = (f"CIK:{cik}", "cik", "resolved")
    elif lei:
        company = (f"LEI:{lei}", "lei", "resolved")
    elif isin and isin[:2] in ("US", "CA"):
        company = (f"ISSUER:{isin[:8]}", "isin_issuer", "resolved")
    elif symbol:
        company = (f"SYM:{symbol}", "symbol", "partial")
    else:
        company = (f"NAME:{normalise_name(display_name)}", "name", "unmatched")

    return Identity(security_key, security_id, security_id_type, symbol, *company,
                    alias_name=alias[1] if alias else None)
