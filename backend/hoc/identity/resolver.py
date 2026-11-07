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

from dataclasses import dataclass, field
from pathlib import Path

ALIASES_PATH = Path(__file__).with_name("aliases.json")


@dataclass(frozen=True)
class Aliases:
    """security identifier (symbol or ISIN) -> (alias id, display company name)."""

    by_identifier: dict[str, tuple[str, str]] = field(default_factory=dict)


def load_aliases(path: Path = ALIASES_PATH) -> Aliases:
    raise NotImplementedError("package d: load_aliases")
