"""Units, enums and constants shared by every layer. FROZEN: change only through the lead.

Every weight in House of Cards is a FRACTION OF 1 (0.05 means 5%), carried as a float.
Adapters convert percent to fractions at the boundary; nothing downstream sees percent.
Sums use math.fsum (exactly rounded, so results do not depend on input order) and every
sort has an explicit tie-break, so the same inputs always give byte-identical output.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import PlainSerializer

WEIGHT_DECIMALS = 10


def _round_weight(value: float) -> float:
    return round(value, WEIGHT_DECIMALS)


Weight = Annotated[float, PlainSerializer(_round_weight, return_type=float)]
"""A fraction of 1. Serialised rounded to 10 dp (exact for products of two 4-dp percentages)."""


def wsum(values: Iterable[float]) -> float:
    """The only way to add weights: exactly rounded, order independent."""
    return math.fsum(values)


class Sector(StrEnum):
    """GICS-style sectors. Every source label maps onto one of these (unmapped -> unknown)."""

    information_technology = "information_technology"
    financials = "financials"
    health_care = "health_care"
    consumer_discretionary = "consumer_discretionary"
    communication_services = "communication_services"
    industrials = "industrials"
    consumer_staples = "consumer_staples"
    energy = "energy"
    utilities = "utilities"
    real_estate = "real_estate"
    materials = "materials"
    unknown = "unknown"


SourceName = Literal["tickerinside", "sec_nport", "ishares", "fake"]
SOURCE_NAMES: tuple[SourceName, ...] = ("tickerinside", "sec_nport", "ishares", "fake")

AssetClass = Literal["equity", "preferred", "fund", "fixed_income", "other", "cash", "derivative", "fx"]
EXCLUDED_ASSET_CLASSES: frozenset[str] = frozenset({"cash", "derivative", "fx"})
"""Lines of these classes are excluded from look-through (they are not company exposure)."""

SecurityIdType = Literal["isin", "figi", "cusip", "symbol", "name"]
CompanyKeyBasis = Literal["alias", "cik", "lei", "isin_issuer", "symbol", "name"]
IdentityStatus = Literal["resolved", "partial", "unmatched"]
SectorSource = Literal["source", "reference", "none"]
SectorBasis = Literal["holdings", "fund_reported", "none"]

METHOD_VERSION = "hoc-1"
MAX_ETFS = 10
ALLOCATION_TOLERANCE = 1e-4
"""Allocations must total 1 within this (so 33.33/33.33/33.34 % passes)."""
RAW_WEIGHT_SUM_MAX = 1.5
"""An ETF whose raw weights sum above this was almost certainly given in percent: reject it."""
SECTOR_COVERAGE_THRESHOLD = 0.95
"""Use line-level sectors only if lines with a known sector are >= 95% of holdings_weight."""
GAP_MIN_PORTFOLIO_WEIGHT = 0.0005
"""Line-level gaps at or above 0.05% of the portfolio are listed one by one; smaller ones are aggregated."""
STALE_INFO_DAYS = 35
STALE_WARNING_DAYS = 100
LOW_COVERAGE_THRESHOLD = 0.95
