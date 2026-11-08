"use client";
// Shared state for AI dependency analysis (G-UI, owned by Yousuf's Gemini).
// Persists the latest DependencyJob, polling loop, analysed portfolio key, and selected
// evidence edge across page navigation (#/dependencies <-> #/exposures, etc.), whether
// <DependenciesProvider> is mounted at the app root or inside DependenciesPage.

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

export const POLL_INTERVAL_MS = 1200;

export type DependenciesRunStatus = "idle" | "starting" | "polling" | "done" | "error";

export interface DependenciesSnapshot {
  status: DependenciesRunStatus;
  job: DependencyJob | null;
  /** The `analysedKey` of the portfolio when the dependency run was triggered. */
  depsKey: string | null;
  topN: number;
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
  error: null,
  selectedEdgeId: null,
  selectedNodeId: null,
  drawerOpen: false,
};

let activeRunId = 0;
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

function handleJobUpdate(runId: number, job: DependencyJob) {
  if (runId !== activeRunId) return;

  if (job.status === "done") {
    stopActivePolling();
    const firstEdge = job.result?.edges[0]?.edge_id ?? null;
    const keepEdge =
      storeState.selectedEdgeId &&
      job.result?.edges.some((e) => e.edge_id === storeState.selectedEdgeId)
        ? storeState.selectedEdgeId
        : firstEdge;
    setStoreState({
      status: "done",
      job,
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
      error: err,
    });
    return;
  }

  // Still queued or running -> schedule next poll
  setStoreState({
    status: "polling",
    job,
    error: null,
  });

  pollTimer = window.setTimeout(async () => {
    if (runId !== activeRunId) return;
    const controller = new AbortController();
    activeController = controller;
    try {
      const updated = await api.dependencyJob(job.job_id, controller.signal);
      handleJobUpdate(runId, updated);
    } catch (cause) {
      if (runId !== activeRunId) return;
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      const apiErr =
        cause instanceof ApiError
          ? cause
          : new ApiError(
              "UNEXPECTED_ERROR",
              cause instanceof Error ? cause.message : "Failed while polling dependency status.",
              0,
            );
      setStoreState({ status: "error", error: apiErr });
    }
  }, POLL_INTERVAL_MS);
}

function holdingsToAllocationInputs(analysis: AnalysisResponse): AllocationInput[] {
  return analysis.request.holdings.map((item) => ({
    ticker: item.ticker,
    allocationPct: item.allocation * 100,
  }));
}

export function triggerDependenciesRun(
  analysis: AnalysisResponse,
  analysedKey: string | null,
  topN = DEFAULT_TOP_N,
) {
  stopActivePolling();
  const runId = ++activeRunId;
  const controller = new AbortController();
  activeController = controller;

  const rows = holdingsToAllocationInputs(analysis);
  setStoreState({
    status: "starting",
    depsKey: analysedKey,
    topN,
    error: null,
  });

  api
    .dependencies(rows, topN, controller.signal)
    .then((job) => {
      handleJobUpdate(runId, job);
    })
    .catch((cause: unknown) => {
      if (runId !== activeRunId) return;
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      const apiErr =
        cause instanceof ApiError
          ? cause
          : new ApiError(
              "UNEXPECTED_ERROR",
              cause instanceof Error ? cause.message : "Could not start dependency analysis.",
              0,
            );
      setStoreState({ status: "error", error: apiErr });
    });
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
      setStoreState({ selectedNodeId: null });
      return;
    }
    const edges = storeState.job?.result?.edges ?? [];
    const matchingEdge = edges.find(
      (e) =>
        e.source_company_key === nodeId ||
        (e.target_key
          ? `TARGET_KEY:${e.target_key}`
          : `TARGET:${e.target_kind}:${e.target_name.trim().toUpperCase()}`) === nodeId,
    );
    setStoreState({
      selectedNodeId: storeState.selectedNodeId === nodeId ? null : nodeId,
      selectedEdgeId: matchingEdge ? matchingEdge.edge_id : storeState.selectedEdgeId,
      drawerOpen: openDrawer && !!matchingEdge ? true : storeState.drawerOpen,
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
