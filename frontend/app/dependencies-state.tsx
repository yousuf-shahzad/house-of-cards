"use client";
// Shared state for AI dependency analysis (G-UI, owned by Yousuf's Gemini).
// Persists the latest DependencyJob, polling loop, analysed portfolio key, and selected
// evidence edge across page navigation (#/dependencies <-> #/exposures, etc.), whether
// <DependenciesProvider> is mounted at the app root or inside DependenciesPage.
//
// Resilient polling:
// - Survives backend restarts during polling: on network errors or HTTP 502/503/504,
//   keeps polling with backoff for up to ~30 s and sets `reconnecting: true`.
// - On HTTP 404 / JOB_NOT_FOUND (in-memory job table cleared by a backend restart),
//   automatically re-POSTs `api.dependencies` once (idempotent job_id; cached companies replay fast).

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { api, ApiError, type AllocationInput } from "@/api/client";
import {
  DEFAULT_TOP_N,
  type AnalysisResponse,
  type DependencyJob,
} from "@/api/types";
import { useAnalysis } from "./analysis";
import { targetNodeIdForEdge } from "./pages/dependencies/graph";

export const POLL_INTERVAL_MS = 1200;
export const RECONNECT_WINDOW_MS = 30_000;

export type DependenciesRunStatus = "idle" | "starting" | "polling" | "done" | "error";

export interface DependenciesSnapshot {
  status: DependenciesRunStatus;
  job: DependencyJob | null;
  /** The `analysedKey` of the portfolio when the dependency run was triggered. */
  depsKey: string | null;
  topN: number;
  /** True while retrying after a transient 502/503/504/network error or 404 re-POST. */
  reconnecting: boolean;
  error: ApiError | null;
  selectedEdgeId: string | null;
  selectedNodeId: string | null;
  drawerOpen: boolean;
}

export interface DependenciesContextValue extends DependenciesSnapshot {
  /** True when the portfolio has changed since the current dependency run. */
  stale: boolean;
  /** Starts or re-runs dependency analysis for the current `analysis` holdings. */
  runDependencies: (topN?: number) => void;
  /** Selects a verified edge (and optionally opens the evidence drawer). */
  selectEdge: (edgeId: string | null, openDrawer?: boolean) => void;
  /** Selects a graph node (company or counterparty/target) to inspect its edges. */
  selectNode: (nodeId: string | null, openDrawer?: boolean) => void;
  /** Opens or closes the evidence drawer. */
  setDrawerOpen: (open: boolean) => void;
}

// ---------- Module-scoped store so state survives tab switches even if unmounted ----------

let storeState: DependenciesSnapshot = {
  status: "idle",
  job: null,
  depsKey: null,
  topN: DEFAULT_TOP_N,
  reconnecting: false,
  error: null,
  selectedEdgeId: null,
  selectedNodeId: null,
  drawerOpen: false,
};

interface RunContext {
  runId: number;
  rows: AllocationInput[];
  topN: number;
  transientSince: number | null;
  transientAttempts: number;
  repostedAfter404: boolean;
}

let activeRun: RunContext | null = null;
let activeController: AbortController | null = null;
let pollTimer: number | null = null;
const listeners = new Set<() => void>();

function emitChange() {
  for (const listener of listeners) {
    listener();
  }
}

function setStoreState(patch: Partial<DependenciesSnapshot>) {
  storeState = { ...storeState, ...patch };
  emitChange();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): DependenciesSnapshot {
  return storeState;
}

function stopActivePolling() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
  if (activeController !== null) {
    activeController.abort();
    activeController = null;
  }
}

function isTransientError(cause: unknown): boolean {
  if (!(cause instanceof ApiError)) return false;
  return (
    cause.code === "NETWORK_ERROR" ||
    cause.status === 0 ||
    cause.status === 502 ||
    cause.status === 503 ||
    cause.status === 504
  );
}

function isJobNotFoundError(cause: unknown): boolean {
  if (!(cause instanceof ApiError)) return false;
  return cause.code === "JOB_NOT_FOUND" || cause.status === 404;
}

function backoffDelayMs(attempts: number): number {
  return Math.min(5000, Math.round(1500 * Math.pow(1.4, Math.max(0, attempts))));
}

