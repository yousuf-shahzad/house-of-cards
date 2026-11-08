"""v2: AI dependency analysis (POST /api/dependencies, GET /api/dependencies/{job_id}). FROZEN.

Mirrored in frontend/api/types.ts. Rules (docs/hoc/PLAN-v2.md):
- An edge exists only if Python found its evidence_quote in the filing's normalised text.
- Every number is Python's: MetricFact values; insight text gets numbers only via {{metric:<id>}}.
- The LLM never chooses a company key: target_key comes from deterministic name resolution or is None.
- Statuses are enums so the UI can branch on them; missing keys/contacts are statuses, never 500s.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .api import Attribution, ErrorBody, PortfolioItem
from .units import Weight


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


DEFAULT_TOP_N = 15


class DependencyRequest(_Model):
    holdings: Annotated[list[PortfolioItem], Field(min_length=1, max_length=50)]
    """The same allocations as POST /api/analysis (fractions). The top_n companies come from its analysis."""
    top_n: Annotated[int, Field(ge=1, le=30)] = DEFAULT_TOP_N


FilingForm = Literal["10-K", "20-F"]


class FilingRef(_Model):
    company_key: str
    """The filer."""
    form: FilingForm
    accession: str
    filed: date
    url: str
    """Primary document on sec.gov."""


CompanyStatus = Literal[
    "queued",
    "fetching",
    "extracting",
    "cached",
    "done",
    "no_sec_filing",        # e.g. Samsung, SK Hynix: appears only as a counterparty in others' filings
    "unsupported_form",     # files with the SEC but not a 10-K/20-F (e.g. 40-F)
    "sec_contact_missing",  # HOC_SEC_CONTACT not set, so SEC filings can't be fetched
    "missing_api_key",      # GEMINI_API_KEY not set and nothing cached for this filing
    "error",
]


class CompanyRunStatus(_Model):
    company_key: str
    company_name: str
    exposure: Weight
    """The company's portfolio exposure (from the analysis)."""
    status: CompanyStatus
    extraction_quality: Literal["sections", "fallback"] | None = None
    """'fallback' when the filing's sections couldn't be located and whole-document chunks were used."""
    filing: FilingRef | None = None
    verified_edges: int = 0
    rejected_edges: int = 0
    message: str | None = None


EdgeType = Literal[
    "supplier", "customer", "contract_manufacturer", "foundry", "key_input", "facility", "jv_partner"
]
TargetKind = Literal["company", "country", "region", "material", "component", "facility", "unnamed_customer"]


class VerifiedEdge(_Model):
    edge_id: str
    """Stable id (hash of filing accession + normalised quote + edge type + target)."""
    source_company_key: str
    """The filer whose document states this. May be outside the portfolio (reverse links)."""
    source_company_name: str
    source_in_portfolio: bool
    edge_type: EdgeType
    target_name: str
    """As written in the filing."""
    target_kind: TargetKind
    target_key: str | None = None
    """Portfolio/company key from deterministic resolution; None = unresolved."""
    target_in_portfolio: bool = False
    sole_source: bool = False
    qualifier: str | None = None
    """e.g. the product or '22% of revenue', copied from the quote."""
    evidence_quote: str
    """Verbatim from the filing (verified by Python)."""
    section: str
    """e.g. 'Item 1', 'Item 1A', 'Item 2', 'Item 4' (20-F)."""
    filing: FilingRef


MetricUnit = Literal["fraction", "count", "ratio", "days"]


class MetricFact(_Model):
    metric_id: str
    label: str
    value: Annotated[float, Field(allow_inf_nan=False)]
    unit: MetricUnit
    """'fraction' values are fractions of the portfolio (0.0731 = 7.31%)."""
    subject_key: str | None = None
    """The company key, country or target this metric is about, if any."""
    supporting_edge_ids: list[str] = []


class InsightClaim(_Model):
    claim_id: str
    kind: Literal["suggestion", "flaw"]
    severity: Literal["info", "warning", "critical"]
    title: str
    text: str
    """Rendered text: every number in it came from a cited metric via {{metric:<id>}}."""
    cited_metric_ids: list[str] = []
    cited_edge_ids: list[str] = []


InsightsStatus = Literal["ok", "metrics_only", "missing_api_key", "no_verified_edges", "error"]


class Insights(_Model):
    status: InsightsStatus
    model: str | None = None
    suggestions: list[InsightClaim] = []
    flaws: list[InsightClaim] = []
    rejected_claims_count: int = 0
    """Claims dropped by Python (invented numbers, unknown ids, names outside the portfolio/edges)."""


class DependencyCounts(_Model):
    companies_requested: int
    companies_analysed: int
    companies_skipped: int
    verified_edges: int
    rejected_edges: int
    unresolved_counterparties: int


class DependencyResult(_Model):
    as_of_date: date
    request: DependencyRequest
    companies: list[CompanyRunStatus]
    edges: list[VerifiedEdge]
    metrics: list[MetricFact]
    insights: Insights
    counts: DependencyCounts
    attributions: list[Attribution] = []


JobStatus = Literal["queued", "running", "done", "error"]


class DependencyJob(_Model):
    """POST /api/dependencies returns this (HTTP 200 if done from cache, 202 otherwise); poll
    GET /api/dependencies/{job_id} every 1-2 s until status is done or error."""

    job_id: str
    status: JobStatus
    progress_done: int = 0
    progress_total: int = 0
    companies: list[CompanyRunStatus] = []
    result: DependencyResult | None = None
    error: ErrorBody | None = None
