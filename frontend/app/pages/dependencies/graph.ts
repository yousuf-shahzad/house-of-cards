// Pure deterministic data and bipartite SVG layout for the Dependencies page (G-UI).
// Zero external layout libraries: computes node positions, radii, cubic Bézier paths,
// unioned counterparty portfolio weights, and facility-by-country concentration.

import type {
  CompanyExposure,
  CompanyRunStatus,
  DependencyResult,
  EdgeType,
  MetricFact,
  TargetKind,
  VerifiedEdge,
  Weight,
} from "@/api/types";

export const SVG_WIDTH = 900;
const SOURCE_X = 240;
const TARGET_X = 640;
const ROW_GAP = 48;
const PAD_Y = 40;

export type EdgeFilterGroup =
  | "all"
  | "supply_chain"
  | "customers"
  | "inputs"
  | "facilities"
  | "sole_source";

export interface EdgeTypeMeta {
  label: string;
  shortLabel: string;
  color: string;
  dash?: string;
  badgeColor: "blue" | "purple" | "orange" | "cyan" | "lime" | "rose" | "yellow" | "neutral";
}

export const EDGE_TYPE_META: Record<EdgeType | "sole_source", EdgeTypeMeta> = {
  foundry: {
    label: "Foundry",
    shortLabel: "Foundry",
    color: "#7c3aed", // violet
    badgeColor: "purple",
  },
  sole_source: {
    label: "Sole-source supplier",
    shortLabel: "Sole source",
    color: "#e11d48", // rose
    badgeColor: "rose",
  },
  contract_manufacturer: {
    label: "Contract manufacturer",
    shortLabel: "Contract mfg",
    color: "#2563eb", // blue
    badgeColor: "blue",
  },
  supplier: {
    label: "Supplier",
    shortLabel: "Supplier",
    color: "#0284c7", // sky/cyan
    badgeColor: "cyan",
  },
  customer: {
    label: "Customer",
    shortLabel: "Customer",
    color: "#16a34a", // green
    dash: "6 3",
    badgeColor: "lime",
  },
  key_input: {
    label: "Key input / material",
    shortLabel: "Key input",
    color: "#d97706", // amber/orange
    dash: "3 3",
    badgeColor: "orange",
  },
  facility: {
    label: "Facility / location",
    shortLabel: "Facility",
    color: "#0d9488", // teal
    dash: "8 4",
    badgeColor: "cyan",
  },
  jv_partner: {
    label: "Joint-venture partner",
    shortLabel: "JV partner",
    color: "#4f46e5", // indigo
    dash: "4 4",
    badgeColor: "purple",
  },
};

export interface SourceGraphNode {
  id: string;
  companyKey: string;
  name: string;
  exposure: Weight;
  status: CompanyRunStatus["status"];
  inPortfolio: boolean;
  edgeCount: number;
  soleSourceCount: number;
  x: number;
  y: number;
  r: number;
}

export interface TargetGraphNode {
  id: string;
  targetKey: string | null;
  name: string;
  kind: TargetKind;
  inPortfolio: boolean;
  /** Unioned portfolio weight of distinct portfolio companies linked to this target. */
  dependentExposure: Weight;
  dependentCompanyKeys: string[];
  edgeIds: string[];
  hasSoleSource: boolean;
  primaryEdgeType: EdgeType;
  x: number;
  y: number;
  r: number;
}

export interface DependencyGraphEdge {
  id: string;
  edge: VerifiedEdge;
  sourceId: string;
  targetId: string;
  sourceExposure: Weight;
  width: number;
  color: string;
  dash?: string;
  path: string;
}

export interface DependencyGraph {
  sources: SourceGraphNode[];
  targets: TargetGraphNode[];
  edges: DependencyGraphEdge[];
  height: number;
  totalEdgesBeforeFilter: number;
}

export interface FacilityCountryRow {
  country: string;
  subjectKey: string | null;
  /** Unioned portfolio exposure of holdings with verified facilities in this jurisdiction. */
  dependentExposure: Weight;
  companyCount: number;
  companies: Array<{
    companyKey: string;
    companyName: string;
    exposure: Weight;
  }>;
  edges: VerifiedEdge[];
  metric: MetricFact | null;
}

const scaled = (value: number, max: number) =>
  max > 0 ? Math.sqrt(Math.max(value, 0) / max) : 0;

