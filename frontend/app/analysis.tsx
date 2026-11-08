"use client";
// Shared Current portfolio: one editable draft (portfolio-draft.ts) plus the debounced analysis
// request built from it. Pages read it through useAnalysis().
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError } from "@/api/client";
import type { AnalysisResponse } from "@/api/types";
import { usePortfolioDraft, type PortfolioDraft } from "@/app/portfolio-draft";

// Re-exported so pages can keep importing the draft types from here.
export {
  validateRows,
  type DraftRow,
  type InputMode,
  type PortfolioDraft,
  type RowIssue,
  type Validation,
  type ValuationStatus,
} from "@/app/portfolio-draft";

export const DEBOUNCE_MS = 400;
export type AnalysisStatus = "invalid" | "loading" | "ready" | "error";

type AnalysisContextValue = Omit<PortfolioDraft, "inputs" | "key" | "retryValuation" | "copyFrom" | "fillShares" | "sharesFill"> & {
  /** The Current portfolio's draft itself, e.g. to copy it into a Compare scenario. */
  draft: PortfolioDraft;
  status: AnalysisStatus;
  /** Latest successful analysis. Kept while a newer request loads. */
  analysis: AnalysisResponse | null;
  /** Key of the rows `analysis` was built from. Compare with your own key to detect stale results. */
  analysedKey: string | null;
  /** True when `analysis` no longer matches the current draft rows. */
  stale: boolean;
  error: ApiError | null;
  /** Re-runs a failed valuation and analysis. */
  retry: () => void;
};

const AnalysisContext = createContext<AnalysisContextValue | null>(null);

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const draft = usePortfolioDraft();
  const { inputs, key, valuation, retryValuation } = draft;
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [analysedKey, setAnalysedKey] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [status, setStatus] = useState<AnalysisStatus>("invalid");
  const [attempt, setAttempt] = useState(0);
  const latestRequest = useRef(0);
  const pricing = valuation.status === "pricing";

  // `key` captures every row value that affects the request.
  useEffect(() => {
    if (!inputs) {
      latestRequest.current += 1;
      setStatus(pricing ? "loading" : "invalid");
      setError(null);
      return;
    }
    const requestId = ++latestRequest.current;
    const controller = new AbortController();
    setStatus("loading");
    setError(null);
    const timer = window.setTimeout(() => {
      api
        .analyse(inputs, controller.signal)
        .then((result) => {
          if (requestId !== latestRequest.current) return;
          setAnalysis(result);
          setAnalysedKey(key);
          setStatus("ready");
        })
        .catch((cause: unknown) => {
          if (requestId !== latestRequest.current) return;
          if (cause instanceof DOMException && cause.name === "AbortError") return;
          setError(
            cause instanceof ApiError
              ? cause
              : new ApiError("UNEXPECTED_ERROR", "Something went wrong while reading the analysis.", 0),
          );
          setStatus("error");
        });
    }, DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [key, attempt, pricing]);

  const retry = useCallback(() => {
    retryValuation();
    setAttempt((value) => value + 1);
  }, [retryValuation]);

  const value = useMemo<AnalysisContextValue>(
    () => ({
      draft,
      rows: draft.rows,
      setRows: draft.setRows,
      addRow: draft.addRow,
      updateRow: draft.updateRow,
      removeRow: draft.removeRow,
      mode: draft.mode,
      setMode: draft.setMode,
      notice: draft.notice,
      dismissNotice: draft.dismissNotice,
      effectivePct: draft.effectivePct,
      priced: draft.priced,
      valuation: draft.valuation,
      validation: draft.validation,
      status,
      analysis,
      analysedKey,
      stale: analysis !== null && analysedKey !== key,
      error,
      retry,
    }),
    [draft, status, analysis, analysedKey, key, error, retry],
  );
  return <AnalysisContext.Provider value={value}>{children}</AnalysisContext.Provider>;
}

export function useAnalysis(): AnalysisContextValue {
  const value = useContext(AnalysisContext);
  if (!value) throw new Error("useAnalysis must be used inside <AnalysisProvider>.");
  return value;
}
