"use client";

import { useCallback, useMemo, useState, type CSSProperties } from "react";
import {
  RiAlertLine,
  RiArrowDownSLine,
  RiArrowRightSLine,
  RiArrowRightUpLine,
  RiBuilding2Line,
  RiCheckboxCircleLine,
  RiDatabase2Line,
  RiErrorWarningLine,
  RiExternalLinkLine,
  RiFileList3Line,
  RiInformationLine,
  RiPieChart2Line,
  RiRefreshLine,
  RiScales3Line,
  RiShieldCheckLine,
  RiSparklingLine,
} from "@remixicon/react";

import { api, ApiError } from "@/api/client";
import type {
  DataGap,
  EtfReport,
  EtfStatus,
  GapKind,
  GapSeverity,
  Sector,
  SectorBasis,
  SourceName,
} from "@/api/types";
import { useAnalysis } from "@/app/analysis";
import { AsOfBadge } from "@/app/ui/as-of-badge";
import { diversificationVerdict } from "@/app/ui/concentration";
import { EtfChip } from "@/app/ui/etf-chip";
import { etfVisual } from "@/app/ui/etf-color";
import { Pct, formatPct } from "@/app/ui/pct";
import { Chip, type ChipColor } from "@/components/base/badges/chip";
import { StatusDot } from "@/components/base/badges/status-dot";
import { Button } from "@/components/base/buttons/button";
import {
  SegmentedControl,
  SegmentedControlItem,
} from "@/components/base/segmented-control/segmented-control";
import { Spinner } from "@/components/base/spinner/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
} from "@/components/base/table/table";
import { cx } from "@/utils/cx";

const SECTOR_LABELS: Record<Sector, string> = {
  information_technology: "Information Technology",
  financials: "Financials",
  health_care: "Health Care",
  consumer_discretionary: "Consumer Discretionary",
  communication_services: "Communication Services",
  industrials: "Industrials",
  consumer_staples: "Consumer Staples",
  energy: "Energy",
  utilities: "Utilities",
  real_estate: "Real Estate",
  materials: "Materials",
  unknown: "Unknown / Unclassified",
};

const SECTOR_COLORS: Record<Sector, ChipColor> = {
  information_technology: "blue",
  financials: "cyan",
  health_care: "lime",
  consumer_discretionary: "purple",
  communication_services: "cyan",
  industrials: "gray",
  consumer_staples: "lime",
  energy: "orange",
  utilities: "yellow",
  real_estate: "rose",
  materials: "purple",
  unknown: "neutral",
};

const SOURCE_LABELS: Record<SourceName, string> = {
  tickerinside: "TickerInside",
  ishares: "iShares CSV",
  sec_nport: "SEC Form N-PORT",
  fake: "Synthetic Fixture",
};

const SECTOR_BASIS_META: Record<
  SectorBasis,
  { label: string; color: ChipColor; description: string }
> = {
  holdings: {
    label: "From company holdings",
    color: "lime",
    description: "Computed directly from the industries of the individual companies held",
  },
  fund_reported: {
    label: "Fund breakdown",
    color: "cyan",
    description: "Scaled from the ETF's published industry breakdown",
  },
  none: {
    label: "No industry data",
    color: "rose",
    description: "Source provides no industry tags; assigned to Unknown",
  },
};

const ETF_STATUS_META: Record<
  EtfStatus,
  { label: string; chipColor: ChipColor; dotColor: "green" | "yellow" | "indigo" }
> = {
  ok: { label: "OK", chipColor: "lime", dotColor: "green" },
  warning: { label: "Warning", chipColor: "yellow", dotColor: "yellow" },
  unavailable: { label: "Unavailable", chipColor: "rose", dotColor: "indigo" },
};

const GAP_KIND_LABELS: Record<GapKind, string> = {
  missing_etf: "Missing ETF",
  unmatched_identity: "Unmatched Identity",
  nested_fund: "Nested Fund",
  stale_disclosure: "Stale Disclosure",
  low_coverage: "Low Coverage",
  excluded_lines: "Excluded Non-Equity",
  no_sector_data: "No Sector Data",
};

const GAP_SEVERITY_META: Record<
  GapSeverity,
  { label: string; chipColor: ChipColor; borderClass: string }
> = {
  critical: {
    label: "Critical",
    chipColor: "rose",
    borderClass: "border-border-error-default",
  },
  warning: {
    label: "Warning",
    chipColor: "yellow",
    borderClass: "border-border-button-default",
  },
  info: {
    label: "Info",
    chipColor: "blue",
    borderClass: "border-border-button-default",
  },
};

/** Avoid displaying "-0.00%" when a weight is a tiny negative (e.g. short futures line in XLK). */
function cleanSignedZero(value: number, digits = 2): number {
  const threshold = 0.5 * Math.pow(10, -(digits + 2));
  return Math.abs(value) < threshold ? 0 : value;
}

function errorCopy(error: ApiError): string {
  const tickers = (error.details as { tickers?: string[] } | undefined)?.tickers;
  if (error.code === "UNKNOWN_TICKER" && tickers?.length) {
    return `We couldn't find ${tickers.join(", ")} in any data source. Check the ticker on the Portfolio page.`;
  }
  if (error.code === "SOURCES_UNAVAILABLE") {
    return "None of the data sources could be reached, so we have no holdings to evaluate.";
  }
  if (error.code === "NETWORK_ERROR") {
    return "We couldn't reach the analysis service. Check that the backend is running.";
  }
  return error.message;
}

function etfBarStyle(index: number, widthPct: number): CSSProperties {
  const { color, dash } = etfVisual(index);
  return {
    width: `${widthPct}%`,
    backgroundColor: color,
    backgroundImage: dash
      ? "repeating-linear-gradient(135deg, transparent 0 4px, var(--color-background-primary-default) 4px 6px)"
      : undefined,
  };
}

