// Beginner mode: the supply-chain check always runs in the background, with no button.
//
// Call useAutoDependencies() from the guide's step 2 (and step 4 as a safety net). It starts one
// dependency run per analysed portfolio, as soon as the analysis is ready. It never re-runs a portfolio
// that is already running or done, and never retries an error in a loop: a failed run stays failed
// until the portfolio changes, and step 4 then shows a friendly message.

import { useEffect } from "react";
import { useAnalysis } from "@/app/analysis";
import { useDependencies } from "@/app/dependencies-state";
import { DEFAULT_TOP_N } from "@/api/types";

/** Portfolio keys we have already started a run for (module scope: survives step changes). */
const started = new Set<string>();

export function useAutoDependencies(): void {
  const { status, analysis, analysedKey, stale } = useAnalysis();
  const { runDependencies, depsKey, status: depsStatus } = useDependencies();

  useEffect(() => {
    if (status !== "ready" || stale || !analysis || !analysedKey) return;
    if (depsKey === analysedKey && depsStatus !== "idle") return; // this portfolio is running, done or failed
    if (started.has(analysedKey)) return;
    started.add(analysedKey);
    runDependencies(DEFAULT_TOP_N);
  }, [status, stale, analysis, analysedKey, depsKey, depsStatus, runDependencies]);
}
