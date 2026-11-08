"use client";
// Dependencies page (G-UI, owned by Yousuf's Gemini).
// Displays (in order per PLAN-v2 & lead audit #6715309042):
// 1. Click-to-run ("Find dependencies") trigger + live per-company job progress
// 2. Verification & Filing Coverage Audit Bar (verified edges, rejected/unverified counts, non-SEC skipped holdings)
// 3. Orchestrator Insights panel (Critical Flaws + Diversification Suggestions) straight after the audit bar,
//    showing metric labels (never raw IDs) and collapsible "N sources" edge citations
// 4. Deterministic Python Dependency Metrics strip (top 8 fraction metrics by value, merged ".companies" counts,
//    human labels, collapsible "N sources", and "Show all N" toggle)
// 5. Zero-dependency bipartite SVG Dependency Graph (top 25 counterparties cap with "Show all N", per-source
//    unnamed customers, keyboard focus-visible rings, and accessible table fallback)
// 6. Facility concentration by country grouped strictly from backend `facility.<ISO2>` metrics, with named
//    sites listed separately under their holdings
// 7. SEC Filing Evidence Drawer + inline Evidence Inspector (verbatim quote, 10-K/20-F form, filing date, section, SEC link)

import { useCallback, useMemo, useState, type KeyboardEvent } from "react";
import {
  RiAlertLine,
  RiArrowRightUpLine,
  RiBuilding2Line,
  RiCheckboxCircleLine,
  RiDoubleQuotesL,
  RiErrorWarningLine,
  RiExternalLinkLine,
  RiFileTextLine,
  RiGlobalLine,
  RiInformationLine,
  RiLinksLine,
  RiMindMap,
  RiPlayCircleLine,
  RiRefreshLine,
  RiShieldCheckLine,
  RiSparklingLine,
} from "@remixicon/react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api, ApiError } from "@/api/client";
import {
  DEFAULT_TOP_N,
  type CompanyRunStatus,
  type CompanyStatus,
  type InsightClaim,
  type Insights,
  type MetricFact,
  type TargetKind,
  type VerifiedEdge,
} from "@/api/types";
import { useAnalysis } from "@/app/analysis";
import { DependenciesProvider, useDependencies } from "@/app/dependencies-state";
import { formatPct, Pct } from "@/app/ui/pct";
import { Chip, type ChipColor } from "@/components/base/badges/chip";
import { StatusDot } from "@/components/base/badges/status-dot";
import { Button, ButtonLink } from "@/components/base/buttons/button";
import { Drawer, DrawerBody, DrawerFooter, DrawerHeader } from "@/components/base/drawer/drawer";
import {
  SegmentedControl,
  SegmentedControlItem,
} from "@/components/base/segmented-control/segmented-control";
import { Spinner } from "@/components/base/spinner/spinner";
import { cx } from "@/utils/cx";
import { buildMetricCards, buildSummaryFacts, metricCitationLabel } from "./metrics";
import {
  buildDependencyGraph,
  buildFacilityBreakdown,
  DEFAULT_TARGET_LIMIT,
  EDGE_TYPE_META,
  SVG_WIDTH,
  targetNodeIdForEdge,
  truncateText,
  type DependencyGraph,
  type EdgeFilterGroup,
} from "./graph";


const COMPANY_STATUS_META: Record<
  CompanyStatus,
  {
    label: string;
    chipColor: ChipColor;
    dotColor: "green" | "yellow" | "indigo";
    isSkipped: boolean;
  }
> = {
  done: { label: "Analysed", chipColor: "lime", dotColor: "green", isSkipped: false },
  cached: { label: "Cached", chipColor: "lime", dotColor: "green", isSkipped: false },
  extracting: { label: "Extracting…", chipColor: "blue", dotColor: "indigo", isSkipped: false },
  fetching: { label: "Fetching filing…", chipColor: "cyan", dotColor: "indigo", isSkipped: false },
  queued: { label: "Queued", chipColor: "neutral", dotColor: "indigo", isSkipped: false },
  no_sec_filing: {
    label: "No SEC 10-K/20-F",
    chipColor: "yellow",
    dotColor: "yellow",
    isSkipped: true,
  },
  unsupported_form: {
    label: "Unsupported form",
    chipColor: "yellow",
    dotColor: "yellow",
    isSkipped: true,
  },
  sec_contact_missing: {
    label: "SEC contact missing",
    chipColor: "orange",
    dotColor: "yellow",
    isSkipped: true,
  },
  missing_api_key: {
    label: "API key missing",
    chipColor: "orange",
    dotColor: "yellow",
    isSkipped: true,
  },
  error: { label: "Error", chipColor: "rose", dotColor: "indigo", isSkipped: true },
};

const TARGET_KIND_LABEL: Record<TargetKind, string> = {
  company: "Company",
  country: "Country",
  region: "Region",
  material: "Material",
  component: "Component",
  facility: "Facility",
  unnamed_customer: "Undisclosed customer",
};

const CLAIM_SEVERITY_META: Record<
  InsightClaim["severity"],
  { label: string; chipColor: ChipColor; borderClass: string }
> = {
  critical: {
    label: "Critical",
    chipColor: "rose",
    borderClass: "border-border-error-default",
  },
  warning: {
    label: "Warning",
    chipColor: "orange",
    borderClass: "border-border-button-default",
  },
  info: {
    label: "Info",
    chipColor: "blue",
    borderClass: "border-border-button-default",
  },
};

/** The backend message for a company, with its internal key (e.g. ALIAS:SAMSUNG_ELEC) shown as its name. */
function companyMessage(company: CompanyRunStatus): string {
  return (company.message ?? "").split(company.company_key).join(company.company_name);
}

function analysisErrorCopy(error: ApiError): string {
  const tickers = (error.details as { tickers?: string[] } | undefined)?.tickers;
  if (error.code === "UNKNOWN_TICKER" && tickers?.length) {
    return `We couldn't find ${tickers.join(", ")} in any data source. Check the ticker on the Portfolio page.`;
  }
  if (error.code === "SOURCES_UNAVAILABLE") {
    return "None of the data sources could be reached, so we have no holdings to show.";
  }
  if (error.code === "NETWORK_ERROR") {
    return "We couldn't reach the analysis service. Check that the backend is running.";
  }
  return error.message;
}

/** Metric cards shown before "Show all": the largest shares, so the page stays short. */
const METRIC_CARDS_SHOWN = 9;

/** Plain-English status of the AI synthesis step (the contract's InsightsStatus). */
const INSIGHTS_STATUS_META: Record<Insights["status"], { label: string; chipColor: ChipColor; note: string | null }> = {
  ok: { label: "Every number checked", chipColor: "lime", note: null },
  metrics_only: {
    label: "Numbers only",
    chipColor: "yellow",
    note: "The AI step was skipped, so these points come straight from the calculated numbers.",
  },
  missing_api_key: {
    label: "AI not set up",
    chipColor: "yellow",
    note: "No Gemini API key is set on the server, so there is no AI synthesis. The numbers below still apply.",
  },
  no_verified_edges: {
    label: "Nothing to reason about",
    chipColor: "yellow",
    note: "No dependency could be verified in the filings, so the AI was not asked to speculate.",
  },
  error: {
    label: "AI step failed",
    chipColor: "rose",
    note: "The AI synthesis failed this time. The verified links and numbers below are unaffected.",
  },
};

type CitationProps = {
  metricById: ReadonlyMap<string, MetricFact>;
  edgeById: ReadonlyMap<string, VerifiedEdge>;
  selectEdge: (edgeId: string, openDrawer: boolean) => void;
};

const CITATION_CHIP =
  "inline-flex cursor-pointer items-center gap-1 rounded-md border border-border-button-default bg-background-secondary-default px-2 py-0.5 text-start text-caption-1-regular text-text-primary hover:bg-background-primary-hover focus-visible:outline-2 focus-visible:outline-border-focus-ring";

