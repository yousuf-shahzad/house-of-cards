// House of Cards API types. FROZEN: a 1:1 mirror of backend/hoc/contract/*.py (snake_case, as sent).
// Change only through the lead, in the same PR as the Pydantic models and the OpenAPI snapshot.
//
// UNITS: every `Weight` is a FRACTION OF 1 (0.05 = 5%). The UI formats for display only;
// frontend/api/client.ts is the only place that converts the user's percent input to fractions.

export type Weight = number;
/** ISO date, e.g. "2026-11-05". */
export type IsoDate = string;
/** ISO datetime with timezone, e.g. "2026-11-07T09:00:00Z". */
export type IsoDateTime = string;

export type Sector =
  | "information_technology"
  | "financials"
  | "health_care"
  | "consumer_discretionary"
  | "communication_services"
  | "industrials"
  | "consumer_staples"
  | "energy"
  | "utilities"
  | "real_estate"
  | "materials"
  | "unknown";

export type SourceName = "tickerinside" | "sec_nport" | "ishares" | "fake";
export type AssetClass = "equity" | "preferred" | "fund" | "fixed_income" | "other" | "cash" | "derivative" | "fx";
export type SecurityIdType = "isin" | "figi" | "cusip" | "symbol" | "name";
export type CompanyKeyBasis = "alias" | "cik" | "lei" | "isin_issuer" | "symbol" | "name";
export type IdentityStatus = "resolved" | "partial" | "unmatched";
export type SectorSource = "source" | "reference" | "none";
export type SectorBasis = "holdings" | "fund_reported" | "none";
export type SourceOutcome = "ok" | "not_found" | "unavailable" | "parse_error" | "skipped";
export type EtfStatus = "ok" | "warning" | "unavailable";
export type GapKind =
  | "missing_etf"
  | "unmatched_identity"
  | "nested_fund"
  | "stale_disclosure"
  | "low_coverage"
  | "excluded_lines"
  | "no_sector_data";
export type GapSeverity = "info" | "warning" | "critical";
export type ErrorCode =
  | "VALIDATION_ERROR"
  | "ALLOCATION_SUM_INVALID"
  | "DUPLICATE_TICKER"
  | "TOO_MANY_ETFS"
  | "UNKNOWN_TICKER"
  | "ETF_NOT_FOUND"
  | "JOB_NOT_FOUND"
  | "RESEARCH_NOT_FOUND"
  | "SOURCES_UNAVAILABLE"
  | "INTERNAL_ERROR";

/** Contract constants (backend/hoc/contract/units.py). */
export const MAX_ETFS = 10;
export const ALLOCATION_TOLERANCE = 1e-4;

// ---------- shared ----------

export interface Notice {
  code: string;
  message: string;
}

export interface SourceAttempt {
  source: SourceName;
  outcome: SourceOutcome;
  message: string | null;
}

export interface NormalisedHolding {
  etf_ticker: string;
  security_key: string;
  security_id: string;
  security_id_type: SecurityIdType;
  symbol: string | null;
  name: string;
  company_key: string;
  company_key_basis: CompanyKeyBasis;
  company_name: string;
  identity_status: IdentityStatus;
  weight: Weight;
  sector: Sector;
  sector_source: SectorSource;
  asset_class: AssetClass;
  country: string | null;
  source: SourceName;
  as_of: IsoDate;
}

// ---------- requests ----------

export interface PortfolioItem {
  /** Upper-cased by the server; pattern ^[A-Za-z0-9.\-]{1,12}$. */
  ticker: string;
  /** Fraction of the portfolio, 0..1. */
  allocation: Weight;
}

export interface PortfolioRequest {
  holdings: PortfolioItem[];
  max_companies?: number;
}

// ---------- analysis response ----------

export interface Contribution {
  etf_ticker: string;
  weight_in_etf: Weight;
  contribution: Weight;
  security_keys: string[];
}

export interface SecurityExposure {
  security_key: string;
  security_id: string;
  security_id_type: SecurityIdType;
  symbol: string | null;
  name: string;
  exposure: Weight;
}

export interface CompanyExposure {
  rank: number;
  company_key: string;
  company_name: string;
  identity_status: IdentityStatus;
  symbols: string[];
  sector: Sector;
  country: string | null;
  exposure: Weight;
  etf_count: number;
  contributions: Contribution[];
  securities: SecurityExposure[];
}

