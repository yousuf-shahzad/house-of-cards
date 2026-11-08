"""v2/v3: AI dependency analysis (POST /api/dependencies, GET /api/dependencies/{job_id}) and the v3
research loop (POST /api/dependencies/{job_id}/research, GET /api/research/{research_id}). FROZEN.

Mirrored in frontend/api/types.ts. Rules (docs/hoc/PLAN-v2.md):
- An edge exists only if Python found its evidence_quote in the filing's normalised text.
- Every number is Python's: MetricFact values; insight text gets numbers only via {{metric:<id>}}.
- The LLM never chooses a company key: target_key comes from deterministic name resolution or is None.
- Statuses are enums so the UI can branch on them; missing keys/contacts are statuses, never 500s.
v3 (docs/hoc/PLAN-v3.md): importance is Python-scored; interpretation-rejected edges are removed and
counted; coverage buckets are portfolio-weight fractions summing to 1; research evidence is verified
exactly like extraction evidence.
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

ImportanceTier = Literal["critical", "high", "medium", "low"]


class EdgeImportance(_Model):
    """v3 R-IMP: how much this relationship matters, scored deterministically in Python."""

    score: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    tier: ImportanceTier
    """critical >= 0.8, high >= 0.6, medium >= 0.4, else low (PLAN-v3 section 4)."""
    reasons: list[str] = []
    """Plain-English reasons; any cue words are quoted from the verified evidence quote."""


InterpretationStatus = Literal["confirmed", "flagged", "rejected"]
InterpretationFlag = Literal[
    "competitor_mention", "negated", "hypothetical", "direction_mismatch", "generic_reference",
    "subject_mismatch", "judge_unclear",
]


class EdgeInterpretation(_Model):
    """v3 V-INT: does the verified quote really mean this relationship? Edges with status 'rejected'
    never appear in DependencyResult.edges (they are counted in counts.interpretation_rejected)."""

    status: InterpretationStatus
    method: Literal["rules", "rules+model"]
    flags: list[InterpretationFlag] = []
    reason: str | None = None
    """Short plain-English reason (rules text or the judge's one-line reason)."""
    model: str | None = None
    """The judge model id when method is 'rules+model'."""


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
    importance: EdgeImportance | None = None
    """v3: None until R-IMP has scored it."""
    interpretation: EdgeInterpretation | None = None
    """v3: None until V-INT has checked it; never 'rejected' inside DependencyResult.edges."""


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
    interpretation_rejected: int = 0
    """v3: edges whose quote verified but whose meaning did not (competitor, negated, wrong direction...)."""


CoverageKind = Literal["verified", "no_disclosures", "no_sec_filing", "not_analysed", "outside_top_n"]


class CoverageBucket(_Model):
    kind: CoverageKind
    weight: Weight
    """Fraction of the whole portfolio in this bucket; the buckets of one report sum to 1 (+-1e-6)."""
    companies: int
    label: str
    """Plain English, e.g. 'Analysed, with verified dependencies'."""


class EtfCoverage(_Model):
    ticker: str
    verified_weight: Weight
    """Fraction of this ETF's own look-through weight that is in the 'verified' bucket."""


class UnanalysedCompany(_Model):
    company_key: str
    company_name: str
    exposure: Weight


CoverageGapKind = Literal[
    "outside_top_n", "unnamed_customers", "non_sec_counterparties", "old_filings", "region_only_facilities",
]


class CoverageGap(_Model):
    kind: CoverageGapKind
    message: str
    """Plain English; numbers in it are Python's (rendered from this report's own values)."""
    weight: Weight | None = None


class CoverageReport(_Model):
    """v3 C-COV: what is known, unknown and possibly missing about this portfolio's dependencies."""

    buckets: list[CoverageBucket]
    by_etf: list[EtfCoverage] = []
    largest_unanalysed: list[UnanalysedCompany] = []
    """The largest exposures outside the analysed top N (at most 10)."""
    gaps: list[CoverageGap] = []


class DependencyResult(_Model):
    as_of_date: date
    request: DependencyRequest
    companies: list[CompanyRunStatus]
    edges: list[VerifiedEdge]
    metrics: list[MetricFact]
    insights: Insights
    counts: DependencyCounts
    attributions: list[Attribution] = []
    coverage: CoverageReport | None = None
    """v3: None until C-COV is wired in."""


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


# ---------- v3 A-RES: agentic research loop ----------

DEFAULT_RESEARCH_ITEMS = 6


class ResearchRequest(_Model):
    max_items: Annotated[int, Field(ge=1, le=10)] = DEFAULT_RESEARCH_ITEMS


ResearchItemKind = Literal[
    "flagged_edge", "undisclosed_customer", "single_source", "no_disclosures", "unresolved_counterparty",
]
ResearchAction = Literal["search_filings", "read_section", "find_in_filing", "conclude"]
ResearchOutcome = Literal["confirmed", "revised", "rejected", "new_evidence", "unresolved"]


class ResearchStep(_Model):
    index: int
    action: ResearchAction
    query: str | None = None
    """The phrase searched or read, as the model asked for it."""
    summary: str
    """Python-rendered description of what the tool returned, e.g. 'found 3 filings'."""
    filing: FilingRef | None = None


class ResearchFinding(_Model):
    finding_id: str
    kind: ResearchItemKind
    subject: str
    """What was investigated, e.g. 'Broadcom's undisclosed largest customer'."""
    question: str
    outcome: ResearchOutcome
    explanation: str
    """The model's conclusion; it may contain digits only inside quotes of verified evidence."""
    steps: list[ResearchStep] = []
    confirmed_edge_ids: list[str] = []
    rejected_edge_ids: list[str] = []
    new_edges: list[VerifiedEdge] = []
    """Each passed verify_quote and interpretation checks, exactly like extracted edges."""


class ResearchJob(_Model):
    """POST /api/dependencies/{job_id}/research returns this (202, or 200 if cached); poll
    GET /api/research/{research_id} until done or error. `result` is the dependency result with the
    findings merged in (edges added/removed, metrics and insights recomputed)."""

    research_id: str
    dependency_job_id: str
    status: JobStatus
    progress_done: int = 0
    progress_total: int = 0
    findings: list[ResearchFinding] = []
    result: DependencyResult | None = None
    error: ErrorBody | None = None
