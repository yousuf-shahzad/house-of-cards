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
from .compare import CompareRequest, CompareResponse, ConcentrationDelta, MetricDelta
from .dependencies import (
    DEFAULT_RESEARCH_ITEMS,
    DEFAULT_TOP_N,
    CompanyRunStatus,
    CoverageBucket,
    CoverageGap,
    CoverageReport,
    DependencyCounts,
    DependencyJob,
    DependencyRequest,
    DependencyResult,
    EdgeImportance,
    EdgeInterpretation,
    EtfCoverage,
    FilingRef,
    InsightClaim,
    Insights,
    MetricFact,
    ResearchFinding,
    ResearchJob,
    ResearchRequest,
    ResearchStep,
    UnanalysedCompany,
    VerifiedEdge,
)
from .errors import (
    CompanyUnavailable,
    EtfNotFoundError,
    HocError,
    JobNotFoundError,
    PortfolioValidationError,
    ResearchNotFoundError,
    SourceError,
    SourceParseError,
    SourcesUnavailableError,
    SourceUnavailable,
    TickerNotFound,
    UnknownTickerError,
)
from .holdings import EtfFailure, EtfHoldings, ExcludedLine, NormalisedHolding, Notice, SourceAttempt
from .ideas import ChangeIdea, ChangeIdeasRequest, ChangeIdeasResponse, RejectedIdeaProposal
from .raw import PriceQuote, RawEtfHoldings, RawHolding, SecurityInfo
from .stress import (
    DEFAULT_SHOCK_DROP,
    HISTORY_YEARS,
    MAX_AFFECTED_LISTED,
    SHOCK_WINDOW_DAYS,
    AffectedCompany,
    ShockBasis,
    ShockKind,
    ShockSource,
    ShockSpec,
    StressRequest,
    StressResponse,
    StressSide,
)
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
