// FIX-47: pure decisions for the guided view, kept free of React and path aliases so node --test can import them.

export type AnalysisStatusLike = "invalid" | "loading" | "ready" | "error";

export interface AutoRunState {
  /** The analysis context's status for the current portfolio. */
  status: AnalysisStatusLike;
  /** True when the last analysis belongs to an earlier version of the portfolio. */
  stale: boolean;
  hasAnalysis: boolean;
  /** Key of the portfolio the analysis was built from. */
  analysedKey: string | null;
  /** Key of the portfolio the dependency store's job belongs to. */
  depsKey: string | null;
  /** The dependency store's status ("idle", "starting", "polling", "done", "error", ...). */
  depsStatus: string;
  /** A run this hook has asked for but the store hasn't reported yet (guards a double start in one tick). */
  pendingKey: string | null;
}

/**
 * Whether the background supply-chain check should start for the analysed portfolio now.
 *
 * Starts when the store holds no run for this exact portfolio, including after A -> B -> A (the store then
 * holds B). Never restarts a portfolio whose run is running, done or failed, so an error doesn't retry in a
 * loop; it re-runs only once the portfolio changes.
 */
export function shouldStartAutoRun(state: AutoRunState): boolean {
  if (state.status !== "ready" || state.stale || !state.hasAnalysis || !state.analysedKey) return false;
  if (state.depsKey === state.analysedKey && state.depsStatus !== "idle") return false;
  if (state.pendingKey === state.analysedKey) return false;
  return true;
}

export type GuideAnalysisView = "loading" | "error" | "changed" | "empty" | "ready";

/**
 * What guide steps 2-3 should show. They never show an earlier portfolio's results as if they were current:
 * a failed analysis shows the error, and an edited but unfinished portfolio says so.
 */
export function guideAnalysisView(state: {
  status: AnalysisStatusLike;
  stale: boolean;
  hasAnalysis: boolean;
  hasError: boolean;
}): GuideAnalysisView {
  if (state.status === "loading") return "loading";
  if (state.status === "error" && state.hasError) return "error";
  if (state.stale && state.hasAnalysis) return "changed";
  if (!state.hasAnalysis) return "empty";
  return "ready";
}
