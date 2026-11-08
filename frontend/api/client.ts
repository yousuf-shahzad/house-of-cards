// The only module that talks to the backend, and the only place percent is
// converted to a fraction. Inputs above this layer are in percent; API responses
// keep the contract's fractions of 1.
import {
  DEFAULT_RESEARCH_ITEMS,
  DEFAULT_SHOCK_DROP,
  DEFAULT_TOP_N,
  type AffectedCompany,
  type PortfolioRequest,
  type AnalysisResponse,
  type ChangeIdeasRequest,
  type ChangeIdeasResponse,
  type CompareRequest,
  type CompareResponse,
  type DependencyJob,
  type DependencyRequest,
  type ErrorResponse,
  type EtfSummary,
  type ExamplesResponse,
  type HealthResponse,
  type ResearchDepth,
  type ResearchJob,
  type ShockSpec,
  type StressRequest,
  type StressResponse,
  type StressSide,
  type ValuationIssue,
  type ValuationRequest,
  type ValuationResponse,
} from "./types";

export const MOCK_MODE = import.meta.env.VITE_API_MOCK === "1";

export type AllocationInput = { ticker: string; allocationPct: number };
/** One shares-mode row. `overridePct` (percent) pins the row; null leaves it valued by its shares. */
export type ShareInput = { ticker: string; shares: number | null; overridePct: number | null };

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function toAnalysisRequest(rows: AllocationInput[]): PortfolioRequest {
  return {
    holdings: rows.map((row) => ({
      ticker: row.ticker.trim().toUpperCase(),
      allocation: row.allocationPct / 100,
    })),
  };
}

export function toValuationRequest(rows: ShareInput[]): ValuationRequest {
  return {
    rows: rows.map((row) => ({
      ticker: row.ticker.trim().toUpperCase(),
      shares: row.overridePct === null ? row.shares : null,
      allocation_override: row.overridePct === null ? null : row.overridePct / 100,
    })),
  };
}

export function toDependencyRequest(
  rows: AllocationInput[],
  topN: number,
  depth?: ResearchDepth,
): DependencyRequest {
  return depth
    ? { ...toAnalysisRequest(rows), top_n: topN, depth }
    : { ...toAnalysisRequest(rows), top_n: topN };
}

export function toChangeIdeasRequest(rows: AllocationInput[], topN: number): ChangeIdeasRequest {
  return { ...toAnalysisRequest(rows), top_n: topN };
}

export function toCompareRequest(baseline: AllocationInput[], candidate: AllocationInput[], topN: number): CompareRequest {
  return {
    baseline: toAnalysisRequest(baseline).holdings,
    candidate: toAnalysisRequest(candidate).holdings,
    top_n: topN,
  };
}

export function toStressRequest(
  baseline: AllocationInput[],
  candidate: AllocationInput[] | null | undefined,
  shock: ShockSpec,
  companyKeys?: string[],
): StressRequest {
  return {
    baseline: toAnalysisRequest(baseline).holdings,
    ...(candidate && candidate.length > 0
      ? { candidate: toAnalysisRequest(candidate).holdings }
      : {}),
    shock,
    ...(companyKeys && companyKeys.length > 0 ? { company_keys: companyKeys } : {}),
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { Accept: "application/json", ...init?.headers },
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError("NETWORK_ERROR", "Could not reach the analysis service.", 0);
  }
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    // A proxy or crash page: reported below using the HTTP status.
  }
  if (!response.ok) {
    const error = (body as Partial<ErrorResponse> | null)?.error;
    throw new ApiError(
      error?.code ?? "HTTP_ERROR",
      error?.message ?? `The analysis service returned HTTP ${response.status}.`,
      response.status,
      error?.details,
    );
  }
  if (body === null) {
    throw new ApiError(
      "BAD_RESPONSE",
      "The analysis service returned an unreadable response.",
      response.status,
    );
  }
  return body as T;
}

const postJson = (body: unknown, signal?: AbortSignal): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
  signal,
});

const mockAnalysis = async (): Promise<AnalysisResponse> =>
  (await import("./__fixtures__/synthetic-analysis.json")).default as unknown as AnalysisResponse;

/** One example built from the fixture's own request, so "load example" works in mock mode. */
const mockExamples = async (): Promise<ExamplesResponse> => {
  const fixture = await mockAnalysis();
  return {
    examples: [
      {
        id: "synthetic",
        name: "Synthetic example",
        description: "Invented ETFs for building pages. Not real holdings.",
        verified: true,
        holdings: fixture.request.holdings.map((item) => ({
          ...item,
          verified: true,
          source: "fake",
          as_of: fixture.as_of_date,
        })),
      },
    ],
  };
};

const mockUnavailable = (what: string) =>
  new ApiError("MOCK_UNAVAILABLE", `${what} is not available in synthetic mock mode.`, 0);

