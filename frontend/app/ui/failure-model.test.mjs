import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import {
  countryOptions,
  formatDollars,
  lossDifference,
  moneyRow,
  NOTIONAL_DOLLARS,
  parseShockHash,
  portfolioValue,
  sectorOptions,
  tidyNotes,
} from "./failure-model.ts";

const fixture = (name) =>
  JSON.parse(fs.readFileSync(new URL(`../../api/__fixtures__/${name}`, import.meta.url), "utf8"));

const company = (company_key, sector, country, exposure) => ({ company_key, sector, country, exposure });

test("sectorOptions uses the fund-reported totals, drops unknown and zero, largest first", () => {
  const options = sectorOptions({
    sectors: [
      { sector: "financials", weight: 0.2 },
      { sector: "unknown", weight: 0.3 },
      { sector: "information_technology", weight: 0.45 },
      { sector: "energy", weight: 0 },
    ],
    exposures: [company("A", "energy", "US", 0.5)],
  });
  assert.deepEqual(
    options.map((o) => [o.key, o.label, o.weight]),
    [
      ["information_technology", "Information Technology", 0.45],
      ["financials", "Financials", 0.2],
    ],
  );
});

test("sectorOptions sums companies when the analysis has no sector totals", () => {
  const options = sectorOptions({
    sectors: [],
    exposures: [
      company("A", "energy", null, 0.1),
      company("B", "health_care", null, 0.3),
      company("C", "energy", null, 0.25),
      company("D", "unknown", null, 0.35),
    ],
  });
  assert.deepEqual(options.map((o) => o.key), ["energy", "health_care"]);
  assert.ok(Math.abs(options[0].weight - 0.35) < 1e-12);
  assert.deepEqual(sectorOptions(null), []);
});

test("countryOptions groups by upper-cased code and reports the unknown weight", () => {
  const { options, unknownWeight } = countryOptions({
    exposures: [
      company("A", "energy", "us", 0.4),
      company("B", "energy", "TW", 0.1),
      company("C", "energy", " US ", 0.2),
      company("D", "energy", null, 0.25),
      company("E", "energy", "", 0.05),
      company("F", "energy", "JP", 0),
    ],
  });
  assert.deepEqual(options.map((o) => o.key), ["US", "TW"]);
  assert.ok(Math.abs(options[0].weight - 0.6) < 1e-12);
  assert.ok(Math.abs(unknownWeight - 0.3) < 1e-12);
  assert.equal(options[1].label, "Taiwan");
});

test("portfolioValue: shares mode only, pinned % rows scale the priced total up", () => {
  assert.equal(portfolioValue("percent", { total_value: 9817.68, pinned_total: 0 }), null);
  assert.equal(portfolioValue("shares", null), null);
  assert.equal(portfolioValue("shares", { total_value: 0, pinned_total: 0 }), null);
  assert.equal(portfolioValue("shares", { total_value: 9817.68, pinned_total: 0 }), 9817.68);
  assert.equal(portfolioValue("shares", { total_value: 7500, pinned_total: 0.25 }), 10000);
});

test("moneyRow reproduces the live IT shock: $9,817.68 -> $8,845.63", () => {
  const live = fixture("stress-it.json");
  const row = moneyRow(9817.68, 0.099010);
  assert.equal(formatDollars(row.before), "$9,818");
  assert.equal(formatDollars(row.after), "$8,846");
  assert.equal(formatDollars(row.loss), "$972");
  assert.ok(Math.abs(row.after - 8845.63) < 0.01);
  // % mode: the same fraction on the notional $10,000.
  const notional = moneyRow(NOTIONAL_DOLLARS, live.baseline.loss_fraction);
  assert.equal(notional.before, 10000);
  assert.ok(Math.abs(notional.after - 10000 * (1 - live.baseline.loss_fraction)) < 1e-9);
  // Out-of-range fractions are clamped.
  assert.equal(moneyRow(100, 1.5).after, 0);
  assert.equal(moneyRow(100, -0.1).loss, 0);
});

test("lossDifference compares whole dollars, as shown", () => {
  assert.deepEqual(lossDifference(972.05, 734.2), { tone: "better", text: "loses $238 less" });
  assert.deepEqual(lossDifference(500, 612.4), { tone: "worse", text: "loses $112 more" });
  assert.deepEqual(lossDifference(500.2, 499.9), { tone: "same", text: "same loss" });
  assert.equal(formatDollars(1234567.4), "$1,234,567");
});

test("tidyNotes dedupes both sides, drops lines under 1%, folds the rest", () => {
  const { shown, folded } = tidyNotes(fixture("stress-it.json").notes);
  assert.deepEqual(shown, ["8.36% of the portfolio has an unknown industry."]);
  assert.deepEqual(folded, [
    "Coverage is incomplete, so the loss may be understated.",
    "Industry totals come from the funds' own reports; the companies listed are the ones we can name.",
  ]);
});

test("tidyNotes keeps the country caveat visible", () => {
  const { shown, folded } = tidyNotes(fixture("stress-tw.json").notes);
  assert.deepEqual(shown, ["We don't know the country for 80.04% of the portfolio, so it isn't counted."]);
  assert.deepEqual(folded, ["Coverage is incomplete, so the loss may be understated."]);
  assert.deepEqual(tidyNotes([]), { shown: [], folded: [] });
});

test("parseShockHash reads ?shock=<kind>:<key> from the Compare hash", () => {
  assert.deepEqual(parseShockHash("#/compare?shock=sector:information_technology"), {
    kind: "sector",
    key: "information_technology",
  });
  assert.deepEqual(parseShockHash("#/compare?shock=country:tw"), { kind: "country", key: "TW" });
  assert.deepEqual(parseShockHash("#/compare?x=1&shock=supplier:ALIAS:TSMC"), { kind: "supplier", key: "ALIAS:TSMC" });
  assert.deepEqual(parseShockHash("#/compare?shock=supplier%3ACIK%3A0001045810"), {
    kind: "supplier",
    key: "CIK:0001045810",
  });
  for (const bad of ["#/compare", "#/compare?shock=", "#/compare?shock=sector", "#/compare?shock=planet:mars", "#/compare?shock=sector:"]) {
    assert.equal(parseShockHash(bad), null, bad);
  }
});

test("both sides start from the same amount, so the comparison is on equal pots", () => {
  const live = fixture("stress-it.json");
  const before = 9817.68;
  const base = moneyRow(before, live.baseline.loss_fraction);
  const cand = moneyRow(before, live.candidate.loss_fraction);
  assert.equal(formatDollars(base.loss), "$972");
  assert.equal(formatDollars(cand.loss), "$743");
  assert.deepEqual(lossDifference(base.loss, cand.loss), { tone: "better", text: "loses $229 less" });
  // A smaller fraction always reads as "less" on the same pot, even if the new mix's own value is bigger.
  const biggerOwnPot = moneyRow(before * 1.4, live.candidate.loss_fraction);
  assert.equal(lossDifference(base.loss, biggerOwnPot.loss).tone, "worse");
  assert.equal(lossDifference(base.loss, cand.loss).tone, "better");
});
