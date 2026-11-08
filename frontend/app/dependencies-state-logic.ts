// FIX-48: pure pieces of dependencies-state.tsx, kept here so `node --test` can check them without React.
import type { DependencyJob } from "@/api/types";

/** The shown job with its progress reset to "just queued". Its result stays, so Go deeper / Run again replace it
 * in place, but the bar no longer flashes 100% with every phase green before the new job's first poll. */
export function restartedJob(job: DependencyJob | null): DependencyJob | null {
  if (!job) return null;
  return { ...job, status: "queued", phase: "queued", steps_done: 0, steps_total: 0, progress_done: 0, research: [] };
}

/** Store patch for selecting an edge: an edge or citation click replaces an earlier node selection, so the
 * highlight and inline inspector follow the edge. Clearing the edge (null) leaves the node as it was. */
export function edgeSelectionPatch(
  edgeId: string | null,
  openDrawer: boolean,
): { selectedEdgeId: string | null; drawerOpen: boolean; selectedNodeId?: null } {
  return {
    selectedEdgeId: edgeId,
    ...(edgeId !== null ? { selectedNodeId: null } : {}),
    drawerOpen: edgeId !== null ? openDrawer : false,
  };
}
