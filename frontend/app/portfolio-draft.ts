"use client";
// One editable portfolio: draft rows, % or shares input, client-side validation and the
// shares-mode valuation. The shared Current portfolio (analysis.tsx) and the Compare page's
// Scenario each own one, so both follow exactly the same rules.
//
// Two input modes:
// - percent: each row's allocationPct is what the analysis uses.
// - shares: each row holds a share count. The backend prices the rows (POST /api/valuation) and
//   returns each row's %. Typing a % into a row pins it; the unpinned rows rescale by value to
//   fill the rest of 100%. Analyses only ever see the resulting percentages (`inputs`).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type AllocationInput, type ShareInput } from "@/api/client";
import { ALLOCATION_TOLERANCE, MAX_ETFS, type ValuationResponse, type ValuationRowResult } from "@/api/types";

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
export type ValuationStatus = "off" | "pricing" | "usable" | "blocked" | "error";

const validPct = (value: number | null): value is number =>
  value !== null && Number.isFinite(value) && value >= 0 && value <= 100;
export const MAX_SHARES = 1_000_000_000;
export const validShares = (value: number | null): value is number =>
  value !== null && Number.isFinite(value) && value >= 0 && value <= MAX_SHARES;

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

export type PortfolioDraft = {
  rows: DraftRow[];
  /** Loads percentage rows (examples, rebalances) and switches to percent mode. */
  setRows: (rows: AllocationInput[]) => void;
  /** Replaces the whole draft with a copy of another (new row ids), keeping its mode, shares and pins. */
  copyFrom: (rows: readonly DraftRow[], mode: InputMode) => void;
  addRow: (ticker?: string, allocationPct?: number | null) => void;
  updateRow: (id: string, patch: Partial<Omit<DraftRow, "id">>) => void;
  removeRow: (id: string) => void;
  mode: InputMode;
  setMode: (mode: InputMode) => void;
  /** Set when setRows replaced entered share counts; cleared by dismissNotice or the next edit. */
  notice: string | null;
  dismissNotice: () => void;
  /** The % each row contributes, or null while it can't be worked out. */
  effectivePct: Record<string, number | null>;
  /** The latest valuation row for each row id (shares mode). May lag the draft while pricing. */
  priced: Record<string, ValuationRowResult | undefined>;
  valuation: {
    status: ValuationStatus;
    result: ValuationResponse | null;
    error: ApiError | null;
  };
  validation: Validation;
  /** Percent rows ready for an analysis or comparison, or null while the draft isn't valid. */
  inputs: AllocationInput[] | null;
  /** Changes whenever the rows an analysis would use change. */
  key: string;
  /** Re-runs a failed valuation. */
  retryValuation: () => void;
  /** Shares mode: prices the pinned rows and turns them into whole share counts at about their %. */
  fillShares: () => void;
  /** Progress of turning pinned rows into shares (setRows does this on its own). */
  sharesFill: SharesFillStatus;
};
export type SharesFillStatus = "idle" | "pricing" | "failed";

let nextRowId = 0;
const rowId = () => `row-${++nextRowId}`;
const newRow = (ticker: string, allocationPct: number | null): DraftRow => ({
  id: rowId(),
  ticker,
  allocationPct,
  shares: null,
  pinned: false,
});
const normalise = (ticker: string) => ticker.trim().toUpperCase();
/** Rough value of a loaded sample when every row is a %, so it becomes sensible whole share counts. */
const SAMPLE_VALUE = 10_000;
/** 4 decimal places of a percent, so 0.07 * 100 doesn't show as 7.000000000000001. */
const tidyPct = (value: number) => Math.round(value * 1e4) / 1e4;

