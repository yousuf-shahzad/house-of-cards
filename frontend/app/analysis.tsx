"use client";
// Shared portfolio state: draft rows, client-side validation, the shares-mode valuation, and
// the debounced analysis request. Pages read it through useAnalysis().
//
// Two input modes:
// - percent: each row's allocationPct is what the analysis uses.
// - shares: each row holds a share count. The backend prices the rows (POST /api/valuation) and
//   returns each row's %. Typing a % into a row pins it; the unpinned rows rescale by value to
//   fill the rest of 100%. The analysis only ever sees the resulting percentages.
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
import { api, ApiError, type AllocationInput, type ShareInput } from "@/api/client";
import {
  ALLOCATION_TOLERANCE,
  MAX_ETFS,
  type AnalysisResponse,
  type ValuationResponse,
  type ValuationRowResult,
} from "@/api/types";

export const DEBOUNCE_MS = 400;
const SUM_TOLERANCE_PCT = ALLOCATION_TOLERANCE * 100;
const TICKER_PATTERN = /^[A-Za-z0-9.\-]{1,12}$/;

export type InputMode = "percent" | "shares";
export type DraftRow = {
  id: string;
  ticker: string;
  /** Percent mode: the allocation. Shares mode: the override, used only when `pinned`. */
  allocationPct: number | null;
  shares: number | null;
  pinned: boolean;
};
export type RowIssue =
  | "empty"
  | "too-many-etfs"
  | "invalid-ticker"
  | "duplicate-ticker"
  | "invalid-allocation"
  | "allocation-sum"
  | "invalid-shares"
  | "pinned-over-100"
  | "nothing-to-rescale"
  | "valuation-blocked"
  | "valuation-error";
export type Validation = { valid: boolean; totalPct: number; issues: RowIssue[] };
export type AnalysisStatus = "invalid" | "loading" | "ready" | "error";
export type ValuationStatus = "off" | "pricing" | "usable" | "blocked" | "error";

const validPct = (value: number | null): value is number =>
  value !== null && Number.isFinite(value) && value >= 0 && value <= 100;
const validShares = (value: number | null): value is number =>
  value !== null && Number.isFinite(value) && value >= 0;

/** Checks that need no prices. Shares mode adds the pinned-row rules from docs/hoc/PLAN-v2.md. */
export function validateRows(rows: DraftRow[], mode: InputMode = "percent"): Validation {
  const issues = new Set<RowIssue>();
  if (rows.length === 0) issues.add("empty");
  if (rows.length > MAX_ETFS) issues.add("too-many-etfs");
  const seen = new Set<string>();
  for (const row of rows) {
    const ticker = row.ticker.trim().toUpperCase();
    if (!ticker) issues.add("empty");
    else if (!TICKER_PATTERN.test(ticker)) issues.add("invalid-ticker");
    if (ticker && seen.has(ticker)) issues.add("duplicate-ticker");
    seen.add(ticker);
  }

  if (mode === "percent") {
    const amounts: number[] = [];
    for (const row of rows) {
      if (validPct(row.allocationPct)) amounts.push(row.allocationPct);
      else issues.add("invalid-allocation");
    }
    const totalPct = amounts.reduce((sum, value) => sum + value, 0);
    if (Math.abs(totalPct - 100) > SUM_TOLERANCE_PCT) issues.add("allocation-sum");
    return { valid: issues.size === 0, totalPct, issues: [...issues] };
  }

  let pinnedPct = 0;
  let unpinnedShares = 0;
  const unpinned = rows.filter((row) => !row.pinned);
  for (const row of rows) {
    if (row.pinned) {
      if (validPct(row.allocationPct)) pinnedPct += row.allocationPct;
      else issues.add("invalid-allocation");
    } else if (validShares(row.shares)) {
      unpinnedShares += row.shares;
    } else {
      issues.add("invalid-shares");
    }
  }
  if (pinnedPct > 100 + SUM_TOLERANCE_PCT) issues.add("pinned-over-100");
  else if (unpinned.length === 0 && rows.length > 0 && Math.abs(pinnedPct - 100) > SUM_TOLERANCE_PCT) {
    issues.add("allocation-sum");
  } else if (unpinned.length > 0 && pinnedPct < 100 - SUM_TOLERANCE_PCT && unpinnedShares === 0) {
    issues.add("nothing-to-rescale");
  }
  return { valid: issues.size === 0, totalPct: pinnedPct, issues: [...issues] };
}

type ValuationState = {
  /** The request key this state belongs to. */
  key: string;
  status: Exclude<ValuationStatus, "off">;
  result: ValuationResponse | null;
  error: ApiError | null;
};

