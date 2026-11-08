// Plain-English view of the backend's dependency metrics (hoc.graph.metrics).
//
// The backend names metrics by id ("dep.ALIAS:TSMC", "dep.ALIAS:TSMC.companies", "spof.ALIAS:TSMC",
// "facility.CN", "customer.NAME:sony", "summary.analysed_weight"). Those ids are for code; people see:
// - one card per subject, with the % of the portfolio and its company count together;
// - "single point of failure" as a badge on the matching "depends on" card, not a second card;
// - summary metrics as a short sentence above the cards.
// Every number still comes from a MetricFact; nothing here computes one.

import type { MetricFact } from "@/api/types";

export type MetricKind = "depends_on" | "facility" | "customer" | "single_point" | "summary" | "other";

export interface MetricCard {
  /** The fraction metric this card shows (its id is the React key). */
  share: MetricFact;
  kind: MetricKind;
  /** Short category shown above the name, e.g. "Depends on". */
  category: string;
  /** Who or where, e.g. "Taiwan Semiconductor Manufacturing Co., Ltd." or "China". */
  subject: string;
  /** From the matching ".companies" metric, when there is one. */
  companies: number | null;
  /** The subject is also flagged as a single point of failure (spof.*). */
  singlePoint: boolean;
  /** Plain sentence completing the % (e.g. "of your portfolio is in 4 companies that rely on it"). */
  explanation: string;
  supportingEdgeIds: string[];
}

export interface SummaryFact {
  metric: MetricFact;
  text: string;
}

const SUBJECT_PATTERNS: RegExp[] = [
  /depends on (.+)$/i,
  /dependent on (.+)$/i,
  /facilities in (.+)$/i,
  /failure exposure on (.+)$/i,
  /customer concentration \((.+)\)$/i,
];

const CATEGORY: Record<MetricKind, string> = {
  depends_on: "Depends on",
  facility: "Key sites in",
  customer: "Major customer",
  single_point: "Single point of failure",
  summary: "Summary",
  other: "Metric",
};

const SUMMARY_TEXT: Record<string, string> = {
  "summary.analysed_weight": "of your portfolio is in companies with at least one verified dependency",
  "summary.verified_edges": "verified links found in company filings",
  "spof.count": "suppliers shared by several of your companies, or their only source",
};

const COMPANIES_SUFFIX = ".companies";

export function metricKind(metricId: string): MetricKind {
  if (metricId.startsWith("dep.")) return "depends_on";
  if (metricId.startsWith("facility.")) return "facility";
  if (metricId.startsWith("customer.")) return "customer";
  if (metricId === "spof.count") return "summary";
  if (metricId.startsWith("spof.")) return "single_point";
  if (metricId.startsWith("summary.")) return "summary";
  return "other";
}

function isUnnamed(subject: string): boolean {
  return /^unnamed customer$/i.test(subject.trim());
}

/** The company, input or country a metric is about, read from its label ("... depends on X" -> "X"). */
export function metricSubject(metric: MetricFact): string {
  for (const pattern of SUBJECT_PATTERNS) {
    const hit = pattern.exec(metric.label);
    if (hit) {
      const subject = hit[1].trim();
      return isUnnamed(subject) ? "Undisclosed major customers" : subject;
    }
  }
  return metric.label;
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

function explain(kind: MetricKind, subject: string, companies: number | null): string {
  switch (kind) {
    case "depends_on":
      return companies === null
        ? "of your portfolio is in companies that rely on it"
        : `of your portfolio is in ${plural(companies, "company", "companies")} that rely on it`;
    case "facility":
      return companies === null
        ? "of your portfolio is in companies with key sites there"
        : `of your portfolio is in ${plural(companies, "company", "companies")} with key sites there`;
    case "customer":
      return subject === "Undisclosed major customers"
        ? "of your portfolio is in companies that rely on a big customer they don't name (each a different one)"
        : "of your portfolio is in companies that name it as a major customer";
    case "single_point":
      return "of your portfolio relies on it, and it is shared or the only source";
    default:
      return "";
  }
}

/** One card per subject, largest share first. Count twins are merged in; spof.* becomes a badge. */
export function buildMetricCards(metrics: readonly MetricFact[]): MetricCard[] {
  const byId = new Map(metrics.map((m) => [m.metric_id, m]));
  const cards: MetricCard[] = [];
  for (const metric of metrics) {
    if (metric.unit !== "fraction") continue; // counts are merged into their fraction twin or shown as summary
    const kind = metricKind(metric.metric_id);
    if (kind === "summary") continue;
    if (kind === "single_point" && byId.has(`dep.${metric.metric_id.slice("spof.".length)}`)) continue;
    const subject = metricSubject(metric);
    const twin = byId.get(`${metric.metric_id}${COMPANIES_SUFFIX}`);
    const companies = twin ? Math.round(twin.value) : null;
    cards.push({
      share: metric,
      kind,
      category: CATEGORY[kind],
      subject,
      companies,
      singlePoint:
        kind === "single_point" ||
        (kind === "depends_on" && byId.has(`spof.${metric.metric_id.slice("dep.".length)}`)),
      explanation: kind === "other" ? "" : explain(kind, subject, companies),
      supportingEdgeIds: [...metric.supporting_edge_ids],
    });
  }
  return cards.sort((a, b) => b.share.value - a.share.value);
}

/** The headline facts above the cards (summary.* and spof.count), in plain words. */
export function buildSummaryFacts(metrics: readonly MetricFact[]): SummaryFact[] {
  return metrics
    .filter((m) => metricKind(m.metric_id) === "summary")
    .map((m) => ({ metric: m, text: SUMMARY_TEXT[m.metric_id] ?? m.label }));
}

/** A short human name for a cited metric, e.g. "Depends on TSMC" or "Companies with key sites in China". */
export function metricCitationLabel(metric: MetricFact): string {
  const id = metric.metric_id;
  if (id.endsWith(COMPANIES_SUFFIX)) {
    const kind = metricKind(id);
    const subject = metricSubject(metric);
    return kind === "facility" ? `Companies with key sites in ${subject}` : `Companies relying on ${subject}`;
  }
  const kind = metricKind(id);
  if (kind === "summary") return SUMMARY_TEXT[id] ? capitalise(SUMMARY_TEXT[id]) : metric.label;
  if (kind === "other") return metric.label;
  return `${CATEGORY[kind]} ${metricSubject(metric)}`;
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
