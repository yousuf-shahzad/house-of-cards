import assert from "node:assert/strict";
import test from "node:test";
import {
  formatFindingOneLiner,
  monotonicProgressPct,
  pickMostOverlappingPair,
  shouldExpandOnKeyChange,
  splitFirstSentence,
} from "./sentence.ts";

test("splitFirstSentence does not split on Co., Ltd.", () => {
  const input =
    "Taiwan Semiconductor Manufacturing Co., Ltd. (4 companies: NVDA, AAPL, AVGO, AMD) is a critical single-source foundry. A disruption in Taiwan would halt chip production across your top holdings.";
  const [first, rest] = splitFirstSentence(input);
  assert.equal(
    first,
    "Taiwan Semiconductor Manufacturing Co., Ltd. (4 companies: NVDA, AAPL, AVGO, AMD) is a critical single-source foundry.",
  );
  assert.equal(
    rest,
    "A disruption in Taiwan would halt chip production across your top holdings.",
  );
});

test("splitFirstSentence does not split on Inc.", () => {
  const input =
    "Apple Inc. and Broadcom Inc. depend heavily on overseas assembly. Shifting capacity would take years.";
  const [first, rest] = splitFirstSentence(input);
  assert.equal(
    first,
    "Apple Inc. and Broadcom Inc. depend heavily on overseas assembly.",
  );
  assert.equal(rest, "Shifting capacity would take years.");
});

test("splitFirstSentence does not split on U.S. or No.", () => {
  const input =
    "Under U.S. export controls, Plant No. 12 faces stricter licensing rules. Second sentence explains the portfolio impact.";
  const [first, rest] = splitFirstSentence(input);
  assert.equal(
    first,
    "Under U.S. export controls, Plant No. 12 faces stricter licensing rules.",
  );
  assert.equal(rest, "Second sentence explains the portfolio impact.");
});

test("splitFirstSentence returns single sentence unchanged when no second sentence exists", () => {
  const input =
    "12% of your money depends on Taiwan Semiconductor Manufacturing Co., Ltd.";
  const [first, rest] = splitFirstSentence(input);
  assert.equal(first, input);
  assert.equal(rest, "");
});

test("pickMostOverlappingPair picks the highest weighted_overlap instead of pairs[0] (FIX-16)", () => {
  const pairs = [
    { etf_a: "IVV", etf_b: "QQQ", weighted_overlap: 0.4882, shared_companies: 89 },
    { etf_a: "IVV", etf_b: "XLK", weighted_overlap: 0.3412, shared_companies: 68 },
    { etf_a: "QQQ", etf_b: "XLK", weighted_overlap: 0.5011, shared_companies: 43 },
    { etf_a: "IVV", etf_b: "EEM", weighted_overlap: 0.0, shared_companies: 0 },
  ];
  const best = pickMostOverlappingPair(pairs);
  assert.deepEqual(best, {
    etf_a: "QQQ",
    etf_b: "XLK",
    weighted_overlap: 0.5011,
    shared_companies: 43,
  });
  assert.equal(pickMostOverlappingPair([]), null);
});

test("monotonicProgressPct never decreases for the same running job_id and resets on a new or restarted job_id (FIX-18 + FIX-19)", () => {
  let state = monotonicProgressPct(null, 0, "job_1", (15 / 16) * 100, null, "running");
  assert.equal(state.jobId, "job_1");
  assert.equal(state.pct, 94);

  // When steps_total grows (e.g. 16 -> 50), percentage must not drop for job_1
  state = monotonicProgressPct(state.jobId, state.pct, "job_1", (15 / 50) * 100, state.status, "running");
  assert.equal(state.pct, 94);

  // Rises normally when raw percentage exceeds previous max
  state = monotonicProgressPct(state.jobId, state.pct, "job_1", (49 / 50) * 100, state.status, "running");
  assert.equal(state.pct, 98);

  // FIX-19 guard: Still-running job reaching 100% (e.g. 15/15) must stay at 100% if total grows (15/30)
  state = monotonicProgressPct(state.jobId, state.pct, "job_1", (15 / 15) * 100, state.status, "running");
  assert.equal(state.pct, 100);
  assert.equal(state.status, "running");
  state = monotonicProgressPct(state.jobId, state.pct, "job_1", (15 / 30) * 100, state.status, "running");
  assert.equal(state.pct, 100);
  assert.equal(state.status, "running");

  // Finishes at 100% when status is done
  state = monotonicProgressPct(state.jobId, state.pct, "job_1", 100, state.status, "done");
  assert.equal(state.pct, 100);
  assert.equal(state.status, "done");

  // FIX-19: Reused job_id transitioning from done -> running resets to the new run's percentage
  state = monotonicProgressPct(state.jobId, state.pct, "job_1", 0, state.status, "running");
  assert.equal(state.jobId, "job_1");
  assert.equal(state.pct, 0);
  assert.equal(state.status, "running");

  // Resets when a new job_id starts
  state = monotonicProgressPct(state.jobId, state.pct, "job_2", 10, state.status, "running");
  assert.equal(state.jobId, "job_2");
  assert.equal(state.pct, 10);
});

