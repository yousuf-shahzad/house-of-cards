// The only module that talks to the backend, and the only place percent is
// converted to a fraction. Inputs above this layer are in percent; API responses
// keep the contract's fractions of 1.
import type {
  PortfolioRequest,
  AnalysisResponse,
  ErrorResponse,
  EtfSummary,
  ExamplesResponse,
  HealthResponse,
} from "./types";

export const MOCK_MODE = import.meta.env.VITE_API_MOCK === "1";

export type AllocationInput = { ticker: string; allocationPct: number };

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
      : request<AnalysisResponse>("/api/analysis", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(toAnalysisRequest(rows)),
          signal,
        }),
};
