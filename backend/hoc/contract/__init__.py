"""The frozen House of Cards contract: every model and exception shared between layers.

Changes go through the lead (Gawyn's Claude) in one PR that also updates frontend/api/types.ts,
tests/snapshots/openapi.json and docs/hoc/CONTRACT.md.
"""

from .api import (
    AnalysisResponse,
    Attribution,
    CompanyExposure,
    Concentration,
    Contribution,
    Coverage,
    DataGap,
    ErrorBody,
    ErrorCode,
    ErrorResponse,
    EtfReport,
    EtfSummary,
    ExampleEtf,
    ExamplePortfolio,
    ExamplesResponse,
    HealthResponse,
    Overlap,
    OverlapPair,
    PortfolioItem,
    PortfolioRequest,
    SectorContribution,
    SectorExposure,
    SecurityExposure,
    TopShared,
)
from .dependencies import (
    DEFAULT_TOP_N,
    CompanyRunStatus,
    DependencyCounts,
    DependencyJob,
    DependencyRequest,
    DependencyResult,
    FilingRef,
    InsightClaim,
    Insights,
    MetricFact,
    VerifiedEdge,
)
from .errors import (
    CompanyUnavailable,
    EtfNotFoundError,
    HocError,
    JobNotFoundError,
    PortfolioValidationError,
    SourceError,
    SourceParseError,
    SourcesUnavailableError,
    SourceUnavailable,
    TickerNotFound,
    UnknownTickerError,
)
from .holdings import EtfFailure, EtfHoldings, ExcludedLine, NormalisedHolding, Notice, SourceAttempt
from .raw import PriceQuote, RawEtfHoldings, RawHolding, SecurityInfo
from .units import (
    ALLOCATION_TOLERANCE,
    EXCLUDED_ASSET_CLASSES,
    MAX_ETFS,
    METHOD_VERSION,
    SOURCE_NAMES,
    AssetClass,
    Sector,
    SourceName,
    Weight,
    wsum,
)
from .valuation import (
    PRICE_STALE_DAYS,
    ValuationIssue,
    ValuationRequest,
    ValuationResponse,
    ValuationRow,
    ValuationRowResult,
)

__all__ = [name for name in dir() if not name.startswith("_")]
