"""Normalised, identity-resolved holdings for one ETF (output of normalisation). FROZEN."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from .raw import PriceQuote
from .units import (
    AssetClass,
    CompanyKeyBasis,
    IdentityStatus,
    Sector,
    SectorBasis,
    SectorSource,
    SecurityIdType,
    SourceName,
    Weight,
)


class Notice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


SourceOutcome = Literal["ok", "not_found", "unavailable", "parse_error", "skipped"]


class SourceAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: SourceName
    outcome: SourceOutcome
    message: str | None = None


class ExcludedLine(BaseModel):
    """A line kept out of look-through (cash, derivative, FX). Still counted in excluded_weight."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    asset_class: AssetClass
    weight: Weight


class NormalisedHolding(BaseModel):
    """One security in one ETF. Duplicate source lines for the same security_key are summed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    etf_ticker: str
    security_key: str
    """Listing-level key: 'SYM:BRK.B', 'SYM:2330.TW', then 'ISIN:...', 'CUSIP:...', 'NAME:...'."""
    security_id: str
    """Best display identifier: ISIN, else FIGI, else CUSIP, else symbol, else name."""
    security_id_type: SecurityIdType
    symbol: str | None = None
    name: str
    company_key: str
    """Company-level key: 'ALIAS:..', 'CIK:..', 'LEI:..', 'ISSUER:..', 'SYM:..' or 'NAME:..'."""
    company_key_basis: CompanyKeyBasis
    company_name: str
    identity_status: IdentityStatus
    weight: Weight
    sector: Sector = Sector.unknown
    sector_source: SectorSource = "none"
    asset_class: AssetClass = "equity"
    country: str | None = None
    source: SourceName
    as_of: date


class EtfHoldings(BaseModel):
    """Everything known about one ETF after normalisation. Cacheable: no portfolio context."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    etf_ticker: str
    etf_name: str | None = None
    source: SourceName
    source_layer: str | None = None
    as_of: date
    retrieved_at: AwareDatetime
    source_url: str
    filing_url: str | None = None
    attribution: str | None = None
    licence: str | None = None
    holdings: list[NormalisedHolding]
    """Sorted by weight descending, then security_key ascending."""
    excluded: list[ExcludedLine] = []
    reported_weight: Weight
    """Sum of every raw line's weight (normally ~1)."""
    holdings_weight: Weight
    """Sum of look-through holdings' weights (raw minus excluded lines)."""
    excluded_weight: Weight
    unmatched_weight: Weight
    """Part of holdings_weight whose identity_status is 'unmatched'."""
    sector_weights: dict[Sector, Weight] = {}
    """Fraction of NAV per sector, on sector_basis. Sums to holdings_weight when basis != 'none'."""
    sector_basis: SectorBasis = "none"
    raw_line_count: int
    warnings: list[Notice] = []
    attempts: list[SourceAttempt] = []
    normaliser_version: str
    price: PriceQuote | None = None
    """Passed through unchanged from RawEtfHoldings.price (v2)."""


class EtfFailure(BaseModel):
    """An ETF that could not be loaded from any source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    etf_ticker: str
    status: Literal["not_found", "unavailable"]
    attempts: list[SourceAttempt] = []
    message: str