type AnalysisContextValue = {
  rows: DraftRow[];
  /** Loads percentage rows (examples, rebalances) and switches to percent mode. */
  setRows: (rows: AllocationInput[]) => void;
  addRow: (ticker?: string, allocationPct?: number | null) => void;
  updateRow: (id: string, patch: Partial<Omit<DraftRow, "id">>) => void;
  removeRow: (id: string) => void;
  mode: InputMode;
  setMode: (mode: InputMode) => void;
  /** Set when setRows replaced entered share counts; cleared by dismissNotice or the next edit. */
  notice: string | null;
  dismissNotice: () => void;
  /** The % each row contributes to the analysis, or null while it can't be worked out. */
  effectivePct: Record<string, number | null>;
  /** The latest valuation row for each row id (shares mode). May lag the draft while pricing. */
  priced: Record<string, ValuationRowResult | undefined>;
  valuation: {
    status: ValuationStatus;
    result: ValuationResponse | null;
    error: ApiError | null;
  };
  validation: Validation;
  status: AnalysisStatus;
  /** Latest successful analysis. Kept while a newer request loads. */
  analysis: AnalysisResponse | null;
  /** Key of the rows `analysis` was built from. Compare with your own key to detect stale results. */
  analysedKey: string | null;
  /** True when `analysis` no longer matches the current draft rows. */
  stale: boolean;
  error: ApiError | null;
  retry: () => void;
};

const AnalysisContext = createContext<AnalysisContextValue | null>(null);

