"use client";

// F3 + P1: ETF overlap page (heatmap matrix + pair detail). Owner: Bekarys's Gemini.
import { useEffect, useMemo, useState } from "react";
import {
  RiArrowRightLine,
  RiErrorWarningLine,
  RiGitMergeLine,
  RiGridLine,
  RiLinksLine,
  RiRefreshLine,
  RiStackLine,
} from "@remixicon/react";
import { api, ApiError } from "@/api/client";
import type {
  CompanyExposure,
  EtfReport,
  ExamplePortfolio,
  OverlapPair,
} from "@/api/types";
import { useAnalysis } from "@/app/analysis";
import { AsOfBadge } from "@/app/ui/as-of-badge";
import { EtfChip } from "@/app/ui/etf-chip";
import { etfVisual } from "@/app/ui/etf-color";
import { Pct, formatPct } from "@/app/ui/pct";
import { EtfColorSwatch, HeatmapMatrix } from "@/components/application/heatmap";
import { Chip } from "@/components/base/badges/chip";
import { Button, ButtonLink } from "@/components/base/buttons/button";
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

type OverlapBasis = "company" | "security";

function canonicalPairKey(a: string, b: string): string {
  return a < b ? `${a}::${b}` : `${b}::${a}`;
}

function errorCopy(error: ApiError): string {
  const tickers = (error.details as { tickers?: string[] } | undefined)?.tickers;
  if (error.code === "UNKNOWN_TICKER" && tickers?.length) {
    return `We couldn't find ${tickers.join(", ")} in any data source. Check the ticker on the Portfolio page.`;
  }
  if (error.code === "SOURCES_UNAVAILABLE") {
    return "None of the data sources could be reached, so we have no holdings to compare.";
  }
  if (error.code === "NETWORK_ERROR") {
    return "We couldn't reach the analysis service. Check that the backend is running.";
  }
  return error.message;
}

const SECTOR_LABELS: Record<string, string> = {
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
  unknown: "Unclassified",
};

function QuickExamples({ onLoad }: { onLoad: (example: ExamplePortfolio) => void }) {
  const [examples, setExamples] = useState<ExamplePortfolio[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    api
      .examples(controller.signal)
      .then((res) => setExamples(res.examples.filter((ex) => ex.verified)))
      .catch(() => {});
    return () => controller.abort();
  }, []);

  if (examples.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {examples.map((example) => (
        <Button
          key={example.id}
          variant="secondary"
          size="small"
          aria-label={`Load example: ${example.name}`}
          onClick={() => onLoad(example)}
        >
          Load {example.name}
        </Button>
      ))}
    </div>
  );
}