export interface EtfReport {
  ticker: string;
  name: string | null;
  allocation: Weight;
  status: EtfStatus;
  source: SourceName | null;
  source_layer: string | null;
  source_url: string | null;
  filing_url: string | null;
  attribution: string | null;
  licence: string | null;
  as_of: IsoDate | null;
  age_days: number | null;
  retrieved_at: IsoDateTime | null;
  holdings_count: number;
  company_count: number;
  reported_weight: Weight;
  holdings_weight: Weight;
  excluded_weight: Weight;
  unmatched_weight: Weight;
  portfolio_covered_weight: Weight;
  sector_basis: SectorBasis;
  warnings: Notice[];
  attempts: SourceAttempt[];
}

/** covered + excluded + missing + unexplained == total_allocation. */
export interface Coverage {
  total_allocation: Weight;
  loaded_allocation: Weight;
  missing_allocation: Weight;
  covered_weight: Weight;
  excluded_weight: Weight;
  unexplained_weight: Weight;
  unmatched_weight: Weight;
  sector_known_weight: Weight;
}

export interface TopShared {
  company_key: string;
  company_name: string;
  weight_a: Weight;
  weight_b: Weight;
  min_weight: Weight;
}

export interface OverlapPair {
  etf_a: string;
  etf_b: string;
  shared_securities: number;
  shared_companies: number;
  weighted_overlap: Weight;
  weighted_overlap_securities: Weight;
  top_shared: TopShared[];
}

export interface Overlap {
  etfs: string[];
  /** Symmetric; diagonal = that ETF's holdings_weight. Rows/columns follow `etfs`. */
  matrix: Weight[][];
  pairs: OverlapPair[];
}

export interface Concentration {
  top5: Weight;
  top10: Weight;
  top20: Weight;
  hhi: Weight;
  effective_companies: number;
  distinct_securities: number;
  distinct_companies: number;
}

export interface SectorContribution {
  etf_ticker: string;
  contribution: Weight;
}

export interface SectorExposure {
  sector: Sector;
  weight: Weight;
  by_etf: SectorContribution[];
}

export interface DataGap {
  kind: GapKind;
  severity: GapSeverity;
  etf_ticker: string | null;
  subject: string | null;
  portfolio_weight: Weight | null;
  message: string;
}

export interface Attribution {
  source: SourceName;
  text: string;
  url: string | null;
  licence: string | null;
}

export interface AnalysisResponse {
  method_version: "hoc-1";
  generated_at: IsoDateTime;
  as_of_date: IsoDate;
  request: Required<PortfolioRequest>;
  etfs: EtfReport[];
  coverage: Coverage;
  /** Sorted by exposure desc; at most request.max_companies. exposures + other_exposure == covered_weight. */
  exposures: CompanyExposure[];
  exposures_truncated: boolean;
  other_exposure: Weight;
  overlap: Overlap;
  concentration: Concentration;
  /** Sorted by weight desc; sums to coverage.covered_weight. */
  sectors: SectorExposure[];
  gaps: DataGap[];
  warnings: Notice[];
  attributions: Attribution[];
}

// ---------- other endpoints ----------

/** GET /api/etfs/{ticker}[?holdings=true&source=...] */
export interface EtfSummary {
  ticker: string;
  name: string | null;
  status: EtfStatus;
  source: SourceName;
  source_layer: string | null;
  source_url: string;
  filing_url: string | null;
  attribution: string | null;
  licence: string | null;
  as_of: IsoDate;
  retrieved_at: IsoDateTime;
  holdings_count: number;
  company_count: number;
  reported_weight: Weight;
  holdings_weight: Weight;
  excluded_weight: Weight;
  unmatched_weight: Weight;
  sector_basis: SectorBasis;
  sector_weights: Partial<Record<Sector, Weight>>;
  warnings: Notice[];
  attempts: SourceAttempt[];
  holdings: NormalisedHolding[] | null;
  /** The ETF's latest price from its source, if published (v2). */
  price: PriceQuote | null;
}

export interface ExampleEtf {
  ticker: string;
  allocation: Weight;
  verified: boolean;
  source: SourceName | null;
  as_of: IsoDate | null;
}

export interface ExamplePortfolio {
  id: string;
  name: string;
  description: string;
  holdings: ExampleEtf[];
  /** Offer the example only when true. */
  verified: boolean;
}

/** GET /api/examples */
export interface ExamplesResponse {
  examples: ExamplePortfolio[];
}

/** GET /api/health */
export interface HealthResponse {
  status: "ok";
  version: string;
  offline: boolean;
  sources: SourceName[];
}

/** Every non-2xx response body. */
export interface ErrorResponse {
  error: {
    code: ErrorCode;
    message: string;
    details: Record<string, unknown>;
  };
}