/**
 * Mock valuation: the fixture's synthetic prices (first fixture price for any other ticker) run through
 * the PLAN-v2 rule allocation_i = (1 - P)·V_i/ΣV, so shares mode is interactive without a backend.
 * The real maths lives in backend/hoc/portfolio/valuation.py.
 */
async function mockValuation(rows: ShareInput[]): Promise<ValuationResponse> {
  const fixture = (await import("./__fixtures__/synthetic-valuation.json")).default as unknown as ValuationResponse;
  const quotes = new Map(fixture.rows.filter((row) => row.price).map((row) => [row.ticker, row.price!]));
  const fallback = [...quotes.values()][0];
  const tickers = rows.map((row) => row.ticker.trim().toUpperCase());
  const pinnedTotal = rows.reduce((sum, row) => sum + (row.overridePct ?? 0) / 100, 0);
  const values = rows.map((row, i) =>
    row.overridePct === null ? (row.shares ?? 0) * (quotes.get(tickers[i]) ?? fallback).price : null,
  );
  const unpinnedValue = values.reduce<number>((sum, value) => sum + (value ?? 0), 0);
  const allPinned = rows.every((row) => row.overridePct !== null);
  const issues: ValuationIssue[] = [];
  const block = (code: ValuationIssue["code"], message: string) =>
    issues.push({ code, severity: "blocking", ticker: null, message });
  if (pinnedTotal > 1 + 1e-9) block("pinned_over_100", "Pinned rows add up to more than 100%.");
  else if (allPinned && Math.abs(pinnedTotal - 1) > 1e-4) block("allocation_sum_invalid", "Pinned rows must total 100%.");
  else if (!allPinned && pinnedTotal < 1 && unpinnedValue <= 0) {
    block("nothing_to_rescale", "No unpinned row has a value to fill the rest of 100%.");
  }
  const blocked = issues.length > 0;
  return {
    status: blocked ? "blocked" : "usable",
    as_of_date: fixture.as_of_date,
    rows: rows.map((row, i) => {
      const pinned = row.overridePct !== null;
      const quote = pinned ? null : (quotes.get(tickers[i]) ?? fallback);
      return {
        ticker: tickers[i],
        pinned,
        shares: pinned ? null : row.shares,
        price: quote,
        price_age_days: quote ? 0 : null,
        price_stale: false,
        value: values[i],
        allocation: blocked
          ? null
          : pinned
            ? row.overridePct! / 100
            : ((1 - pinnedTotal) * (values[i] ?? 0)) / unpinnedValue,
        issues: [],
      };
    }),
    total_value: unpinnedValue,
    pinned_total: pinnedTotal,
    issues,
    attributions: fixture.attributions,
  };
}

const mockChangeIdeas = async (): Promise<ChangeIdeasResponse> =>
  (await import("./__fixtures__/synthetic-change-ideas.json")).default as unknown as ChangeIdeasResponse;

const mockCompare = async (): Promise<CompareResponse> =>
  (await import("./__fixtures__/synthetic-compare.json")).default as unknown as CompareResponse;

const mockResearch = async (): Promise<ResearchJob> =>
  (await import("./__fixtures__/synthetic-research.json")).default as unknown as ResearchJob;

const mockDependencies = async (): Promise<DependencyJob> =>
  (await import("./__fixtures__/synthetic-dependencies.json")).default as unknown as DependencyJob;

async function mockStress(req: StressRequest): Promise<StressResponse> {
  const analysis = await mockAnalysis();
  const drop = req.shock.drop ?? DEFAULT_SHOCK_DROP;
  const keyUpper = req.shock.key.trim().toUpperCase();
  const keyLower = req.shock.key.trim().toLowerCase();
  const companyKeySet = new Set((req.company_keys ?? []).map((k) => k.trim()));

  const buildSide = (): StressSide => {
    const matched = analysis.exposures.filter((c) => {
      if (req.shock.kind === "sector") return c.sector.toLowerCase() === keyLower;
      if (req.shock.kind === "country") return (c.country ?? "").trim().toUpperCase() === keyUpper;
      return companyKeySet.has(c.company_key);
    });
    const sectorRow =
      req.shock.kind === "sector"
        ? analysis.sectors.find((s) => s.sector.toLowerCase() === keyLower)
        : undefined;
    const affectedWeight =
      sectorRow !== undefined
        ? sectorRow.weight
        : matched.reduce((sum, c) => sum + c.exposure, 0);
    const affected: AffectedCompany[] = matched
      .map((c) => ({
        company_key: c.company_key,
        company_name: c.company_name,
        exposure: c.exposure,
        loss: c.exposure * drop,
      }))
      .sort((a, b) => b.loss - a.loss || a.company_key.localeCompare(b.company_key))
      .slice(0, 10);
    return {
      affected_weight: affectedWeight,
      loss_fraction: affectedWeight * drop,
      affected_count: matched.length,
      affected,
    };
  };

  return {
    status: "ok",
    shock: req.shock,
    basis: {
      source: "simulated",
      drop,
      proxy: null,
      window_start: null,
      window_end: null,
      description: `Simulated ${Math.round(drop * 100)}% fall across affected companies.`,
    },
    baseline: buildSide(),
    candidate: req.candidate ? buildSide() : null,
    notes: [],
  };
}

