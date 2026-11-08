import assert from "node:assert/strict";
import test from "node:test";

import { largestCountryShock, largestIndustryShock } from "./shocks.ts";

test("largestIndustryShock picks the largest non-unknown sector and formats #/compare?shock=sector:<key>", () => {
  const sectors = [
    { sector: "unknown", weight: 0.6, by_etf: [] },
    { sector: "financials", weight: 0.14, by_etf: [] },
    { sector: "information_technology", weight: 0.5112, by_etf: [] },
  ];

  assert.deepEqual(largestIndustryShock(sectors), {
    key: "information_technology",
    label: "Information Technology",
    weight: 0.5112,
    href: "#/compare?shock=sector:information_technology",
  });
});

test("largestIndustryShock returns null when only unknown or zero-weight sectors exist", () => {
  assert.equal(largestIndustryShock([]), null);
  assert.equal(largestIndustryShock([{ sector: "unknown", weight: 1, by_etf: [] }]), null);
});

test("largestCountryShock aggregates known ISO-2 countries, ignores null countries, and builds #/compare?shock=country:<code>", () => {
  const exposures = [
    { company_key: "CIK:1", company_name: "Apple", exposure: 0.08, country: null },
    { company_key: "CIK:2", company_name: "TSMC", exposure: 0.035, country: "tw" },
    { company_key: "CIK:3", company_name: "MediaTek", exposure: 0.0185, country: "TW" },
    { company_key: "CIK:4", company_name: "Samsung", exposure: 0.031, country: "KR" },
  ];

  assert.deepEqual(largestCountryShock(exposures), {
    code: "TW",
    label: "Taiwan",
    weight: 0.0535,
    companyCount: 2,
    unknownWeight: 0.9155,
    href: "#/compare?shock=country:TW",
  });
});

test("largestCountryShock returns null when no company has a known country", () => {
  assert.equal(
    largestCountryShock([{ company_key: "CIK:1", company_name: "Apple", exposure: 0.1, country: null }]),
    null,
  );
  assert.equal(largestCountryShock([]), null);
});