export function truncateText(text: string, max: number): string {
  const clean = text.trim().replace(/\s+/g, " ");
  return clean.length <= max ? clean : `${clean.slice(0, max - 1).trimEnd()}…`;
}

export function matchesEdgeFilter(edge: VerifiedEdge, filter: EdgeFilterGroup): boolean {
  if (filter === "all") return true;
  if (filter === "sole_source") return edge.sole_source;
  if (filter === "supply_chain") {
    return (
      edge.edge_type === "supplier" ||
      edge.edge_type === "foundry" ||
      edge.edge_type === "contract_manufacturer" ||
      edge.edge_type === "jv_partner"
    );
  }
  if (filter === "customers") return edge.edge_type === "customer";
  if (filter === "inputs") return edge.edge_type === "key_input";
  if (filter === "facilities") return edge.edge_type === "facility";
  return true;
}

export function targetNodeIdForEdge(edge: VerifiedEdge): string {
  if (edge.target_key) return `TARGET_KEY:${edge.target_key}`;
  return `TARGET:${edge.target_kind}:${edge.target_name.trim().toUpperCase()}`;
}

export function buildDependencyGraph(
  result: DependencyResult,
  portfolioExposures: CompanyExposure[],
  filter: EdgeFilterGroup = "all",
): DependencyGraph {
  const exposureByKey = new Map<string, Weight>();
  const nameByKey = new Map<string, string>();
  const statusByKey = new Map<string, CompanyRunStatus["status"]>();

  for (const exp of portfolioExposures) {
    exposureByKey.set(exp.company_key, exp.exposure);
    nameByKey.set(exp.company_key, exp.company_name);
  }
  for (const comp of result.companies) {
    if (!exposureByKey.has(comp.company_key) || comp.exposure > 0) {
      exposureByKey.set(comp.company_key, comp.exposure);
    }
    nameByKey.set(comp.company_key, comp.company_name);
    statusByKey.set(comp.company_key, comp.status);
  }

  const filteredEdges = result.edges.filter((edge) => matchesEdgeFilter(edge, filter));

  // Normalize each edge into (leftPortfolioSource, rightTarget)
  type NormalizedPair = {
    edge: VerifiedEdge;
    sourceId: string;
    sourceName: string;
    sourceInPortfolio: boolean;
    sourceExposure: Weight;
    targetId: string;
    targetKey: string | null;
    targetName: string;
    targetKind: TargetKind;
    targetInPortfolio: boolean;
  };

  const pairs: NormalizedPair[] = filteredEdges.map((edge) => {
    // Reverse-link case: external filer (not in portfolio) names a portfolio company as target
    if (!edge.source_in_portfolio && edge.target_in_portfolio && edge.target_key) {
      const pKey = edge.target_key;
      const pName = nameByKey.get(pKey) ?? edge.target_name;
      const pExp = exposureByKey.get(pKey) ?? 0;
      return {
        edge,
        sourceId: pKey,
        sourceName: pName,
        sourceInPortfolio: true,
        sourceExposure: pExp,
        targetId: `TARGET_KEY:${edge.source_company_key}`,
        targetKey: edge.source_company_key,
        targetName: edge.source_company_name,
        targetKind: "company",
        targetInPortfolio: false,
      };
    }

    const sKey = edge.source_company_key;
    const sName = nameByKey.get(sKey) ?? edge.source_company_name;
    const sExp = exposureByKey.get(sKey) ?? 0;
    const tId = targetNodeIdForEdge(edge);

    return {
      edge,
      sourceId: sKey,
      sourceName: sName,
      sourceInPortfolio: edge.source_in_portfolio || exposureByKey.has(sKey),
      sourceExposure: sExp,
      targetId: tId,
      targetKey: edge.target_key,
      targetName: edge.target_name,
      targetKind: edge.target_kind,
      targetInPortfolio: edge.target_in_portfolio,
    };
  });

  // Collect left-hand source nodes (all companies that have at least one edge in the current filter,
  // or if filter === "all" and there are edges, the companies participating in those edges).
  const sourceAccumulator = new Map<
    string,
    {
      companyKey: string;
      name: string;
      exposure: Weight;
      status: CompanyRunStatus["status"];
      inPortfolio: boolean;
      edgeCount: number;
      soleSourceCount: number;
    }
  >();

  for (const pair of pairs) {
    const existing = sourceAccumulator.get(pair.sourceId);
    if (existing) {
      existing.edgeCount += 1;
      if (pair.edge.sole_source) existing.soleSourceCount += 1;
    } else {
      sourceAccumulator.set(pair.sourceId, {
        companyKey: pair.sourceId,
        name: pair.sourceName,
        exposure: pair.sourceExposure,
        status: statusByKey.get(pair.sourceId) ?? "done",
        inPortfolio: pair.sourceInPortfolio,
        edgeCount: 1,
        soleSourceCount: pair.edge.sole_source ? 1 : 0,
      });
    }
  }

  // Sort left nodes by portfolio exposure desc, then name
  const orderedSources = [...sourceAccumulator.values()].sort(
    (a, b) => b.exposure - a.exposure || a.name.localeCompare(b.name),
  );

  // Collect right-hand target nodes, unioning dependent portfolio company exposures
  const targetAccumulator = new Map<
    string,
    {
      id: string;
      targetKey: string | null;
      name: string;
      kind: TargetKind;
      inPortfolio: boolean;
      dependentCompanies: Map<string, Weight>;
      edgeIds: string[];
      hasSoleSource: boolean;
      primaryEdgeType: EdgeType;
    }
  >();

  for (const pair of pairs) {
    const existing = targetAccumulator.get(pair.targetId);
    if (existing) {
      existing.dependentCompanies.set(pair.sourceId, pair.sourceExposure);
      existing.edgeIds.push(pair.edge.edge_id);
      if (pair.edge.sole_source) existing.hasSoleSource = true;
    } else {
      const depMap = new Map<string, Weight>();
      depMap.set(pair.sourceId, pair.sourceExposure);
      targetAccumulator.set(pair.targetId, {
        id: pair.targetId,
        targetKey: pair.targetKey,
        name: pair.targetName,
        kind: pair.targetKind,
        inPortfolio: pair.targetInPortfolio,
        dependentCompanies: depMap,
        edgeIds: [pair.edge.edge_id],
        hasSoleSource: pair.edge.sole_source,
        primaryEdgeType: pair.edge.edge_type,
      });
    }
  }

  // Sort right nodes: shared dependencies (2+ portfolio holdings) or higher unioned dependent weight first
  const orderedTargets = [...targetAccumulator.values()]
    .map((item) => {
      let dependentExposure = 0;
      for (const w of item.dependentCompanies.values()) {
        dependentExposure += w;
      }
      return {
        ...item,
        dependentExposure,
        dependentCompanyKeys: [...item.dependentCompanies.keys()],
      };
    })
    .sort(
      (a, b) =>
        b.dependentExposure - a.dependentExposure ||
        b.dependentCompanyKeys.length - a.dependentCompanyKeys.length ||
        a.name.localeCompare(b.name),
    );

  const maxRows = Math.max(orderedSources.length, orderedTargets.length, 1);
  const contentHeight = maxRows * ROW_GAP;
  const height = contentHeight + PAD_Y * 2;

  const maxSourceExposure = Math.max(0.001, ...orderedSources.map((s) => s.exposure));
  const sources: SourceGraphNode[] = orderedSources.map((s, idx) => ({
    id: s.companyKey,
    companyKey: s.companyKey,
    name: s.name,
    exposure: s.exposure,
    status: s.status,
    inPortfolio: s.inPortfolio,
    edgeCount: s.edgeCount,
    soleSourceCount: s.soleSourceCount,
    x: SOURCE_X,
    y: PAD_Y + ((idx + 0.5) * contentHeight) / orderedSources.length,
    r: 7 + 13 * scaled(s.exposure, maxSourceExposure),
  }));

  const maxTargetExposure = Math.max(0.001, ...orderedTargets.map((t) => t.dependentExposure));
  const targets: TargetGraphNode[] = orderedTargets.map((t, idx) => ({
    id: t.id,
    targetKey: t.targetKey,
    name: t.name,
    kind: t.kind,
    inPortfolio: t.inPortfolio,
    dependentExposure: t.dependentExposure,
    dependentCompanyKeys: t.dependentCompanyKeys,
    edgeIds: t.edgeIds,
    hasSoleSource: t.hasSoleSource,
    primaryEdgeType: t.primaryEdgeType,
    x: TARGET_X,
    y: PAD_Y + ((idx + 0.5) * contentHeight) / orderedTargets.length,
    r: 7 + 14 * scaled(t.dependentExposure, maxTargetExposure),
  }));

  const sourceById = new Map(sources.map((s) => [s.id, s]));
  const targetById = new Map(targets.map((t) => [t.id, t]));

  const edges: DependencyGraphEdge[] = [];
  for (const pair of pairs) {
    const from = sourceById.get(pair.sourceId);
    const to = targetById.get(pair.targetId);
    if (!from || !to) continue;
    const midX = (from.x + to.x) / 2;
    const meta = pair.edge.sole_source
      ? EDGE_TYPE_META.sole_source
      : (EDGE_TYPE_META[pair.edge.edge_type] ?? EDGE_TYPE_META.supplier);
    const width =
      maxSourceExposure > 0
        ? Math.max(1.75, (7.5 * pair.sourceExposure) / maxSourceExposure)
        : 2;
    edges.push({
      id: pair.edge.edge_id,
      edge: pair.edge,
      sourceId: from.id,
      targetId: to.id,
      sourceExposure: pair.sourceExposure,
      width,
      color: meta.color,
      dash: meta.dash,
      path: `M ${from.x} ${from.y} C ${midX} ${from.y}, ${midX} ${to.y}, ${to.x} ${to.y}`,
    });
  }

  return {
    sources,
    targets,
    edges,
    height,
    totalEdgesBeforeFilter: result.edges.length,
  };
}

