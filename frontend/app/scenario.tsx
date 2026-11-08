"use client";
// The Compare page's Scenario: an editable copy of the Current portfolio plus the latest
// comparison. Mounted at the app root (inside AnalysisProvider) so it survives tab switches.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "@/api/client";
import type { CompareResponse } from "@/api/types";
import { useAnalysis } from "@/app/analysis";
import { usePortfolioDraft, type PortfolioDraft } from "@/app/portfolio-draft";

export type CompareStatus = "idle" | "loading" | "ready" | "error";

type ScenarioContextValue = {
  scenario: PortfolioDraft;
  /** Replaces the Scenario with a copy of the Current portfolio. */
  resetToCurrent: () => void;
  compare: () => void;
  compareStatus: CompareStatus;
  result: CompareResponse | null;
  error: ApiError | null;
  /** True when Current or Scenario changed after `result` was computed. */
  stale: boolean;
};

const ScenarioContext = createContext<ScenarioContextValue | null>(null);

export function ScenarioProvider({ children }: { children: ReactNode }) {
  const { draft: current } = useAnalysis();
  const scenario = usePortfolioDraft();
  const [compareStatus, setCompareStatus] = useState<CompareStatus>("idle");
  const [result, setResult] = useState<CompareResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [comparedKey, setComparedKey] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);

  const resetToCurrent = useCallback(() => {
    scenario.copyFrom(current.rows, current.mode);
  }, [scenario, current.rows, current.mode]);

  // Seed the Scenario from Current the first time Current has rows.
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current || current.rows.length === 0 || scenario.rows.length > 0) return;
    seeded.current = true;
    scenario.copyFrom(current.rows, current.mode);
  }, [current.rows, current.mode, scenario]);

  const pairKey = `${current.key}|${scenario.key}`;
  const compare = useCallback(() => {
    if (!current.inputs || !scenario.inputs) return;
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    const key = pairKey;
    setCompareStatus("loading");
    setError(null);
    api
      .compare(current.inputs, scenario.inputs, undefined, next.signal)
      .then((response) => {
        setResult(response);
        setComparedKey(key);
        setCompareStatus("ready");
      })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(
          cause instanceof ApiError
            ? cause
            : new ApiError("UNEXPECTED_ERROR", "Something went wrong while comparing the portfolios.", 0),
        );
        setCompareStatus("error");
      });
  }, [current.inputs, scenario.inputs, pairKey]);

  useEffect(() => () => controller.current?.abort(), []);

  const value = useMemo<ScenarioContextValue>(
    () => ({
      scenario,
      resetToCurrent,
      compare,
      compareStatus,
      result,
      error,
      stale: result !== null && comparedKey !== pairKey,
    }),
    [scenario, resetToCurrent, compare, compareStatus, result, error, comparedKey, pairKey],
  );
  return <ScenarioContext.Provider value={value}>{children}</ScenarioContext.Provider>;
}

export function useScenario(): ScenarioContextValue {
  const value = useContext(ScenarioContext);
  if (!value) throw new Error("useScenario must be used inside <ScenarioProvider>.");
  return value;
}