/** One AI claim: its text, the numbers it cites in plain words, and its filing quotes folded away. */
function ClaimCard({ claim, metricById, edgeById, selectEdge }: CitationProps & { claim: InsightClaim }) {
  const sev = CLAIM_SEVERITY_META[claim.severity] ?? CLAIM_SEVERITY_META.warning;
  const sources = claim.cited_edge_ids.length;
  return (
    <article className={cx("flex flex-col gap-2.5 rounded-2xl border bg-background-primary-default p-4", sev.borderClass)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h5 className="text-body-medium text-text-primary">{claim.title}</h5>
        <Chip variant="caption" color={sev.chipColor}>
          {sev.label}
        </Chip>
      </div>
      <p className="text-body-2-regular text-text-secondary">{claim.text}</p>
      {claim.cited_metric_ids.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {claim.cited_metric_ids.map((metricId) => {
            const metric = metricById.get(metricId);
            const firstEdgeId = metric?.supporting_edge_ids[0] ?? null;
            return (
              <button
                key={metricId}
                type="button"
                disabled={!firstEdgeId}
                onClick={() => firstEdgeId && selectEdge(firstEdgeId, true)}
                className={CITATION_CHIP}
              >
                {metric ? `${metricCitationLabel(metric)}: ${formatMetricValue(metric)}` : "Cited number"}
              </button>
            );
          })}
        </div>
      )}
      {sources > 0 && (
        <details>
          <summary className="cursor-pointer text-caption-1-regular text-text-tertiary">
            {sources === 1 ? "1 source in the filings" : `${sources} sources in the filings`}
          </summary>
          <div className="flex flex-wrap gap-1.5 pt-2">
            {claim.cited_edge_ids.map((edgeId) => {
              const edge = edgeById.get(edgeId);
              return (
                <button key={edgeId} type="button" onClick={() => selectEdge(edgeId, true)} className={CITATION_CHIP}>
                  <RiDoubleQuotesL className="size-3" aria-hidden />
                  <span>
                    {edge ? `${edge.source_company_name} → ${edge.target_name} (${edge.filing.form})` : "Filing quote"}
                  </span>
                </button>
              );
            })}
          </div>
        </details>
      )}
    </article>
  );
}

