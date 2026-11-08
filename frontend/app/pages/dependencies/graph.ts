// Pure deterministic data and bipartite SVG layout for the Dependencies page (G-UI).
// Zero external layout libraries: computes node positions, radii, cubic Bézier paths,
// unioned counterparty portfolio weights, and facility-by-country concentration.

import type {
  CompanyExposure,
  CompanyRunStatus,
  DependencyResult,
  EdgeType,
  ImportanceTier,
  MetricFact,
  TargetKind,
  VerifiedEdge,
  Weight,
} from "@/api/types";

export const SVG_WIDTH = 900;
export const DEFAULT_TARGET_LIMIT = 25;
const SOURCE_X = 240;
const TARGET_X = 640;
const ROW_GAP = 46;
const PAD_Y = 40;

export type EdgeFilterGroup =
  | "all"
  | "supply_chain"
  | "customers"
  | "inputs"
  | "facilities"
  | "sole_source";

export type ImportanceFilterGroup = "all" | "critical_high" | "critical" | "flagged";

export interface ImportanceTierMeta {
  label: string;
  shortLabel: string;
  badgeColor: "rose" | "orange" | "blue" | "neutral";
  rank: number;
}

export const IMPORTANCE_TIER_META: Record<ImportanceTier, ImportanceTierMeta> = {
  critical: {
    label: "Critical importance",
    shortLabel: "Critical",
    badgeColor: "rose",
    rank: 4,
  },
  high: {
    label: "High importance",
    shortLabel: "High",
    badgeColor: "orange",
    rank: 3,
  },
  medium: {
    label: "Medium importance",
    shortLabel: "Medium",
    badgeColor: "blue",
    rank: 2,
  },
  low: {
    label: "Low importance",
    shortLabel: "Low",
    badgeColor: "neutral",
    rank: 1,
  },
};

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

const ISO2_COUNTRY_NAMES: Record<string, string> = {
  AT: "Austria",
  AU: "Australia",
  BE: "Belgium",
  BR: "Brazil",
  CA: "Canada",
  CH: "Switzerland",
  CL: "Chile",
  CN: "China",
  CR: "Costa Rica",
  CZ: "Czechia",
  DE: "Germany",
  DK: "Denmark",
  ES: "Spain",
  FI: "Finland",
  FR: "France",
  GB: "United Kingdom",
  HK: "Hong Kong",
  HU: "Hungary",
  ID: "Indonesia",
  IE: "Ireland",
  IL: "Israel",
  IN: "India",
  IT: "Italy",
  JP: "Japan",
  KR: "South Korea",
  LU: "Luxembourg",
  MX: "Mexico",
  MY: "Malaysia",
  NL: "Netherlands",
  NO: "Norway",
  NZ: "New Zealand",
  PH: "Philippines",
  PL: "Poland",
  PT: "Portugal",
  RO: "Romania",
  SA: "Saudi Arabia",
  SE: "Sweden",
  SG: "Singapore",
  TH: "Thailand",
  TR: "Turkey",
  TW: "Taiwan",
  UA: "Ukraine",
  US: "United States",
  VN: "Vietnam",
  ZA: "South Africa",
};

