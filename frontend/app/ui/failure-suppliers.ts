// Pure helper for FIX-63 (Failure simulator on the Compare screen):
// extracts the top supplier/foundry/contract_manufacturer/key_input options from a DependencyResult.

import type { CompanyRunStatus, DependencyResult, EdgeType, VerifiedEdge } from "@/api/types";

export const MAX_SUPPLIER_OPTIONS = 15;

export const SUPPLIER_EDGE_TYPES: ReadonlySet<EdgeType> = new Set<EdgeType>([
  "supplier",
  "foundry",
  "contract_manufacturer",
  "key_input",
]);

export interface SupplierOption {
  /** Canonical supplier target key (e.g. "ALIAS:TSMC", "CIK:0001045810", or "NAME:asml-holding"). */
  key: string;
  /** Human-readable display name for the supplier. */
  label: string;
  /** Portfolio company_keys hit if this supplier fails: dependents + the supplier itself if held. */
  companyKeys: string[];
  /** Unioned portfolio weight of dependent companies (fraction of portfolio, 0..1). */
  weight: number;
}

function canonicalSupplierTarget(
  edge: VerifiedEdge,
  companyByKey: ReadonlyMap<string, CompanyRunStatus>,
): { key: string; label: string } {
  const rawTargetKey = edge.target_key?.trim();
  const rawTargetName = edge.target_name?.trim() ?? "";

  if (rawTargetKey) {
    const heldName = companyByKey.get(rawTargetKey)?.company_name?.trim();
    return {
      key: rawTargetKey,
      label: heldName || rawTargetName || rawTargetKey,
    };
  }

  const slug =
    rawTargetName
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "unknown";
  return {
    key: `NAME:${slug}`,
    label: rawTargetName || slug,
  };
}

/**
 * Extract up to `limit` (default 15) supplier shock options from a completed `DependencyResult`.
 *
 * - Considers verified `supplier`, `foundry`, `contract_manufacturer`, and `key_input` edges.
 * - Unions dependent portfolio companies per supplier target so no company is double-counted.
 * - `companyKeys` = sorted dependent company keys + the supplier's own key if held in the portfolio.
 * - Sorted descending by dependent portfolio weight, then dependent count, then key.
 */
export function supplierOptions(
  result: DependencyResult | null | undefined,
  limit: number = MAX_SUPPLIER_OPTIONS,
): SupplierOption[] {
  if (!result || !Array.isArray(result.edges) || result.edges.length === 0 || limit <= 0) {
    return [];
  }

  const companyByKey = new Map<string, CompanyRunStatus>();
  for (const comp of result.companies ?? []) {
    const key = comp.company_key?.trim();
    if (key) {
      companyByKey.set(key, comp);
    }
  }

  const groups = new Map<
    string,
    {
      key: string;
      label: string;
      dependentKeys: Set<string>;
      supplierHeld: boolean;
    }
  >();

  for (const edge of result.edges) {
    if (!SUPPLIER_EDGE_TYPES.has(edge.edge_type)) continue;
    if (edge.interpretation?.status === "rejected") continue;

    const srcKey = edge.source_company_key?.trim();
    if (!srcKey) continue;
    if (edge.source_in_portfolio === false && !companyByKey.has(srcKey)) continue;

    const { key, label } = canonicalSupplierTarget(edge, companyByKey);
    const heldComp = companyByKey.get(key);
    const isHeld =
      Boolean(edge.target_key?.trim() && edge.target_in_portfolio) ||
      Boolean(heldComp && heldComp.exposure > 0);

    const existing = groups.get(key);
    if (existing) {
      existing.dependentKeys.add(srcKey);
      if (isHeld) existing.supplierHeld = true;
      if (heldComp?.company_name?.trim()) {
        existing.label = heldComp.company_name.trim();
      }
    } else {
      groups.set(key, {
        key,
        label,
        dependentKeys: new Set([srcKey]),
        supplierHeld: isHeld,
      });
    }
  }

  const options: Array<SupplierOption & { dependentCount: number }> = [];

  for (const group of groups.values()) {
    const sortedDependents = [...group.dependentKeys].sort((a, b) => {
      const expA = companyByKey.get(a)?.exposure ?? 0;
      const expB = companyByKey.get(b)?.exposure ?? 0;
      if (Math.abs(expB - expA) > 1e-12) return expB - expA;
      return a.localeCompare(b);
    });

    let rawWeight = 0;
    for (const depKey of sortedDependents) {
      const exp = companyByKey.get(depKey)?.exposure ?? 0;
      if (exp > 0) rawWeight += exp;
    }
    const weight = Number(rawWeight.toFixed(10));

    const companyKeys = [...sortedDependents];
    if (group.supplierHeld && !group.dependentKeys.has(group.key)) {
      companyKeys.push(group.key);
    }

    options.push({
      key: group.key,
      label: group.label,
      companyKeys,
      weight,
      dependentCount: sortedDependents.length,
    });
  }

  options.sort((a, b) => {
    if (Math.abs(b.weight - a.weight) > 1e-12) return b.weight - a.weight;
    if (b.dependentCount !== a.dependentCount) return b.dependentCount - a.dependentCount;
    return a.key.localeCompare(b.key);
  });

  return options.slice(0, limit).map(({ key, label, companyKeys, weight }) => ({
    key,
    label,
    companyKeys,
    weight,
  }));
}
