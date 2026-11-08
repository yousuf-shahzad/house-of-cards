// The only module that talks to the backend, and the only place percent is
// converted to a fraction. Inputs above this layer are in percent; API responses
// keep the contract's fractions of 1.
import {
  DEFAULT_TOP_N,
  type PortfolioRequest,
  type AnalysisResponse,
  type DependencyJob,
  type DependencyRequest,
  type ErrorResponse,
  type EtfSummary,
  type ExamplesResponse,
  type HealthResponse,
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

export function toDependencyRequest(rows: AllocationInput[], topN: number): DependencyRequest {
  return { ...toAnalysisRequest(rows), top_n: topN };
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

const mockDependencies = async (): Promise<DependencyJob> =>
  (await import("./__fixtures__/synthetic-dependencies.json")).default as unknown as DependencyJob;

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
  dependencies: (rows: AllocationInput[], topN = DEFAULT_TOP_N, signal?: AbortSignal) =>
    MOCK_MODE
      ? mockDependencies()
      : request<DependencyJob>("/api/dependencies", postJson(toDependencyRequest(rows, topN), signal)),
  dependencyJob: (jobId: string, signal?: AbortSignal) =>
    MOCK_MODE
      ? mockDependencies()
      : request<DependencyJob>(`/api/dependencies/${encodeURIComponent(jobId)}`, { signal }),
};
