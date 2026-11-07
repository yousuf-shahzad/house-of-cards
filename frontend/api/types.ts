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