function postJobWithRecovery(run: RunContext) {
  if (activeRun?.runId !== run.runId) return;
  const controller = new AbortController();
  activeController = controller;

  api
    .dependencies(run.rows, run.topN, controller.signal)
    .then((job) => {
      if (activeRun?.runId !== run.runId) return;
      run.transientSince = null;
      run.transientAttempts = 0;
      handleJobUpdate(run, job);
    })
    .catch((cause: unknown) => {
      if (activeRun?.runId !== run.runId) return;
      if (cause instanceof DOMException && cause.name === "AbortError") return;

      if (isTransientError(cause)) {
        const now = Date.now();
        if (run.transientSince === null) run.transientSince = now;
        if (now - run.transientSince < RECONNECT_WINDOW_MS) {
          const delay = backoffDelayMs(run.transientAttempts++);
          setStoreState({ reconnecting: true, error: null });
          pollTimer = window.setTimeout(() => postJobWithRecovery(run), delay);
          return;
        }
      }

      const apiErr =
        cause instanceof ApiError
          ? cause
          : new ApiError(
              "UNEXPECTED_ERROR",
              cause instanceof Error ? cause.message : "Could not start dependency analysis.",
              0,
            );
      setStoreState({ status: "error", reconnecting: false, error: apiErr });
    });
}

function scheduleNextPoll(run: RunContext, jobId: string, delayMs: number) {
  if (activeRun?.runId !== run.runId) return;
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
  }
  pollTimer = window.setTimeout(async () => {
    if (activeRun?.runId !== run.runId) return;
    const controller = new AbortController();
    activeController = controller;
    try {
      const updated = await api.dependencyJob(jobId, controller.signal);
      if (activeRun?.runId !== run.runId) return;
      run.transientSince = null;
      run.transientAttempts = 0;
      handleJobUpdate(run, updated);
    } catch (cause) {
      if (activeRun?.runId !== run.runId) return;
      if (cause instanceof DOMException && cause.name === "AbortError") return;

      // 404 JOB_NOT_FOUND after a backend restart: re-POST once (idempotent job_id; cached companies replay fast)
      if (isJobNotFoundError(cause) && !run.repostedAfter404) {
        run.repostedAfter404 = true;
        run.transientSince = null;
        run.transientAttempts = 0;
        setStoreState({ status: "polling", reconnecting: true, error: null });
        postJobWithRecovery(run);
        return;
      }

      // Network error or 502/503/504 during backend restart: keep polling with backoff for up to ~30 s
      if (isTransientError(cause)) {
        const now = Date.now();
        if (run.transientSince === null) run.transientSince = now;
        if (now - run.transientSince < RECONNECT_WINDOW_MS) {
          const nextDelay = backoffDelayMs(run.transientAttempts++);
          setStoreState({ status: "polling", reconnecting: true, error: null });
          scheduleNextPoll(run, jobId, nextDelay);
          return;
        }
      }

      const apiErr =
        cause instanceof ApiError
          ? cause
          : new ApiError(
              "UNEXPECTED_ERROR",
              cause instanceof Error ? cause.message : "Failed while polling dependency status.",
              0,
            );
      setStoreState({ status: "error", reconnecting: false, error: apiErr });
    }
  }, delayMs);
}

function handleJobUpdate(run: RunContext, job: DependencyJob) {
  if (activeRun?.runId !== run.runId) return;

  if (job.status === "done") {
    stopActivePolling();
    const keepEdge =
      storeState.selectedEdgeId &&
      job.result?.edges.some((e) => e.edge_id === storeState.selectedEdgeId)
        ? storeState.selectedEdgeId
        : null;
    setStoreState({
      status: "done",
      job,
      reconnecting: false,
      error: null,
      selectedEdgeId: keepEdge,
    });
    return;
  }

  if (job.status === "error") {
    stopActivePolling();
    const err = job.error
      ? new ApiError(job.error.code, job.error.message, 500, job.error.details)
      : new ApiError("DEPENDENCY_JOB_ERROR", "Dependency extraction failed.", 500);
    setStoreState({
      status: "error",
      job,
      reconnecting: false,
      error: err,
    });
    return;
  }

  // Still queued or running -> schedule next poll
  setStoreState({
    status: "polling",
    job,
    reconnecting: false,
    error: null,
  });

  scheduleNextPoll(run, job.job_id, POLL_INTERVAL_MS);
}