function etfDotStyle(index: number): CSSProperties {
  const { color, dash } = etfVisual(index);
  return dash
    ? {
        backgroundColor: color,
        boxShadow: "inset 0 0 0 1.5px var(--color-background-primary-default)",
        border: `1.5px dashed ${color}`,
      }
    : { backgroundColor: color };
}

export default function RiskPage() {
  const { analysis, status, stale, error, retry, setRows } = useAnalysis();
  const [loadingExample, setLoadingExample] = useState(false);
  const [exampleError, setExampleError] = useState<string | null>(null);

  // Interactive controls
  const [topNMode, setTopNMode] = useState<"top5" | "top10" | "top20">("top5");
  const [sectorBarMode, setSectorBarMode] = useState<"stacked" | "total">("stacked");
  const [gapSeverityFilter, setGapSeverityFilter] = useState<"all" | GapSeverity>("all");
  const [expandedEtfs, setExpandedEtfs] = useState<Record<string, boolean>>({});

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

  const etfIndexMap = useMemo(() => {
    const map = new Map<string, number>();
    if (!analysis) return map;
    analysis.etfs.forEach((etf, idx) => {
      map.set(etf.ticker, idx);
    });
    return map;
  }, [analysis]);

  const unavailableEtfs = useMemo<EtfReport[]>(() => {
    if (!analysis) return [];
    return analysis.etfs.filter((e) => e.status === "unavailable");
  }, [analysis]);

  const gapCounts = useMemo(() => {
    const counts = { all: 0, critical: 0, warning: 0, info: 0 };
    if (!analysis) return counts;
    for (const gap of analysis.gaps) {
      counts.all += 1;
      counts[gap.severity] += 1;
    }
    return counts;
  }, [analysis]);

  const filteredGaps = useMemo<DataGap[]>(() => {
    if (!analysis) return [];
    if (gapSeverityFilter === "all") return analysis.gaps;
    return analysis.gaps.filter((g) => g.severity === gapSeverityFilter);
  }, [analysis, gapSeverityFilter]);

  const toggleEtfDetails = useCallback((ticker: string) => {
    setExpandedEtfs((prev) => ({ ...prev, [ticker]: !prev[ticker] }));
  }, []);

  if (!analysis) {
    if (status === "loading") {
      return (
        <section
          aria-live="polite"
          className="flex flex-col items-center justify-center gap-3 rounded-3xl border border-border-button-default bg-background-secondary-default p-10 text-center"
        >
          <Spinner size="md" />
          <p className="text-body-medium text-text-primary">
            Evaluating portfolio concentration, sector exposures, and data provenance…
          </p>
          <p className="text-body-2-regular text-text-secondary">
            Verifying coverage accounting, disclosure freshness, and source attributions.
          </p>
        </section>
      );
    }

    if (status === "error" && error) {
      return (
        <section
          role="alert"
          className="flex flex-col items-start gap-4 rounded-3xl border border-border-error-default bg-background-secondary-default p-6"
        >
          <div className="flex items-center gap-2 text-text-error-primary">
            <RiErrorWarningLine className="size-5 shrink-0" aria-hidden />
            <h2 className="text-headline-medium">
              Could not load risk &amp; data report ({error.code})
            </h2>
          </div>
          <p className="text-body-regular text-text-secondary">{errorCopy(error)}</p>
          <div className="flex flex-wrap items-center gap-3">
            {error.code !== "UNKNOWN_TICKER" && (
              <Button variant="primary" size="small" leadingIcon={RiRefreshLine} onClick={retry}>
                Retry analysis
              </Button>
            )}
            <Button
              variant="secondary"
              size="small"
              onClick={() => {
                location.hash = "#/portfolio";
              }}
            >
              Edit portfolio
            </Button>
          </div>
        </section>
      );
    }

    return (
      <section className="flex flex-col items-start gap-4 rounded-3xl border border-border-button-default bg-background-secondary-default p-6">
        <div className="flex flex-col gap-1">
          <h2 className="text-headline-medium text-text-primary">
            No valid portfolio loaded yet
          </h2>
          <p className="text-body-regular text-text-secondary">
            Enter ETF tickers totaling 100% on the Portfolio page, or load a verified example
            portfolio to inspect concentration metrics, industry breakdown, coverage accounting,
            and source disclosure dates.
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
          <Button
            variant="secondary"
            size="small"
            trailingIcon={RiArrowRightUpLine}
            onClick={() => {
              location.hash = "#/portfolio";
            }}
          >
            Open Portfolio builder
          </Button>
        </div>
      </section>
    );
  }

  const { concentration, coverage, sectors, etfs, attributions, warnings } = analysis;
  const hhiMeta = diversificationVerdict({ hhi: concentration.hhi, sectors });
  const selectedTopNWeight =
    topNMode === "top5"
      ? concentration.top5
      : topNMode === "top10"
        ? concentration.top10
        : concentration.top20;
  const selectedTopNCount = topNMode === "top5" ? 5 : topNMode === "top10" ? 10 : 20;
  const topCompaniesPreview = analysis.exposures.slice(0, 5);
  const mergedListingsDelta = Math.max(
    0,
    concentration.distinct_securities - concentration.distinct_companies,
  );
  const maxSectorWeight = Math.max(0.01, ...sectors.map((s) => s.weight));
  const totalAlloc = Math.max(coverage.total_allocation, 1e-9);

  return (
    <div className="flex w-full flex-col gap-6">
      {/* Background refresh / stale notice */}
      {(stale || status === "loading") && (
        <div
          role="status"
          className="flex items-center justify-between gap-3 rounded-2xl border border-border-button-default bg-background-secondary-default px-4 py-2.5"
        >
          <div className="flex items-center gap-2 text-body-2-medium text-text-secondary">
            <Spinner size="sm" />
            <span>Updating risk, sector, and coverage diagnostics…</span>
          </div>
        </div>
      )}

      {/* Non-blocking error banner when previous analysis is still displayed */}
      {status === "error" && error && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border-error-default bg-background-secondary-default px-4 py-3"
        >
          <div className="flex items-center gap-2 text-body-2-medium text-text-error-primary">
            <RiErrorWarningLine className="size-4 shrink-0" aria-hidden />
            <span>
              {errorCopy(error)} (showing last valid analysis)
            </span>
          </div>
          <div className="flex items-center gap-2">
            {error.code !== "UNKNOWN_TICKER" && (
              <Button variant="secondary" size="xs" leadingIcon={RiRefreshLine} onClick={retry}>
                Retry
              </Button>
            )}
            <Button
              variant="secondary"
              size="xs"
              onClick={() => {
                location.hash = "#/portfolio";
              }}
            >
              Edit portfolio
            </Button>
          </div>
        </div>
      )}

      {/* Unavailable ETF alert banner when partial outage occurs */}
      {unavailableEtfs.length > 0 && (
        <section
          role="alert"
          aria-label="Unavailable ETFs alert"
          className="flex flex-col gap-2 rounded-2xl border border-border-error-default bg-background-secondary-default p-4"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-text-error-primary">
              <RiAlertLine className="size-5 shrink-0" aria-hidden />
              <h2 className="text-body-semibold">
                {unavailableEtfs.length} ETF{unavailableEtfs.length > 1 ? "s" : ""} could not be
                loaded (<Pct value={coverage.missing_allocation} digits={2} /> of portfolio
                not covered)
              </h2>
            </div>
            <Chip variant="subtle" color="rose">
              Partial coverage
            </Chip>
          </div>
          <p className="text-body-2-regular text-text-secondary">
            Remaining ETFs keep their true share of your portfolio so missing funds stay visible:
          </p>
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {unavailableEtfs.map((u) => {
              const idx = etfIndexMap.get(u.ticker) ?? 0;
              return (
                <div
                  key={u.ticker}
                  className="flex items-center gap-2 rounded-lg border border-separator-border bg-background-primary-default px-2.5 py-1.5 text-caption-1-regular"
                >
                  <span
                    className="size-2 rounded-full"
                    style={etfDotStyle(idx)}
                    aria-hidden
                  />
                  <EtfChip ticker={u.ticker} />
                  <span className="text-text-secondary">
                    Allocation: <Pct value={u.allocation} digits={2} />
                  </span>
                  {u.attempts.length > 0 && (
                    <span className="text-text-tertiary">
                      ({u.attempts.map((a) => `${a.source}: ${a.outcome}`).join(", ")})
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Section 1: Concentration & Coverage StatCards */}
      <section
        aria-label="Concentration and risk summary cards"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4"
      >
        {/* Card 1: Top-5 / Top-10 / Top-20 Concentration */}
        <div className="flex flex-col justify-between gap-3 rounded-2xl border border-border-button-default bg-background-secondary-default p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-body-2-medium text-text-secondary">Top-N concentration</span>
            <SegmentedControl
              aria-label="Top N concentration selector"
              selectedKeys={new Set([topNMode])}
              onSelectionChange={(keys) => {
                const next = [...keys][0];
                if (next === "top5" || next === "top10" || next === "top20") {
                  setTopNMode(next);
                }
              }}
            >
              <SegmentedControlItem id="top5">Top 5</SegmentedControlItem>
              <SegmentedControlItem id="top10">Top 10</SegmentedControlItem>
              <SegmentedControlItem id="top20">Top 20</SegmentedControlItem>
            </SegmentedControl>
          </div>

          <div className="flex items-baseline justify-between gap-2">
            <Pct
              value={selectedTopNWeight}
              digits={2}
              className="text-title-2-medium text-text-primary"
            />
            <span className="text-caption-1-regular text-text-tertiary tabular-nums">
              Top 5: <Pct value={concentration.top5} digits={2} /> · Top 10:{" "}
              <Pct value={concentration.top10} digits={2} />
            </span>
          </div>

          <div className="flex flex-col gap-1.5">
            <div
              className="h-2 w-full overflow-hidden rounded-full bg-background-tertiary-default"
              aria-hidden
            >
              <div
                className="h-full rounded-full bg-chart-1 transition-[width] duration-200"
                style={{ width: `${Math.min(100, Math.max(0, selectedTopNWeight * 100))}%` }}
              />
            </div>
            <p className="text-caption-1-regular text-text-tertiary">
              Share of total portfolio held in the {selectedTopNCount} largest companies.
            </p>
          </div>
        </div>

        {/* Card 2: Effective Companies */}
        <div
          className="flex flex-col justify-between gap-3 rounded-2xl border border-border-button-default bg-background-secondary-default p-4"
          title={`Herfindahl-Hirschman concentration index (HHI): ${concentration.hhi.toFixed(4)} (${Math.round(concentration.hhi * 10_000).toLocaleString()} pts)`}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-body-2-medium text-text-secondary">
              Effective company count
            </span>
            <RiScales3Line className="size-4 text-foreground-icon-tertiary" aria-hidden />
          </div>

          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div className="flex items-baseline gap-2">
              <span className="text-title-2-medium text-text-primary tabular-nums">
                {concentration.effective_companies.toFixed(1)}
              </span>
              <span className="text-caption-1-regular text-text-tertiary">
                equal-sized companies
              </span>
            </div>
            <Chip variant="caption" color={hhiMeta.color}>
              {hhiMeta.label}
            </Chip>
          </div>

          <p className="text-caption-1-regular text-text-tertiary">
            How many equal-sized holdings this portfolio behaves like.
          </p>
        </div>

        {/* Card 3: Distinct Companies vs Securities */}
        <div className="flex flex-col justify-between gap-3 rounded-2xl border border-border-button-default bg-background-secondary-default p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-body-2-medium text-text-secondary">
              Distinct companies &amp; listings
            </span>
            <RiBuilding2Line className="size-4 text-foreground-icon-tertiary" aria-hidden />
          </div>

          <div className="flex items-baseline justify-between gap-2">
            <div className="flex items-baseline gap-2">
              <span className="text-title-2-medium text-text-primary tabular-nums">
                {concentration.distinct_companies.toLocaleString()}
              </span>
              <span className="text-caption-1-regular text-text-tertiary">companies</span>
            </div>
            <span className="text-body-2-medium text-text-secondary tabular-nums">
              {concentration.distinct_securities.toLocaleString()} securities
            </span>
          </div>

          <p className="text-caption-1-regular text-text-tertiary">
            {mergedListingsDelta > 0
              ? `${mergedListingsDelta} duplicate share class / ADR listing${mergedListingsDelta === 1 ? "" : "s"} merged (such as GOOG and GOOGL).`
              : "Every security resolves to a distinct company."}
          </p>
        </div>

        {/* Card 4: Holdings Traced to Companies & Data Quality */}
        <div className="flex flex-col justify-between gap-3 rounded-2xl border border-border-button-default bg-background-secondary-default p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-body-2-medium text-text-secondary">
              Holdings traced to companies
            </span>
            <RiShieldCheckLine className="size-4 text-foreground-icon-tertiary" aria-hidden />
          </div>

          <div className="flex items-baseline justify-between gap-2">
            <Pct
              value={coverage.covered_weight}
              digits={2}
              className="text-title-2-medium text-text-primary"
            />
            <AsOfBadge date={analysis.as_of_date} />
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 text-caption-1-regular text-text-tertiary">
            <span>
              Industry known: <Pct value={coverage.sector_known_weight} digits={1} />
            </span>
            <span>
              Unmatched: <Pct value={coverage.unmatched_weight} digits={2} />
            </span>
          </div>
        </div>
      </section>

      {/* Section 2: Portfolio Coverage Stacked Bar + Top-5 Concentration Strip */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Coverage Stacked Bar Card */}
        <section
          aria-labelledby="coverage-heading"
          className="flex flex-col justify-between gap-4 rounded-3xl border border-border-button-default bg-background-secondary-default p-5 lg:col-span-7"
        >
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="flex flex-col gap-0.5">
              <h2 id="coverage-heading" className="text-headline-medium text-text-primary">
                Portfolio coverage accounting
              </h2>
              <p className="text-body-2-regular text-text-secondary">
                How every dollar of your <Pct value={coverage.total_allocation} digits={2} />{" "}
                portfolio breaks down between company holdings, non-equity items, and gaps.
              </p>
            </div>
            <Chip
              variant="subtle"
              color={coverage.covered_weight >= 0.95 ? "lime" : "yellow"}
            >
              <Pct value={coverage.covered_weight} digits={2} /> covered
            </Chip>
          </div>

          {/* 4-part stacked bar: covered + excluded + missing + unexplained == total_allocation */}
          <div className="flex flex-col gap-2">
            <div
              role="img"
              aria-label={`Coverage breakdown: Covered ${formatPct(coverage.covered_weight)}, Excluded ${formatPct(cleanSignedZero(coverage.excluded_weight))}, Missing ${formatPct(coverage.missing_allocation)}, Unexplained ${formatPct(cleanSignedZero(coverage.unexplained_weight))}`}
              className="flex h-4 w-full overflow-hidden rounded-full border border-separator-border bg-background-tertiary-default"
            >
              {coverage.covered_weight > 0 && (
                <div
                  className="h-full bg-chart-1 transition-[width] duration-200"
                  style={{ width: `${Math.min(100, (coverage.covered_weight / totalAlloc) * 100)}%` }}
                  title={`Covered company holdings: ${formatPct(coverage.covered_weight)}`}
                />
              )}
              {coverage.excluded_weight > 0 && (
                <div
                  className="h-full bg-chart-3 transition-[width] duration-200"
                  style={{ width: `${Math.min(100, (coverage.excluded_weight / totalAlloc) * 100)}%` }}
                  title={`Excluded cash, derivatives & FX: ${formatPct(cleanSignedZero(coverage.excluded_weight))}`}
                />
              )}
              {coverage.missing_allocation > 0 && (
                <div
                  className="h-full bg-chart-5 transition-[width] duration-200"
                  style={{ width: `${Math.min(100, (coverage.missing_allocation / totalAlloc) * 100)}%` }}
                  title={`Missing ETF allocation: ${formatPct(coverage.missing_allocation)}`}
                />
              )}
              {coverage.unexplained_weight > 0 && (
                <div
                  className="h-full bg-chart-4 transition-[width] duration-200"
                  style={{ width: `${Math.min(100, (coverage.unexplained_weight / totalAlloc) * 100)}%` }}
                  title={`Unexplained weight drift: ${formatPct(cleanSignedZero(coverage.unexplained_weight))}`}
                />
              )}
            </div>

            {/* Legend & numeric breakdown */}
            <div className="grid grid-cols-2 gap-2.5 pt-1 sm:grid-cols-4">
              <div className="flex flex-col gap-0.5 rounded-xl border border-separator-border bg-background-primary-default p-2.5">
                <div className="flex items-center gap-1.5 text-caption-1-medium text-text-secondary">
                  <span className="size-2.5 rounded-full bg-chart-1" aria-hidden />
                  <span>Covered equity</span>
                </div>
                <Pct
                  value={coverage.covered_weight}
                  digits={2}
                  className="text-body-semibold text-text-primary"
                />
                <span className="text-caption-1-regular text-text-tertiary">
                  Traced to companies
                </span>
              </div>

              <div className="flex flex-col gap-0.5 rounded-xl border border-separator-border bg-background-primary-default p-2.5">
                <div className="flex items-center gap-1.5 text-caption-1-medium text-text-secondary">
                  <span className="size-2.5 rounded-full bg-chart-3" aria-hidden />
                  <span>Excluded items</span>
                </div>
                <Pct
                  value={cleanSignedZero(coverage.excluded_weight)}
                  digits={2}
                  className="text-body-semibold text-text-primary"
                />
                <span className="text-caption-1-regular text-text-tertiary">
                  {coverage.excluded_weight < 0
                    ? "Short futures / cash offset"
                    : "Cash, futures & FX"}
                </span>
              </div>

              <div className="flex flex-col gap-0.5 rounded-xl border border-separator-border bg-background-primary-default p-2.5">
                <div className="flex items-center gap-1.5 text-caption-1-medium text-text-secondary">
                  <span className="size-2.5 rounded-full bg-chart-5" aria-hidden />
                  <span>Missing ETFs</span>
                </div>
                <Pct
                  value={cleanSignedZero(coverage.missing_allocation)}
                  digits={2}
                  className="text-body-semibold text-text-primary"
                />
                <span className="text-caption-1-regular text-text-tertiary">
                  Failed source loads
                </span>
              </div>

              <div className="flex flex-col gap-0.5 rounded-xl border border-separator-border bg-background-primary-default p-2.5">
                <div className="flex items-center gap-1.5 text-caption-1-medium text-text-secondary">
                  <span className="size-2.5 rounded-full bg-chart-4" aria-hidden />
                  <span>Unexplained</span>
                </div>
                <Pct
                  value={cleanSignedZero(coverage.unexplained_weight)}
                  digits={2}
                  className="text-body-semibold text-text-primary"
                />
                <span className="text-caption-1-regular text-text-tertiary">
                  Rounding remainder
                </span>
              </div>
            </div>
          </div>

          {/* Quality sub-metrics: Sector known vs Unmatched identity */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-separator-border pt-3 text-caption-1-regular text-text-secondary">
            <span>
              Loaded ETFs allocation:{" "}
              <Pct
                value={coverage.loaded_allocation}
                digits={2}
                className="font-medium text-text-primary"
              />
            </span>
            <span>
              Industry-mapped weight:{" "}
              <Pct
                value={coverage.sector_known_weight}
                digits={2}
                className="font-medium text-text-primary"
              />
            </span>
            <span>
              Unmatched companies:{" "}
              <Pct
                value={coverage.unmatched_weight}
                digits={2}
                className="font-medium text-text-primary"
              />
            </span>
          </div>
        </section>

        {/* Top-5 Contributors to Concentration Card */}
        <section
          aria-labelledby="top5-contributors-heading"
          className="flex flex-col justify-between gap-4 rounded-3xl border border-border-button-default bg-background-secondary-default p-5 lg:col-span-5"
        >
          <div className="flex items-start justify-between gap-2">
            <div className="flex flex-col gap-0.5">
              <h2 id="top5-contributors-heading" className="text-headline-medium text-text-primary">
                Top-5 company concentration
              </h2>
              <p className="text-body-2-regular text-text-secondary">
                Largest single-name exposures driving <Pct value={concentration.top5} digits={2} />{" "}
                of the portfolio.
              </p>
            </div>
            <Button
              variant="secondary"
              size="xs"
              trailingIcon={RiArrowRightUpLine}
              onClick={() => {
                location.hash = "#/exposures";
              }}
            >
              All exposures
            </Button>
          </div>

          <div className="flex flex-col gap-2.5">
            {topCompaniesPreview.map((company) => {
              const widthPct = Math.min(
                100,
                Math.max(2, (company.exposure / Math.max(concentration.top5, 0.01)) * 100),
              );
              return (
                <div
                  key={company.company_key}
                  className="flex flex-col gap-1 rounded-xl border border-separator-border bg-background-primary-default px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="text-caption-1-semibold text-text-tertiary tabular-nums">
                        #{company.rank}
                      </span>
                      <span className="truncate text-body-2-medium text-text-primary">
                        {company.company_name}
                      </span>
                      {company.symbols[0] && (
                        <span className="rounded bg-background-secondary-default px-1.5 py-0.5 font-mono text-caption-1-regular text-text-secondary">
                          {company.symbols.join(", ")}
                        </span>
                      )}
                    </div>
                    <Pct
                      value={company.exposure}
                      digits={2}
                      className="text-body-2-medium text-text-primary"
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <div
                      className="flex h-1.5 flex-1 overflow-hidden rounded-full bg-background-tertiary-default"
                      aria-hidden
                    >
                      {company.contributions.map((c) => {
                        const etfIdx = etfIndexMap.get(c.etf_ticker) ?? 0;
                        const segPct =
                          company.exposure > 0
                            ? (c.contribution / company.exposure) * widthPct
                            : 0;
                        return (
                          <span
                            key={c.etf_ticker}
                            className="h-full"
                            style={etfBarStyle(etfIdx, segPct)}
                          />
                        );
                      })}
                    </div>
                    <span className="text-caption-1-regular text-text-tertiary tabular-nums">
                      {company.etf_count} ETF{company.etf_count > 1 ? "s" : ""}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      </div>

      {/* Section 3: GICS Sector Breakdown Bars */}
      <section
        aria-labelledby="sector-breakdown-heading"
        className="flex flex-col gap-4 rounded-3xl border border-border-button-default bg-background-secondary-default p-5"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <RiPieChart2Line className="size-5 text-foreground-icon-secondary" aria-hidden />
              <h2 id="sector-breakdown-heading" className="text-headline-medium text-text-primary">
                Industry breakdown
              </h2>
            </div>
            <p className="text-body-2-regular text-text-secondary">
              Each bar adds up what every ETF contributes to that industry across your covered
              holdings (<Pct value={coverage.covered_weight} digits={2} />).
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* ETF colour legend + sector basis per ETF */}
            <div
              className="flex flex-wrap items-center gap-2"
              aria-label="ETF colour key and sector basis"
            >
              {etfs.map((etf, idx) => {
                const basisMeta = SECTOR_BASIS_META[etf.sector_basis];
                return (
                  <span
                    key={etf.ticker}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-separator-border bg-background-primary-default px-2 py-1 text-caption-1-regular"
                    title={`${etf.ticker} sector source: ${basisMeta.description}`}
                  >
                    <span
                      className="size-2.5 rounded-full"
                      style={etfDotStyle(idx)}
                      aria-hidden
                    />
                    <EtfChip ticker={etf.ticker} />
                    <span className="text-text-tertiary">{basisMeta.label}</span>
                  </span>
                );
              })}
            </div>

            <SegmentedControl
              aria-label="Sector bar display mode"
              selectedKeys={new Set([sectorBarMode])}
              onSelectionChange={(keys) => {
                const next = [...keys][0];
                if (next === "stacked" || next === "total") {
                  setSectorBarMode(next);
                }
              }}
            >
              <SegmentedControlItem id="stacked">By ETF</SegmentedControlItem>
              <SegmentedControlItem id="total">Total</SegmentedControlItem>
            </SegmentedControl>
          </div>
        </div>

        <div className="flex flex-col gap-3">
          {sectors.map((sec) => {
            const shareOfCovered =
              coverage.covered_weight > 0 ? sec.weight / coverage.covered_weight : 0;
            const totalBarPct = Math.min(100, Math.max(0.5, (sec.weight / maxSectorWeight) * 100));

            return (
              <div
                key={sec.sector}
                className="flex flex-col gap-2 rounded-2xl border border-separator-border bg-background-primary-default p-3.5"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Chip variant="subtle" color={SECTOR_COLORS[sec.sector] ?? "neutral"}>
                      {SECTOR_LABELS[sec.sector] ?? sec.sector}
                    </Chip>
                    <span className="text-caption-1-regular text-text-tertiary tabular-nums">
                      ({formatPct(shareOfCovered, 1)} of covered equity)
                    </span>
                  </div>

                  <div className="flex items-center gap-3">
                    <div className="hidden flex-wrap items-center gap-2 sm:flex">
                      {sec.by_etf.map((contrib) => {
                        const etfIdx = etfIndexMap.get(contrib.etf_ticker) ?? 0;
                        return (
                          <span
                            key={contrib.etf_ticker}
                            className="inline-flex items-center gap-1 text-caption-1-regular text-text-secondary tabular-nums"
                          >
                            <span
                              className="size-2 rounded-full"
                              style={etfDotStyle(etfIdx)}
                              aria-hidden
                            />
                            <span className="font-mono text-text-tertiary">
                              {contrib.etf_ticker}:
                            </span>
                            <Pct value={contrib.contribution} digits={2} />
                          </span>
                        );
                      })}
                    </div>
                    <Pct
                      value={sec.weight}
                      digits={2}
                      className="text-body-semibold text-text-primary"
                    />
                  </div>
                </div>

                {/* Horizontal bar */}
                <div
                  className="flex h-3 w-full overflow-hidden rounded-full bg-background-tertiary-default"
                  aria-hidden
                >
                  {sectorBarMode === "stacked" ? (
                    sec.by_etf.map((contrib) => {
                      const etfIdx = etfIndexMap.get(contrib.etf_ticker) ?? 0;
                      const segWidthPct =
                        maxSectorWeight > 0
                          ? Math.min(100, (contrib.contribution / maxSectorWeight) * 100)
                          : 0;
                      return (
                        <div
                          key={contrib.etf_ticker}
                          className="h-full transition-[width] duration-200"
                          style={etfBarStyle(etfIdx, segWidthPct)}
                          title={`${contrib.etf_ticker}: ${formatPct(contrib.contribution)}`}
                        />
                      );
                    })
                  ) : (
                    <div
                      className="h-full rounded-full bg-chart-1 transition-[width] duration-200"
                      style={{ width: `${totalBarPct}%` }}
                    />
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Section 4: ETF Sources, Disclosure Dates & Attribution Table */}
      <section
        aria-labelledby="sources-table-heading"
        className="flex flex-col gap-4 rounded-3xl border border-border-button-default bg-background-secondary-default p-5"
      >
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <RiDatabase2Line className="size-5 text-foreground-icon-secondary" aria-hidden />
              <h2 id="sources-table-heading" className="text-headline-medium text-text-primary">
                ETF sources, disclosure dates &amp; attribution
              </h2>
            </div>
            <p className="text-body-2-regular text-text-secondary">
              Per-ETF data provenance, holdings disclosure age (vs {analysis.as_of_date}), sector
              basis, and licensing attribution.
            </p>
          </div>
        </div>

        <Table aria-label="ETF data sources and disclosure dates" size="md">
          <TableHeader>
            <TableColumn className="w-[180px]">ETF &amp; Allocation</TableColumn>
            <TableColumn className="w-[120px]">Status</TableColumn>
            <TableColumn className="w-[180px]">Source</TableColumn>
            <TableColumn className="w-[170px]">Disclosure Date</TableColumn>
            <TableColumn className="w-[160px]">Industry Source</TableColumn>
            <TableColumn className="w-[180px]">Holdings Coverage</TableColumn>
            <TableColumn className="min-w-[240px]">Attribution &amp; Links</TableColumn>
          </TableHeader>
          <TableBody>
            {etfs.map((etf, idx) => {
              const statusMeta = ETF_STATUS_META[etf.status];
              const basisMeta = SECTOR_BASIS_META[etf.sector_basis];
              const isExpanded = !!expandedEtfs[etf.ticker];
              const hasExtraDetails = etf.warnings.length > 0 || etf.attempts.length > 0;

              return (
                <TableRow key={etf.ticker}>
                  <TableCell>
                    <div className="flex flex-col gap-1 py-0.5">
                      <div className="flex items-center gap-2">
                        <span
                          className="size-2.5 shrink-0 rounded-full"
                          style={etfDotStyle(idx)}
                          aria-hidden
                        />
                        <EtfChip ticker={etf.ticker} />
                        <Pct
                          value={etf.allocation}
                          digits={1}
                          className="text-body-2-medium text-text-primary"
                        />
                      </div>
                      {etf.name && (
                        <span className="truncate text-caption-1-regular text-text-secondary">
                          {etf.name}
                        </span>
                      )}
                    </div>
                  </TableCell>

                  <TableCell>
                    <div className="flex items-center gap-1.5">
                      <StatusDot color={statusMeta.dotColor} />
                      <Chip variant="caption" color={statusMeta.chipColor}>
                        {statusMeta.label}
                      </Chip>
                    </div>
                  </TableCell>

                  <TableCell>
                    <div className="flex flex-col gap-0.5">
                      <span
                        className="text-body-2-medium text-text-primary"
                        title={etf.source_layer ? `Source layer: ${etf.source_layer}` : undefined}
                      >
                        {etf.source ? SOURCE_LABELS[etf.source] : "None"}
                      </span>
                    </div>
                  </TableCell>

                  <TableCell>
                    <div className="flex flex-col items-start gap-1">
                      <AsOfBadge date={etf.as_of} />
                      {typeof etf.age_days === "number" && (
                        <span className="text-caption-1-regular text-text-tertiary tabular-nums">
                          {etf.age_days} day{etf.age_days === 1 ? "" : "s"} old
                        </span>
                      )}
                    </div>
                  </TableCell>

                  <TableCell>
                    <div className="flex flex-col items-start gap-1">
                      <Chip
                        variant="caption"
                        color={basisMeta.color}
                        title={basisMeta.description}
                      >
                        {basisMeta.label}
                      </Chip>
                      <span className="text-caption-1-regular text-text-tertiary tabular-nums">
                        {etf.company_count.toLocaleString()} companies ·{" "}
                        {etf.holdings_count.toLocaleString()} holdings
                      </span>
                    </div>
                  </TableCell>

                  <TableCell>
                    <div className="flex flex-col gap-0.5 text-caption-1-regular">
                      <span className="text-text-primary">
                        Holdings: <Pct value={etf.holdings_weight} digits={2} />
                      </span>
                      <span className="text-text-tertiary">
                        Excluded: <Pct value={cleanSignedZero(etf.excluded_weight)} digits={2} /> · Unmatched:{" "}
                        <Pct value={cleanSignedZero(etf.unmatched_weight)} digits={2} />
                      </span>
                      <span className="text-text-secondary">
                        Portfolio coverage:{" "}
                        <Pct
                          value={etf.portfolio_covered_weight}
                          digits={2}
                          className="font-medium text-text-primary"
                        />
                      </span>
                    </div>
                  </TableCell>

                  <TableCell>
                    <div className="flex flex-col gap-1.5 py-0.5">
                      <div className="flex flex-wrap items-center gap-2">
                        {etf.licence && (
                          <Chip variant="caption" color="neutral">
                            {etf.licence}
                          </Chip>
                        )}
                        {etf.source_url && (
                          <a
                            href={etf.source_url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-caption-1-medium text-text-primary underline hover:text-text-secondary focus-visible:ring-2 focus-visible:ring-border-focus-ring outline-none"
                          >
                            <span>Source file</span>
                            <RiExternalLinkLine className="size-3.5" aria-hidden />
                          </a>
                        )}
                        {etf.filing_url && (
                          <a
                            href={etf.filing_url}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-caption-1-medium text-text-primary underline hover:text-text-secondary focus-visible:ring-2 focus-visible:ring-border-focus-ring outline-none"
                          >
                            <span>SEC Filing</span>
                            <RiExternalLinkLine className="size-3.5" aria-hidden />
                          </a>
                        )}
                        {hasExtraDetails && (
                          <button
                            type="button"
                            onClick={() => toggleEtfDetails(etf.ticker)}
                            aria-expanded={isExpanded}
                            className="inline-flex cursor-pointer items-center gap-0.5 rounded px-1.5 py-0.5 text-caption-1-medium text-text-secondary hover:bg-background-primary-hover focus-visible:ring-2 focus-visible:ring-border-focus-ring outline-none"
                          >
                            {isExpanded ? (
                              <RiArrowDownSLine className="size-3.5" aria-hidden />
                            ) : (
                              <RiArrowRightSLine className="size-3.5 rtl:rotate-180" aria-hidden />
                            )}
                            <span>
                              {etf.warnings.length > 0
                                ? `${etf.warnings.length} notice${etf.warnings.length > 1 ? "s" : ""}`
                                : "Attempts"}
                            </span>
                          </button>
                        )}
                      </div>

                      {etf.attribution && (
                        <p className="text-caption-1-regular text-text-tertiary">
                          {etf.attribution}
                        </p>
                      )}

                      {isExpanded && hasExtraDetails && (
                        <div className="mt-1 flex flex-col gap-1.5 rounded-lg border border-separator-border bg-background-primary-default p-2.5 text-caption-1-regular">
                          {etf.warnings.map((w, wIdx) => (
                            <div
                              key={`${w.code}-${wIdx}`}
                              className="flex items-start gap-1.5 text-text-secondary"
                            >
                              <RiAlertLine
                                className="mt-0.5 size-3.5 shrink-0 text-foreground-icon-secondary"
                                aria-hidden
                              />
                              <span title={w.code}>{w.message}</span>
                            </div>
                          ))}
                          {etf.attempts.length > 0 && (
                            <div className="flex flex-wrap items-center gap-1.5 text-text-tertiary">
                              <span>Fallback chain:</span>
                              {etf.attempts.map((att, aIdx) => (
                                <span
                                  key={`${att.source}-${aIdx}`}
                                  className="rounded bg-background-secondary-default px-1.5 py-0.5 font-mono"
                                >
                                  {att.source}: {att.outcome}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>

        {/* Source attributions & CC BY 4.0 citations block */}
        {attributions.length > 0 && (
          <div className="flex flex-col gap-2 rounded-2xl border border-separator-border bg-background-primary-default p-3.5">
            <div className="flex items-center gap-1.5 text-caption-1-semibold text-text-secondary">
              <RiFileList3Line className="size-4 text-foreground-icon-tertiary" aria-hidden />
              <span>Required data attributions &amp; licences</span>
            </div>
            <ul className="flex flex-col gap-1.5">
              {attributions.map((attr, idx) => (
                <li
                  key={`${attr.source}-${idx}`}
                  className="flex flex-wrap items-center justify-between gap-2 text-caption-1-regular text-text-secondary"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Chip variant="caption" color="neutral">
                      {SOURCE_LABELS[attr.source] ?? attr.source}
                    </Chip>
                    <span>{attr.text}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {attr.licence && (
                      <Chip variant="caption" color="blue">
                        {attr.licence}
                      </Chip>
                    )}
                    {attr.url && (
                      <a
                        href={attr.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-caption-1-medium text-text-primary underline hover:text-text-secondary focus-visible:ring-2 focus-visible:ring-border-focus-ring outline-none"
                      >
                        <span>Source</span>
                        <RiExternalLinkLine className="size-3.5" aria-hidden />
                      </a>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {/* Section 5: Data Gaps & Warnings List */}
      <section
        aria-labelledby="gaps-list-heading"
        className="flex flex-col gap-4 rounded-3xl border border-border-button-default bg-background-secondary-default p-5"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <RiAlertLine className="size-5 text-foreground-icon-secondary" aria-hidden />
              <h2 id="gaps-list-heading" className="text-headline-medium text-text-primary">
                Data gaps &amp; disclosure warnings ({gapCounts.all})
              </h2>
            </div>
            <p className="text-body-2-regular text-text-secondary">
              Explicit audit trail of unmatched identities, stale filings, excluded non-equity
              lines, and coverage gaps.
            </p>
          </div>

          <SegmentedControl
            aria-label="Filter data gaps by severity"
            selectedKeys={new Set([gapSeverityFilter])}
            onSelectionChange={(keys) => {
              const next = [...keys][0];
              if (
                next === "all" ||
                next === "critical" ||
                next === "warning" ||
                next === "info"
              ) {
                setGapSeverityFilter(next);
              }
            }}
          >
            <SegmentedControlItem id="all">All ({gapCounts.all})</SegmentedControlItem>
            <SegmentedControlItem id="critical">
              Critical ({gapCounts.critical})
            </SegmentedControlItem>
            <SegmentedControlItem id="warning">
              Warning ({gapCounts.warning})
            </SegmentedControlItem>
            <SegmentedControlItem id="info">Info ({gapCounts.info})</SegmentedControlItem>
          </SegmentedControl>
        </div>

        {warnings.length > 0 && (
          <div className="flex flex-col gap-1.5 rounded-2xl border border-separator-border bg-background-primary-default p-3">
            <span className="text-caption-1-semibold text-text-secondary">
              Portfolio-level notices
            </span>
            {warnings.map((w, idx) => (
              <div
                key={`${w.code}-${idx}`}
                className="flex items-center gap-2 text-body-2-regular text-text-secondary"
              >
                <RiInformationLine className="size-4 shrink-0 text-foreground-icon-tertiary" />
                <span title={w.code}>{w.message}</span>
              </div>
            ))}
          </div>
        )}

        {filteredGaps.length === 0 ? (
          <div className="flex items-center gap-2.5 rounded-2xl border border-separator-border bg-background-primary-default p-4 text-body-2-regular text-text-secondary">
            <RiCheckboxCircleLine className="size-5 shrink-0 text-foreground-icon-secondary" />
            <span>
              {gapCounts.all === 0
                ? "No data gaps detected across loaded ETFs."
                : `No ${gapSeverityFilter} gaps in this portfolio.`}
            </span>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {filteredGaps.map((gap, idx) => {
              const sevMeta = GAP_SEVERITY_META[gap.severity];
              const etfIdx = gap.etf_ticker ? (etfIndexMap.get(gap.etf_ticker) ?? 0) : undefined;
              return (
                <div
                  key={`${gap.kind}-${gap.etf_ticker ?? "all"}-${gap.subject ?? idx}-${idx}`}
                  className={cx(
                    "flex flex-col justify-between gap-2 rounded-2xl border bg-background-primary-default p-3.5",
                    sevMeta.borderClass,
                  )}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Chip variant="caption" color={sevMeta.chipColor}>
                        {sevMeta.label}
                      </Chip>
                      <span className="text-body-2-semibold text-text-primary">
                        {GAP_KIND_LABELS[gap.kind] ?? gap.kind}
                      </span>
                      {gap.etf_ticker && (
                        <span className="inline-flex items-center gap-1.5">
                          {typeof etfIdx === "number" && (
                            <span
                              className="size-2 rounded-full"
                              style={etfDotStyle(etfIdx)}
                              aria-hidden
                            />
                          )}
                          <EtfChip ticker={gap.etf_ticker} />
                        </span>
                      )}
                    </div>

                    {typeof gap.portfolio_weight === "number" && (
                      <span className="text-caption-1-medium text-text-secondary tabular-nums">
                        Impact:{" "}
                        <Pct
                          value={cleanSignedZero(gap.portfolio_weight)}
                          digits={2}
                          className="text-text-primary"
                        />
                      </span>
                    )}
                  </div>

                  <p className="text-body-2-regular text-text-secondary">{gap.message}</p>

                  {gap.subject && (
                    <div className="flex items-center gap-1.5 text-caption-1-regular text-text-tertiary">
                      <span>Subject:</span>
                      <code className="rounded bg-background-secondary-default px-1.5 py-0.5 font-mono text-text-secondary">
                        {gap.subject}
                      </code>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
