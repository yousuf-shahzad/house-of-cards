import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

import { MAX_SUPPLIER_OPTIONS, supplierOptions } from "./failure-suppliers.ts";

const syntheticJob = JSON.parse(
  fs.readFileSync(new URL("../../api/__fixtures__/synthetic-dependencies.json", import.meta.url), "utf8"),
);

const BASE_FILING = {
  company_key: "CIK:0000320193",
  form: "10-K",
  accession: "0000320193-26-000001",
  filed: "2026-10-30",
  url: "https://example.invalid/10k",
};

function makeEdge(overrides) {
  return {
    edge_id: "e1",
    source_company_key: "CIK:0000320193",
    source_company_name: "Apple Inc.",
    source_in_portfolio: true,
    edge_type: "supplier",
    target_name: "Taiwan Semiconductor Manufacturing Co., Ltd.",
    target_kind: "company",
    target_key: "ALIAS:TSMC",
    target_in_portfolio: false,
    sole_source: false,
    qualifier: null,
    evidence_quote: "Sample quote.",
    section: "Item 1A",
    filing: BASE_FILING,
    importance: null,
    interpretation: null,
    ...overrides,
  };
}

test("extracts held supplier + dependents from synthetic-dependencies fixture", () => {
  const opts = supplierOptions(syntheticJob.result);
  assert.equal(opts.length, 1);
  assert.deepEqual(opts[0], {
    key: "ALIAS:ZZEPSILON",
    label: "ZZ Epsilon Semiconductor",
    companyKeys: ["CIK:9990000001", "CIK:9990000002", "ALIAS:ZZEPSILON"],
    weight: 0.58,
  });
});

test("filters to supplier/foundry/contract_manufacturer/key_input and deduplicates multiple edges per dependent", () => {
  const result = {
    ...syntheticJob.result,
    companies: [
      { company_key: "CIK:1", company_name: "Alpha", exposure: 0.2 },
      { company_key: "CIK:2", company_name: "Beta", exposure: 0.15 },
      { company_key: "CIK:3", company_name: "Gamma", exposure: 0.1 },
    ],
    edges: [
      // Two edges from CIK:1 to the same supplier must only count CIK:1 once
      makeEdge({
        edge_id: "e1",
        source_company_key: "CIK:1",
        edge_type: "foundry",
        target_key: "ALIAS:TSMC",
        target_name: "TSMC",
      }),
      makeEdge({
        edge_id: "e2",
        source_company_key: "CIK:1",
        edge_type: "supplier",
        target_key: "ALIAS:TSMC",
        target_name: "TSMC",
      }),
      makeEdge({
        edge_id: "e3",
        source_company_key: "CIK:2",
        edge_type: "contract_manufacturer",
        target_key: "ALIAS:FOXCONN",
        target_name: "Foxconn",
      }),
      makeEdge({
        edge_id: "e4",
        source_company_key: "CIK:3",
        edge_type: "key_input",
        target_key: null,
        target_name: "EUV Lithography Systems",
      }),
      // Excluded edge types: customer, facility, jv_partner
      makeEdge({
        edge_id: "e5",
        source_company_key: "CIK:1",
        edge_type: "customer",
        target_key: "ALIAS:CUST",
        target_name: "Big Customer",
      }),
      makeEdge({
        edge_id: "e6",
        source_company_key: "CIK:1",
        edge_type: "facility",
        target_key: "TW",
        target_name: "Taiwan",
      }),
      makeEdge({
        edge_id: "e7",
        source_company_key: "CIK:1",
        edge_type: "jv_partner",
        target_key: "ALIAS:JV",
        target_name: "JV Partner",
      }),
      // Rejected interpretation is ignored
      makeEdge({
        edge_id: "e8",
        source_company_key: "CIK:1",
        edge_type: "supplier",
        target_key: "ALIAS:REJECTED",
        target_name: "Rejected Co",
        interpretation: {
          status: "rejected",
          method: "rules",
          flags: ["negated"],
          reason: "Negated",
          model: null,
        },
      }),
    ],
  };

  const opts = supplierOptions(result);
  assert.deepEqual(opts, [
    {
      key: "ALIAS:TSMC",
      label: "TSMC",
      companyKeys: ["CIK:1"],
      weight: 0.2,
    },
    {
      key: "ALIAS:FOXCONN",
      label: "Foxconn",
      companyKeys: ["CIK:2"],
      weight: 0.15,
    },
    {
      key: "NAME:euv-lithography-systems",
      label: "EUV Lithography Systems",
      companyKeys: ["CIK:3"],
      weight: 0.1,
    },
  ]);
});

test("sorts by dependent weight descending and caps at top 15", () => {
  const companies = Array.from({ length: 20 }, (_, i) => ({
    company_key: `CIK:${String(i + 1).padStart(2, "0")}`,
    company_name: `Company ${i + 1}`,
    exposure: Number(((i + 1) * 0.01).toFixed(4)),
  }));
  const edges = companies.map((c, i) =>
    makeEdge({
      edge_id: `edge-${i + 1}`,
      source_company_key: c.company_key,
      source_company_name: c.company_name,
      target_key: `SUP:${String(i + 1).padStart(2, "0")}`,
      target_name: `Supplier ${i + 1}`,
    }),
  );

  const opts = supplierOptions({ ...syntheticJob.result, companies, edges });
  assert.equal(opts.length, MAX_SUPPLIER_OPTIONS);
  assert.equal(opts[0].key, "SUP:20");
  assert.equal(opts[0].weight, 0.2);
  assert.equal(opts[14].key, "SUP:06");
  assert.equal(opts[14].weight, 0.06);
});

test("returns empty list when result is null or has no qualifying edges", () => {
  assert.deepEqual(supplierOptions(null), []);
  assert.deepEqual(supplierOptions(undefined), []);
  assert.deepEqual(supplierOptions({ ...syntheticJob.result, edges: [] }), []);
});

test("only company targets become supplier options (no countries, regions, materials, facilities)", () => {
  const result = {
    ...syntheticJob.result,
    companies: [{ company_key: "CIK:0000320193", company_name: "Apple Inc.", exposure: 0.07 }],
    edges: [
      makeEdge({ edge_id: "c1" }),
      makeEdge({ edge_id: "x1", edge_type: "key_input", target_kind: "country", target_name: "China", target_key: null }),
      makeEdge({ edge_id: "x2", edge_type: "supplier", target_kind: "region", target_name: "Asia", target_key: null }),
      makeEdge({ edge_id: "x3", edge_type: "key_input", target_kind: "material", target_name: "Rare earths", target_key: null }),
      makeEdge({ edge_id: "x4", edge_type: "contract_manufacturer", target_kind: "facility", target_name: "Zhengzhou plant", target_key: null }),
    ],
  };
  const opts = supplierOptions(result);
  assert.deepEqual(opts.map((o) => o.label), ["Taiwan Semiconductor Manufacturing Co., Ltd."]);
});
