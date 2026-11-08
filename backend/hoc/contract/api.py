"""HTTP request/response models. FROZEN: mirrored 1:1 in frontend/api/types.ts.

Definitions (see docs/hoc/CONTRACT.md for the full text):
  A_e      allocation to ETF e (fraction of the portfolio)
  w_{e,s}  weight of security s in ETF e (fraction of the ETF's NAV); w_{e,c} = sum over s in c
  exposure E_c = fsum_e A_e * w_{e,c}; never renormalised, so sum_c E_c == coverage.covered_weight
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from .holdings import NormalisedHolding, Notice, SourceAttempt
from .raw import PriceQuote
from .units import METHOD_VERSION, IdentityStatus, Sector, SectorBasis, SecurityIdType, SourceName, Weight

TICKER_PATTERN = r"^[A-Za-z0-9.\-]{1,12}$"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- requests ----------


class PortfolioItem(_Model):
    ticker: Annotated[str, Field(pattern=TICKER_PATTERN)]
    allocation: Annotated[float, Field(ge=0, le=1)]
    """Fraction of the portfolio (0.40 = 40%). The UI converts percent in frontend/api/client.ts."""

    @field_validator("ticker")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()


class PortfolioRequest(_Model):
    holdings: Annotated[list[PortfolioItem], Field(min_length=1, max_length=50)]
    """Business rules (total == 1 +/- ALLOCATION_TOLERANCE, no duplicates, <= MAX_ETFS) are checked by
    hoc.portfolio.validation and reported with their own error codes, not as schema errors."""
    max_companies: Annotated[int, Field(ge=1, le=20000)] = 2000


# ---------- analysis response ----------


class Contribution(_Model):
    etf_ticker: str
    weight_in_etf: Weight
    """w_{e,c}: the company's weight inside this ETF (all its share classes summed)."""
    contribution: Weight
    """A_e * w_{e,c}."""
    security_keys: list[str]


class SecurityExposure(_Model):
    security_key: str
    security_id: str
    security_id_type: SecurityIdType
    symbol: str | None = None
    name: str
    exposure: Weight


class CompanyExposure(_Model):
    rank: int
    company_key: str
    company_name: str
    identity_status: IdentityStatus
    symbols: list[str]
    sector: Sector
    country: str | None = None
    exposure: Weight
    etf_count: int
    contributions: list[Contribution]
    """Sorted by contribution descending, then etf_ticker. Contributions sum to exposure."""
    securities: list[SecurityExposure]


EtfStatus = Literal["ok", "warning", "unavailable"]


class EtfReport(_Model):
    ticker: str
    name: str | None = None
    allocation: Weight
    status: EtfStatus
    source: SourceName | None = None
    source_layer: str | None = None
    source_url: str | None = None
    filing_url: str | None = None
    attribution: str | None = None
    licence: str | None = None
    as_of: date | None = None
    age_days: int | None = None
    """(analysis as_of_date - as_of) in days."""
    retrieved_at: AwareDatetime | None = None
    holdings_count: int = 0
    company_count: int = 0
    reported_weight: Weight = 0.0
    holdings_weight: Weight = 0.0
    excluded_weight: Weight = 0.0
    unmatched_weight: Weight = 0.0
    portfolio_covered_weight: Weight = 0.0
    """allocation * holdings_weight."""
    sector_basis: SectorBasis = "none"
    warnings: list[Notice] = []
    attempts: list[SourceAttempt] = []


class Coverage(_Model):
    """covered + excluded + missing + unexplained == total_allocation (== 1 for a valid request)."""

    total_allocation: Weight
    loaded_allocation: Weight
    missing_allocation: Weight
    covered_weight: Weight
    excluded_weight: Weight
    unexplained_weight: Weight
    unmatched_weight: Weight
    sector_known_weight: Weight


class TopShared(_Model):
    company_key: str
    company_name: str
    weight_a: Weight
    weight_b: Weight
    min_weight: Weight


class OverlapPair(_Model):
    etf_a: str
    etf_b: str
    shared_securities: int
    shared_companies: int
    weighted_overlap: Weight
    """fsum over companies of min(max(w_a,c,0), max(w_b,c,0)). Not renormalised for cash."""
    weighted_overlap_securities: Weight
    """The same at security (listing) level."""
    top_shared: list[TopShared]
    """Up to 10, by min_weight descending, then company_key."""


