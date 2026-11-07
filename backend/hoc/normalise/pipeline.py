"""RawEtfHoldings -> EtfHoldings. Owner: package d (Kendrick's Claude). Signature fixed by W0-B.

Responsibilities (docs/hoc/CONTRACT.md): reject percent-unit inputs (raw sum > RAW_WEIGHT_SUM_MAX);
move cash/derivative/fx lines to `excluded`; resolve security_key and company_key via hoc.identity;
merge duplicate lines per security_key; map sector labels onto Sector; compute reported/holdings/
excluded/unmatched weights and the sector basis; sort holdings by weight desc, then security_key.
Pure and deterministic: no network (reference data is passed in), no clock.
"""

from __future__ import annotations

from hoc.contract import EtfHoldings, RawEtfHoldings
from hoc.identity.resolver import Aliases
from hoc.sources.base import ReferenceProvider

NORMALISER_VERSION = "norm-1"


def normalise_etf(raw: RawEtfHoldings, reference: ReferenceProvider, aliases: Aliases) -> EtfHoldings:
    raise NotImplementedError("package d: normalise_etf")
