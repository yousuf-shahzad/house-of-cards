import assert from "node:assert/strict";
import test from "node:test";

import { formatElapsed, scanActivity, scanBarIndeterminate, shortCompanyName } from "./scan-activity.ts";

const company = (company_name, status, exposure) => ({
  company_key: `KEY:${company_name}`,
  company_name,
  exposure,
  status,
  extraction_quality: null,
  filing: null,
  verified_edges: 0,
  rejected_edges: 0,
  message: null,
});

const job = (overrides) => ({
  job_id: "job-1",
  status: "running",
  progress_done: 0,
  progress_total: 15,
  phase: "reading",
  steps_done: 0,
  steps_total: 20,
  companies: [],
  result: null,
  error: null,
  research: [],
  ...overrides,
});

test("before a job exists: only while starting", () => {
  assert.deepEqual(scanActivity(null, true), { now: "Starting the scan…", count: null });
  assert.deepEqual(scanActivity(null), { now: null, count: null });
  assert.deepEqual(scanActivity(job({ status: "queued", phase: "queued" })), {
    now: "Getting ready to read the annual reports…",
    count: null,
  });
});

test("reading: names the biggest company being read, then fetched, and counts finished ones", () => {
  const companies = [
    company("Microsoft Corporation", "fetching", 0.07),
    company("Apple Inc.", "extracting", 0.06),
    company("NVIDIA Corporation", "extracting", 0.08),
    company("Amazon.com, Inc.", "done", 0.04),
    company("Meta Platforms, Inc. Class A", "cached", 0.03),
    company("Berkshire Hathaway Inc. Class B", "no_sec_filing", 0.02),
    company("Alphabet Inc. Class C", "queued", 0.02),
  ];
  assert.deepEqual(scanActivity(job({ companies })), {
    now: "Reading NVIDIA's annual report and 2 more…",
    count: "Read 3 of 7 companies",
  });
  const onlyFetching = [company("Microsoft Corporation", "fetching", 0.07), company("Apple Inc.", "queued", 0.06)];
  assert.deepEqual(scanActivity(job({ companies: onlyFetching })), {
    now: "Fetching Microsoft's annual report…",
    count: "Read 0 of 2 companies",
  });
  const waiting = [company("Apple Inc.", "done", 0.06), company("Tesla, Inc.", "queued", 0.02)];
  assert.equal(scanActivity(job({ companies: waiting })).now, "Waiting for the next annual report…");
});

test("researching and synthesising phases", () => {
  const companies = [
    company("Apple Inc.", "researching", 0.06),
    company("Broadcom Inc.", "researching", 0.03),
    company("Tesla, Inc.", "done", 0.02),
  ];
  assert.deepEqual(scanActivity(job({ phase: "researching", companies })), {
    now: "Double-checking Apple's findings and 1 more…",
    count: "Read 3 of 3 companies",
  });
  assert.equal(
    scanActivity(job({ phase: "researching", companies: [company("Tesla, Inc.", "done", 0.02)] })).now,
    "Double-checking the findings…",
  );
  assert.equal(scanActivity(job({ phase: "synthesising", companies })).now, "Putting the results together…");
});

test("finished jobs have no 'now' line", () => {
  const companies = [company("Apple Inc.", "done", 0.06)];
  assert.deepEqual(scanActivity(job({ status: "done", phase: "done", companies })), {
    now: null,
    count: "Read 1 of 1 company",
  });
  assert.equal(scanActivity(job({ status: "error", companies })).now, null);
});

test("shortCompanyName and possessives", () => {
  assert.equal(shortCompanyName("Apple Inc."), "Apple");
  assert.equal(shortCompanyName("Taiwan Semiconductor Manufacturing Co., Ltd."), "Taiwan Semiconductor Manufacturing");
  assert.equal(shortCompanyName("Alphabet Inc. Class A"), "Alphabet");
  assert.equal(shortCompanyName("Inc."), "Inc.");
  const companies = [company("Costco Wholesale Corp", "extracting", 0.01), company("Visa Inc.", "extracting", 0.02)];
  assert.equal(scanActivity(job({ companies })).now, "Reading Visa's annual report and 1 more…");
  assert.equal(
    scanActivity(job({ companies: [company("Adobe Systems", "extracting", 0.01)] })).now,
    "Reading Adobe Systems' annual report…",
  );
});

test("scanBarIndeterminate: sweeps only while running at 0%", () => {
  assert.equal(scanBarIndeterminate(null, 0, true), true);
  assert.equal(scanBarIndeterminate(job({ status: "queued" }), 0), true);
  assert.equal(scanBarIndeterminate(job({}), 0), true);
  assert.equal(scanBarIndeterminate(job({}), 4), false);
  assert.equal(scanBarIndeterminate(job({ status: "done" }), 0), false);
  assert.equal(scanBarIndeterminate(null, 0), false);
});

test("formatElapsed", () => {
  assert.equal(formatElapsed(0), "0 s");
  assert.equal(formatElapsed(12_400), "12 s");
  assert.equal(formatElapsed(65_000), "1 min 05 s");
  assert.equal(formatElapsed(-5), "0 s");
});