class Overlap(_Model):
    etfs: list[str]
    """Loaded ETFs in request order; matrix rows/columns follow this order."""
    matrix: list[list[Weight]]
    """Symmetric weighted (company-level) overlap. Diagonal = that ETF's holdings_weight."""
    pairs: list[OverlapPair]
    """Every unordered pair once, etf_a before etf_b in request order."""


class Concentration(_Model):
    top5: Weight
    top10: Weight
    top20: Weight
    """Sum of the N largest company exposures, as a fraction of the whole portfolio."""
    hhi: Weight
    """Herfindahl index over p_c = E_c / sum E (positive exposures only)."""
    effective_companies: float
    """1 / hhi (0 when there is no exposure)."""
    distinct_securities: int
    distinct_companies: int


class SectorContribution(_Model):
    etf_ticker: str
    contribution: Weight


class SectorExposure(_Model):
    sector: Sector
    weight: Weight
    by_etf: list[SectorContribution]


GapKind = Literal[
    "missing_etf",
    "unmatched_identity",
    "nested_fund",
    "stale_disclosure",
    "low_coverage",
    "excluded_lines",
    "no_sector_data",
]
GapSeverity = Literal["info", "warning", "critical"]


class DataGap(_Model):
    kind: GapKind
    severity: GapSeverity
    etf_ticker: str | None = None
    subject: str | None = None
    portfolio_weight: Weight | None = None
    message: str


class Attribution(_Model):
    source: SourceName
    text: str
    url: str | None = None
    licence: str | None = None


class AnalysisResponse(_Model):
    method_version: Literal["hoc-1"] = METHOD_VERSION
    generated_at: AwareDatetime
    as_of_date: date
    """The 'today' the analysis used for age_days and staleness."""
    request: PortfolioRequest
    etfs: list[EtfReport]
    coverage: Coverage
    exposures: list[CompanyExposure]
    """Sorted by exposure descending, then company_key. At most request.max_companies entries."""
    exposures_truncated: bool
    other_exposure: Weight
    """Exposure of companies cut by max_companies (so exposures + other == covered_weight)."""
    overlap: Overlap
    concentration: Concentration
    sectors: list[SectorExposure]
    """Sorted by weight descending, then sector. Sum == coverage.covered_weight."""
    gaps: list[DataGap]
    warnings: list[Notice]
    attributions: list[Attribution]


# ---------- other endpoints ----------


class EtfSummary(_Model):
    """GET /api/etfs/{ticker}: one ETF without portfolio context."""

    ticker: str
    name: str | None = None
    status: EtfStatus
    source: SourceName
    source_layer: str | None = None
    source_url: str
    filing_url: str | None = None
    attribution: str | None = None
    licence: str | None = None
    as_of: date
    retrieved_at: AwareDatetime
    holdings_count: int
    company_count: int
    reported_weight: Weight
    holdings_weight: Weight
    excluded_weight: Weight
    unmatched_weight: Weight
    sector_basis: SectorBasis
    sector_weights: dict[Sector, Weight]
    warnings: list[Notice]
    attempts: list[SourceAttempt]
    holdings: list[NormalisedHolding] | None = None
    """Only with ?holdings=true."""
    price: PriceQuote | None = None
    """The ETF's latest price from its source, if published (v2)."""


class ExampleEtf(_Model):
    ticker: str
    allocation: Weight
    verified: bool
    """True when this ETF's real holdings loaded (live or cached) just now."""
    source: SourceName | None = None
    as_of: date | None = None


class ExamplePortfolio(_Model):
    id: str
    name: str
    description: str
    holdings: list[ExampleEtf]
    verified: bool
    """True only if every ETF verified. The UI offers only verified examples."""


class ExamplesResponse(_Model):
    examples: list[ExamplePortfolio]


class HealthResponse(_Model):
    status: Literal["ok"] = "ok"
    version: str
    offline: bool
    sources: list[SourceName]


ErrorCode = Literal[
    "VALIDATION_ERROR",
    "ALLOCATION_SUM_INVALID",
    "DUPLICATE_TICKER",
    "TOO_MANY_ETFS",
    "UNKNOWN_TICKER",
    "ETF_NOT_FOUND",
    "JOB_NOT_FOUND",
    "RESEARCH_NOT_FOUND",
    "SOURCES_UNAVAILABLE",
    "INTERNAL_ERROR",
]


class ErrorBody(_Model):
    code: ErrorCode
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(_Model):
    error: ErrorBody
