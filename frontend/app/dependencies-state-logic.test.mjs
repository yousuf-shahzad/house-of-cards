import assert from "node:assert/strict";
import test from "node:test";
import { edgeSelectionPatch, restartedJob } from "./dependencies-state-logic.ts";

const finished = {
  job_id: "dep_1",
  status: "done",
  phase: "done",
  steps_done: 65,
  steps_total: 65,
  progress_done: 15,
  progress_total: 15,
  companies: [],
  result: { edges: [{ edge_id: "e1" }] },
  error: null,
  research: [{ finding_id: "f1" }],
};

test("restarting a scan resets the shown progress but keeps the result", () => {
  const job = restartedJob(finished);
  assert.equal(job.status, "queued");
  assert.equal(job.phase, "queued");
  assert.equal(job.steps_done, 0);
  assert.equal(job.steps_total, 0);
  assert.equal(job.progress_done, 0);
  assert.deepEqual(job.research, []);
  assert.equal(job.result, finished.result); // replaced in place when the new job is done
  assert.equal(finished.status, "done"); // the old object isn't mutated
});

test("restarting with nothing shown stays empty", () => {
  assert.equal(restartedJob(null), null);
});

test("selecting an edge clears the selected node", () => {
  assert.deepEqual(edgeSelectionPatch("e1", true), { selectedEdgeId: "e1", selectedNodeId: null, drawerOpen: true });
  assert.deepEqual(edgeSelectionPatch("e1", false), { selectedEdgeId: "e1", selectedNodeId: null, drawerOpen: false });
});

test("clearing the edge leaves the node selection alone and closes the drawer", () => {
  const patch = edgeSelectionPatch(null, true);
  assert.equal("selectedNodeId" in patch, false);
  assert.deepEqual(patch, { selectedEdgeId: null, drawerOpen: false });
});
