import assert from "node:assert/strict";
import test from "node:test";
import { guideAnalysisView, shouldStartAutoRun } from "./auto-run.ts";

const ready = (over = {}) => ({
  status: "ready",
  stale: false,
  hasAnalysis: true,
  analysedKey: "A",
  depsKey: null,
  depsStatus: "idle",
  pendingKey: null,
  ...over,
});

test("starts the first run for an analysed portfolio", () => {
  assert.equal(shouldStartAutoRun(ready()), true);
});

test("does not restart a portfolio that is running, done or failed", () => {
  for (const depsStatus of ["starting", "polling", "done", "error"]) {
    assert.equal(shouldStartAutoRun(ready({ depsKey: "A", depsStatus })), false, depsStatus);
  }
});

test("re-runs portfolio A after switching A -> B -> A (the store holds B)", () => {
  assert.equal(shouldStartAutoRun(ready({ analysedKey: "B", depsKey: "A", depsStatus: "done" })), true);
  assert.equal(shouldStartAutoRun(ready({ analysedKey: "A", depsKey: "B", depsStatus: "done" })), true);
  assert.equal(shouldStartAutoRun(ready({ analysedKey: "A", depsKey: "B", depsStatus: "polling" })), true);
});

test("does not start twice before the store reports the run", () => {
  assert.equal(shouldStartAutoRun(ready({ depsKey: "B", pendingKey: "A" })), false);
});

test("waits while the analysis is missing, stale or not ready", () => {
  assert.equal(shouldStartAutoRun(ready({ status: "loading" })), false);
  assert.equal(shouldStartAutoRun(ready({ status: "invalid", stale: true })), false);
  assert.equal(shouldStartAutoRun(ready({ hasAnalysis: false })), false);
  assert.equal(shouldStartAutoRun(ready({ analysedKey: null })), false);
});

test("guide steps never show an earlier portfolio as current", () => {
  const view = (over) => guideAnalysisView({ status: "ready", stale: false, hasAnalysis: true, hasError: false, ...over });
  assert.equal(view({}), "ready");
  assert.equal(view({ status: "loading", stale: true }), "loading");
  assert.equal(view({ status: "error", stale: true, hasError: true }), "error");
  assert.equal(view({ status: "error", hasAnalysis: false, hasError: true }), "error");
  assert.equal(view({ status: "invalid", stale: true }), "changed");
  assert.equal(view({ status: "invalid", hasAnalysis: false }), "empty");
});