export function usePortfolioDraft(): PortfolioDraft {
  const [rows, setDraftRows] = useState<DraftRow[]>([]);
  const [mode, setModeState] = useState<InputMode>("shares");
  const [notice, setNotice] = useState<string | null>(null);
  const [valuationState, setValuationState] = useState<ValuationState | null>(null);
  const [attempt, setAttempt] = useState(0);

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
      .then((result) => setValuationState({ key: valuationKey, status: result.status, result, error: null }))
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
  const currentResult = valuationStatus === "usable" ? (valuationState?.result ?? null) : null;

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
    // While pricing there is no issue to show, but analyses must wait for the new %.
    const ready = valuationStatus === "usable" && issues.length === 0;
    return { valid: ready, totalPct: valuationStatus === "usable" ? totalPct : baseValidation.totalPct, issues };
  }, [mode, needsPrices, baseValidation, valuationStatus, rows, effectivePct]);

  const inputs = useMemo<AllocationInput[] | null>(() => {
    if (!validation.valid) return null;
    return rows
      .filter((row) => (effectivePct[row.id] ?? 0) > 0)
      .map((row) => ({ ticker: row.ticker, allocationPct: effectivePct[row.id] as number }));
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

  // Turning pinned % rows into whole shares. `fillTarget` is the rows array the latest attempt
  // started from: any edit replaces the array, so a late answer for older rows is dropped.
  const [sharesFill, setSharesFill] = useState<SharesFillStatus>("idle");
  const fillTarget = useRef<DraftRow[] | null>(null);
  const rowsRef = useRef(rows);
  rowsRef.current = rows;

  const fillSharesFor = useCallback((target: DraftRow[]) => {
    const pinned = target.filter((row) => row.pinned);
    fillTarget.current = target;
    if (pinned.length === 0) {
      setSharesFill("idle");
      return;
    }
    setSharesFill("pricing");
    api
      // Pinned rows ask for 1 share to learn the price; unpinned rows send their shares (blank as 0).
      .valuation(target.map((row) => ({ ticker: row.ticker, shares: row.pinned ? 1 : validShares(row.shares) ? row.shares : 0, overridePct: null })))
      .then((res) => {
        if (fillTarget.current !== target) return;
        const pinnedPct = pinned.reduce((sum, row) => sum + (row.allocationPct ?? 0), 0);
        let unpinnedValue = 0;
        const prices: (number | null)[] = target.map((row, i) => {
          const match = res.rows[i];
          if (!match || match.ticker !== normalise(row.ticker)) return null;
          if (!row.pinned) unpinnedValue += match.value ?? 0;
          const price = match.price?.price;
          return typeof price === "number" && Number.isFinite(price) && price > 0 ? price : null;
        });
        // Size the pinned rows against the unpinned rows' value, or ~$10,000 when every row is pinned.
        const unpinnedPct = 100 - pinnedPct;
        const total = unpinnedValue > 0 && unpinnedPct > SUM_TOLERANCE_PCT ? unpinnedValue / (unpinnedPct / 100) : SAMPLE_VALUE;
        if (target.some((row, i) => row.pinned && prices[i] === null)) {
          fillTarget.current = null;
          setSharesFill("failed");
          return;
        }
        fillTarget.current = null;
        setSharesFill("idle");
        setDraftRows((current) =>
          current !== target
            ? current
            : target.map((row, i) => {
                if (!row.pinned) return row;
                const pct = row.allocationPct ?? 0;
                const shares = pct <= 0 ? 0 : Math.max(1, Math.round(((pct / 100) * total) / (prices[i] as number)));
                return { ...row, shares, allocationPct: null, pinned: false };
              }),
        );
      })
      .catch(() => {
        if (fillTarget.current !== target) return;
        fillTarget.current = null;
        setSharesFill("failed");
      });
  }, []);

  const fillShares = useCallback(() => {
    if (mode === "shares") fillSharesFor(rowsRef.current);
  }, [mode, fillSharesFor]);

  const setRows = useCallback(
    (next: AllocationInput[]) => {
      setNotice(null);
      setModeState("shares");
      if (next.length === 0) {
        fillTarget.current = null;
        setSharesFill("idle");
        setDraftRows([]);
        return;
      }
      // Loads pinned at the given % (so analyses can start at once), then becomes whole shares
      // once prices arrive. If pricing fails the rows stay pinned and sharesFill says "failed".
      const sampleRows: DraftRow[] = next.map((row) => ({
        id: rowId(),
        ticker: normalise(row.ticker),
        allocationPct: row.allocationPct,
        shares: null,
        pinned: true,
      }));
      setDraftRows(sampleRows);
      fillSharesFor(sampleRows);
    },
    [fillSharesFor],
  );
  const copyFrom = useCallback((source: readonly DraftRow[], sourceMode: InputMode) => {
    setNotice(null);
    fillTarget.current = null;
    setSharesFill("idle");
    setModeState(sourceMode);
    setDraftRows(source.map((row) => ({ ...row, id: rowId() })));
  }, []);
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
  const retryValuation = useCallback(() => setAttempt((value) => value + 1), []);

  const valuation = useMemo(
    () => ({
      status: valuationStatus,
      result: mode === "shares" ? (valuationState?.result ?? null) : null,
      error: valuationStatus === "error" ? (valuationState?.error ?? null) : null,
    }),
    [valuationStatus, mode, valuationState],
  );

  return useMemo<PortfolioDraft>(
    () => ({
      rows,
      setRows,
      copyFrom,
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
      inputs,
      key,
      retryValuation,
      fillShares,
      sharesFill,
    }),
    [
      rows,
      setRows,
      copyFrom,
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
      inputs,
      key,
      retryValuation,
      fillShares,
      sharesFill,
    ],
  );
}