const COUNTRY_NAME_TO_ISO2: Record<string, { code: string; name: string }> = {
  tw: { code: "TW", name: "Taiwan" },
  taiwan: { code: "TW", name: "Taiwan" },
  "taiwan roc": { code: "TW", name: "Taiwan" },
  "republic of china": { code: "TW", name: "Taiwan" },
  hsinchu: { code: "TW", name: "Taiwan" },
  tainan: { code: "TW", name: "Taiwan" },
  taichung: { code: "TW", name: "Taiwan" },
  us: { code: "US", name: "United States" },
  usa: { code: "US", name: "United States" },
  "u s": { code: "US", name: "United States" },
  "u s a": { code: "US", name: "United States" },
  "united states": { code: "US", name: "United States" },
  "united states of america": { code: "US", name: "United States" },
  unitedstates: { code: "US", name: "United States" },
  arizona: { code: "US", name: "United States" },
  california: { code: "US", name: "United States" },
  cupertino: { code: "US", name: "United States" },
  texas: { code: "US", name: "United States" },
  oregon: { code: "US", name: "United States" },
  ohio: { code: "US", name: "United States" },
  "new mexico": { code: "US", name: "United States" },
  cn: { code: "CN", name: "China" },
  china: { code: "CN", name: "China" },
  prc: { code: "CN", name: "China" },
  "mainland china": { code: "CN", name: "China" },
  "china mainland": { code: "CN", name: "China" },
  kr: { code: "KR", name: "South Korea" },
  korea: { code: "KR", name: "South Korea" },
  "south korea": { code: "KR", name: "South Korea" },
  "republic of korea": { code: "KR", name: "South Korea" },
  jp: { code: "JP", name: "Japan" },
  japan: { code: "JP", name: "Japan" },
  kumamoto: { code: "JP", name: "Japan" },
  de: { code: "DE", name: "Germany" },
  germany: { code: "DE", name: "Germany" },
  dresden: { code: "DE", name: "Germany" },
  nl: { code: "NL", name: "Netherlands" },
  netherlands: { code: "NL", name: "Netherlands" },
  "the netherlands": { code: "NL", name: "Netherlands" },
  veldhoven: { code: "NL", name: "Netherlands" },
  vn: { code: "VN", name: "Vietnam" },
  vietnam: { code: "VN", name: "Vietnam" },
  in: { code: "IN", name: "India" },
  india: { code: "IN", name: "India" },
  ie: { code: "IE", name: "Ireland" },
  ireland: { code: "IE", name: "Ireland" },
  sg: { code: "SG", name: "Singapore" },
  singapore: { code: "SG", name: "Singapore" },
  il: { code: "IL", name: "Israel" },
  israel: { code: "IL", name: "Israel" },
  my: { code: "MY", name: "Malaysia" },
  malaysia: { code: "MY", name: "Malaysia" },
  gb: { code: "GB", name: "United Kingdom" },
  uk: { code: "GB", name: "United Kingdom" },
  "united kingdom": { code: "GB", name: "United Kingdom" },
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
  totalTargetsBeforeLimit: number;
}

export interface FacilityHoldingSite {
  companyKey: string;
  companyName: string;
  exposure: Weight;
  /** Specific named sites/facilities (e.g. "Gigafactory Shanghai", "Boise fab") under this holding. */
  namedSites: Array<{
    siteName: string;
    qualifier: string | null;
    edgeId: string;
  }>;
  edges: VerifiedEdge[];
}

export interface FacilityCountryRow {
  country: string;
  countryCode: string;
  subjectKey: string | null;
  /** Unioned portfolio exposure of holdings with verified facilities in this jurisdiction. */
  dependentExposure: Weight;
  companyCount: number;
  companies: FacilityHoldingSite[];
  edges: VerifiedEdge[];
  metric: MetricFact | null;
}

const scaled = (value: number, max: number) =>
  max > 0 ? Math.sqrt(Math.max(value, 0) / max) : 0;

/** Inserts spaces into camelCase/PascalCase strings like "FremontFactory" -> "Fremont Factory". */
export function humaniseSiteName(text: string): string {
  return text
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\s+/g, " ")
    .trim();
}