export const api = {
  health: (signal?: AbortSignal) =>
    MOCK_MODE
      ? Promise.reject<HealthResponse>(mockUnavailable("Health"))
      : request<HealthResponse>("/api/health", { signal }),
  etf: (ticker: string, signal?: AbortSignal) =>
    MOCK_MODE
      ? Promise.reject<EtfSummary>(mockUnavailable("ETF detail"))
      : request<EtfSummary>(`/api/etfs/${encodeURIComponent(ticker.trim().toUpperCase())}`, {
          signal,
        }),
  examples: (signal?: AbortSignal) =>
    MOCK_MODE
      ? mockExamples()
      : request<ExamplesResponse>("/api/examples", { signal }),
  analyse: (rows: AllocationInput[], signal?: AbortSignal) =>
    MOCK_MODE
      ? mockAnalysis()
      : request<AnalysisResponse>("/api/analysis", postJson(toAnalysisRequest(rows), signal)),
  /** Prices share-count rows and returns each row's allocation. Cheap: call it on every edit. */
  valuation: (rows: ShareInput[], signal?: AbortSignal) =>
    MOCK_MODE
      ? mockValuation(rows)
      : request<ValuationResponse>("/api/valuation", postJson(toValuationRequest(rows), signal)),
  /**
   * Starts (or joins, the job id is idempotent) a dependency run for the top companies.
   * 200 = already done from cache, 202 = queued; both bodies are a DependencyJob, so callers check
   * `status` and poll `dependencyJob(job_id)` every 1–2 s until it is "done" or "error".
   */
  dependencies: (
    rows: AllocationInput[],
    topN = DEFAULT_TOP_N,
    signal?: AbortSignal,
    depth?: ResearchDepth,
  ) =>
    MOCK_MODE
      ? mockDependencies()
      : request<DependencyJob>(
          "/api/dependencies",
          postJson(toDependencyRequest(rows, topN, depth), signal),
        ),
  dependencyJob: (jobId: string, signal?: AbortSignal) =>
    MOCK_MODE
      ? mockDependencies()
      : request<DependencyJob>(`/api/dependencies/${encodeURIComponent(jobId)}`, { signal }),
  /** Before/after comparison of two portfolios. Synchronous and cache-only: it never calls Gemini. */
  /** Up to three ETF ideas that would improve the portfolio, each with its before/after (FIX-17). Never calls Gemini. */
  changeIdeas: (rows: AllocationInput[], topN = DEFAULT_TOP_N, signal?: AbortSignal) =>
    MOCK_MODE
      ? mockChangeIdeas()
      : request<ChangeIdeasResponse>("/api/change-ideas", postJson(toChangeIdeasRequest(rows, topN), signal)),
  compare: (baseline: AllocationInput[], candidate: AllocationInput[], topN = DEFAULT_TOP_N, signal?: AbortSignal) =>
    MOCK_MODE
      ? mockCompare()
      : request<CompareResponse>("/api/compare", postJson(toCompareRequest(baseline, candidate, topN), signal)),
  /** Simulates a sector, country, or supplier failure before and after the change (POST /api/stress). */
  stress: (
    baseline: AllocationInput[],
    candidate: AllocationInput[] | null | undefined,
    shock: ShockSpec,
    companyKeys?: string[],
    signal?: AbortSignal,
  ) =>
    MOCK_MODE
      ? mockStress(toStressRequest(baseline, candidate, shock, companyKeys))
      : request<StressResponse>(
          "/api/stress",
          postJson(toStressRequest(baseline, candidate, shock, companyKeys), signal),
        ),
  /** Starts the research loop on a finished dependency job (202, or 200 if cached); poll researchJob(research_id). */
  research: (dependencyJobId: string, maxItems = DEFAULT_RESEARCH_ITEMS, signal?: AbortSignal) =>
    MOCK_MODE
      ? mockResearch()
      : request<ResearchJob>(
          `/api/dependencies/${encodeURIComponent(dependencyJobId)}/research`,
          postJson({ max_items: maxItems }, signal),
        ),
  researchJob: (researchId: string, signal?: AbortSignal) =>
    MOCK_MODE
      ? mockResearch()
      : request<ResearchJob>(`/api/research/${encodeURIComponent(researchId)}`, { signal }),
};