// =====================================================================================
// v2: share-based valuation (backend/hoc/contract/valuation.py)
// =====================================================================================

/** An ETF's latest market price (backend/hoc/contract/raw.py PriceQuote). */
export interface PriceQuote {
  price: number;
  /** ISO 4217, e.g. "USD". */
  currency: string;
  /** Trading date of the price, not the download date. */
  as_of: IsoDate;
  /** "close" = exchange closing price (not NAV); "nav" = net asset value per share. */
  kind: "close" | "nav";
  source: SourceName;
  attribution: string | null;
}

/** Calendar days after which a price is flagged stale (warning only). */
export const PRICE_STALE_DAYS = 4;

export interface ValuationRow {
  ticker: string;
  /** Shares held (fractional allowed). Ignored when allocation_override is set. */
  shares?: number | null;
  /** Pinned target allocation as a FRACTION (0.25 = 25%); null = unpinned (valued from shares). */
  allocation_override?: Weight | null;
}

export interface ValuationRequest {
  rows: ValuationRow[];
}

export type ValuationIssueCode =
  | "no_price"
  | "invalid_price"
  | "non_usd_price"
  | "price_unavailable"
  | "stale_price"
  | "missing_shares"
  | "pinned_over_100"
  | "nothing_to_rescale"
  | "allocation_sum_invalid"
  | "duplicate_ticker"
  | "too_many_etfs";

export interface ValuationIssue {
  code: ValuationIssueCode;
  severity: "warning" | "blocking";
  ticker: string | null;
  message: string;
}

export interface ValuationRowResult {
  ticker: string;
  pinned: boolean;
  shares: number | null;
  price: PriceQuote | null;
  price_age_days: number | null;
  price_stale: boolean;
  /** shares x price, in price.currency (unpinned rows with a usable price). */
  value: number | null;
  /** Resulting allocation (fraction); null when blocked for this row. */
  allocation: Weight | null;
  issues: ValuationIssue[];
}

/** POST /api/valuation. When status is "usable", rows' allocations total 1 and go straight to /api/analysis. */
export interface ValuationResponse {
  status: "usable" | "blocked";
  as_of_date: IsoDate;
  rows: ValuationRowResult[];
  total_value: number;
  pinned_total: Weight;
  issues: ValuationIssue[];
  attributions: Attribution[];
}

// =====================================================================================
// v2: AI dependency analysis (backend/hoc/contract/dependencies.py)
// =====================================================================================

export const DEFAULT_TOP_N = 15;

export type ResearchDepth = "light" | "thorough";

export interface DependencyRequest {
  holdings: PortfolioItem[];
  top_n?: number;
  /** v3.1: how far each company's agent investigates (part of the job id). Default "light". */
  depth?: ResearchDepth;
}

export type FilingForm = "10-K" | "20-F";

export interface FilingRef {
  /** The filer. */
  company_key: string;
  form: FilingForm;
  accession: string;
  filed: IsoDate;
  url: string;
}

export type CompanyStatus =
  | "queued"
  | "fetching"
  | "extracting"
  | "cached"
  | "done"
  | "no_sec_filing"
  | "unsupported_form"
  | "sec_contact_missing"
  | "missing_api_key"
  | "error"
  | "researching";

export interface CompanyRunStatus {
  company_key: string;
  company_name: string;
  exposure: Weight;
  status: CompanyStatus;
  extraction_quality: "sections" | "fallback" | null;
  filing: FilingRef | null;
  verified_edges: number;
  rejected_edges: number;
  message: string | null;
}

export type EdgeType =
  | "supplier"
  | "customer"
  | "contract_manufacturer"
  | "foundry"
  | "key_input"
  | "facility"
  | "jv_partner";

export type TargetKind =
  | "company"
  | "country"
  | "region"
  | "material"
  | "component"
  | "facility"
  | "unnamed_customer";

/** Only edges whose evidence_quote Python found verbatim in the filing. */
// ---------- v3 (docs/hoc/PLAN-v3.md): importance and interpretation of an edge ----------

export type ImportanceTier = "critical" | "high" | "medium" | "low";

/** R-IMP: scored in Python. critical >= 0.8, high >= 0.6, medium >= 0.4, else low. */
export interface EdgeImportance {
  score: number;
  tier: ImportanceTier;
  /** Plain English; cue words are quoted from the verified evidence. */
  reasons: string[];
}

export type InterpretationStatus = "confirmed" | "flagged" | "rejected";
export type InterpretationFlag =
  | "competitor_mention"
  | "negated"
  | "hypothetical"
  | "direction_mismatch"
  | "generic_reference"
  | "subject_mismatch"
  | "judge_unclear";