export function truncateText(text: string, max: number): string {
  const clean = humaniseSiteName(text);
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

export function matchesImportanceFilter(
  edge: VerifiedEdge,
  filter: ImportanceFilterGroup,
): boolean {
  if (filter === "all") return true;
  if (filter === "flagged") return edge.interpretation?.status === "flagged";
  const tier = edge.importance?.tier;
  if (filter === "critical") return tier === "critical";
  if (filter === "critical_high") return tier === "critical" || tier === "high";
  return true;
}

export function compareEdgesByImportance(
  a: VerifiedEdge,
  b: VerifiedEdge,
  exposureMap?: Map<string, number>,
): number {
  const scoreDiff = (b.importance?.score ?? 0) - (a.importance?.score ?? 0);
  if (Math.abs(scoreDiff) > 1e-6) return scoreDiff;
  if (a.sole_source !== b.sole_source) return a.sole_source ? -1 : 1;
  const expA = exposureMap?.get(a.source_company_key) ?? 0;
  const expB = exposureMap?.get(b.source_company_key) ?? 0;
  if (Math.abs(expB - expA) > 1e-6) return expB - expA;
  return a.source_company_name.localeCompare(b.source_company_name);
}

function isUnnamedCustomerEdge(edge: VerifiedEdge): boolean {
  if (edge.target_kind === "unnamed_customer") return true;
  if (
    edge.edge_type === "customer" &&
    !edge.target_key &&
    /unnamed|undisclosed|one customer|single customer|largest customer|direct customer|customer [a-z0-9]/i.test(
      edge.target_name,
    )
  ) {
    return true;
  }
  return false;
}

function shortCompanyName(name: string): string {
  const cleaned = name
    .replace(
      // The lookahead (not \b) lets a trailing "." go too: \b after "Inc." would keep "Apple." .
      /,?\s+\b(Inc\.?|Corp\.?|Corporation|Company|Co\.?|Ltd\.?|Limited|PLC|N\.V\.|S\.A\.|AG|SE|Holdings?)(?=[\s,]|$)/gi,
      "",
    )
    .trim();
  return cleaned || name.trim();
}

/**
 * Each company's undisclosed customer is a distinct entity (e.g. "Broadcom's customer (32% of net revenue)")
 * so multiple holdings with anonymous major customers never merge into a fake shared customer node.
 */
export function targetNodeIdForEdge(edge: VerifiedEdge): string {
  if (isUnnamedCustomerEdge(edge)) {
    const qualKey = (edge.qualifier ?? edge.target_name).trim().toUpperCase();
    return `TARGET:unnamed_customer:${edge.source_company_key}:${qualKey}`;
  }
  if (edge.target_key) return `TARGET_KEY:${edge.target_key}`;
  return `TARGET:${edge.target_kind}:${edge.target_name.trim().toUpperCase()}`;
}

export function targetDisplayNameForEdge(edge: VerifiedEdge, sourceName?: string): string {
  if (isUnnamedCustomerEdge(edge)) {
    const owner = shortCompanyName(sourceName ?? edge.source_company_name);
    const qual = edge.qualifier ? `, ${edge.qualifier}` : "";
    return `${owner}'s customer${qual}`;
  }
  return humaniseSiteName(edge.target_name);
}

export function buildDependencyGraph(
  result: DependencyResult,
  portfolioExposures: CompanyExposure[],
  filter: EdgeFilterGroup = "all",
  targetLimit: number | null = DEFAULT_TARGET_LIMIT,
  importanceFilter: ImportanceFilterGroup = "all",
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

  const filteredEdges = result.edges.filter(
    (edge) =>
      matchesEdgeFilter(edge, filter) && matchesImportanceFilter(edge, importanceFilter),
  );

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

  const allPairs: NormalizedPair[] = filteredEdges.map((edge) => {
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
    const tName = targetDisplayNameForEdge(edge, sName);

    return {
      edge,
      sourceId: sKey,
      sourceName: sName,
      sourceInPortfolio: edge.source_in_portfolio || exposureByKey.has(sKey),
      sourceExposure: sExp,
      targetId: tId,
      targetKey: edge.target_key,
      targetName: tName,
      targetKind: isUnnamedCustomerEdge(edge) ? "unnamed_customer" : edge.target_kind,
      targetInPortfolio: edge.target_in_portfolio,
    };
  });

  // Collect right-hand target nodes first so we can rank and optionally cap to top 25 counterparties
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

  for (const pair of allPairs) {
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

  const allOrderedTargets = [...targetAccumulator.values()]
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

  const totalTargetsBeforeLimit = allOrderedTargets.length;
  const orderedTargets =
    targetLimit !== null && allOrderedTargets.length > targetLimit
      ? allOrderedTargets.slice(0, targetLimit)
      : allOrderedTargets;

  const allowedTargetIds = new Set(orderedTargets.map((t) => t.id));
  const pairs = allPairs.filter((p) => allowedTargetIds.has(p.targetId));

  // Collect left-hand source nodes participating in the visible pairs
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

  const orderedSources = [...sourceAccumulator.values()].sort(
    (a, b) => b.exposure - a.exposure || a.name.localeCompare(b.name),
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
    totalTargetsBeforeLimit,
  };
}

function isDistinctSiteName(targetName: string, countryName: string, countryCode: string): boolean {
  const normTarget = targetName.replace(/[^a-zA-Z0-9]+/g, "").toLowerCase();
  const normCountry = countryName.replace(/[^a-zA-Z0-9]+/g, "").toLowerCase();
  const normCode = countryCode.replace(/[^a-zA-Z0-9]+/g, "").toLowerCase();
  if (!normTarget) return false;
  if (normTarget === normCountry || normTarget === normCode) return false;
  if (
    normCountry === "unitedstates" &&
    (normTarget === "usa" || normTarget === "us" || normTarget === "unitedstatesofamerica")
  ) {
    return false;
  }
  if (
    normCountry === "china" &&
    (normTarget === "prc" || normTarget === "mainlandchina" || normTarget === "chinamainland")
  ) {
    return false;
  }
  if (
    normCountry === "taiwan" &&
    (normTarget === "taiwanroc" || normTarget === "republicofchina")
  ) {
    return false;
  }
  if (normCountry === "southkorea" && (normTarget === "korea" || normTarget === "republicofkorea")) {
    return false;
  }
  return true;
}

/**
 * Groups facility concentration strictly from the backend's `facility.<ISO2>` metrics
 * (e.g. `facility.US`, `facility.CN`, `facility.TW`) so variants like "United States",
 * "U.S.", "US", and named factories never split into separate country bars.
 * Named sites (e.g. "Gigafactory Shanghai", "Boise fab", "Fremont Factory") are listed
 * separately under their respective portfolio holdings inside each country card.
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

  const edgeById = new Map(result.edges.map((e) => [e.edge_id, e]));
  const metricById = new Map(result.metrics.map((m) => [m.metric_id, m]));

  // Primary path: group strictly by backend `facility.<ISO2>` fraction metrics. The backend also
  // emits site-level ids (facility.FAB_22, facility.GIGAFACTORY_SHANGHAI) when a filing names a
  // site without its country; those are sites, not countries, so they stay out of the country view.
  const primaryFacilityMetrics = result.metrics.filter(
    (m) =>
      /^facility\.[A-Z]{2}$/.test(m.metric_id) &&
      m.unit === "fraction",
  );

  if (primaryFacilityMetrics.length > 0) {
    return primaryFacilityMetrics
      .map((metric) => {
        const rawCode = (metric.subject_key ?? metric.metric_id.slice("facility.".length)).trim();
        const upperCode = rawCode.toUpperCase();
        const labelSuffix = metric.label
          .replace(/^Portfolio exposure with key facilities in\s+/i, "")
          .trim();
        const countryDisplay =
          ISO2_COUNTRY_NAMES[upperCode] ?? humaniseSiteName(labelSuffix || rawCode);

        const supportingEdges = metric.supporting_edge_ids
          .map((id) => edgeById.get(id))
          .filter((e): e is VerifiedEdge => e !== undefined);

        const holdingsMap = new Map<string, FacilityHoldingSite>();
        for (const edge of supportingEdges) {
          const compKey = edge.source_company_key;
          const compName = nameByKey.get(compKey) ?? edge.source_company_name;
          const compExp = exposureByKey.get(compKey) ?? 0;

          let holding = holdingsMap.get(compKey);
          if (!holding) {
            holding = {
              companyKey: compKey,
              companyName: compName,
              exposure: compExp,
              namedSites: [],
              edges: [],
            };
            holdingsMap.set(compKey, holding);
          }
          holding.edges.push(edge);

          const prettyTarget = humaniseSiteName(edge.target_name);
          if (
            edge.target_kind === "facility" ||
            isDistinctSiteName(prettyTarget, countryDisplay, upperCode)
          ) {
            if (!holding.namedSites.some((s) => s.siteName.toLowerCase() === prettyTarget.toLowerCase())) {
              holding.namedSites.push({
                siteName: prettyTarget,
                qualifier: edge.qualifier,
                edgeId: edge.edge_id,
              });
            }
          }
        }

        const companies = [...holdingsMap.values()].sort(
          (a, b) => b.exposure - a.exposure || a.companyName.localeCompare(b.companyName),
        );
        const countMetric = metricById.get(`${metric.metric_id}.companies`);
        const companyCount = countMetric
          ? Math.round(countMetric.value)
          : Math.max(companies.length, 1);

        return {
          country: countryDisplay,
          countryCode: upperCode,
          subjectKey: metric.subject_key ?? upperCode,
          dependentExposure: metric.value,
          companyCount,
          companies,
          edges: supportingEdges,
          metric,
        };
      })
      .sort(
        (a, b) =>
          b.dependentExposure - a.dependentExposure ||
          b.companyCount - a.companyCount ||
          a.country.localeCompare(b.country),
      );
  }

  // Fallback path if no `facility.*` metrics exist in `result.metrics`
  const fallbackGroups = new Map<
    string,
    {
      country: string;
      countryCode: string;
      holdings: Map<string, FacilityHoldingSite>;
      edges: VerifiedEdge[];
    }
  >();

  for (const edge of result.edges) {
    const isFacility =
      edge.edge_type === "facility" ||
      edge.target_kind === "country" ||
      edge.target_kind === "region" ||
      edge.target_kind === "facility";
    if (!isFacility) continue;

    const norm = edge.target_name
      .replace(/[^a-zA-Z0-9]+/g, " ")
      .trim()
      .toLowerCase();
    const mapped = COUNTRY_NAME_TO_ISO2[norm] ?? {
      code: norm.toUpperCase().replace(/\s+/g, "_") || "UNKNOWN",
      name: humaniseSiteName(edge.target_name),
    };

    let group = fallbackGroups.get(mapped.code);
    if (!group) {
      group = {
        country: mapped.name,
        countryCode: mapped.code,
        holdings: new Map(),
        edges: [],
      };
      fallbackGroups.set(mapped.code, group);
    }
    group.edges.push(edge);

    const compKey = edge.source_company_key;
    const compName = nameByKey.get(compKey) ?? edge.source_company_name;
    const compExp = exposureByKey.get(compKey) ?? 0;
    let holding = group.holdings.get(compKey);
    if (!holding) {
      holding = {
        companyKey: compKey,
        companyName: compName,
        exposure: compExp,
        namedSites: [],
        edges: [],
      };
      group.holdings.set(compKey, holding);
    }
    holding.edges.push(edge);
    const prettyTarget = humaniseSiteName(edge.target_name);
    if (isDistinctSiteName(prettyTarget, mapped.name, mapped.code)) {
      if (!holding.namedSites.some((s) => s.siteName.toLowerCase() === prettyTarget.toLowerCase())) {
        holding.namedSites.push({
          siteName: prettyTarget,
          qualifier: edge.qualifier,
          edgeId: edge.edge_id,
        });
      }
    }
  }

  return [...fallbackGroups.values()]
    .map((g) => {
      const companies = [...g.holdings.values()].sort(
        (a, b) => b.exposure - a.exposure || a.companyName.localeCompare(b.companyName),
      );
      const dependentExposure = companies.reduce((sum, c) => sum + c.exposure, 0);
      return {
        country: g.country,
        countryCode: g.countryCode,
        subjectKey: g.countryCode,
        dependentExposure,
        companyCount: companies.length,
        companies,
        edges: g.edges,
        metric: null,
      };
    })
    .sort(
      (a, b) =>
        b.dependentExposure - a.dependentExposure ||
        b.companyCount - a.companyCount ||
        a.country.localeCompare(b.country),
    );
}