/**
 * Computes facility concentration by country/region without double-counting a company
 * that has multiple facility edges in the same country.
 */
export function buildFacilityBreakdown(
  result: DependencyResult,
  portfolioExposures: CompanyExposure[],
): FacilityCountryRow[] {
  const exposureByKey = new Map<string, Weight>();
  const nameByKey = new Map<string, string>();

  for (const exp of portfolioExposures) {
    exposureByKey.set(exp.company_key, exp.exposure);
    nameByKey.set(exp.company_key, exp.company_name);
  }
  for (const comp of result.companies) {
    if (!exposureByKey.has(comp.company_key) || comp.exposure > 0) {
      exposureByKey.set(comp.company_key, comp.exposure);
    }
    nameByKey.set(comp.company_key, comp.company_name);
  }

  const facilityMetrics = result.metrics.filter((m) => m.metric_id.startsWith("facility."));

  const groups = new Map<
    string,
    {
      country: string;
      subjectKey: string | null;
      companies: Map<string, { companyKey: string; companyName: string; exposure: Weight }>;
      edges: VerifiedEdge[];
      metric: MetricFact | null;
    }
  >();

  for (const edge of result.edges) {
    const isFacility =
      edge.edge_type === "facility" ||
      edge.target_kind === "country" ||
      edge.target_kind === "region" ||
      edge.target_kind === "facility";
    if (!isFacility) continue;

    const countryLabel = edge.target_name.trim();
    const normKey = countryLabel.toUpperCase();
    const compKey = edge.source_company_key;
    const compName = nameByKey.get(compKey) ?? edge.source_company_name;
    const compExp = exposureByKey.get(compKey) ?? 0;

    let group = groups.get(normKey);
    if (!group) {
      const matchingMetric =
        facilityMetrics.find(
          (m) =>
            m.supporting_edge_ids.includes(edge.edge_id) ||
            (m.subject_key && m.subject_key.toUpperCase() === normKey) ||
            m.label.toLowerCase().includes(countryLabel.toLowerCase()),
        ) ?? null;
      group = {
        country: countryLabel,
        subjectKey: matchingMetric?.subject_key ?? edge.target_key,
        companies: new Map(),
        edges: [],
        metric: matchingMetric,
      };
      groups.set(normKey, group);
    }

    group.companies.set(compKey, {
      companyKey: compKey,
      companyName: compName,
      exposure: compExp,
    });
    group.edges.push(edge);
  }

  return [...groups.values()]
    .map((group) => {
      const companies = [...group.companies.values()].sort(
        (a, b) => b.exposure - a.exposure || a.companyName.localeCompare(b.companyName),
      );
      const unionSum = companies.reduce((sum, item) => sum + item.exposure, 0);
      const dependentExposure =
        group.metric && group.metric.unit === "fraction" ? group.metric.value : unionSum;
      return {
        country: group.country,
        subjectKey: group.subjectKey,
        dependentExposure,
        companyCount: companies.length,
        companies,
        edges: group.edges,
        metric: group.metric,
      };
    })
    .sort(
      (a, b) =>
        b.dependentExposure - a.dependentExposure ||
        b.companyCount - a.companyCount ||
        a.country.localeCompare(b.country),
    );
}
