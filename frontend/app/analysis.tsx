"use client";
// Shared portfolio state: draft rows, client-side validation, and the debounced
// analysis request. Pages read it through useAnalysis().
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
import { api, ApiError, type AllocationInput } from "@/api/client";
import { ALLOCATION_TOLERANCE, MAX_ETFS, type AnalysisResponse } from "@/api/types";

export const DEBOUNCE_MS = 400;
const SUM_TOLERANCE_PCT = ALLOCATION_TOLERANCE * 100;
const TICKER_PATTERN = /^[A-Za-z0-9.\-]{1,12}$/;

export type DraftRow = { id: string; ticker: string; allocationPct: number | null };
export type RowIssue =
  | "empty"
  | "too-many-etfs"
  | "invalid-ticker"
  | "duplicate-ticker"
  | "invalid-allocation"
  | "allocation-sum";
export type Validation = { valid: boolean; totalPct: number; issues: RowIssue[] };
export type AnalysisStatus = "invalid" | "loading" | "ready" | "error";

export function validateRows(rows: DraftRow[]): Validation {
  const issues = new Set<RowIssue>();
  if (rows.length === 0) issues.add("empty");
  if (rows.length > MAX_ETFS) issues.add("too-many-etfs");
  const seen = new Set<string>();
  const amounts: number[] = [];
  for (const row of rows) {
    const ticker = row.ticker.trim().toUpperCase();
    if (!ticker) issues.add("empty");
    else if (!TICKER_PATTERN.test(ticker)) issues.add("invalid-ticker");
    if (ticker && seen.has(ticker)) issues.add("duplicate-ticker");
    seen.add(ticker);
    if (row.allocationPct === null || !Number.isFinite(row.allocationPct) || row.allocationPct < 0) {
      issues.add("invalid-allocation");
    } else {
      amounts.push(row.allocationPct);
    }
  }
  const totalPct = amounts.reduce((sum, value) => sum + value, 0);
  if (Math.abs(totalPct - 100) > SUM_TOLERANCE_PCT) issues.add("allocation-sum");
  return { valid: issues.size === 0, totalPct, issues: [...issues] };
}

type AnalysisContextValue = {
  rows: DraftRow[];
  setRows: (rows: AllocationInput[]) => void;
  addRow: (ticker?: string, allocationPct?: number | null) => void;
  updateRow: (id: string, patch: Partial<Omit<DraftRow, "id">>) => void;
  removeRow: (id: string) => void;
  validation: Validation;
  status: AnalysisStatus;
  /** Latest successful analysis. Kept while a newer request loads. */
  analysis: AnalysisResponse | null;
  /** True when `analysis` no longer matches the current draft rows. */
  stale: boolean;
  error: ApiError | null;
  retry: () => void;
};

const AnalysisContext = createContext<AnalysisContextValue | null>(null);

let nextRowId = 0;
const rowId = () => `row-${++nextRowId}`;

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const [rows, setDraftRows] = useState<DraftRow[]>([]);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [analysedKey, setAnalysedKey] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [status, setStatus] = useState<AnalysisStatus>("invalid");
  const [attempt, setAttempt] = useState(0);
  const latestRequest = useRef(0);

  const validation = useMemo(() => validateRows(rows), [rows]);
  const key = useMemo(
    () => JSON.stringify(rows.map((row) => [row.ticker.trim().toUpperCase(), row.allocationPct])),
    [rows],
  );

  // `key` captures every row value that affects the request.
  useEffect(() => {
    if (!validation.valid) {
      latestRequest.current += 1;
      setStatus("invalid");
      setError(null);
      return;
    }
    const requestId = ++latestRequest.current;
    const controller = new AbortController();
    setStatus("loading");
    setError(null);
    const inputs: AllocationInput[] = rows.map((row) => ({
      ticker: row.ticker,
      allocationPct: row.allocationPct as number,
    }));
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
  }, [key, validation.valid, attempt]);

  const setRows = useCallback((next: AllocationInput[]) => {
    setDraftRows(
      next.map((row) => ({ id: rowId(), ticker: row.ticker, allocationPct: row.allocationPct })),
    );
  }, []);
  const addRow = useCallback((ticker = "", allocationPct: number | null = null) => {
    setDraftRows((current) => [...current, { id: rowId(), ticker, allocationPct }]);
  }, []);
  const updateRow = useCallback((id: string, patch: Partial<Omit<DraftRow, "id">>) => {
    setDraftRows((current) => current.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  }, []);
  const removeRow = useCallback((id: string) => {
    setDraftRows((current) => current.filter((row) => row.id !== id));
  }, []);
  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  const value = useMemo<AnalysisContextValue>(
    () => ({
      rows,
      setRows,
      addRow,
      updateRow,
      removeRow,
      validation,
      status,
      analysis,
      stale: analysis !== null && analysedKey !== key,
      error,
      retry,
    }),
    [rows, setRows, addRow, updateRow, removeRow, validation, status, analysis, analysedKey, key, error, retry],
  );
  return <AnalysisContext.Provider value={value}>{children}</AnalysisContext.Provider>;
}

export function useAnalysis(): AnalysisContextValue {
  const value = useContext(AnalysisContext);
  if (!value) throw new Error("useAnalysis must be used inside <AnalysisProvider>.");
  return value;
}