function holdingsToAllocationInputs(analysis: AnalysisResponse): AllocationInput[] {
  return analysis.request.holdings.map((item) => ({
    ticker: item.ticker,
    allocationPct: item.allocation * 100,
  }));
}

let nextRunSeq = 0;

export function triggerDependenciesRun(
  analysis: AnalysisResponse,
  analysedKey: string | null,
  topN = DEFAULT_TOP_N,
) {
  stopActivePolling();
  const rows = holdingsToAllocationInputs(analysis);
  const run: RunContext = {
    runId: ++nextRunSeq,
    rows,
    topN,
    transientSince: null,
    transientAttempts: 0,
    repostedAfter404: false,
  };
  activeRun = run;

  setStoreState({
    status: "starting",
    depsKey: analysedKey,
    topN,
    reconnecting: false,
    error: null,
  });

  postJobWithRecovery(run);
}

// ---------- React Context + Hook ----------

const DependenciesContext = createContext<DependenciesContextValue | null>(null);

function useDependenciesInternal(): DependenciesContextValue {
  const { analysis, analysedKey, stale: analysisStale } = useAnalysis();
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  // Clean up polling only on full window unload
  useEffect(() => {
    const onUnload = () => stopActivePolling();
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, []);

  const runDependencies = useCallback(
    (topN = snapshot.topN || DEFAULT_TOP_N) => {
      if (!analysis) return;
      triggerDependenciesRun(analysis, analysedKey, topN);
    },
    [analysis, analysedKey, snapshot.topN],
  );

  const selectEdge = useCallback((edgeId: string | null, openDrawer = true) => {
    setStoreState({
      selectedEdgeId: edgeId,
      drawerOpen: edgeId !== null ? openDrawer : false,
    });
  }, []);

  const selectNode = useCallback((nodeId: string | null, openDrawer = false) => {
    if (nodeId === null) {
      setStoreState({ selectedNodeId: null, selectedEdgeId: null });
      return;
    }
    const nextNodeId = storeState.selectedNodeId === nodeId ? null : nodeId;
    if (!openDrawer) {
      setStoreState({
        selectedNodeId: nextNodeId,
        selectedEdgeId: null,
      });
      return;
    }
    const edges = storeState.job?.result?.edges ?? [];
    const matchingEdge = edges.find(
      (e) =>
        e.source_company_key === nodeId ||
        (e.target_in_portfolio && e.target_key === nodeId) ||
        targetNodeIdForEdge(e) === nodeId,
    );
    setStoreState({
      selectedNodeId: nextNodeId,
      selectedEdgeId: matchingEdge ? matchingEdge.edge_id : null,
      drawerOpen: !!matchingEdge,
    });
  }, []);

  const setDrawerOpen = useCallback((open: boolean) => {
    setStoreState({ drawerOpen: open });
  }, []);

  const stale =
    snapshot.job !== null &&
    (analysisStale ||
      (snapshot.depsKey !== null && analysedKey !== null && snapshot.depsKey !== analysedKey));

  return useMemo<DependenciesContextValue>(
    () => ({
      ...snapshot,
      stale,
      runDependencies,
      selectEdge,
      selectNode,
      setDrawerOpen,
    }),
    [snapshot, stale, runDependencies, selectEdge, selectNode, setDrawerOpen],
  );
}

export function DependenciesProvider({ children }: { children: ReactNode }) {
  const value = useDependenciesInternal();
  return <DependenciesContext.Provider value={value}>{children}</DependenciesContext.Provider>;
}

/**
 * Reads the shared dependency analysis state. Works both inside <DependenciesProvider>
 * and standalone (backed by the same module store so state survives page switches).
 */
export function useDependencies(): DependenciesContextValue {
  const ctx = useContext(DependenciesContext);
  const fallback = useDependenciesInternal();
  return ctx ?? fallback;
}
