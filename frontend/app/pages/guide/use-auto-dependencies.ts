// Beginner mode: the supply-chain check always runs in the background, with no button.
//
// Call useAutoDependencies() from the guide's step 2 (and step 4 as a safety net). It starts a dependency run
// whenever the dependency store holds no run for the current analysed portfolio, including after switching
// A -> B -> A (FIX-47). It never restarts a portfolio whose run is running, done or failed, so an error is not
// retried in a loop: it stays failed until the portfolio changes, and step 4 then shows a friendly message.

import { useEffect } from "react";
import { useAnalysis } from "@/app/analysis";
import { useDependencies } from "@/app/dependencies-state";
import { DEFAULT_TOP_N } from "@/api/types";
import { shouldStartAutoRun } from "./auto-run";

/** The portfolio we just asked to run, until the store reports it. Guards a double start within one tick. */
let pendingKey: string | null = null;

export function useAutoDependencies(): void {
  const { status, analysis, analysedKey, stale } = useAnalysis();
  const { runDependencies, depsKey, status: depsStatus } = useDependencies();

  useEffect(() => {
    if (pendingKey !== null && depsKey === pendingKey) pendingKey = null; // the store has caught up
    const start = shouldStartAutoRun({
      status,
      stale,
      hasAnalysis: analysis !== null,
      analysedKey,
      depsKey,
      depsStatus,
      pendingKey,
    });
    if (!start || !analysedKey) return;
    pendingKey = analysedKey;
    runDependencies(DEFAULT_TOP_N);
  }, [status, stale, analysis, analysedKey, depsKey, depsStatus, runDependencies]);
}