/** The AI synthesis: critical flaws and diversification ideas, each citing checked numbers and quotes. */
function InsightsPanel({ insights, ...citations }: CitationProps & { insights: Insights }) {
  const status = INSIGHTS_STATUS_META[insights.status] ?? INSIGHTS_STATUS_META.error;
  const columns = [
    {
      key: "flaws",
      icon: <RiAlertLine className="size-4 text-text-error-primary" aria-hidden />,
      title: "Critical flaws",
      claims: insights.flaws,
      empty: "No critical concentration flaws were flagged in the verified links.",
    },
    {
      key: "suggestions",
      icon: <RiMindMap className="size-4 text-text-primary" aria-hidden />,
      title: "Diversification ideas",
      claims: insights.suggestions,
      empty: "No diversification changes were suggested from the verified links.",
    },
  ];
  return (
    <section
      aria-label="AI synthesis: critical flaws and diversification ideas"
      className="flex flex-col gap-4 rounded-3xl border border-border-button-default bg-background-secondary-default p-5"
    >
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <RiSparklingLine className="size-5 text-text-primary" aria-hidden />
          <h3 className="text-headline-small text-text-primary">AI synthesis: critical flaws &amp; diversification ideas</h3>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Chip variant="caption" color={status.chipColor}>
            {status.label}
          </Chip>
          {insights.model && (
            <Chip variant="caption" color="purple">
              {insights.model}
            </Chip>
          )}
          {insights.rejected_claims_count > 0 && (
            <Chip variant="caption" color="orange">
              {insights.rejected_claims_count} unchecked {insights.rejected_claims_count === 1 ? "claim" : "claims"} dropped
            </Chip>
          )}
        </div>
        <p className="text-body-2-regular text-text-secondary">
          {status.note ??
            "Written by the AI from the verified filing quotes. Every number in it was checked against the calculated numbers, and claims that failed were dropped. Advisory only, not investment advice."}
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {columns.map((column) => (
          <div key={column.key} className="flex flex-col gap-3">
            <div className="flex items-center gap-2">
              {column.icon}
              <h4 className="text-body-semibold text-text-primary">
                {column.title} ({column.claims.length})
              </h4>
            </div>
            {column.claims.length === 0 ? (
              <p className="rounded-2xl border border-separator-border bg-background-primary-default p-4 text-body-2-regular text-text-secondary">
                {column.empty}
              </p>
            ) : (
              column.claims.map((claim) => <ClaimCard key={claim.claim_id} claim={claim} {...citations} />)
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function formatMetricValue(metric: MetricFact): string {
  if (metric.unit === "fraction") return formatPct(metric.value, 2);
  if (metric.unit === "count") return `${Math.round(metric.value)}`;
  if (metric.unit === "days") return `${Math.round(metric.value)} days`;
  return metric.value.toFixed(2);
}

function formatSectionLabel(section: string): string {
  if (/^(1|1A|1B|2|3|3D|3\.D|4|5|7|7A)$/i.test(section.trim())) {
    return `Item ${section.trim()}`;
  }
  if (/^concentration_\d+$/i.test(section.trim())) {
    return "Concentration note";
  }
  return section;
}

function EdgeEvidenceCard({
  edge,
  exposureMap,
  isSelected,
  onSelect,
}: {
  edge: VerifiedEdge;
  exposureMap: Map<string, number>;
  isSelected?: boolean;
  onSelect?: (edgeId: string) => void;
}) {
  const meta = edge.sole_source
    ? EDGE_TYPE_META.sole_source
    : (EDGE_TYPE_META[edge.edge_type] ?? EDGE_TYPE_META.supplier);
  const sourceExp = exposureMap.get(edge.source_company_key);

  return (
    <article
      className={cx(
        "flex flex-col gap-3 rounded-2xl border p-4 transition-colors",
        isSelected
          ? "border-border-focus-ring bg-background-primary-default"
          : "border-separator-border bg-background-primary-default",
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Chip variant="caption" color={meta.badgeColor}>
            {EDGE_TYPE_META[edge.edge_type]?.label ?? edge.edge_type}
          </Chip>
          {edge.sole_source && (
            <Chip variant="caption" color="rose">
              Sole source
            </Chip>
          )}
          {edge.qualifier && (
            <Chip variant="caption" color="orange">
              {edge.qualifier}
            </Chip>
          )}
          <Chip variant="caption" color="neutral">
            {TARGET_KIND_LABEL[edge.target_kind] ?? edge.target_kind}
          </Chip>
        </div>
        <Chip variant="caption" color="lime">
          <RiCheckboxCircleLine className="me-1 inline size-3.5" aria-hidden />
          Verified quote
        </Chip>
      </div>

      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-body-medium text-text-primary">{edge.source_company_name}</span>
        {typeof sourceExp === "number" && sourceExp > 0 && (
          <span className="text-caption-1-regular text-text-tertiary tabular-nums">
            (<Pct value={sourceExp} digits={2} /> of portfolio)
          </span>
        )}
        <span className="text-body-2-regular text-text-tertiary">→</span>
        <span className="text-body-medium text-text-primary">{edge.target_name}</span>
        {edge.target_in_portfolio && (
          <Chip variant="caption" color="purple">
            In portfolio
          </Chip>
        )}
      </div>

      <blockquote className="rounded-xl border-s-4 border-border-focus-ring bg-background-secondary-default px-3.5 py-2.5 text-body-2-regular text-text-primary italic">
        <RiDoubleQuotesL className="me-1.5 inline size-4 text-text-tertiary" aria-hidden />
        {edge.evidence_quote}
      </blockquote>

      <div className="flex flex-wrap items-center justify-between gap-2 text-caption-1-regular text-text-secondary">
        <div className="flex flex-wrap items-center gap-2">
          <Chip variant="caption" color="neutral">
            <RiFileTextLine className="me-1 inline size-3" aria-hidden />
            SEC {edge.filing.form}
          </Chip>
          <span>{formatSectionLabel(edge.section)}</span>
          <span>·</span>
          <span className="tabular-nums">Filed {edge.filing.filed}</span>
          <span className="font-mono text-text-tertiary">({edge.filing.accession})</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {onSelect && !isSelected && (
            <Button variant="secondary" size="xs" onClick={() => onSelect(edge.edge_id)}>
              Inspect in drawer
            </Button>
          )}
          <a
            href={edge.filing.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 font-medium text-text-primary underline hover:text-text-secondary"
          >
            <span>Open SEC filing</span>
            <RiExternalLinkLine className="size-3.5" aria-hidden />
          </a>
        </div>
      </div>
    </article>
  );
}

function CollapsibleEdgeSources({
  edgeIds,
  edgeById,
  onSelectEdge,
}: {
  edgeIds: string[];
  edgeById: Map<string, VerifiedEdge>;
  onSelectEdge: (edgeId: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  if (edgeIds.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
        className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-border-button-default bg-background-secondary-default px-2 py-0.5 text-caption-1-medium text-text-primary hover:bg-background-primary-hover focus-visible:ring-2 focus-visible:ring-border-focus-ring outline-none"
      >
        <RiDoubleQuotesL className="size-3 text-text-tertiary" aria-hidden />
        <span>
          {edgeIds.length} {edgeIds.length === 1 ? "source" : "sources"}
          {expanded ? " (hide)" : ""}
        </span>
      </button>
      {!expanded && edgeIds[0] && (
        <button
          type="button"
          onClick={() => onSelectEdge(edgeIds[0])}
          className="cursor-pointer text-caption-1-regular text-text-secondary underline hover:text-text-primary focus-visible:ring-2 focus-visible:ring-border-focus-ring outline-none"
        >
          View quote
        </button>
      )}
      {expanded &&
        edgeIds.map((edgeId) => {
          const edge = edgeById.get(edgeId);
          return (
            <button
              key={edgeId}
              type="button"
              onClick={() => onSelectEdge(edgeId)}
              className="inline-flex cursor-pointer items-center gap-1 rounded-md border border-border-button-default bg-background-primary-default px-2 py-0.5 text-caption-1-regular text-text-primary hover:bg-background-primary-hover focus-visible:ring-2 focus-visible:ring-border-focus-ring outline-none"
            >
              <RiDoubleQuotesL className="size-3 text-text-tertiary" aria-hidden />
              <span>
                {edge
                  ? `${edge.source_company_name} → ${edge.target_name} (${edge.filing.form})`
                  : "Filing quote"}
              </span>
            </button>
          );
        })}
    </div>
  );
}

function DependencyDiagram({
  graph,
  activeNodeId,
  selectedEdgeId,
  onHoverNode,
  onSelectNode,
  onSelectEdge,
}: {
  graph: DependencyGraph;
  activeNodeId: string | null;
  selectedEdgeId: string | null;
  onHoverNode: (id: string | null) => void;
  onSelectNode: (id: string | null) => void;
  onSelectEdge: (edgeId: string) => void;
}) {
  const linkedNodes = useMemo(() => {
    const ids = new Set<string>();
    if (activeNodeId) {
      ids.add(activeNodeId);
      for (const edge of graph.edges) {
        if (edge.sourceId === activeNodeId || edge.targetId === activeNodeId) {
          ids.add(edge.sourceId);
          ids.add(edge.targetId);
        }
      }
    } else if (selectedEdgeId) {
      const found = graph.edges.find((e) => e.id === selectedEdgeId);
      if (found) {
        ids.add(found.sourceId);
        ids.add(found.targetId);
      }
    }
    return ids;
  }, [graph.edges, activeNodeId, selectedEdgeId]);

  const hasHighlight = activeNodeId !== null || selectedEdgeId !== null;

  const isEdgeHighlighted = (edge: DependencyGraph["edges"][number]) => {
    if (activeNodeId) {
      return edge.sourceId === activeNodeId || edge.targetId === activeNodeId;
    }
    if (selectedEdgeId) {
      return edge.id === selectedEdgeId;
    }
    return true;
  };

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${SVG_WIDTH} ${graph.height}`}
        role="group"
        aria-label="Supply chain, customer, input, and facility dependency network"
        className="block w-full min-w-[680px]"
        onClick={(e) => {
          if (e.target === e.currentTarget) onSelectNode(null);
        }}
      >
        <text
          x={230}
          y={20}
          textAnchor="end"
          className="fill-text-tertiary text-caption-1-semibold"
        >
          PORTFOLIO HOLDINGS
        </text>
        <text
          x={650}
          y={20}
          textAnchor="start"
          className="fill-text-tertiary text-caption-1-semibold"
        >
          COUNTERPARTIES, INPUTS & FACILITIES (DEPENDENT WEIGHT)
        </text>

        <g fill="none">
          {graph.edges.map((edge) => {
            const highlighted = isEdgeHighlighted(edge);
            const isSelected = edge.id === selectedEdgeId;
            return (
              <g key={edge.id}>
                <path
                  d={edge.path}
                  stroke="transparent"
                  strokeWidth={Math.max(14, edge.width + 8)}
                  className="cursor-pointer focus-visible:outline-2 focus-visible:outline-border-focus-ring"
                  role="button"
                  tabIndex={0}
                  aria-label={`${edge.edge.source_company_name} ${EDGE_TYPE_META[edge.edge.edge_type]?.label ?? edge.edge.edge_type} ${edge.edge.target_name}${edge.edge.sole_source ? " (sole source)" : ""}. Click to inspect verbatim SEC filing quote.`}
                  onClick={(ev) => {
                    ev.stopPropagation();
                    onSelectEdge(edge.id);
                  }}
                  onKeyDown={(ev: KeyboardEvent) => {
                    if (ev.key === "Enter" || ev.key === " ") {
                      ev.preventDefault();
                      onSelectEdge(edge.id);
                    }
                  }}
                >
                  <title>
                    {`${edge.edge.source_company_name} → ${edge.edge.target_name} (${EDGE_TYPE_META[edge.edge.edge_type]?.label ?? edge.edge.edge_type}): "${edge.edge.evidence_quote}" [${edge.edge.filing.form} ${edge.edge.filing.filed}]`}
                  </title>
                </path>
                <path
                  d={edge.path}
                  stroke={edge.color}
                  strokeWidth={isSelected ? edge.width + 1.5 : edge.width}
                  strokeDasharray={edge.dash}
                  strokeOpacity={hasHighlight ? (highlighted ? 0.95 : 0.12) : 0.65}
                  className="pointer-events-none"
                  style={{ transition: "stroke-opacity 120ms, stroke-width 120ms" }}
                />
              </g>
            );
          })}
        </g>

        {graph.sources.map((node) => {
          const dimmed = hasHighlight && !linkedNodes.has(node.id);
          return (
            <g
              key={node.id}
              role="button"
              tabIndex={0}
              aria-label={`${node.name}, ${formatPct(node.exposure)} of portfolio, ${node.edgeCount} verified dependency edges`}
              aria-pressed={activeNodeId === node.id}
              className="cursor-pointer outline-none focus-visible:outline-2 focus-visible:outline-border-focus-ring [&:focus-visible>circle]:stroke-border-focus-ring [&:focus-visible>circle]:stroke-[3px]"
              style={{ opacity: dimmed ? 0.25 : 1, transition: "opacity 120ms" }}
              onMouseEnter={() => onHoverNode(node.id)}
              onMouseLeave={() => onHoverNode(null)}
              onFocus={() => onHoverNode(node.id)}
              onBlur={() => onHoverNode(null)}
              onClick={(ev) => {
                ev.stopPropagation();
                onSelectNode(node.id);
              }}
              onKeyDown={(ev: KeyboardEvent) => {
                if (ev.key === "Enter" || ev.key === " ") {
                  ev.preventDefault();
                  onSelectNode(node.id);
                }
              }}
            >
              <circle
                cx={node.x}
                cy={node.y}
                r={node.r}
                fill="var(--color-text-primary)"
                stroke={
                  node.soleSourceCount > 0 ? "#e11d48" : "var(--color-background-primary-default)"
                }
                strokeWidth={node.soleSourceCount > 0 ? 2.5 : 2}
              />
              <text
                x={node.x - node.r - 10}
                y={node.y - 2}
                textAnchor="end"
                className="fill-text-primary text-body-2-medium"
              >
                <title>{node.name}</title>
                {truncateText(node.name, 26)}
              </text>
              <text
                x={node.x - node.r - 10}
                y={node.y + 13}
                textAnchor="end"
                className="fill-text-secondary text-caption-1-regular"
              >
                {formatPct(node.exposure, 2)} · {node.edgeCount}{" "}
                {node.edgeCount === 1 ? "edge" : "edges"}
              </text>
            </g>
          );
        })}

        {graph.targets.map((node) => {
          const dimmed = hasHighlight && !linkedNodes.has(node.id);
          const meta = node.hasSoleSource
            ? EDGE_TYPE_META.sole_source
            : (EDGE_TYPE_META[node.primaryEdgeType] ?? EDGE_TYPE_META.supplier);
          const isSharedBottleneck = node.dependentCompanyKeys.length >= 2;
          return (
            <g
              key={node.id}
              role="button"
              tabIndex={0}
              aria-label={`${node.name} (${TARGET_KIND_LABEL[node.kind]}), ${formatPct(node.dependentExposure)} dependent portfolio exposure across ${node.dependentCompanyKeys.length} holdings`}
              aria-pressed={activeNodeId === node.id}
              className="cursor-pointer outline-none focus-visible:outline-2 focus-visible:outline-border-focus-ring [&:focus-visible>circle]:stroke-border-focus-ring [&:focus-visible>circle]:stroke-[3px]"
              style={{ opacity: dimmed ? 0.25 : 1, transition: "opacity 120ms" }}
              onMouseEnter={() => onHoverNode(node.id)}
              onMouseLeave={() => onHoverNode(null)}
              onFocus={() => onHoverNode(node.id)}
              onBlur={() => onHoverNode(null)}
              onClick={(ev) => {
                ev.stopPropagation();
                onSelectNode(node.id);
              }}
              onKeyDown={(ev: KeyboardEvent) => {
                if (ev.key === "Enter" || ev.key === " ") {
                  ev.preventDefault();
                  onSelectNode(node.id);
                }
              }}
            >
              <circle
                cx={node.x}
                cy={node.y}
                r={node.r}
                fill={meta.color}
                stroke={
                  isSharedBottleneck || node.hasSoleSource
                    ? "#e11d48"
                    : "var(--color-background-primary-default)"
                }
                strokeWidth={isSharedBottleneck || node.hasSoleSource ? 2.5 : 2}
              />
              <text
                x={node.x + node.r + 10}
                y={node.y - 2}
                textAnchor="start"
                className="fill-text-primary text-body-2-medium"
              >
                <title>{node.name}</title>
                {truncateText(node.name, 28)}
              </text>
              <text
                x={node.x + node.r + 10}
                y={node.y + 13}
                textAnchor="start"
                className="fill-text-secondary text-caption-1-regular"
              >
                {formatPct(node.dependentExposure, 2)} dep.
                {isSharedBottleneck ? ` · ${node.dependentCompanyKeys.length} holdings` : ""}
                {node.hasSoleSource ? " · sole source" : ""}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function DependenciesPageContent() {
  const {
    analysis,
    status: analysisStatus,
    stale: analysisStale,
    error: analysisError,
    retry: retryAnalysis,
    setRows,
  } = useAnalysis();

  const {
    status: depStatus,
    job,
    stale: depStale,
    reconnecting,
    error: depError,
    selectedEdgeId,
    selectedNodeId,
    drawerOpen,
    runDependencies,
    selectEdge,
    selectNode,
    setDrawerOpen,
  } = useDependencies();

  const [loadingExample, setLoadingExample] = useState(false);
  const [exampleError, setExampleError] = useState<string | null>(null);
  const [edgeFilter, setEdgeFilter] = useState<EdgeFilterGroup>("all");
  const [showAllTargets, setShowAllTargets] = useState(false);
  const [showAllMetrics, setShowAllMetrics] = useState(false);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  const handleLoadExample = useCallback(async () => {
    setLoadingExample(true);
    setExampleError(null);
    try {
      const res = await api.examples();
      const chosen = res.examples.find((ex) => ex.verified) ?? res.examples[0];
      if (!chosen || chosen.holdings.length === 0) {
        setExampleError("No verified example portfolio is currently available.");
        return;
      }
      setRows(
        chosen.holdings.map((h) => ({
          ticker: h.ticker,
          allocationPct: Number((h.allocation * 100).toFixed(4)),
        })),
      );
    } catch (cause) {
      setExampleError(
        cause instanceof Error ? cause.message : "Could not load the example portfolio.",
      );
    } finally {
      setLoadingExample(false);
    }
  }, [setRows]);

  const topExposures = useMemo(
    () =>
      analysis
        ? analysis.exposures.filter((c) => c.exposure > 0).slice(0, DEFAULT_TOP_N)
        : [],
    [analysis],
  );

  const topExposureSum = useMemo(
    () => topExposures.reduce((sum, item) => sum + item.exposure, 0),
    [topExposures],
  );

  const result = job?.result ?? null;

  const exposureMap = useMemo(() => {
    const map = new Map<string, number>();
    if (analysis) {
      for (const item of analysis.exposures) {
        map.set(item.company_key, item.exposure);
      }
    }
    if (result) {
      for (const comp of result.companies) {
        if (!map.has(comp.company_key) || comp.exposure > 0) {
          map.set(comp.company_key, comp.exposure);
        }
      }
    }
    return map;
  }, [analysis, result]);

  const graph = useMemo(
    () =>
      result
        ? buildDependencyGraph(
            result,
            analysis?.exposures ?? [],
            edgeFilter,
            showAllTargets ? null : DEFAULT_TARGET_LIMIT,
          )
        : null,
    [result, analysis?.exposures, edgeFilter, showAllTargets],
  );

  const facilityRows = useMemo(
    () =>
      result ? buildFacilityBreakdown(result, analysis?.exposures ?? []) : [],
    [result, analysis?.exposures],
  );

  const edgeById = useMemo(() => {
    const map = new Map<string, VerifiedEdge>();
    if (result) {
      for (const edge of result.edges) {
        map.set(edge.edge_id, edge);
      }
    }
    return map;
  }, [result]);

  const metricById = useMemo(() => {
    const map = new Map<string, MetricFact>();
    if (result) {
      for (const m of result.metrics) {
        map.set(m.metric_id, m);
      }
    }
    return map;
  }, [result]);

  const metricCards = useMemo(() => (result ? buildMetricCards(result.metrics) : []), [result]);
  const summaryFacts = useMemo(() => (result ? buildSummaryFacts(result.metrics) : []), [result]);
  const visibleMetricCards = showAllMetrics ? metricCards : metricCards.slice(0, METRIC_CARDS_SHOWN);

  const activeNodeId = hoveredNodeId ?? selectedNodeId;

  const inspectedEdges = useMemo<VerifiedEdge[]>(() => {
    if (!result) return [];
    if (activeNodeId) {
      return result.edges.filter(
        (e) =>
          e.source_company_key === activeNodeId ||
          (e.target_in_portfolio && e.target_key === activeNodeId) ||
          targetNodeIdForEdge(e) === activeNodeId ||
          `TARGET_KEY:${e.source_company_key}` === activeNodeId,
      );
    }
    if (selectedEdgeId && edgeById.has(selectedEdgeId)) {
      return [edgeById.get(selectedEdgeId)!];
    }
    return result.edges.slice(0, 2);
  }, [result, activeNodeId, selectedEdgeId, edgeById]);

  const drawerEdge = useMemo<VerifiedEdge | null>(
    () => (selectedEdgeId ? (edgeById.get(selectedEdgeId) ?? null) : null),
    [selectedEdgeId, edgeById],
  );

  const companiesList: CompanyRunStatus[] = result?.companies ?? job?.companies ?? [];

  const missingKeyCompanies = useMemo(
    () => companiesList.filter((c) => c.status === "missing_api_key"),
    [companiesList],
  );
  const missingSecContactCompanies = useMemo(
    () => companiesList.filter((c) => c.status === "sec_contact_missing"),
    [companiesList],
  );
  const nonSecCompanies = useMemo(
    () =>
      companiesList.filter(
        (c) => c.status === "no_sec_filing" || c.status === "unsupported_form",
      ),
    [companiesList],
  );
  const fallbackQualityCompanies = useMemo(
    () => companiesList.filter((c) => c.extraction_quality === "fallback"),
    [companiesList],
  );

  const showMissingKeyBanner =
    missingKeyCompanies.length > 0 || result?.insights.status === "missing_api_key";
  const showMissingSecBanner = missingSecContactCompanies.length > 0;

  // ---------- 1. Empty / Loading / Error states when no portfolio analysis exists ----------
  if (!analysis) {
    if (analysisStatus === "loading") {
      return (
        <section
          aria-live="polite"
          className="flex flex-col items-center justify-center gap-3 rounded-3xl border border-border-button-default bg-background-secondary-default p-10 text-center"
        >
          <Spinner size="md" />
          <p className="text-body-medium text-text-primary">
            Computing look-through company exposures…
          </p>
          <p className="text-body-2-regular text-text-secondary">
            Resolving top portfolio holdings before scanning SEC 10-K and 20-F dependency disclosures.
          </p>
        </section>
      );
    }

    if (analysisStatus === "error" && analysisError) {
      return (
        <section
          role="alert"
          className="flex flex-col items-start gap-4 rounded-3xl border border-border-error-default bg-background-secondary-default p-6"
        >
          <div className="flex items-center gap-2 text-text-error-primary">
            <RiErrorWarningLine className="size-5 shrink-0" aria-hidden />
            <h2 className="text-headline-medium">
              Could not load portfolio analysis ({analysisError.code})
            </h2>
          </div>
          <p className="text-body-regular text-text-secondary">
            {analysisErrorCopy(analysisError)}
          </p>
          <div className="flex flex-wrap items-center gap-3">
            {analysisError.code !== "UNKNOWN_TICKER" && (
              <Button
                variant="primary"
                size="small"
                leadingIcon={RiRefreshLine}
                onClick={retryAnalysis}
              >
                Retry analysis
              </Button>
            )}
            <ButtonLink variant="secondary" size="small" href="#/portfolio">
              Edit portfolio
            </ButtonLink>
          </div>
        </section>
      );
    }

    return (
      <section className="flex flex-col items-start gap-4 rounded-3xl border border-border-button-default bg-background-secondary-default p-6">
        <div className="flex flex-col gap-1">
          <h2 className="text-headline-medium text-text-primary">
            Enter a portfolio to inspect supply-chain dependencies
          </h2>
          <p className="text-body-regular text-text-secondary">
            Load a verified example portfolio or enter ETF allocations on the Portfolio page, then
            run AI dependency extraction over your top {DEFAULT_TOP_N} company holdings.
          </p>
        </div>
        {exampleError && (
          <p role="alert" className="text-body-2-medium text-text-error-primary">
            {exampleError}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="primary"
            size="small"
            leadingIcon={RiSparklingLine}
            disabled={loadingExample}
            onClick={handleLoadExample}
          >
            {loadingExample ? "Loading example…" : "Load example portfolio"}
          </Button>
          <ButtonLink variant="secondary" size="small" href="#/portfolio">
            Go to your portfolio
          </ButtonLink>
        </div>
      </section>
    );
  }

  const isRunning = depStatus === "starting" || depStatus === "polling";

  return (
    <div
      className="flex w-full flex-col gap-6"
      onKeyDown={(ev) => {
        if (ev.key === "Escape") {
          selectNode(null);
          setDrawerOpen(false);
        }
      }}
    >
      {/* Top CTA + overview bar */}
      <section
        aria-label="Dependency scan controls"
        className="flex flex-col gap-4 rounded-3xl border border-border-button-default bg-background-secondary-default p-5"
      >
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-headline-medium text-text-primary">
                SEC 10-K / 20-F Supply-Chain & Facility Intelligence
              </h2>
              <Chip variant="caption" color="purple">
                {/* One string: the chip is a flex box, which drops the space before " of". */}
                {`Top ${topExposures.length} holdings (${formatPct(topExposureSum, 1)} of portfolio)`}
              </Chip>
            </div>
            <p className="text-body-2-regular text-text-secondary">
              Gemini sub-agents extract suppliers, foundries, contract manufacturers, key inputs,
              customers, and facility locations from SEC filings. Python verifies every quote
              verbatim and computes deterministic exposure metrics.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <Button
              variant="primary"
              size="small"
              leadingIcon={isRunning ? undefined : result ? RiRefreshLine : RiPlayCircleLine}
              disabled={isRunning || topExposures.length === 0}
              onClick={() => runDependencies(DEFAULT_TOP_N)}
            >
              {isRunning
                ? reconnecting
                  ? "Reconnecting…"
                  : `Scanning filings (${job?.progress_done ?? 0}/${job?.progress_total ?? topExposures.length})…`
                : result
                  ? depStale
                    ? "Re-evaluate dependencies"
                    : "Run again"
                  : "Find dependencies"}
            </Button>
          </div>
        </div>

        {(depStale || analysisStale) && result && (
          <div
            role="status"
            aria-live="polite"
            className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border-button-default bg-background-primary-default px-4 py-3"
          >
            <div className="flex items-center gap-2 text-body-2-medium text-text-primary">
              <RiAlertLine className="size-4 shrink-0 text-foreground-icon-secondary" aria-hidden />
              <span>
                Your portfolio allocations have changed since this dependency scan ran. Showing
                results from your previous portfolio.
              </span>
            </div>
            <Button
              variant="secondary"
              size="xs"
              leadingIcon={RiRefreshLine}
              disabled={isRunning}
              onClick={() => runDependencies(DEFAULT_TOP_N)}
            >
              Re-evaluate dependencies
            </Button>
          </div>
        )}

        {showMissingKeyBanner && (
          <div
            role="status"
            className="flex items-start gap-2.5 rounded-2xl border border-border-button-default bg-background-primary-default px-4 py-3 text-body-2-regular text-text-secondary"
          >
            <RiInformationLine className="mt-0.5 size-4 shrink-0 text-text-primary" aria-hidden />
            <div>
              <span className="font-medium text-text-primary">
                GEMINI_API_KEY not configured for live extraction:
              </span>{" "}
              Showing cached filing extractions and deterministic Python metrics. Set{" "}
              <code className="rounded bg-background-secondary-default px-1.5 py-0.5 font-mono text-caption-1-regular">
                GEMINI_API_KEY
              </code>{" "}
              in your local backend environment to extract uncached companies or run the{" "}
              <code className="rounded bg-background-secondary-default px-1.5 py-0.5 font-mono text-caption-1-regular">
                gemini-4-argon
              </code>{" "}
              orchestrator live.
            </div>
          </div>
        )}

        {showMissingSecBanner && (
          <div
            role="status"
            className="flex items-start gap-2.5 rounded-2xl border border-border-button-default bg-background-primary-default px-4 py-3 text-body-2-regular text-text-secondary"
          >
            <RiInformationLine className="mt-0.5 size-4 shrink-0 text-text-primary" aria-hidden />
            <div>
              <span className="font-medium text-text-primary">
                HOC_SEC_CONTACT not set for uncached EDGAR fetches:
              </span>{" "}
              Serving cached filings only. Set{" "}
              <code className="rounded bg-background-secondary-default px-1.5 py-0.5 font-mono text-caption-1-regular">
                HOC_SEC_CONTACT
              </code>{" "}
              to fetch new 10-K/20-F documents from SEC EDGAR.
            </div>
          </div>
        )}

        {depStatus === "error" && depError && (
          <div
            role="alert"
            className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border-error-default bg-background-primary-default px-4 py-3"
          >
            <div className="flex items-center gap-2 text-body-2-medium text-text-error-primary">
              <RiErrorWarningLine className="size-4 shrink-0" aria-hidden />
              <span>
                Could not complete dependency scan ({depError.code}): {depError.message}
              </span>
            </div>
            <Button
              variant="secondary"
              size="xs"
              leadingIcon={RiRefreshLine}
              onClick={() => runDependencies(DEFAULT_TOP_N)}
            >
              Try again
            </Button>
          </div>
        )}

        {isRunning && (
          <div
            role="status"
            aria-live="polite"
            className="flex flex-col gap-3 rounded-2xl border border-border-button-default bg-background-primary-default p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-body-2-medium text-text-primary">
                <Spinner size="sm" />
                <span>
                  {reconnecting
                    ? "Reconnecting… Waiting for the backend service and resuming your dependency scan…"
                    : `Extracting and verifying SEC 10-K / 20-F disclosures… (${job?.progress_done ?? 0} of ${job?.progress_total ?? topExposures.length} companies)`}
                </span>
              </div>
              <span className="font-mono text-caption-1-regular text-text-tertiary">
                {job?.job_id ? `Job ${job.job_id.slice(0, 12)}` : "Starting job…"}
              </span>
            </div>
            {job && job.progress_total > 0 && (
              <div className="h-2 w-full overflow-hidden rounded-full bg-background-tertiary-default">
                <div
                  className="h-full rounded-full bg-text-primary transition-all duration-300"
                  style={{
                    width: `${Math.min(100, Math.round((job.progress_done / job.progress_total) * 100))}%`,
                  }}
                />
              </div>
            )}
            {companiesList.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {companiesList.map((comp) => {
                  const meta = COMPANY_STATUS_META[comp.status] ?? COMPANY_STATUS_META.queued;
                  return (
                    <Chip key={comp.company_key} variant="caption" color={meta.chipColor}>
                      {comp.company_name}: {meta.label}
                    </Chip>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </section>

      {!result && !isRunning && (
        <section
          aria-label="Top holdings queued for dependency scan"
          className="flex flex-col gap-4 rounded-3xl border border-border-button-default bg-background-secondary-default p-6"
        >
          <div className="flex flex-col gap-1">
            <h3 className="text-headline-small text-text-primary">
              Ready to scan your top {topExposures.length} company exposures
            </h3>
            <p className="text-body-2-regular text-text-secondary">
              Click <strong>Find dependencies</strong> above to inspect verified supplier, foundry,
              customer, input, and facility relationships for these holdings:
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {topExposures.map((comp) => (
              <div
                key={comp.company_key}
                className="flex items-center gap-2 rounded-xl border border-separator-border bg-background-primary-default px-3 py-1.5 text-body-2-regular"
              >
                <span className="font-mono text-caption-1-regular text-text-tertiary">
                  #{comp.rank}
                </span>
                <span className="font-medium text-text-primary">{comp.company_name}</span>
                {comp.symbols[0] && (
                  <Chip variant="caption" color="neutral">
                    {comp.symbols[0]}
                  </Chip>
                )}
                <Pct
                  value={comp.exposure}
                  digits={2}
                  className="text-caption-1-semibold text-text-secondary"
                />
              </div>
            ))}
          </div>
        </section>
      )}

      {result && (
        <div
          className="flex flex-col gap-6"
          style={{ opacity: depStale ? 0.82 : 1, transition: "opacity 150ms" }}
        >
          {/* 2. Verification & Filing Coverage Audit Bar (non-clipping badges at 800px / 360px) */}
          <section
            aria-label="Verification and filing coverage audit"
            className="flex flex-col gap-4 rounded-3xl border border-border-button-default bg-background-secondary-default p-5"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <RiShieldCheckLine className="size-5 text-text-primary" aria-hidden />
                <h3 className="text-headline-small text-text-primary">
                  Verification & Filing Coverage Audit
                </h3>
              </div>
              <span className="text-caption-1-regular text-text-tertiary">
                As of {result.as_of_date} · Zero unverified edges or numbers are ever drawn
              </span>
            </div>

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              <div className="flex min-w-0 flex-col gap-1 rounded-2xl border border-separator-border bg-background-primary-default p-4">
                <div className="flex flex-wrap items-center justify-between gap-1.5">
                  <span className="text-caption-1-semibold text-text-secondary">
                    VERIFIED EDGES
                  </span>
                  <Chip variant="caption" color="lime">
                    Verified
                  </Chip>
                </div>
                <span className="text-display-4-medium text-text-primary tabular-nums">
                  {result.counts.verified_edges}
                </span>
                <span className="text-caption-1-regular text-text-secondary">
                  Verbatim quotes matched in SEC 10-K / 20-F text
                </span>
              </div>

              <div className="flex min-w-0 flex-col gap-1 rounded-2xl border border-separator-border bg-background-primary-default p-4">
                <div className="flex flex-wrap items-center justify-between gap-1.5">
                  <span className="text-caption-1-semibold text-text-secondary">
                    UNVERIFIED OMITTED
                  </span>
                  <Chip
                    variant="caption"
                    color={
                      result.counts.rejected_edges + result.insights.rejected_claims_count > 0
                        ? "orange"
                        : "neutral"
                    }
                  >
                    Dropped
                  </Chip>
                </div>
                <span className="flex flex-col text-display-4-medium text-text-primary tabular-nums">
                  <span>
                    {result.counts.rejected_edges} {result.counts.rejected_edges === 1 ? "quote" : "quotes"}
                  </span>
                  <span className="text-body-semibold text-text-secondary">
                    {result.insights.rejected_claims_count} AI{" "}
                    {result.insights.rejected_claims_count === 1 ? "claim" : "claims"}
                  </span>
                </span>
                <span className="text-caption-1-regular text-text-secondary">
                  Failed verbatim quote or metric check; never shown
                </span>
              </div>

              <div className="flex min-w-0 flex-col gap-1 rounded-2xl border border-separator-border bg-background-primary-default p-4">
                <div className="flex flex-wrap items-center justify-between gap-1.5">
                  <span className="text-caption-1-semibold text-text-secondary">
                    FILINGS ANALYSED
                  </span>
                  <Chip variant="caption" color="blue">
                    10-K / 20-F
                  </Chip>
                </div>
                <span className="text-display-4-medium text-text-primary tabular-nums">
                  {result.counts.companies_analysed} / {result.counts.companies_requested}
                </span>
                <span className="text-caption-1-regular text-text-secondary">
                  {result.counts.unresolved_counterparties} unresolved counterparty{" "}
                  {result.counts.unresolved_counterparties === 1 ? "name" : "names"}
                </span>
              </div>

              <div className="flex min-w-0 flex-col gap-1 rounded-2xl border border-separator-border bg-background-primary-default p-4">
                <div className="flex flex-wrap items-center justify-between gap-1.5">
                  <span className="text-caption-1-semibold text-text-secondary">
                    SKIPPED HOLDINGS
                  </span>
                  <Chip
                    variant="caption"
                    color={result.counts.companies_skipped > 0 ? "yellow" : "neutral"}
                  >
                    Coverage
                  </Chip>
                </div>
                <span className="text-display-4-medium text-text-primary tabular-nums">
                  {result.counts.companies_skipped}
                </span>
                <span className="text-caption-1-regular text-text-secondary">
                  {nonSecCompanies.length > 0
                    ? `No primary SEC filing (${nonSecCompanies.map((c) => c.company_name).join(", ")})`
                    : "All requested holdings had primary SEC filings"}
                </span>
              </div>
            </div>

            {nonSecCompanies.length > 0 && (
              <p className="text-caption-1-regular text-text-secondary">
                <strong>Non-SEC holdings note:</strong>{" "}
                {nonSecCompanies
                  .map(
                    (c) =>
                      `${c.company_name} (${formatPct(c.exposure, 2)}${c.message ? ` — ${companyMessage(c)}` : " — no primary SEC 10-K/20-F disclosure; appears only in other filers' verified quotes"})`,
                  )
                  .join("; ")}
                .
              </p>
            )}

            {fallbackQualityCompanies.length > 0 && (
              <p className="text-caption-1-regular text-text-secondary">
                <strong>Section fallback notice:</strong>{" "}
                {fallbackQualityCompanies.map((c) => c.company_name).join(", ")} used full-document
                fallback chunks because standard Item headings were absent or abbreviated.
              </p>
            )}

            <details className="rounded-2xl border border-separator-border bg-background-primary-default px-4 py-3">
              <summary className="cursor-pointer text-body-2-medium text-text-primary">
                Show per-company filing status and quote verification counts (
                {result.companies.length} companies)
              </summary>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-start text-body-2-regular text-text-secondary">
                  <thead>
                    <tr className="border-b border-separator-border text-text-primary">
                      <th scope="col" className="py-2 pe-4 text-start font-medium">
                        Company
                      </th>
                      <th scope="col" className="py-2 pe-4 text-start font-medium">
                        Exposure
                      </th>
                      <th scope="col" className="py-2 pe-4 text-start font-medium">
                        Status
                      </th>
                      <th scope="col" className="py-2 pe-4 text-start font-medium">
                        Filing & date
                      </th>
                      <th scope="col" className="py-2 pe-4 text-end font-medium">
                        Verified edges
                      </th>
                      <th scope="col" className="py-2 text-end font-medium">
                        Rejected quotes
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.companies.map((comp) => {
                      const meta = COMPANY_STATUS_META[comp.status] ?? COMPANY_STATUS_META.done;
                      return (
                        <tr key={comp.company_key} className="border-b border-separator-border">
                          <td className="py-2 pe-4">
                            <div className="flex flex-col">
                              <span className="font-medium text-text-primary">
                                {comp.company_name}
                              </span>
                              <span className="font-mono text-caption-1-regular text-text-tertiary">
                                {comp.company_key}
                              </span>
                            </div>
                          </td>
                          <td className="py-2 pe-4 tabular-nums">
                            <Pct value={comp.exposure} digits={2} />
                          </td>
                          <td className="py-2 pe-4">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <StatusDot color={meta.dotColor} />
                              <Chip variant="caption" color={meta.chipColor}>
                                {meta.label}
                              </Chip>
                              {comp.extraction_quality === "fallback" && (
                                <Chip variant="caption" color="yellow">
                                  Fallback chunks
                                </Chip>
                              )}
                            </div>
                            {comp.message && (
                              <p className="mt-0.5 text-caption-1-regular text-text-tertiary">
                                {companyMessage(comp)}
                              </p>
                            )}
                          </td>
                          <td className="py-2 pe-4">
                            {comp.filing ? (
                              <a
                                href={comp.filing.url}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 text-text-primary underline hover:text-text-secondary"
                              >
                                <span>
                                  {comp.filing.form} ({comp.filing.filed})
                                </span>
                                <RiExternalLinkLine className="size-3.5" aria-hidden />
                              </a>
                            ) : (
                              <span className="text-text-tertiary">—</span>
                            )}
                          </td>
                          <td className="py-2 pe-4 text-end font-medium text-text-primary tabular-nums">
                            {comp.verified_edges}
                          </td>
                          <td className="py-2 text-end tabular-nums">
                            {comp.rejected_edges}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </details>
          </section>

          {/* 4. AI synthesis, straight after the audit bar so the key findings come first */}
          <InsightsPanel
            insights={result.insights}
            metricById={metricById}
            edgeById={edgeById}
            selectEdge={selectEdge}
          />

          {/* 5. Key numbers: one plain-English card per subject (% and company count together) */}
          {(metricCards.length > 0 || summaryFacts.length > 0) && (
            <section
              aria-label="Key dependency numbers"
              className="flex flex-col gap-3 rounded-3xl border border-border-button-default bg-background-secondary-default p-5"
            >
              <div className="flex flex-col gap-1">
                <h3 className="text-headline-small text-text-primary">Key numbers</h3>
                <p className="text-body-2-regular text-text-secondary">
                  Calculated directly from the verified filing quotes, not by the AI. Each of your
                  companies is counted once, so the percentages never double-count.
                </p>
              </div>
              {summaryFacts.length > 0 && (
                <ul className="flex flex-wrap gap-x-5 gap-y-1">
                  {summaryFacts.map(({ metric, text }) => (
                    <li key={metric.metric_id} className="text-body-2-regular text-text-secondary">
                      <span className="text-body-semibold text-text-primary tabular-nums">
                        {formatMetricValue(metric)}
                      </span>{" "}
                      {text}
                    </li>
                  ))}
                </ul>
              )}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {visibleMetricCards.map((card) => (
                  <div
                    key={card.share.metric_id}
                    className="flex flex-col justify-between gap-2 rounded-2xl border border-separator-border bg-background-primary-default p-4"
                  >
                    <div className="flex flex-col gap-1">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="text-caption-1-regular text-text-tertiary">
                          {card.category}
                        </span>
                        {card.singlePoint && (
                          <Chip variant="caption" color="orange">
                            Single point of failure
                          </Chip>
                        )}
                      </div>
                      <p className="text-body-semibold text-text-primary">{card.subject}</p>
                      <p className="text-body-2-regular text-text-secondary">
                        <span className="text-display-4-medium text-text-primary tabular-nums">
                          {formatMetricValue(card.share)}
                        </span>{" "}
                        {card.explanation}
                      </p>
                    </div>
                    {card.supportingEdgeIds.length > 0 && (
                      <details className="border-t border-separator-border pt-2">
                        <summary className="cursor-pointer text-caption-1-regular text-text-tertiary">
                          {card.supportingEdgeIds.length === 1
                            ? "1 source in the filings"
                            : `${card.supportingEdgeIds.length} sources in the filings`}
                        </summary>
                        <div className="flex flex-wrap gap-1.5 pt-2">
                          {card.supportingEdgeIds.map((edgeId) => {
                            const edge = edgeById.get(edgeId);
                            return (
                              <button
                                key={edgeId}
                                type="button"
                                onClick={() => selectEdge(edgeId, true)}
                                className="cursor-pointer rounded-md border border-border-button-default bg-background-secondary-default px-2 py-0.5 text-caption-1-regular text-text-primary hover:bg-background-primary-hover"
                              >
                                {edge ? `${edge.source_company_name} → ${edge.target_name}` : edgeId}
                              </button>
                            );
                          })}
                        </div>
                      </details>
                    )}
                  </div>
                ))}
              </div>
              {metricCards.length > METRIC_CARDS_SHOWN && (
                <div>
                  <Button
                    variant="ghost"
                    size="small"
                    onClick={() => setShowAllMetrics((shown) => !shown)}
                  >
                    {showAllMetrics
                      ? "Show only the largest"
                      : `Show all ${metricCards.length} numbers`}
                  </Button>
                </div>
              )}
            </section>
          )}

          {/* 6. Bipartite SVG Dependency Graph + Evidence Inspector */}
          <section
            aria-label="Supply-chain and counterparty dependency graph"
            className="flex flex-col gap-4 rounded-3xl border border-border-button-default bg-background-secondary-default p-5"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-col gap-0.5">
                <div className="flex items-center gap-2">
                  <RiLinksLine className="size-5 text-text-primary" aria-hidden />
                  <h3 className="text-headline-small text-text-primary">
                    Verified Counterparty & Supply-Chain Graph
                  </h3>
                </div>
                <p className="text-caption-1-regular text-text-secondary">
                  Showing {graph?.targets.length ?? 0} of {graph?.totalTargetsBeforeLimit ?? 0}{" "}
                  counterparties ({graph?.edges.length ?? 0} verified edges). Click any line or
                  circle to inspect its verbatim SEC filing quote.
                </p>
              </div>
              <div className="flex max-w-full flex-wrap items-center gap-2">
                {graph && graph.totalTargetsBeforeLimit > DEFAULT_TARGET_LIMIT && (
                  <Button
                    variant="secondary"
                    size="xs"
                    onClick={() => setShowAllTargets((prev) => !prev)}
                  >
                    {showAllTargets
                      ? `Show top ${DEFAULT_TARGET_LIMIT} counterparties`
                      : `Show all ${graph.totalTargetsBeforeLimit} counterparties`}
                  </Button>
                )}
                <div className="max-w-full overflow-x-auto pb-1">
                  <SegmentedControl
                    aria-label="Filter dependency edges by type"
                    selectedKeys={[edgeFilter]}
                    onSelectionChange={(keys) => {
                      const [key] = [...keys];
                      if (key) setEdgeFilter(String(key) as EdgeFilterGroup);
                    }}
                  >
                    <SegmentedControlItem id="all">
                      All ({result.edges.length})
                    </SegmentedControlItem>
                    <SegmentedControlItem id="supply_chain">
                      Suppliers & Foundries
                    </SegmentedControlItem>
                    <SegmentedControlItem id="sole_source">Sole source</SegmentedControlItem>
                    <SegmentedControlItem id="customers">Customers</SegmentedControlItem>
                    <SegmentedControlItem id="inputs">Key inputs</SegmentedControlItem>
                    <SegmentedControlItem id="facilities">Facilities</SegmentedControlItem>
                  </SegmentedControl>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3 text-caption-1-regular text-text-secondary">
              {(
                [
                  "sole_source",
                  "foundry",
                  "contract_manufacturer",
                  "supplier",
                  "customer",
                  "key_input",
                  "facility",
                ] as const
              ).map((typeKey) => {
                const meta = EDGE_TYPE_META[typeKey];
                return (
                  <span key={typeKey} className="inline-flex items-center gap-1.5">
                    <span
                      className="inline-block h-2.5 w-2.5 rounded-full"
                      style={{ backgroundColor: meta.color }}
                      aria-hidden
                    />
                    <span>{meta.shortLabel}</span>
                  </span>
                );
              })}
            </div>

            {graph && graph.edges.length > 0 ? (
              <div className="rounded-2xl border border-separator-border bg-background-primary-default p-3">
                <DependencyDiagram
                  graph={graph}
                  activeNodeId={activeNodeId}
                  selectedEdgeId={selectedEdgeId}
                  onHoverNode={setHoveredNodeId}
                  onSelectNode={(id) => selectNode(id, false)}
                  onSelectEdge={(edgeId) => selectEdge(edgeId, true)}
                />
              </div>
            ) : (
              <p className="rounded-2xl border border-separator-border bg-background-primary-default p-6 text-body-regular text-text-secondary">
                No verified dependency edges match the selected filter.
              </p>
            )}

            {/* Inline Evidence Inspector for selected node/edge */}
            <div
              aria-label="Selected dependency evidence"
              aria-live="polite"
              className="flex flex-col gap-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-body-semibold text-text-primary">
                  {activeNodeId
                    ? `Verified Evidence for Selected Node (${inspectedEdges.length})`
                    : selectedEdgeId
                      ? "Selected Edge Evidence"
                      : "Sample Verified Filing Evidence"}
                </h4>
                {(selectedEdgeId || selectedNodeId) && (
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() => {
                      selectEdge(null, false);
                      selectNode(null, false);
                    }}
                  >
                    Clear selection
                  </Button>
                )}
              </div>

              {inspectedEdges.length === 0 ? (
                <p className="text-body-2-regular text-text-secondary">
                  Select a node or line in the graph above to inspect the verbatim SEC filing quote.
                </p>
              ) : (
                <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                  {inspectedEdges.slice(0, 6).map((edge) => (
                    <EdgeEvidenceCard
                      key={edge.edge_id}
                      edge={edge}
                      exposureMap={exposureMap}
                      isSelected={edge.edge_id === selectedEdgeId && drawerOpen}
                      onSelect={(id) => selectEdge(id, true)}
                    />
                  ))}
                </div>
              )}
            </div>

            {result.edges.length > 0 && (
              <details className="rounded-2xl border border-separator-border bg-background-primary-default px-4 py-3">
                <summary className="cursor-pointer text-body-2-medium text-text-primary">
                  Show all {result.edges.length} verified edges as a table
                </summary>
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-start text-body-2-regular text-text-secondary">
                    <thead>
                      <tr className="border-b border-separator-border text-text-primary">
                        <th scope="col" className="py-2 pe-4 text-start font-medium">
                          Source company
                        </th>
                        <th scope="col" className="py-2 pe-4 text-start font-medium">
                          Relationship
                        </th>
                        <th scope="col" className="py-2 pe-4 text-start font-medium">
                          Target / Counterparty
                        </th>
                        <th scope="col" className="py-2 pe-4 text-start font-medium">
                          Verbatim filing quote
                        </th>
                        <th scope="col" className="py-2 pe-4 text-start font-medium">
                          Filing
                        </th>
                        <th scope="col" className="py-2 text-end font-medium">
                          Evidence
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.edges.map((edge) => {
                        const meta = edge.sole_source
                          ? EDGE_TYPE_META.sole_source
                          : (EDGE_TYPE_META[edge.edge_type] ?? EDGE_TYPE_META.supplier);
                        return (
                          <tr key={edge.edge_id} className="border-b border-separator-border">
                            <td className="py-2 pe-4 font-medium text-text-primary">
                              {edge.source_company_name}
                            </td>
                            <td className="py-2 pe-4">
                              <div className="flex flex-wrap gap-1">
                                <Chip variant="caption" color={meta.badgeColor}>
                                  {EDGE_TYPE_META[edge.edge_type]?.shortLabel ?? edge.edge_type}
                                </Chip>
                                {edge.sole_source && (
                                  <Chip variant="caption" color="rose">
                                    Sole source
                                  </Chip>
                                )}
                              </div>
                            </td>
                            <td className="py-2 pe-4 text-text-primary">
                              {edge.target_name}
                              {edge.qualifier ? ` (${edge.qualifier})` : ""}
                            </td>
                            <td className="max-w-md py-2 pe-4 italic">
                              “{edge.evidence_quote}”
                            </td>
                            <td className="py-2 pe-4">
                              <a
                                href={edge.filing.url}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 text-text-primary underline"
                              >
                                <span>
                                  {edge.filing.form} · {formatSectionLabel(edge.section)} (
                                  {edge.filing.filed})
                                </span>
                                <RiExternalLinkLine className="size-3.5" aria-hidden />
                              </a>
                            </td>
                            <td className="py-2 text-end">
                              <Button
                                variant="secondary"
                                size="xs"
                                onClick={() => selectEdge(edge.edge_id, true)}
                              >
                                View quote
                              </Button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </details>
            )}
          </section>

          {/* 6. Facility Concentration by Country (grouped strictly from backend `facility.<ISO2>` metrics) */}
          <section
            aria-label="Facility concentration by country"
            className="flex flex-col gap-4 rounded-3xl border border-border-button-default bg-background-secondary-default p-5"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <RiGlobalLine className="size-5 text-text-primary" aria-hidden />
                <h3 className="text-headline-small text-text-primary">
                  Facility & Manufacturing Concentration by Country
                </h3>
              </div>
              <span className="text-caption-1-regular text-text-tertiary">
                Grouped by canonical country from deterministic Python metrics, with named sites
                listed under each holding
              </span>
            </div>

            {facilityRows.length === 0 ? (
              <p className="rounded-2xl border border-separator-border bg-background-primary-default p-5 text-body-2-regular text-text-secondary">
                No verified facility or country edges were extracted for the current holdings.
              </p>
            ) : (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
                <div className="flex flex-col justify-center rounded-2xl border border-separator-border bg-background-primary-default p-4 lg:col-span-5">
                  <div
                    className="w-full"
                    style={{ height: Math.max(200, facilityRows.length * 44) }}
                  >
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        data={facilityRows.map((row) => ({
                          country: row.country,
                          exposurePct: Number((row.dependentExposure * 100).toFixed(2)),
                          companyCount: row.companyCount,
                        }))}
                        layout="vertical"
                        margin={{ top: 8, right: 24, bottom: 8, left: 16 }}
                      >
                        <XAxis
                          type="number"
                          unit="%"
                          tick={{ fontSize: 12 }}
                          stroke="var(--color-text-tertiary)"
                        />
                        <YAxis
                          type="category"
                          dataKey="country"
                          width={120}
                          tick={{ fontSize: 12 }}
                          stroke="var(--color-text-secondary)"
                        />
                        <Tooltip
                          formatter={(value) => [
                            `${Number(value).toFixed(2)}%`,
                            "Dependent exposure",
                          ]}
                        />
                        <Bar
                          dataKey="exposurePct"
                          fill="#0d9488"
                          radius={[0, 6, 6, 0]}
                        />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                <div className="flex flex-col gap-3 lg:col-span-7">
                  {facilityRows.map((row) => (
                    <div
                      key={row.countryCode}
                      className="flex flex-col gap-2.5 rounded-2xl border border-separator-border bg-background-primary-default p-4"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <RiBuilding2Line className="size-4 text-text-primary" aria-hidden />
                          <span className="text-body-semibold text-text-primary">
                            {row.country}
                          </span>
                          <Chip variant="caption" color="neutral">
                            {row.countryCode}
                          </Chip>
                          <Chip variant="caption" color="cyan">
                            {row.companyCount} {row.companyCount === 1 ? "company" : "companies"}
                          </Chip>
                        </div>
                        <span className="text-body-semibold text-text-primary tabular-nums">
                          <Pct value={row.dependentExposure} digits={2} /> of portfolio
                        </span>
                      </div>

                      <div className="flex flex-col gap-2">
                        {row.companies.map((c) => (
                          <div
                            key={c.companyKey}
                            className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-separator-border bg-background-secondary-default px-3 py-2 text-caption-1-regular"
                          >
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="font-medium text-text-primary">
                                {c.companyName}
                              </span>
                              <span className="text-text-tertiary tabular-nums">
                                ({formatPct(c.exposure, 2)})
                              </span>
                              {c.namedSites.map((site) => (
                                <button
                                  key={site.edgeId}
                                  type="button"
                                  onClick={() => selectEdge(site.edgeId, true)}
                                  className="cursor-pointer rounded-md border border-border-button-default bg-background-primary-default px-2 py-0.5 text-caption-1-regular text-text-primary hover:bg-background-primary-hover"
                                >
                                  Site: {site.siteName}
                                  {site.qualifier ? ` (${site.qualifier})` : ""}
                                </button>
                              ))}
                            </div>
                            <CollapsibleEdgeSources
                              edgeIds={c.edges.map((e) => e.edge_id)}
                              edgeById={edgeById}
                              onSelectEdge={(edgeId) => selectEdge(edgeId, true)}
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>
        </div>
      )}

      {/* 7. Slide-over Evidence Drawer for inspecting a selected VerifiedEdge */}
      <Drawer
        aria-label="SEC filing evidence drawer"
        isOpen={drawerOpen && drawerEdge !== null}
        onOpenChange={setDrawerOpen}
        placement="end"
        size="md"
      >
        <DrawerHeader
          title={
            drawerEdge
              ? `${drawerEdge.source_company_name} → ${drawerEdge.target_name}`
              : "Filing Evidence"
          }
        />
        <DrawerBody>
          {drawerEdge && (
            <div className="flex flex-col gap-4 py-2">
              <EdgeEvidenceCard
                edge={drawerEdge}
                exposureMap={exposureMap}
                isSelected
              />
              <div className="rounded-2xl border border-separator-border bg-background-secondary-default p-4 text-caption-1-regular text-text-secondary">
                <p className="font-medium text-text-primary">How this edge was verified:</p>
                <p className="mt-1">
                  Python normalised the canonical text of {drawerEdge.source_company_name}&apos;s SEC{" "}
                  {drawerEdge.filing.form} (accession{" "}
                  <code className="font-mono">{drawerEdge.filing.accession}</code>, filed{" "}
                  {drawerEdge.filing.filed}) and confirmed that the quote above appears verbatim in{" "}
                  {formatSectionLabel(drawerEdge.section)}.
                </p>
              </div>
            </div>
          )}
        </DrawerBody>
        <DrawerFooter className="flex items-center justify-between gap-2">
          {drawerEdge && (
            <a
              href={drawerEdge.filing.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-body-2-medium text-text-primary underline"
            >
              <span>Open full SEC {drawerEdge.filing.form} filing</span>
              <RiArrowRightUpLine className="size-4" aria-hidden />
            </a>
          )}
          <Button variant="secondary" size="small" onClick={() => setDrawerOpen(false)}>
            Close
          </Button>
        </DrawerFooter>
      </Drawer>
    </div>
  );
}

export default function DependenciesPage() {
  return (
    <DependenciesProvider>
      <DependenciesPageContent />
    </DependenciesProvider>
  );
}