export default function OverlapPage() {
  const { rows, setRows, status, analysis, stale, error, retry } = useAnalysis();
  const [basis, setBasis] = useState<OverlapBasis>("company");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const etfMap = useMemo(() => {
    const map = new Map<string, EtfReport>();
    if (!analysis) return map;
    for (const etf of analysis.etfs) {
      map.set(etf.ticker.toUpperCase(), etf);
    }
    return map;
  }, [analysis]);

  /** Maps upper-case ticker -> index in `analysis.etfs` for consistent `etfVisual(index)` colours across pages. */
  const etfIndexMap = useMemo(() => {
    const map = new Map<string, number>();
    if (!analysis) return map;
    analysis.etfs.forEach((etf, idx) => {
      map.set(etf.ticker.toUpperCase(), idx);
    });
    return map;
  }, [analysis]);

  const unavailableEtfs = useMemo(
    () => (analysis ? analysis.etfs.filter((etf) => etf.status === "unavailable") : []),
    [analysis],
  );

  const companyMap = useMemo(() => {
    const map = new Map<string, CompanyExposure>();
    if (!analysis) return map;
    for (const company of analysis.exposures) {
      map.set(company.company_key, company);
    }
    return map;
  }, [analysis]);

  const pairMap = useMemo(() => {
    const map = new Map<string, OverlapPair>();
    if (!analysis) return map;
    for (const pair of analysis.overlap.pairs) {
      map.set(canonicalPairKey(pair.etf_a, pair.etf_b), pair);
    }
    return map;
  }, [analysis]);

  const sortedPairs = useMemo(() => {
    if (!analysis) return [];
    return [...analysis.overlap.pairs].sort((a, b) => {
      const diff =
        basis === "company"
          ? b.weighted_overlap - a.weighted_overlap
          : b.weighted_overlap_securities - a.weighted_overlap_securities;
      if (Math.abs(diff) > 1e-9) return diff;
      return canonicalPairKey(a.etf_a, a.etf_b).localeCompare(
        canonicalPairKey(b.etf_a, b.etf_b),
      );
    });
  }, [analysis, basis]);

  const activePair: OverlapPair | null = useMemo(() => {
    if (sortedPairs.length === 0) return null;
    if (selectedKey && pairMap.has(selectedKey)) {
      return pairMap.get(selectedKey) ?? sortedPairs[0];
    }
    return sortedPairs[0];
  }, [sortedPairs, selectedKey, pairMap]);

  const activeMatrix = useMemo(() => {
    if (!analysis) return [];
    const { etfs, matrix } = analysis.overlap;
    if (basis === "company") return matrix;
    return etfs.map((rowTicker, i) =>
      etfs.map((colTicker, j) => {
        if (i === j) return matrix[i]?.[j] ?? 0;
        const pair = pairMap.get(canonicalPairKey(rowTicker, colTicker));
        return pair?.weighted_overlap_securities ?? 0;
      }),
    );
  }, [analysis, basis, pairMap]);

  // 1. No analysis yet
  if (!analysis) {
    if (status === "loading") {
      return (
        <section
          className="suite-card"
          aria-live="polite"
          aria-label="Loading overlap analysis"
        >
          <div className="flex items-center gap-3">
            <Spinner size="sm" aria-label="Analysing" />
            <p className="text-body-medium text-text-primary">
              Computing pairwise ETF overlap…
            </p>
          </div>
        </section>
      );
    }

    if (status === "error" && error) {
      return (
        <section className="suite-card" role="alert" aria-label="Overlap error">
          <div className="flex items-center gap-2 text-text-error-primary">
            <RiErrorWarningLine className="size-5 shrink-0" aria-hidden />
            <h2 className="text-headline-medium">Could not compute overlap</h2>
          </div>
          <p className="text-body-regular text-text-secondary">{errorCopy(error)}</p>
          <div className="flex flex-wrap items-center gap-2">
            {error.code !== "UNKNOWN_TICKER" && (
              <Button
                variant="secondary"
                size="small"
                leadingIcon={RiRefreshLine}
                onClick={retry}
              >
                Try again
              </Button>
            )}
            <ButtonLink variant="ghost" size="small" href="#/portfolio">
              Edit portfolio
            </ButtonLink>
          </div>
        </section>
      );
    }

    return (
      <section className="suite-card" aria-label="Portfolio required for overlap">
        <div className="flex flex-col gap-2">
          <h2 className="text-headline-medium text-text-primary">
            Enter at least two ETFs to inspect overlap
          </h2>
          <p className="text-body-regular text-text-secondary">
            {rows.length === 0
              ? "Add your ETFs and allocations totaling 100% on the Portfolio page, or load a verified example portfolio below."
              : "Your current portfolio draft needs valid tickers totaling 100% before overlap can be calculated."}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <ButtonLink
            variant="primary"
            size="small"
            href="#/portfolio"
            trailingIcon={RiArrowRightLine}
          >
            Go to Portfolio
          </ButtonLink>
          {rows.length === 0 && (
            <QuickExamples
              onLoad={(example) =>
                setRows(
                  example.holdings.map((item) => ({
                    ticker: item.ticker,
                    allocationPct: Math.round(item.allocation * 1e6) / 1e4,
                  })),
                )
              }
            />
          )}
        </div>
      </section>
    );
  }

  const { etfs } = analysis.overlap;

  return (
    <div className="flex flex-col gap-6">
      {/* Stale / reloading / error notice when draft rows changed */}
      {(stale || status === "loading" || status === "error") && (
        <div
          role={status === "error" ? "alert" : "status"}
          aria-live="polite"
          className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border-button-default bg-background-secondary-default px-4 py-3"
        >
          <div className="flex items-center gap-2.5">
            {status === "loading" ? (
              <Spinner size="sm" aria-label="Updating" />
            ) : (
              <Chip variant="caption" color={status === "error" ? "rose" : "yellow"}>
                {status === "error" ? "Update failed" : "Stale view"}
              </Chip>
            )}
            <p className="text-body-2-regular text-text-secondary">
              {status === "loading"
                ? "Updating overlap matrix for your latest portfolio changes…"
                : status === "error" && error
                  ? `${errorCopy(error)} Showing last valid analysis.`
                  : "Showing the last valid analysis. Finish editing your portfolio so allocations total 100%."}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {status === "error" && error?.code !== "UNKNOWN_TICKER" && (
              <Button
                variant="secondary"
                size="xs"
                leadingIcon={RiRefreshLine}
                onClick={retry}
              >
                Retry
              </Button>
            )}
            <ButtonLink variant="ghost" size="xs" href="#/portfolio">
              Portfolio
            </ButtonLink>
          </div>
        </div>
      )}

      {/* Unavailable ETF notice when one or more ETFs failed to load */}
      {unavailableEtfs.length > 0 && (
        <div
          role="status"
          aria-live="polite"
          className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border-button-default bg-background-secondary-default px-4 py-3"
        >
          <div className="flex flex-wrap items-center gap-2 text-body-2-regular text-text-secondary">
            <Chip variant="caption" color="rose">
              Missing ETF data
            </Chip>
            <span>
              Holdings were unavailable for{" "}
              {unavailableEtfs.map((etf, idx) => (
                <span key={etf.ticker} className="inline-flex items-center gap-1">
                  {idx > 0 && ", "}
                  <strong className="text-body-2-medium text-text-primary">
                    {etf.ticker}
                  </strong>{" "}
                  (<Pct value={etf.allocation} digits={1} /> allocation)
                </span>
              ))}
              . Unavailable ETFs are omitted from the overlap matrix.
            </span>
          </div>
          <ButtonLink variant="ghost" size="xs" href="#/risk">
            See Risk &amp; data
          </ButtonLink>
        </div>
      )}

      <div className={cx("flex flex-col gap-6 transition-opacity", stale && "opacity-75")}>
        {/* Heatmap Matrix Card */}
        <section className="suite-card" aria-label="ETF overlap heatmap">
          <div className="suite-card-heading flex-wrap">
            <div>
              <span className="text-caption-1-medium text-text-tertiary">
                PAIRWISE WEIGHTED OVERLAP
              </span>
              <h2 className="text-title-2-medium text-text-primary">
                Overlap matrix
              </h2>
              <p className="mt-1 text-body-regular text-text-secondary">
                {basis === "company"
                  ? "Company-level overlap merges dual share classes and cross-listed ADRs into a single issuer before summing min(weight A, weight B)."
                  : "Security-level overlap compares exact listing keys only, without merging multiple share classes of the same company."}
              </p>
            </div>

            <SegmentedControl
              aria-label="Overlap resolution level"
              selectedKeys={[basis]}
              onSelectionChange={(keys) => {
                const next = [...keys][0];
                if (next === "company" || next === "security") {
                  setBasis(next);
                }
              }}
            >
              <SegmentedControlItem id="company">Company level</SegmentedControlItem>
              <SegmentedControlItem id="security">Security level</SegmentedControlItem>
            </SegmentedControl>
          </div>

          <HeatmapMatrix
            etfs={etfs}
            matrix={activeMatrix}
            getEtfIndex={(ticker, fallbackIdx) =>
              etfIndexMap.get(ticker.toUpperCase()) ?? fallbackIdx
            }
            selectedPair={activePair ? [activePair.etf_a, activePair.etf_b] : null}
            onSelectPair={(a, b) => setSelectedKey(canonicalPairKey(a, b))}
            renderRowMeta={(ticker) => {
              const report = etfMap.get(ticker.toUpperCase());
              if (!report) return null;
              return (
                <span className="flex flex-wrap items-center gap-1.5">
                  <span>
                    <Pct value={report.allocation} digits={0} /> alloc
                  </span>
                  <span className="text-text-tertiary">·</span>
                  <span>{report.company_count.toLocaleString()} co.</span>
                </span>
              );
            }}
            getCellSubtitle={(rowTicker, colTicker, _val, isDiagonal) => {
              if (isDiagonal) return "Covered NAV";
              const pair = pairMap.get(canonicalPairKey(rowTicker, colTicker));
              if (!pair) return "Overlap";
              return basis === "company"
                ? `${pair.shared_companies.toLocaleString()} shared co.`
                : `${pair.shared_securities.toLocaleString()} shared sec.`;
            }}
            getCellTitle={(rowTicker, colTicker, val, isDiagonal) => {
              if (isDiagonal) {
                return `${rowTicker} covered holdings weight: ${formatPct(val)} (unadjusted for cash/exclusions)`;
              }
              const pair = pairMap.get(canonicalPairKey(rowTicker, colTicker));
              if (!pair) return `${rowTicker} × ${colTicker}: ${formatPct(val)}`;
              return `${rowTicker} × ${colTicker}: ${formatPct(pair.weighted_overlap)} company overlap (${pair.shared_companies} companies), ${formatPct(pair.weighted_overlap_securities)} security overlap (${pair.shared_securities} securities)`;
            }}
          />

          {etfs.length < 2 && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-background-secondary-default p-4">
              <p className="text-body-regular text-text-secondary">
                {etfs.length === 0
                  ? "None of the ETFs in your portfolio could be loaded for overlap comparison."
                  : `Only one loaded ETF (${etfs[0]}) is available. Add at least two loaded ETFs to compare pairwise overlap.`}
              </p>
              <ButtonLink
                variant="secondary"
                size="small"
                href="#/portfolio"
                trailingIcon={RiArrowRightLine}
              >
                Edit portfolio
              </ButtonLink>
            </div>
          )}
        </section>

        {/* Pair Detail Card */}
        {activePair && (
          <PairDetailSection
            pair={activePair}
            allPairs={sortedPairs}
            basis={basis}
            etfMap={etfMap}
            etfIndexMap={etfIndexMap}
            companyMap={companyMap}
            onSelectPair={(a, b) => setSelectedKey(canonicalPairKey(a, b))}
          />
        )}
      </div>
    </div>
  );
}