/** V-INT: never "rejected" inside DependencyResult.edges (rejected edges are only counted). */
export interface EdgeInterpretation {
  status: InterpretationStatus;
  method: "rules" | "rules+model";
  flags: InterpretationFlag[];
  reason: string | null;
  model: string | null;
}

export interface VerifiedEdge {
  edge_id: string;
  source_company_key: string;
  source_company_name: string;
  source_in_portfolio: boolean;
  edge_type: EdgeType;
  target_name: string;
  target_kind: TargetKind;
  /** Deterministic resolution; null = unresolved counterparty. */
  target_key: string | null;
  target_in_portfolio: boolean;
  sole_source: boolean;
  qualifier: string | null;
  evidence_quote: string;
  section: string;
  filing: FilingRef;
  /** v3: null until R-IMP has scored it. */
  importance: EdgeImportance | null;
  /** v3: null until V-INT has checked it. */
  interpretation: EdgeInterpretation | null;
}

export type MetricUnit = "fraction" | "count" | "ratio" | "days";

export interface MetricFact {
  metric_id: string;
  label: string;
  value: number;
  /** "fraction" values are fractions of the portfolio. */
  unit: MetricUnit;
  subject_key: string | null;
  supporting_edge_ids: string[];
}

export interface InsightClaim {
  claim_id: string;
  kind: "suggestion" | "flaw";
  severity: "info" | "warning" | "critical";
  title: string;
  /** Rendered text; every number came from a cited metric. */
  text: string;
  cited_metric_ids: string[];
  cited_edge_ids: string[];
  /** v3.1: beginner title (<= 8 words), or null if the model's version failed verification. */
  plain_title: string | null;
  /** v3.1: beginner one-liner (<= 25 words, numbers only from cited metrics), or null. */
  plain_text: string | null;
}

export type InsightsStatus = "ok" | "metrics_only" | "missing_api_key" | "no_verified_edges" | "error";

export interface Insights {
  status: InsightsStatus;
  model: string | null;
  suggestions: InsightClaim[];
  flaws: InsightClaim[];
  /** Claims Python dropped (invented numbers, unknown ids, names outside portfolio/edges). */
  rejected_claims_count: number;
}

export interface DependencyCounts {
  companies_requested: number;
  companies_analysed: number;
  companies_skipped: number;
  verified_edges: number;
  rejected_edges: number;
  unresolved_counterparties: number;
  /** v3: quote verified but meaning did not (competitor, negated, wrong direction...). */
  interpretation_rejected: number;
}

// ---------- v3 C-COV: coverage ----------

export type CoverageKind = "verified" | "no_disclosures" | "no_sec_filing" | "not_analysed" | "outside_top_n";

export interface CoverageBucket {
  kind: CoverageKind;
  /** Fraction of the whole portfolio; the buckets of one report sum to 1. */
  weight: number;
  companies: number;
  label: string;
}

export interface EtfCoverage {
  ticker: string;
  /** Fraction of this ETF's own look-through weight in the "verified" bucket. */
  verified_weight: number;
}

export interface UnanalysedCompany {
  company_key: string;
  company_name: string;
  exposure: number;
}

export type CoverageGapKind =
  | "outside_top_n"
  | "unnamed_customers"
  | "non_sec_counterparties"
  | "old_filings"
  | "region_only_facilities";

export interface CoverageGap {
  kind: CoverageGapKind;
  message: string;
  weight: number | null;
}

export interface CoverageReport {
  buckets: CoverageBucket[];
  by_etf: EtfCoverage[];
  /** The largest exposures outside the analysed top N (at most 10). */
  largest_unanalysed: UnanalysedCompany[];
  gaps: CoverageGap[];
}

export interface DependencyResult {
  as_of_date: IsoDate;
  request: Required<DependencyRequest>;
  companies: CompanyRunStatus[];
  edges: VerifiedEdge[];
  metrics: MetricFact[];
  insights: Insights;
  counts: DependencyCounts;
  attributions: Attribution[];
  /** v3: null until C-COV is wired in. */
  coverage: CoverageReport | null;
  /** v3.1: findings from the run's own agentic loop. */
  research: ResearchFinding[];
  research_depth: "none" | "light" | "thorough";
}

export type JobStatus = "queued" | "running" | "done" | "error";
/** v3.1: reading (fetch + extract) -> researching (agentic loop) -> synthesising (metrics + insights) -> done. */
export type JobPhase = "queued" | "reading" | "researching" | "synthesising" | "done";