let nextRowId = 0;
const rowId = () => `row-${++nextRowId}`;
const newRow = (ticker: string, allocationPct: number | null): DraftRow => ({
  id: rowId(),
  ticker,
  allocationPct,
  shares: null,
  pinned: false,
});
/** 4 decimal places of a percent, so 0.07 * 100 doesn't show as 7.000000000000001. */
const tidyPct = (value: number) => Math.round(value * 1e4) / 1e4;

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const [rows, setDraftRows] = useState<DraftRow[]>([]);
  const [mode, setModeState] = useState<InputMode>("percent");
  const [notice, setNotice] = useState<string | null>(null);
  const [valuationState, setValuationState] = useState<ValuationState | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [analysedKey, setAnalysedKey] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [status, setStatus] = useState<AnalysisStatus>("invalid");
  const [attempt, setAttempt] = useState(0);
  const latestRequest = useRef(0);

  const baseValidation = useMemo(() => validateRows(rows, mode), [rows, mode]);
  const needsPrices = mode === "shares" && rows.some((row) => !row.pinned);
  const shareInputs = useMemo<ShareInput[]>(
    () =>
      rows.map((row) => ({
        ticker: row.ticker,
        shares: row.shares,
        overridePct: row.pinned ? row.allocationPct : null,
      })),
    [rows],
  );
  const valuationKey = useMemo(
    () => JSON.stringify(shareInputs.map((row) => [row.ticker.trim().toUpperCase(), row.shares, row.overridePct])),
    [shareInputs],
  );

  // Valuation: no debounce (it is a cheap, cached calculation); a newer edit aborts the older call.
  useEffect(() => {
    if (!needsPrices || !baseValidation.valid) return;
    const controller = new AbortController();
    setValuationState((previous) => ({
      key: valuationKey,
      status: "pricing",
      result: previous?.result ?? null,
      error: null,
    }));
    api
      .valuation(shareInputs, controller.signal)
      .then((result) =>
        setValuationState({ key: valuationKey, status: result.status, result, error: null }),
      )
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setValuationState((previous) => ({
          key: valuationKey,
          status: "error",
          result: previous?.result ?? null,
          error:
            cause instanceof ApiError
              ? cause
              : new ApiError("UNEXPECTED_ERROR", "Something went wrong while pricing your shares.", 0),
        }));
      });
    return () => controller.abort();
    // `valuationKey` captures every value in `shareInputs` that the request sends.
  }, [valuationKey, needsPrices, baseValidation.valid, attempt]);

  const valuationStatus: ValuationStatus = !needsPrices
    ? "off"
    : !baseValidation.valid
      ? "off"
      : valuationState?.key === valuationKey
        ? valuationState.status
        : "pricing";
  const currentResult = valuationStatus === "usable" ? valuationState?.result ?? null : null;

  const priced = useMemo(() => {
    const out: Record<string, ValuationRowResult | undefined> = {};
    const result = mode === "shares" ? valuationState?.result : null;
    if (!result) return out;
    rows.forEach((row, i) => {
      const match = result.rows[i];
      if (match && match.ticker === row.ticker.trim().toUpperCase()) out[row.id] = match;
    });
    return out;
  }, [rows, mode, valuationState]);

  const effectivePct = useMemo(() => {
    const out: Record<string, number | null> = {};
    rows.forEach((row, i) => {
      if (mode === "percent" || row.pinned) out[row.id] = validPct(row.allocationPct) ? row.allocationPct : null;
      else {
        const match = currentResult?.rows[i];
        out[row.id] = match && match.allocation !== null ? match.allocation * 100 : null;
      }
    });
    return out;
  }, [rows, mode, currentResult]);

  const validation = useMemo<Validation>(() => {
    if (mode === "percent" || !needsPrices || !baseValidation.valid) return baseValidation;
    const issues = [...baseValidation.issues];
    if (valuationStatus === "blocked") issues.push("valuation-blocked");
    if (valuationStatus === "error") issues.push("valuation-error");
    const totalPct = rows.reduce((sum, row) => sum + (effectivePct[row.id] ?? 0), 0);
    if (valuationStatus === "usable" && Math.abs(totalPct - 100) > SUM_TOLERANCE_PCT) issues.push("allocation-sum");
    // While pricing there is no issue to show, but the analysis must wait for the new %.
    const ready = valuationStatus === "usable" && issues.length === 0;
    return { valid: ready, totalPct: valuationStatus === "usable" ? totalPct : baseValidation.totalPct, issues };
  }, [mode, needsPrices, baseValidation, valuationStatus, rows, effectivePct]);

  const inputs = useMemo<AllocationInput[] | null>(() => {
    if (!validation.valid) return null;
    return rows.map((row) => ({ ticker: row.ticker, allocationPct: effectivePct[row.id] as number }));
  }, [validation.valid, rows, effectivePct]);
  const key = useMemo(
    () =>
      JSON.stringify(
        inputs
          ? inputs.map((row) => [row.ticker.trim().toUpperCase(), row.allocationPct])
          : rows.map((row) => [row.ticker.trim().toUpperCase(), effectivePct[row.id] ?? null]),
      ),
    [inputs, rows, effectivePct],
  );
  const pricing = valuationStatus === "pricing";

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

  const setRows = useCallback(
    (next: AllocationInput[]) => {
      if (mode === "shares" && rows.some((row) => row.shares !== null)) {
        setNotice("Switched to percentages: the loaded portfolio replaced the share counts you entered.");
      }
      setModeState("percent");
      setDraftRows(next.map((row) => newRow(row.ticker, row.allocationPct)));
    },
    [mode, rows],
  );
  const setMode = useCallback(
    (next: InputMode) => {
      if (next === mode) return;
      setNotice(null);
      if (next === "shares") {
        // Keep every % the user already has: rows without shares start pinned at their %.
        setDraftRows((current) =>
          current.map((row) => ({ ...row, pinned: row.shares === null && validPct(row.allocationPct) })),
        );
      } else {
        setDraftRows((current) =>
          current.map((row) => {
            const pct = effectivePct[row.id];
            return { ...row, pinned: false, allocationPct: pct === null || pct === undefined ? null : tidyPct(pct) };
          }),
        );
      }
      setModeState(next);
    },
    [mode, effectivePct],
  );
  const addRow = useCallback(
    (ticker = "", allocationPct: number | null = null) => {
      setDraftRows((current) => [...current, newRow(ticker, mode === "shares" ? null : allocationPct)]);
    },
    [mode],
  );
  const updateRow = useCallback((id: string, patch: Partial<Omit<DraftRow, "id">>) => {
    setNotice(null);
    setDraftRows((current) => current.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  }, []);
  const removeRow = useCallback((id: string) => {
    setDraftRows((current) => current.filter((row) => row.id !== id));
  }, []);
  const dismissNotice = useCallback(() => setNotice(null), []);
  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  const valuation = useMemo(
    () => ({
      status: valuationStatus,
      result: mode === "shares" ? (valuationState?.result ?? null) : null,
      error: valuationStatus === "error" ? (valuationState?.error ?? null) : null,
    }),
    [valuationStatus, mode, valuationState],
  );

  const value = useMemo<AnalysisContextValue>(
    () => ({
      rows,
      setRows,
      addRow,
      updateRow,
      removeRow,
      mode,
      setMode,
      notice,
      dismissNotice,
      effectivePct,
      priced,
      valuation,
      validation,
      status,
      analysis,
      analysedKey,
      stale: analysis !== null && analysedKey !== key,
      error,
      retry,
    }),
    [
      rows,
      setRows,
      addRow,
      updateRow,
      removeRow,
      mode,
      setMode,
      notice,
      dismissNotice,
      effectivePct,
      priced,
      valuation,
      validation,
      status,
      analysis,
      analysedKey,
      key,
      error,
      retry,
    ],
  );
  return <AnalysisContext.Provider value={value}>{children}</AnalysisContext.Provider>;
}

export function useAnalysis(): AnalysisContextValue {
  const value = useContext(AnalysisContext);
  if (!value) throw new Error("useAnalysis must be used inside <AnalysisProvider>.");
  return value;
}
