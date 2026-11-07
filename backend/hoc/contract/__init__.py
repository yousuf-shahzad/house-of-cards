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
from .errors import (
    EtfNotFoundError,
    HocError,
    PortfolioValidationError,
    SourceError,
    SourceParseError,
    SourcesUnavailableError,
    SourceUnavailable,
    TickerNotFound,
    UnknownTickerError,
)
from .holdings import EtfFailure, EtfHoldings, ExcludedLine, NormalisedHolding, Notice, SourceAttempt
from .raw import RawEtfHoldings, RawHolding, SecurityInfo
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

__all__ = [name for name in dir() if not name.startswith("_")]