function EtfWeightBar({
  index,
  widthPct,
}: {
  index: number;
  widthPct: number;
}) {
  const { color, dash } = etfVisual(index);
  const clamped = Math.max(0, Math.min(100, widthPct));
  return (
    <div
      className="h-1.5 w-full overflow-hidden rounded-full bg-background-secondary-default"
      aria-hidden
    >
      <div
        className="h-full rounded-full transition-[width] duration-150 ease"
        style={{
          width: `${clamped}%`,
          backgroundColor: color,
          backgroundImage: dash
            ? "repeating-linear-gradient(135deg, transparent 0 4px, var(--color-background-primary-default) 4px 6px)"
            : undefined,
        }}
      />
    </div>
  );
}

function PairDetailSection({
  pair,
  allPairs,
  basis,
  etfMap,
  etfIndexMap,
  companyMap,
  onSelectPair,
}: {
  pair: OverlapPair;
  allPairs: OverlapPair[];
  basis: OverlapBasis;
  etfMap: Map<string, EtfReport>;
  etfIndexMap: Map<string, number>;
  companyMap: Map<string, CompanyExposure>;
  onSelectPair: (a: string, b: string) => void;
}) {
  const reportA = etfMap.get(pair.etf_a.toUpperCase());
  const reportB = etfMap.get(pair.etf_b.toUpperCase());
  const indexA = etfIndexMap.get(pair.etf_a.toUpperCase()) ?? 0;
  const indexB = etfIndexMap.get(pair.etf_b.toUpperCase()) ?? 1;
  const identityDelta = Math.max(0, pair.weighted_overlap - pair.weighted_overlap_securities);
  const maxSharedWeight = useMemo(() => {
    if (pair.top_shared.length === 0) return 0.01;
    return Math.max(
      ...pair.top_shared.map((item) => Math.max(item.weight_a, item.weight_b)),
      0.01,
    );
  }, [pair.top_shared]);

  return (
    <section
      className="suite-card"
      aria-label={`Pair detail for ${pair.etf_a} and ${pair.etf_b}`}
    >
      <div className="suite-card-heading flex-wrap">
        <div className="flex flex-col gap-1.5">
          <span className="text-caption-1-medium text-text-tertiary">
            SELECTED PAIR BREAKDOWN
          </span>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5">
              <EtfColorSwatch index={indexA} />
              <EtfChip ticker={pair.etf_a} />
            </span>
            <span className="text-title-3-semibold text-text-tertiary">×</span>
            <span className="inline-flex items-center gap-1.5">
              <EtfColorSwatch index={indexB} />
              <EtfChip ticker={pair.etf_b} />
            </span>
            <h2 className="text-title-2-medium text-text-primary">
              {reportA?.name && reportB?.name
                ? `${reportA.name} & ${reportB.name}`
                : `${pair.etf_a} & ${pair.etf_b} overlap`}
            </h2>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-body-2-regular text-text-secondary">
            {reportA && (
              <span className="inline-flex items-center gap-1.5">
                <EtfColorSwatch index={indexA} />
                <span className="text-body-2-medium text-text-primary">{pair.etf_a}:</span>
                <Pct value={reportA.allocation} digits={0} /> portfolio alloc
                <AsOfBadge date={reportA.as_of} />
              </span>
            )}
            {reportB && (
              <span className="inline-flex items-center gap-1.5">
                <EtfColorSwatch index={indexB} />
                <span className="text-body-2-medium text-text-primary">{pair.etf_b}:</span>
                <Pct value={reportB.allocation} digits={0} /> portfolio alloc
                <AsOfBadge date={reportB.as_of} />
              </span>
            )}
          </div>
        </div>

        {/* Pair switcher pills when >1 pair exists */}
        {allPairs.length > 1 && (
          <div
            role="group"
            aria-label="Switch ETF pair"
            className="flex flex-wrap items-center gap-1.5"
          >
            {allPairs.map((item) => {
              const key = canonicalPairKey(item.etf_a, item.etf_b);
              const isCurrent =
                key === canonicalPairKey(pair.etf_a, pair.etf_b);
              const val =
                basis === "company"
                  ? item.weighted_overlap
                  : item.weighted_overlap_securities;
              return (
                <Button
                  key={key}
                  variant={isCurrent ? "primary" : "secondary"}
                  size="xs"
                  aria-pressed={isCurrent}
                  onClick={() => onSelectPair(item.etf_a, item.etf_b)}
                >
                  {item.etf_a} × {item.etf_b} (<Pct value={val} digits={1} />)
                </Button>
              );
            })}
          </div>
        )}
      </div>

      {/* 4 KPI cards for the selected pair */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="flex flex-col justify-between gap-3 rounded-2xl bg-background-secondary-default p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-body-medium text-text-secondary">
              Company overlap
            </span>
            <span className="flex rounded-md bg-stat-card-icon-background p-1.5">
              <RiGitMergeLine className="size-5 text-foreground-icon-primary" aria-hidden />
            </span>
          </div>
          <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-baseline gap-2">
              <Pct
                value={pair.weighted_overlap}
                className="text-title-1-medium text-text-primary"
              />
              {identityDelta > 1e-6 && (
                <Chip variant="caption" color="blue">
                  +<Pct value={identityDelta} /> merged
                </Chip>
              )}
            </div>
            <p className="text-caption-1-regular text-text-tertiary">
              Sum of min(w_a, w_b) after merging share classes &amp; aliases
            </p>
          </div>
        </div>

        <div className="flex flex-col justify-between gap-3 rounded-2xl bg-background-secondary-default p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-body-medium text-text-secondary">
              Security overlap
            </span>
            <span className="flex rounded-md bg-stat-card-icon-background p-1.5">
              <RiLinksLine className="size-5 text-foreground-icon-primary" aria-hidden />
            </span>
          </div>
          <div className="flex flex-col gap-1">
            <Pct
              value={pair.weighted_overlap_securities}
              className="text-title-1-medium text-text-primary"
            />
            <p className="text-caption-1-regular text-text-tertiary">
              Exact listing match only (before company resolution)
            </p>
          </div>
        </div>

        <div className="flex flex-col justify-between gap-3 rounded-2xl bg-background-secondary-default p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-body-medium text-text-secondary">
              Shared companies
            </span>
            <span className="flex rounded-md bg-stat-card-icon-background p-1.5">
              <RiGridLine className="size-5 text-foreground-icon-primary" aria-hidden />
            </span>
          </div>
          <div className="flex flex-col gap-1">
            <span
              className="text-title-1-medium text-text-primary"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {pair.shared_companies.toLocaleString()}
            </span>
            <p className="text-caption-1-regular text-text-tertiary">
              {reportA && reportB
                ? `Out of ${reportA.company_count.toLocaleString()} in ${pair.etf_a} and ${reportB.company_count.toLocaleString()} in ${pair.etf_b}`
                : "Issuers held with positive weight in both ETFs"}
            </p>
          </div>
        </div>

        <div className="flex flex-col justify-between gap-3 rounded-2xl bg-background-secondary-default p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-body-medium text-text-secondary">
              Shared securities
            </span>
            <span className="flex rounded-md bg-stat-card-icon-background p-1.5">
              <RiStackLine className="size-5 text-foreground-icon-primary" aria-hidden />
            </span>
          </div>
          <div className="flex flex-col gap-1">
            <span
              className="text-title-1-medium text-text-primary"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {pair.shared_securities.toLocaleString()}
            </span>
            <p className="text-caption-1-regular text-text-tertiary">
              {reportA && reportB
                ? `Out of ${reportA.holdings_count.toLocaleString()} in ${pair.etf_a} and ${reportB.holdings_count.toLocaleString()} in ${pair.etf_b}`
                : "Distinct security listings held in both ETFs"}
            </p>
          </div>
        </div>
      </div>

      {/* Top shared companies table */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h3 className="text-headline-medium text-text-primary">
              Top shared companies
            </h3>
            <p className="text-body-2-regular text-text-secondary">
              Ranked by overlapping ETF weight min(weight in {pair.etf_a}, weight in {pair.etf_b}). Weights are unadjusted fractions of each ETF’s NAV.
            </p>
          </div>
          <Chip variant="caption" color="neutral">
            Showing top {pair.top_shared.length} of {pair.shared_companies.toLocaleString()}
          </Chip>
        </div>

        {pair.top_shared.length === 0 ? (
          <div className="rounded-2xl bg-background-secondary-default p-6 text-center">
            <p className="text-body-regular text-text-secondary">
              {pair.etf_a} and {pair.etf_b} do not share any underlying companies.
            </p>
          </div>
        ) : (
          <Table
            size="sm"
            aria-label={`Top shared companies between ${pair.etf_a} and ${pair.etf_b}`}
          >
            <TableHeader>
              <TableColumn isRowHeader>Company</TableColumn>
              <TableColumn>
                <span className="inline-flex items-center gap-1.5">
                  <EtfColorSwatch index={indexA} />
                  <span>In {pair.etf_a}</span>
                </span>
              </TableColumn>
              <TableColumn>
                <span className="inline-flex items-center gap-1.5">
                  <EtfColorSwatch index={indexB} />
                  <span>In {pair.etf_b}</span>
                </span>
              </TableColumn>
              <TableColumn>Overlap (min)</TableColumn>
              <TableColumn>Share of overlap</TableColumn>
            </TableHeader>
            <TableBody>
              {pair.top_shared.map((item, idx) => {
                const company = companyMap.get(item.company_key);
                const symbols = company?.symbols ?? [];
                const sectorLabel = company?.sector
                  ? SECTOR_LABELS[company.sector] ?? company.sector
                  : null;
                const shareOfOverlap =
                  pair.weighted_overlap > 0
                    ? item.min_weight / pair.weighted_overlap
                    : 0;
                const barWidthA = (item.weight_a / maxSharedWeight) * 100;
                const barWidthB = (item.weight_b / maxSharedWeight) * 100;

                return (
                  <TableRow key={item.company_key} id={item.company_key}>
                    <TableCell>
                      <div className="flex items-start gap-2.5">
                        <span
                          className="mt-0.5 text-caption-1-medium text-text-tertiary"
                          style={{ fontVariantNumeric: "tabular-nums" }}
                        >
                          {String(idx + 1).padStart(2, "0")}
                        </span>
                        <div className="flex flex-col gap-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="text-body-medium text-text-primary">
                              {item.company_name}
                            </span>
                            {symbols.map((sym) => (
                              <Chip key={sym} variant="caption" color="soft">
                                {sym}
                              </Chip>
                            ))}
                            {symbols.length > 1 && (
                              <Chip variant="caption" color="blue">
                                {symbols.length} classes merged
                              </Chip>
                            )}
                          </div>
                          <span className="text-caption-1-regular text-text-tertiary">
                            {sectorLabel ? `${sectorLabel} · ` : ""}
                            <span dir="ltr">{item.company_key}</span>
                          </span>
                        </div>
                      </div>
                    </TableCell>

                    <TableCell>
                      <div className="flex min-w-[7.5rem] flex-col gap-1">
                        <Pct
                          value={item.weight_a}
                          className="text-body-medium text-text-primary"
                        />
                        <EtfWeightBar index={indexA} widthPct={barWidthA} />
                      </div>
                    </TableCell>

                    <TableCell>
                      <div className="flex min-w-[7.5rem] flex-col gap-1">
                        <Pct
                          value={item.weight_b}
                          className="text-body-medium text-text-primary"
                        />
                        <EtfWeightBar index={indexB} widthPct={barWidthB} />
                      </div>
                    </TableCell>

                    <TableCell>
                      <Chip variant="bold" color="blue">
                        <Pct value={item.min_weight} />
                      </Chip>
                    </TableCell>

                    <TableCell>
                      <Pct
                        value={shareOfOverlap}
                        digits={1}
                        className="text-body-regular text-text-secondary"
                      />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </div>
    </section>
  );
}