/** POST /api/dependencies (200 if done from cache, 202 otherwise) and GET /api/dependencies/{job_id}. Poll every 1-2 s. */
export interface DependencyJob {
  job_id: string;
  status: JobStatus;
  progress_done: number;
  progress_total: number;
  /** v3.1: progress bar across all phases. */
  phase: JobPhase;
  steps_done: number;
  steps_total: number;
  companies: CompanyRunStatus[];
  result: DependencyResult | null;
  error: ErrorResponse["error"] | null;
}

// ---------- v3 A-RES: research loop ----------

export const DEFAULT_RESEARCH_ITEMS = 6;

/** POST /api/dependencies/{job_id}/research */
export interface ResearchRequest {
  max_items?: number;
}

export type ResearchItemKind =
  | "flagged_edge"
  | "undisclosed_customer"
  | "single_source"
  | "no_disclosures"
  | "unresolved_counterparty";
export type ResearchAction = "search_filings" | "read_section" | "find_in_filing" | "conclude";
export type ResearchOutcome = "confirmed" | "revised" | "rejected" | "new_evidence" | "unresolved";

export interface ResearchStep {
  index: number;
  action: ResearchAction;
  query: string | null;
  /** Python-rendered description of what the tool returned. */
  summary: string;
  filing: FilingRef | null;
}

export interface ResearchFinding {
  finding_id: string;
  kind: ResearchItemKind;
  subject: string;
  question: string;
  outcome: ResearchOutcome;
  explanation: string;
  steps: ResearchStep[];
  confirmed_edge_ids: string[];
  rejected_edge_ids: string[];
  new_edges: VerifiedEdge[];
}

/** POST /api/dependencies/{job_id}/research (202, or 200 if cached); poll GET /api/research/{research_id}. */
export interface ResearchJob {
  research_id: string;
  dependency_job_id: string;
  status: JobStatus;
  progress_done: number;
  progress_total: number;
  findings: ResearchFinding[];
  /** The dependency result with findings merged in (metrics and insights recomputed). */
  result: DependencyResult | null;
  error: ErrorResponse["error"] | null;
}

// ---------- v3 X-API: before/after comparison (POST /api/compare; cache-only, no Gemini) ----------

export interface CompareRequest {
  baseline: PortfolioItem[];
  candidate: PortfolioItem[];
  top_n?: number;
}

export interface MetricDelta {
  metric_id: string;
  label: string;
  unit: MetricUnit;
  baseline: number | null;
  candidate: number | null;
  /** candidate - baseline when both exist. */
  delta: number | null;
}

/** top_sector (v3.1): the largest industry's share of the portfolio. */
export type ConcentrationName = "top5" | "top10" | "top20" | "effective_n" | "largest_company" | "top_sector";

export interface ConcentrationDelta {
  name: ConcentrationName;
  baseline: number;
  candidate: number;
  delta: number;
}

export interface CompareResponse {
  /** "partial" when some candidate top-N companies have no cached extraction yet. */
  status: "ok" | "partial";
  baseline_top_n_weight: number;
  candidate_top_n_weight: number;
  /** Fraction metrics first, then counts; within each unit by |delta| (one-sided: by value), ties by metric_id. */
  dependency_deltas: MetricDelta[];
  concentration_deltas: ConcentrationDelta[];
  candidate_unanalysed: UnanalysedCompany[];
  notes: string[];
}

// ---------- FIX-17: deterministic ETF ideas (POST /api/change-ideas) ----------

export interface ChangeIdeasRequest {
  holdings: PortfolioItem[];
  top_n?: number;
}

export interface ChangeIdea {
  idea_id: string;
  ticker: string;
  etf_name: string;
  add_fraction: 0.1 | 0.2;
  addresses: "top_sector" | "dependency" | "top10" | "effective_n";
  /** dep.<key> when addresses is dependency, otherwise null. */
  metric_id: string | null;
  /** One to eight words, no digits. */
  title: string;
  /** One Python-rendered sentence with the addressed measure's before/after values. */
  reason: string;
  /** Complete scenario allocations; whole-share rounding can change the result. */
  holdings: PortfolioItem[];
  concentration_deltas: ConcentrationDelta[];
  biggest_dependency_delta: MetricDelta | null;
  status: "ok" | "partial";
  candidate_unanalysed: UnanalysedCompany[];
  notes: string[];
}

export interface ChangeIdeasResponse {
  status: "ok" | "partial";
  /** At most three distinct ETFs, best tested fraction for each. */
  ideas: ChangeIdea[];
  notes: string[];
}
