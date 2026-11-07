"use client";

import { useCallback, useMemo, useState, type KeyboardEvent } from "react";
import {
  RiAlertLine,
  RiArrowDownSLine,
  RiArrowLeftSLine,
  RiArrowRightSLine,
  RiArrowRightUpLine,
  RiBarChartHorizontalLine,
  RiBuilding2Line,
  RiErrorWarningLine,
  RiGitMergeLine,
  RiPieChart2Line,
  RiRefreshLine,
  RiSparklingLine,
} from "@remixicon/react";
import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type PaginationState,
  type SortingState,
} from "@tanstack/react-table";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { api } from "@/api/client";
import type {
  CompanyExposure,
  IdentityStatus,
  Sector,
} from "@/api/types";
import { useAnalysis } from "@/app/analysis";
import { AsOfBadge } from "@/app/ui/as-of-badge";
import { EtfChip } from "@/app/ui/etf-chip";
import { etfVisual } from "@/app/ui/etf-color";
import { Pct, formatPct } from "@/app/ui/pct";
import { Chip, type ChipColor } from "@/components/base/badges/chip";
import { StatusDot } from "@/components/base/badges/status-dot";
import { Button } from "@/components/base/buttons/button";
import { Pagination } from "@/components/base/pagination/pagination";
import { SearchField } from "@/components/base/search-field/search-field";
import {
  SegmentedControl,
  SegmentedControlItem,
} from "@/components/base/segmented-control/segmented-control";
import { Select, SelectItem } from "@/components/base/select/select";
import { Spinner } from "@/components/base/spinner/spinner";
import {
  Table,
  TableBody,
  TableCell,
  TableColumn,
  TableHeader,
  TableRow,
  type TableSize,
} from "@/components/base/table/table";
import { ChevronSortDown } from "@/components/foundations/icons/chevrons";
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
  unknown: "Unknown",
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

const IDENTITY_META: Record<
  IdentityStatus,
  { label: string; chipColor: ChipColor; dotColor: "green" | "yellow" | "indigo" }
> = {
  resolved: { label: "Resolved", chipColor: "lime", dotColor: "green" },
  partial: { label: "Partial", chipColor: "yellow", dotColor: "yellow" },
  unmatched: { label: "Unmatched", chipColor: "rose", dotColor: "indigo" },
};

type ChartDatum = {
  companyKey: string;
  rank: number;
  label: string;
  shortLabel: string;
  companyName: string;
  symbols: string[];
  totalExposure: number;
  etfCount: number;
  company: CompanyExposure;
  [etfKey: `etf_${string}`]: number;
};

function SortChevron({ dir }: { dir: false | "asc" | "desc" }) {
  return (
    <ChevronSortDown
      className={cx(
        "size-5 shrink-0 transition-[transform,color] duration-150",
        dir === "asc" && "rotate-180",
        dir ? "text-text-secondary" : "text-text-tertiary",
      )}
    />
  );
}

function truncateLabel(text: string, maxLen = 18): string {
  if (text.length <= maxLen) return text;
  return `${text.slice(0, maxLen - 1)}…`;
}