test("shouldExpandOnKeyChange expands only when expandKey changes to a non-null selection (FIX-27)", () => {
  // Initial mount with null or pre-existing selection in app-level store does not force-expand
  let step = shouldExpandOnKeyChange(null, null);
  assert.equal(step.shouldExpand, false);
  step = shouldExpandOnKeyChange("NODE_NVDA", "NODE_NVDA");
  assert.equal(step.shouldExpand, false);

  // Selecting a node or edge unfolds the Graph section
  step = shouldExpandOnKeyChange(null, "NODE_NVDA");
  assert.equal(step.shouldExpand, true);
  assert.equal(step.prevKey, "NODE_NVDA");

  // Clicking "Show less" while NODE_NVDA is still selected must NOT re-expand
  step = shouldExpandOnKeyChange(step.prevKey, "NODE_NVDA");
  assert.equal(step.shouldExpand, false);

  // Selecting a different node or edge unfolds again
  step = shouldExpandOnKeyChange(step.prevKey, "EDGE_NVDA_TSMC");
  assert.equal(step.shouldExpand, true);
  assert.equal(step.prevKey, "EDGE_NVDA_TSMC");

  // Clearing selection does not expand
  step = shouldExpandOnKeyChange(step.prevKey, null);
  assert.equal(step.shouldExpand, false);
  assert.equal(step.prevKey, null);
});

test("formatFindingOneLiner produces one concise plain-English line per finding (FIX-29)", () => {
  assert.equal(
    formatFindingOneLiner("Apple Inc. → Japan (facility)", "confirmed"),
    "Checked: Apple's reliance on Japan — confirmed",
  );
  assert.equal(
    formatFindingOneLiner(
      "NVIDIA Corp. → Taiwan Semiconductor Manufacturing Co., Ltd. (foundry)",
      "confirmed",
    ),
    "Checked: NVIDIA's reliance on Taiwan Semiconductor Manufacturing — confirmed",
  );
  assert.equal(
    formatFindingOneLiner("Advanced Micro Devices, Inc. → Sanmina Corp.", "rejected"),
    "Checked: Advanced Micro Devices' reliance on Sanmina — ruled out",
  );
  assert.equal(
    formatFindingOneLiner(
      "Broadcom Inc. — undisclosed major customer",
      "unresolved",
      "Not finished in time: step budget reached after 3 lookups.",
    ),
    "Checked: Broadcom (undisclosed major customer) — not finished in time",
  );
  assert.equal(
    formatFindingOneLiner("Nvidia -> OpenAI (jv_partner)", "unresolved"),
    "Checked: Nvidia's partnership with OpenAI — still unclear",
  );
  assert.equal(
    formatFindingOneLiner("Broadcom -> Apple Inc. (customer)", "confirmed"),
    "Checked: Broadcom's sales to Apple — confirmed",
  );
  assert.equal(
    formatFindingOneLiner("Qualcomm Inc. -> Arm Ltd. (licensing)", "revised"),
    "Checked: Qualcomm's licensing with Arm — updated",
  );
  assert.equal(
    formatFindingOneLiner("Apple Inc. single-source reliance on Japan", "confirmed"),
    "Checked: Apple's reliance on Japan — confirmed",
  );
});