export default function ExposuresPage() {
  const { analysis, status, stale, error, retry, setRows } = useAnalysis();
  const [loadingExample, setLoadingExample] = useState(false);
  const [exampleError, setExampleError] = useState<string | null>(null);

  // Chart state
  const [chartLimit, setChartLimit] = useState<"20" | "10">("20");
  const [activeChartIdx, setActiveChartIdx] = useState<number>(0);

  // Table state
  const [query, setQuery] = useState("");
  const [sectorFilter, setSectorFilter] = useState<string>("all");
  const [etfFilter, setEtfFilter] = useState<string>("all");
  const [identityFilter, setIdentityFilter] = useState<string>("all");
  const [sorting, setSorting] = useState<SortingState>([{ id: "exposure", desc: true }]);
  const [pagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize: 15 });
  const [tableSize, setTableSize] = useState<TableSize>("md");
  const [expandedKeys, setExpandedKeys] = useState<Record<string, boolean>>({});

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

  const etfTickers = useMemo(
    () => (analysis ? analysis.etfs.map((e) => e.ticker) : []),
    [analysis],
  );

  // Colour convention across all pages: etfVisual(index) by position in analysis.etfs
  const etfVisualMap = useMemo(() => {
    const map = new Map<string, ReturnType<typeof etfVisual>>();
    etfTickers.forEach((ticker, index) => {
      map.set(ticker, etfVisual(index));
    });
    return map;
  }, [etfTickers]);

  const etfAllocationMap = useMemo(() => {
    const map = new Map<string, number>();
    if (!analysis) return map;
    for (const etf of analysis.etfs) {
      map.set(etf.ticker, etf.allocation);
    }
    return map;
  }, [analysis]);

  const unavailableEtfs = useMemo(
    () => (analysis ? analysis.etfs.filter((etf) => etf.status === "unavailable") : []),
    [analysis],
  );

  const topLimit = chartLimit === "10" ? 10 : 20;

  const chartData = useMemo<ChartDatum[]>(() => {
    if (!analysis) return [];
    return analysis.exposures.slice(0, topLimit).map((company) => {
      const primarySymbol = company.symbols[0];
      const baseLabel = primarySymbol
        ? `${primarySymbol} · ${company.company_name}`
        : company.company_name;
      const row: ChartDatum = {
        companyKey: company.company_key,
        rank: company.rank,
        label: baseLabel,
        shortLabel: primarySymbol
          ? `${primarySymbol} (${truncateLabel(company.company_name, 14)})`
          : truncateLabel(company.company_name, 18),
        companyName: company.company_name,
        symbols: company.symbols,
        totalExposure: company.exposure,
        etfCount: company.etf_count,
        company,
      };
      for (const ticker of etfTickers) {
        const found = company.contributions.find((c) => c.etf_ticker === ticker);
        row[`etf_${ticker}`] = found ? found.contribution : 0;
      }
      return row;
    });
  }, [analysis, etfTickers, topLimit]);

  const clampedChartIdx =
    chartData.length > 0 ? Math.min(Math.max(0, activeChartIdx), chartData.length - 1) : 0;
  const activeChartPoint = chartData[clampedChartIdx] ?? null;

  const handleChartKeyDown = useCallback(
    (event: KeyboardEvent<HTMLElement>) => {
      if (chartData.length === 0) return;
      if (event.key === "ArrowDown" || event.key === "ArrowRight") {
        event.preventDefault();
        setActiveChartIdx((prev) => (prev + 1) % chartData.length);
      } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
        event.preventDefault();
        setActiveChartIdx((prev) => (prev - 1 + chartData.length) % chartData.length);
      } else if (event.key === "Home") {
        event.preventDefault();
        setActiveChartIdx(0);
      } else if (event.key === "End") {
        event.preventDefault();
        setActiveChartIdx(chartData.length - 1);
      }
    },
    [chartData.length],
  );

  const availableSectors = useMemo(() => {
    if (!analysis) return [];
    const seen = new Set<Sector>();
    for (const item of analysis.exposures) {
      seen.add(item.sector);
    }
    return [...seen];
  }, [analysis]);

  const multiEtfCompanyCount = useMemo(() => {
    if (!analysis) return 0;
    return analysis.exposures.filter((c) => c.etf_count > 1).length;
  }, [analysis]);

  const mergedClassCompanyCount = useMemo(() => {
    if (!analysis) return 0;
    return analysis.exposures.filter((c) => c.securities.length > 1 || c.symbols.length > 1).length;
  }, [analysis]);

  const filteredExposures = useMemo(() => {
    if (!analysis) return [];
    const q = query.trim().toLowerCase();
    return analysis.exposures.filter((item) => {
      if (sectorFilter !== "all" && item.sector !== sectorFilter) return false;
      if (identityFilter !== "all" && item.identity_status !== identityFilter) return false;
      if (etfFilter === "__overlap__") {
        if (item.etf_count < 2) return false;
      } else if (etfFilter !== "all") {
        if (!item.contributions.some((c) => c.etf_ticker === etfFilter)) return false;
      }
      if (!q) return true;
      if (item.company_name.toLowerCase().includes(q)) return true;
      if (item.company_key.toLowerCase().includes(q)) return true;
      if (item.symbols.some((sym) => sym.toLowerCase().includes(q))) return true;
      if (
        item.securities.some(
          (sec) =>
            sec.name.toLowerCase().includes(q) ||
            sec.security_id.toLowerCase().includes(q) ||
            (sec.symbol && sec.symbol.toLowerCase().includes(q)),
        )
      ) {
        return true;
      }
      return false;
    });
  }, [analysis, etfFilter, identityFilter, query, sectorFilter]);

  const filteredWeightSum = useMemo(
    () => filteredExposures.reduce((sum, item) => sum + item.exposure, 0),
    [filteredExposures],
  );

  const toggleRowExpanded = useCallback((companyKey: string) => {
    setExpandedKeys((prev) => ({ ...prev, [companyKey]: !prev[companyKey] }));
  }, []);

  const columns = useMemo<ColumnDef<CompanyExposure>[]>(
    () => [
      {
        accessorKey: "rank",
        header: "Rank",
        cell: ({ row }) => {
          const item = row.original;
          const isExpanded = !!expandedKeys[item.company_key];
          const panelId = `contrib-panel-${item.rank}`;
          return (
            <div className="flex items-start gap-1.5 py-0.5">
              <button
                type="button"
                onClick={() => toggleRowExpanded(item.company_key)}
                aria-expanded={isExpanded}
                aria-controls={isExpanded ? panelId : undefined}
                aria-label={`${isExpanded ? "Collapse" : "Expand"} contributions for ${item.company_name}`}
                className={cx(
                  "inline-flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-md",
                  "border border-border-button-default bg-background-primary-default text-foreground-icon-secondary",
                  "hover:border-border-button-hover hover:bg-background-primary-hover hover:text-foreground-icon-primary",
                  "focus-visible:ring-2 focus-visible:ring-border-focus-ring outline-none",
                )}
              >
                {isExpanded ? (
                  <RiArrowDownSLine className="size-4" aria-hidden />
                ) : (
                  <RiArrowRightSLine className="size-4" aria-hidden />
                )}
              </button>
              <span className="pt-0.5 text-body-2-medium text-text-tertiary tabular-nums">
                #{item.rank}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "company_name",
        header: "Company & underlying securities",
        cell: ({ row }) => {
          const item = row.original;
          const isExpanded = !!expandedKeys[item.company_key];
          const panelId = `contrib-panel-${item.rank}`;
          const hasMergedSecurities = item.securities.length > 1 || item.symbols.length > 1;
          return (
            <div className="flex min-w-0 flex-col gap-2 py-0.5">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => toggleRowExpanded(item.company_key)}
                  aria-expanded={isExpanded}
                  aria-controls={isExpanded ? panelId : undefined}
                  className="cursor-pointer rounded-sm text-start text-body-medium text-text-primary hover:underline focus-visible:ring-2 focus-visible:ring-border-focus-ring outline-none"
                >
                  {item.company_name}
                </button>
                {item.symbols.map((sym) => (
                  <Chip key={sym} variant="caption" color="neutral" className="font-mono">
                    {sym}
                  </Chip>
                ))}
                {hasMergedSecurities && (
                  <Chip variant="caption" color="purple">
                    <RiGitMergeLine className="me-1 inline size-3" aria-hidden />
                    {item.securities.length > 1
                      ? `${item.securities.length} classes merged`
                      : `${item.symbols.length} listings`}
                  </Chip>
                )}
                {item.country && (
                  <span className="text-caption-1-regular text-text-tertiary">{item.country}</span>
                )}
              </div>

              {isExpanded && (
                <div
                  id={panelId}
                  role="region"
                  aria-label={`Per-ETF contributions and securities for ${item.company_name}`}
                  className="mt-1 flex flex-col gap-3 rounded-xl border border-separator-border bg-background-secondary-default p-3"
                >
                  {/* Per-ETF contribution breakdown */}
                  <div className="flex flex-col gap-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-caption-1-semibold text-text-secondary">
                        Per-ETF contribution breakdown (A_e × w_e,c)
                      </span>
                      <span className="text-caption-1-regular text-text-tertiary tabular-nums">
                        Total effective exposure: <Pct value={item.exposure} digits={2} />
                      </span>
                    </div>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {item.contributions.map((contrib) => {
                        const visual = etfVisualMap.get(contrib.etf_ticker) ?? etfVisual(0);
                        const etfAlloc = etfAllocationMap.get(contrib.etf_ticker);
                        const shareOfCompany =
                          item.exposure > 0 ? contrib.contribution / item.exposure : 0;
                        return (
                          <div
                            key={contrib.etf_ticker}
                            className="flex flex-col gap-1.5 rounded-lg border border-border-button-default bg-background-primary-default p-2.5"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <div className="flex items-center gap-1.5">
                                <span
                                  className="size-2.5 shrink-0 rounded-full"
                                  style={{ backgroundColor: visual.color }}
                                  aria-hidden
                                />
                                <EtfChip ticker={contrib.etf_ticker} />
                                {typeof etfAlloc === "number" && (
                                  <span className="text-caption-1-regular text-text-tertiary tabular-nums">
                                    (<Pct value={etfAlloc} digits={1} /> of portfolio)
                                  </span>
                                )}
                              </div>
                              <Pct
                                value={contrib.contribution}
                                digits={2}
                                className="text-body-2-medium text-text-primary"
                              />
                            </div>
                            <div className="flex flex-wrap items-center justify-between gap-2 text-caption-1-regular text-text-secondary">
                              <span>
                                Weight in {contrib.etf_ticker}:{" "}
                                <Pct
                                  value={contrib.weight_in_etf}
                                  digits={2}
                                  className="text-text-primary"
                                />
                              </span>
                              <span className="text-text-tertiary tabular-nums">
                                <Pct value={shareOfCompany} digits={1} /> of this holding
                              </span>
                            </div>
                            {contrib.security_keys.length > 0 && (
                              <div className="flex flex-wrap items-center gap-1 pt-0.5">
                                <span className="text-caption-1-regular text-text-tertiary">
                                  Keys:
                                </span>
                                {contrib.security_keys.map((sk) => (
                                  <span
                                    key={sk}
                                    className="rounded bg-background-secondary-default px-1.5 py-0.5 font-mono text-caption-1-regular text-text-secondary"
                                  >
                                    {sk}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Underlying security listings */}
                  {item.securities.length > 0 && (
                    <div className="flex flex-col gap-1.5 border-t border-separator-border pt-2.5">
                      <span className="text-caption-1-semibold text-text-secondary">
                        Resolved securities ({item.securities.length})
                      </span>
                      <div className="flex flex-wrap gap-2">
                        {item.securities.map((sec) => (
                          <div
                            key={sec.security_key}
                            className="flex items-center gap-2 rounded-lg border border-separator-border bg-background-primary-default px-2.5 py-1.5 text-caption-1-regular"
                          >
                            {sec.symbol && (
                              <span className="font-mono text-caption-1-semibold text-text-primary">
                                {sec.symbol}
                              </span>
                            )}
                            <span className="text-text-secondary">{sec.name}</span>
                            <span className="font-mono text-text-tertiary">
                              {sec.security_id_type.toUpperCase()}: {sec.security_id}
                            </span>
                            <Pct
                              value={sec.exposure}
                              digits={2}
                              className="text-caption-1-semibold text-text-primary"
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        },
      },
      {
        accessorKey: "sector",
        header: "Sector",
        cell: ({ row }) => {
          const sector = row.original.sector;
          return (
            <Chip
              variant={tableSize === "sm" ? "caption" : "subtle"}
              color={SECTOR_COLORS[sector] ?? "neutral"}
            >
              {SECTOR_LABELS[sector] ?? sector}
            </Chip>
          );
        },
      },
      {
        accessorKey: "identity_status",
        header: "Identity",
        cell: ({ row }) => {
          const item = row.original;
          const meta = IDENTITY_META[item.identity_status];
          return (
            <div className="flex flex-col items-start gap-1">
              <div className="flex items-center gap-1.5">
                <StatusDot color={meta.dotColor} />
                <span className="text-body-2-medium text-text-primary">{meta.label}</span>
              </div>
              <span className="font-mono text-caption-1-regular text-text-tertiary">
                {item.company_key}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "etf_count",
        header: "ETFs & split",
        cell: ({ row }) => {
          const item = row.original;
          return (
            <div className="flex flex-col gap-1.5">
              <div className="flex flex-wrap items-center gap-1">
                {item.contributions.map((c) => (
                  <EtfChip key={c.etf_ticker} ticker={c.etf_ticker} />
                ))}
              </div>
              {/* Proportional mini bar across contributing ETFs using etfVisual(index) */}
              {item.exposure > 0 && (
                <div
                  className="flex h-1.5 w-28 overflow-hidden rounded-full bg-background-tertiary-default"
                  aria-hidden
                >
                  {item.contributions.map((c) => {
                    const visual = etfVisualMap.get(c.etf_ticker) ?? etfVisual(0);
                    const widthPct = Math.max(
                      0,
                      Math.min(100, (c.contribution / item.exposure) * 100),
                    );
                    return (
                      <span
                        key={c.etf_ticker}
                        className="h-full"
                        style={{
                          width: `${widthPct}%`,
                          backgroundColor: visual.color,
                        }}
                      />
                    );
                  })}
                </div>
              )}
            </div>
          );
        },
      },
      {
        accessorKey: "exposure",
        header: "Effective exposure",
        cell: ({ row }) => {
          const item = row.original;
          const isExpanded = !!expandedKeys[item.company_key];
          return (
            <div className="flex items-center justify-end gap-2">
              <Pct
                value={item.exposure}
                digits={2}
                className="text-body-medium text-text-primary"
              />
              <Button
                variant="secondary"
                size="xs"
                onClick={() => toggleRowExpanded(item.company_key)}
                aria-expanded={isExpanded}
                aria-label={`${isExpanded ? "Hide" : "Show"} details for ${item.company_name}`}
              >
                {isExpanded ? "Hide" : "Details"}
              </Button>
            </div>
          );
        },
      },
    ],
    [etfAllocationMap, etfVisualMap, expandedKeys, tableSize, toggleRowExpanded],
  );

  const table = useReactTable({
    data: filteredExposures,
    columns,
    getRowId: (row) => row.company_key,
    state: { sorting, pagination },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  const resetPage = useCallback(() => {
    setPagination((prev) => ({ ...prev, pageIndex: 0 }));
  }, []);

  const expandTopRows = useCallback(() => {
    const visibleRows = table.getRowModel().rows;
    const allCurrentlyExpanded =
      visibleRows.length > 0 && visibleRows.every((r) => expandedKeys[r.original.company_key]);
    if (allCurrentlyExpanded) {
      setExpandedKeys({});
    } else {
      const next: Record<string, boolean> = {};
      for (const r of visibleRows) {
        next[r.original.company_key] = true;
      }
      setExpandedKeys(next);
    }
  }, [expandedKeys, table]);

  // Empty / loading / error states when no analysis is available yet
  if (!analysis) {
    if (status === "loading") {
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
            Resolving underlying holdings and aggregating effective portfolio weights.
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
            <h2 className="text-headline-medium">Could not load exposures ({error.code})</h2>
          </div>
          <p className="text-body-regular text-text-secondary">{error.message}</p>
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" size="small" leadingIcon={RiRefreshLine} onClick={retry}>
              Retry analysis
            </Button>
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
            portfolio to inspect your top-20 company exposures and per-ETF contributions.
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

  const headers = table.getHeaderGroups()[0]?.headers ?? [];
  const rows = table.getRowModel().rows;
  const totalPages = table.getPageCount();
  const allVisibleExpanded =
    rows.length > 0 && rows.every((r) => expandedKeys[r.original.company_key]);

  const colWidths: Record<string, string> = {
    rank: "w-[88px]",
    company_name: "min-w-[300px]",
    sector: "w-[190px]",
    identity_status: "w-[170px]",
    etf_count: "w-[170px]",
    exposure: "w-[165px]",
  };

  const maxChartExposure = Math.max(
    0.01,
    ...chartData.map((d) => d.totalExposure),
  );

  return (
    <div className="flex w-full flex-col gap-6">
      {/* Stale / background refresh banner while keeping previous analysis visible */}
      {(stale || status === "loading") && (
        <div
          role="status"
          aria-live="polite"
          className="flex items-center justify-between gap-3 rounded-2xl border border-border-button-default bg-background-secondary-default px-4 py-2.5"
        >
          <div className="flex items-center gap-2 text-body-2-medium text-text-secondary">
            <Spinner size="sm" />
            <span>Updating exposures for your latest portfolio allocation…</span>
          </div>
        </div>
      )}

      {status === "error" && error && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border-error-default bg-background-secondary-default px-4 py-3"
        >
          <div className="flex items-center gap-2 text-body-2-medium text-text-error-primary">
            <RiErrorWarningLine className="size-4 shrink-0" aria-hidden />
            <span>
              {error.code}: {error.message} (showing last valid analysis)
            </span>
          </div>
          <Button variant="secondary" size="xs" leadingIcon={RiRefreshLine} onClick={retry}>
            Retry
          </Button>
        </div>
      )}

      {/* Unavailable ETF partial-outage alert (never renormalised per contract) */}
      {unavailableEtfs.length > 0 && (
        <section
          role="alert"
          aria-label="Unavailable ETF warning"
          className="flex flex-col gap-2 rounded-2xl border border-border-error-default bg-background-secondary-default p-4"
        >
          <div className="flex flex-wrap items-center gap-2">
            <RiAlertLine className="size-5 shrink-0 text-text-error-primary" aria-hidden />
            <h2 className="text-body-medium text-text-error-primary">
              Partial portfolio coverage: {unavailableEtfs.length}{" "}
              {unavailableEtfs.length === 1 ? "ETF" : "ETFs"} unavailable (
              <Pct value={analysis.coverage.missing_allocation} digits={2} /> of portfolio)
            </h2>
            <div className="flex flex-wrap items-center gap-1.5">
              {unavailableEtfs.map((etf) => (
                <EtfChip key={etf.ticker} ticker={etf.ticker} />
              ))}
            </div>
          </div>
          <p className="text-body-2-regular text-text-secondary">
            Exposures are never renormalised over missing funds: effective weights below represent
            fractions of your full portfolio, leaving the{" "}
            <Pct value={analysis.coverage.missing_allocation} digits={2} /> missing allocation
            explicitly visible.
          </p>
        </section>
      )}

      {/* Summary KPI Cards */}
      <section
        aria-label="Exposure summary metrics"
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
      >
        <div className="flex flex-col justify-between gap-2 rounded-2xl border border-border-button-default bg-background-secondary-default p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-body-2-medium text-text-secondary">Look-through coverage</span>
            <RiPieChart2Line className="size-4 text-foreground-icon-tertiary" aria-hidden />
          </div>
          <div className="flex items-baseline gap-2">
            <Pct
              value={analysis.coverage.covered_weight}
              digits={2}
              className="text-title-2-medium text-text-primary"
            />
            <AsOfBadge date={analysis.as_of_date} />
          </div>
          <p className="text-caption-1-regular text-text-tertiary">
            Excluded cash/derivatives: <Pct value={analysis.coverage.excluded_weight} digits={2} />
            {analysis.other_exposure > 0 && (
              <>
                {" · "}Other tail: <Pct value={analysis.other_exposure} digits={2} />
              </>
            )}
          </p>
        </div>

        <div className="flex flex-col justify-between gap-2 rounded-2xl border border-border-button-default bg-background-secondary-default p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-body-2-medium text-text-secondary">Distinct companies</span>
            <RiBuilding2Line className="size-4 text-foreground-icon-tertiary" aria-hidden />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-title-2-medium text-text-primary tabular-nums">
              {analysis.concentration.distinct_companies.toLocaleString()}
            </span>
            <span className="text-caption-1-regular text-text-tertiary tabular-nums">
              from {analysis.concentration.distinct_securities.toLocaleString()} securities
            </span>
          </div>
          <p className="text-caption-1-regular text-text-tertiary">
            {mergedClassCompanyCount > 0
              ? `${mergedClassCompanyCount} multi-class ${mergedClassCompanyCount === 1 ? "issuer" : "issuers"} merged (e.g. share classes)`
              : "Resolved across CIK, LEI, alias, and ISIN keys"}
          </p>
        </div>

        <div className="flex flex-col justify-between gap-2 rounded-2xl border border-border-button-default bg-background-secondary-default p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-body-2-medium text-text-secondary">Top-20 concentration</span>
            <RiBarChartHorizontalLine className="size-4 text-foreground-icon-tertiary" aria-hidden />
          </div>
          <div className="flex items-baseline gap-2">
            <Pct
              value={analysis.concentration.top20}
              digits={2}
              className="text-title-2-medium text-text-primary"
            />
            <span className="text-caption-1-regular text-text-tertiary">
              Top 10: <Pct value={analysis.concentration.top10} digits={2} />
            </span>
          </div>
          <p className="text-caption-1-regular text-text-tertiary">
            Top 5 companies: <Pct value={analysis.concentration.top5} digits={2} /> of total
            portfolio
          </p>
        </div>

        <div className="flex flex-col justify-between gap-2 rounded-2xl border border-border-button-default bg-background-secondary-default p-4">
          <div className="flex items-center justify-between gap-2">
            <span className="text-body-2-medium text-text-secondary">Multi-ETF holdings</span>
            <RiGitMergeLine className="size-4 text-foreground-icon-tertiary" aria-hidden />
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-title-2-medium text-text-primary tabular-nums">
              {multiEtfCompanyCount.toLocaleString()}
            </span>
            <span className="text-caption-1-regular text-text-tertiary">
              held in 2+ ETFs
            </span>
          </div>
          <p className="text-caption-1-regular text-text-tertiary">
            Across {analysis.etfs.length} portfolio{" "}
            {analysis.etfs.length === 1 ? "ETF" : "ETFs"}
          </p>
        </div>
      </section>

      {/* Top-20 Stacked Bar Chart of Per-ETF Contributions */}
      <section
        aria-label="Top company exposures chart"
        onKeyDown={handleChartKeyDown}
        className="flex w-full flex-col gap-5 rounded-3xl border border-border-button-default bg-background-secondary-default p-5"
      >
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex min-w-0 flex-col gap-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-headline-medium text-text-primary">
                Top-{chartData.length} company exposures by ETF contribution
              </h2>
              <Chip variant="caption" color="blue">
                Stacked by ETF
              </Chip>
            </div>
            <p className="text-body-2-regular text-text-secondary">
              Each bar stacks <span className="font-mono">A_e × w_e,c</span> across your ETFs
              without renormalisation. Hover a bar or use the keyboard controls to inspect per-ETF
              contributions.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Legend using etfVisual(index) */}
            <dl className="flex flex-wrap items-center gap-2.5 text-body-2-medium text-text-secondary">
              {analysis.etfs.map((etf, idx) => {
                const visual = etfVisual(idx);
                return (
                  <div
                    key={etf.ticker}
                    className="flex items-center gap-1.5 rounded-full border border-separator-border bg-background-primary-default px-2.5 py-1"
                  >
                    <span
                      className="size-2.5 shrink-0 rounded-full"
                      style={{
                        backgroundColor: visual.color,
                        outline: visual.dash ? "1px dashed var(--color-text-secondary)" : undefined,
                        outlineOffset: visual.dash ? "1px" : undefined,
                      }}
                      aria-hidden
                    />
                    <dt className="font-mono text-caption-1-semibold text-text-primary">
                      {etf.ticker}
                    </dt>
                    <dd className="text-caption-1-regular text-text-tertiary tabular-nums">
                      (<Pct value={etf.allocation} digits={0} />)
                    </dd>
                  </div>
                );
              })}
            </dl>

            {analysis.exposures.length > 10 && (
              <SegmentedControl
                aria-label="Chart company count"
                selectedKeys={new Set([chartLimit])}
                onSelectionChange={(keys) => {
                  const next = [...keys][0];
                  if (next === "10" || next === "20") {
                    setChartLimit(next);
                    setActiveChartIdx(0);
                  }
                }}
              >
                <SegmentedControlItem id="20">Top 20</SegmentedControlItem>
                <SegmentedControlItem id="10">Top 10</SegmentedControlItem>
              </SegmentedControl>
            )}
          </div>
        </div>

        {/* Interactive & Keyboard-Accessible Company Readout Strip */}
        {activeChartPoint && (
          <div
            role="region"
            aria-live="polite"
            aria-label="Selected chart company contribution breakdown"
            className="flex flex-col justify-between gap-3 rounded-2xl border border-separator-border bg-background-primary-default px-4 py-3 sm:flex-row sm:items-center"
          >
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <div className="flex items-center gap-1">
                <Button
                  variant="secondary"
                  size="xs"
                  iconOnly
                  leadingIcon={RiArrowLeftSLine}
                  aria-label="Previous company in chart"
                  disabled={chartData.length <= 1}
                  onClick={() =>
                    setActiveChartIdx((prev) => (prev - 1 + chartData.length) % chartData.length)
                  }
                />
                <Button
                  variant="secondary"
                  size="xs"
                  iconOnly
                  leadingIcon={RiArrowRightSLine}
                  aria-label="Next company in chart"
                  disabled={chartData.length <= 1}
                  onClick={() => setActiveChartIdx((prev) => (prev + 1) % chartData.length)}
                />
              </div>
              <Chip variant="caption" color="neutral">
                #{activeChartPoint.rank}
              </Chip>
              <span className="truncate text-body-medium text-text-primary">
                {activeChartPoint.companyName}
              </span>
              {activeChartPoint.symbols.map((sym) => (
                <Chip key={sym} variant="caption" color="blue" className="font-mono">
                  {sym}
                </Chip>
              ))}
              <span className="text-body-2-medium text-text-secondary">
                Total:{" "}
                <Pct
                  value={activeChartPoint.totalExposure}
                  digits={2}
                  className="text-text-primary"
                />
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              {activeChartPoint.company.contributions.map((c) => {
                const visual = etfVisualMap.get(c.etf_ticker) ?? etfVisual(0);
                return (
                  <div
                    key={c.etf_ticker}
                    className="flex items-center gap-1.5 text-caption-1-regular text-text-secondary"
                  >
                    <span
                      className="size-2 shrink-0 rounded-full"
                      style={{ backgroundColor: visual.color }}
                      aria-hidden
                    />
                    <span className="font-mono text-caption-1-semibold text-text-primary">
                      {c.etf_ticker}:
                    </span>
                    <Pct value={c.contribution} digits={2} className="text-text-primary" />
                    <span className="text-text-tertiary">
                      (<Pct value={c.weight_in_etf} digits={2} /> in ETF)
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Recharts Horizontal Stacked Bar Chart */}
        {chartData.length > 0 ? (
          <div
            tabIndex={0}
            role="group"
            aria-label={`Stacked bar chart of top ${chartData.length} companies. Use Up and Down arrow keys to inspect each company's per-ETF contributions.`}
            className="w-full rounded-xl focus-visible:ring-2 focus-visible:ring-border-focus-ring outline-none"
            style={{ height: `${Math.max(260, chartData.length * 32 + 36)}px` }}
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={chartData}
                layout="vertical"
                margin={{ top: 4, right: 24, bottom: 4, left: 8 }}
                barCategoryGap="22%"
                onMouseMove={(state) => {
                  const index = Number(state?.activeTooltipIndex);
                  if (state?.isTooltipActive && Number.isFinite(index)) {
                    setActiveChartIdx(index);
                  }
                }}
              >
                <XAxis
                  type="number"
                  domain={[0, maxChartExposure * 1.05]}
                  tickCount={6}
                  tickFormatter={(v: number) => formatPct(v, 1)}
                  tickLine={false}
                  axisLine={false}
                  tick={{ fontSize: 12, fill: "var(--color-text-tertiary)" }}
                />
                <YAxis
                  type="category"
                  dataKey="shortLabel"
                  width={156}
                  tickLine={false}
                  axisLine={false}
                  tick={{ fontSize: 12, fill: "var(--color-text-secondary)" }}
                />
                <Tooltip
                  content={() => null}
                  cursor={{ fill: "var(--color-chart-track)", opacity: 0.45 }}
                />
                {etfTickers.map((ticker, idx) => {
                  const visual = etfVisual(idx);
                  const isLast = idx === etfTickers.length - 1;
                  return (
                    <Bar
                      key={ticker}
                      dataKey={`etf_${ticker}`}
                      name={ticker}
                      stackId="exposure"
                      fill={visual.color}
                      stroke={visual.dash ? "var(--color-background-primary-default)" : undefined}
                      strokeDasharray={visual.dash}
                      radius={isLast ? [0, 4, 4, 0] : [0, 0, 0, 0]}
                      isAnimationActive
                      animationDuration={350}
                    />
                  );
                })}
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="flex h-40 items-center justify-center text-body-medium text-text-tertiary">
            No company exposures available for this portfolio.
          </div>
        )}
      </section>

      {/* Holdings Table with Search, Filters, Sorting, and Expandable Contributions */}
      <section
        aria-label="Holdings exposure table"
        className="flex w-full flex-col gap-4"
      >
        <div
          className={cx(
            "flex w-full flex-col rounded-2xl border border-border-table bg-background-primary-default pt-3",
            totalPages > 1 ? "pb-3" : "pb-0",
          )}
        >
          {/* Table Toolbar */}
          <div className="flex w-full flex-col items-start gap-3 px-4 py-1.5 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-col gap-0.5">
              <div className="flex items-center gap-2">
                <h2 className="text-body-medium text-text-primary">
                  Company holdings ({filteredExposures.length.toLocaleString()})
                </h2>
                <Chip variant="caption" color="neutral">
                  <Pct value={filteredWeightSum} digits={2} /> portfolio weight
                </Chip>
                {analysis.exposures_truncated && (
                  <Chip variant="caption" color="yellow">
                    Top {analysis.exposures.length} shown (+
                    <Pct value={analysis.other_exposure} digits={2} /> other)
                  </Chip>
                )}
              </div>
              <p className="text-caption-1-regular text-text-tertiary">
                Select any company row or Details button to expand per-ETF contributions and merged
                security listings.
              </p>
            </div>

            <div className="flex w-full flex-wrap items-center gap-2.5 lg:w-auto lg:justify-end">
              <SearchField
                aria-label="Search companies, tickers, or identifiers"
                placeholder="Search company, symbol, CIK/ISIN…"
                value={query}
                onChange={(next) => {
                  setQuery(next);
                  resetPage();
                }}
                className="w-full sm:w-[240px]"
              />

              <Select
                aria-label="Filter by sector"
                className="shrink-0"
                popoverClassName="min-w-48"
                selectedKey={sectorFilter}
                onSelectionChange={(k) => {
                  setSectorFilter(String(k));
                  resetPage();
                }}
              >
                <SelectItem id="all" textValue="All sectors">
                  All sectors
                </SelectItem>
                {availableSectors.map((sec) => (
                  <SelectItem key={sec} id={sec} textValue={SECTOR_LABELS[sec] ?? sec}>
                    {SECTOR_LABELS[sec] ?? sec}
                  </SelectItem>
                ))}
              </Select>

              <Select
                aria-label="Filter by ETF"
                className="shrink-0"
                popoverClassName="min-w-44"
                selectedKey={etfFilter}
                onSelectionChange={(k) => {
                  setEtfFilter(String(k));
                  resetPage();
                }}
              >
                <SelectItem id="all" textValue="All ETFs">
                  All ETFs
                </SelectItem>
                {analysis.etfs.length > 1 && (
                  <SelectItem id="__overlap__" textValue="In 2+ ETFs (overlap)">
                    In 2+ ETFs (overlap)
                  </SelectItem>
                )}
                {etfTickers.map((t) => (
                  <SelectItem key={t} id={t} textValue={`Held in ${t}`}>
                    Held in {t}
                  </SelectItem>
                ))}
              </Select>

              <Select
                aria-label="Filter by identity status"
                className="shrink-0"
                popoverClassName="min-w-40"
                selectedKey={identityFilter}
                onSelectionChange={(k) => {
                  setIdentityFilter(String(k));
                  resetPage();
                }}
              >
                <SelectItem id="all" textValue="All identities">
                  All identities
                </SelectItem>
                <SelectItem id="resolved" textValue="Resolved">
                  Resolved
                </SelectItem>
                <SelectItem id="partial" textValue="Partial">
                  Partial
                </SelectItem>
                <SelectItem id="unmatched" textValue="Unmatched">
                  Unmatched
                </SelectItem>
              </Select>

              <Button
                variant="secondary"
                size="small"
                onClick={expandTopRows}
              >
                {allVisibleExpanded ? "Collapse page" : "Expand page"}
              </Button>
            </div>
          </div>

          {/* Table */}
          <div className="mt-2">
            <Table
              aria-label="Company exposures"
              size={tableSize}
              selectionMode="none"
              className="min-w-[920px]"
            >
              <TableHeader>
                {headers.map((header) => {
                  const id = header.column.id;
                  const canSort = header.column.getCanSort();
                  const sortedDir = header.column.getIsSorted();
                  const label = flexRender(header.column.columnDef.header, header.getContext());
                  return (
                    <TableColumn
                      key={header.id}
                      id={header.id}
                      isRowHeader={id === "company_name"}
                      className={colWidths[id]}
                    >
                      {canSort ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          aria-label={`Sort by ${typeof label === "string" ? label : id}${
                            sortedDir === "asc"
                              ? " (currently ascending)"
                              : sortedDir === "desc"
                                ? " (currently descending)"
                                : ""
                          }`}
                          className={cx(
                            "flex cursor-pointer items-center gap-1 rounded-sm focus-visible:ring-2 focus-visible:ring-border-focus-ring outline-none",
                            id === "exposure" && "ms-auto justify-end",
                          )}
                        >
                          {label}
                          <SortChevron dir={sortedDir} />
                        </button>
                      ) : (
                        label
                      )}
                    </TableColumn>
                  );
                })}
              </TableHeader>
              <TableBody
                renderEmptyState={() => (
                  <div className="flex h-36 flex-col items-center justify-center gap-2 text-center">
                    <p className="text-body-medium text-text-secondary">
                      No holdings match your current search or filters.
                    </p>
                    <Button
                      variant="secondary"
                      size="xs"
                      onClick={() => {
                        setQuery("");
                        setSectorFilter("all");
                        setEtfFilter("all");
                        setIdentityFilter("all");
                        resetPage();
                      }}
                    >
                      Clear filters
                    </Button>
                  </div>
                )}
              >
                {rows.map((row) => {
                  const isExpanded = !!expandedKeys[row.original.company_key];
                  return (
                    <TableRow
                      key={row.id}
                      id={row.id}
                      style={
                        isExpanded
                          ? { backgroundColor: "var(--color-background-secondary-default)" }
                          : undefined
                      }
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell
                          key={cell.id}
                          className={cx("align-top", colWidths[cell.column.id])}
                        >
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </TableCell>
                      ))}
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>

          {/* Pagination Footer */}
          {totalPages > 1 && (
            <div className="border-t border-separator-border px-4 pt-3">
              <Pagination
                page={pagination.pageIndex + 1}
                totalPages={totalPages}
                onChange={(p) => table.setPageIndex(p - 1)}
              />
            </div>
          )}
        </div>

        {/* Table density control */}
        <div className="flex items-center justify-end">
          <SegmentedControl
            aria-label="Table density"
            selectedKeys={new Set([tableSize])}
            onSelectionChange={(keys) => {
              const next = [...keys][0];
              if (next === "md" || next === "sm") setTableSize(next);
            }}
          >
            <SegmentedControlItem id="md">Normal</SegmentedControlItem>
            <SegmentedControlItem id="sm">Compact</SegmentedControlItem>
          </SegmentedControl>
        </div>
      </section>
    </div>
  );
}
