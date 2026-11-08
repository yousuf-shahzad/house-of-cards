// Network page: which ETF gives you which company. Owner: Yousuf's Claude.
import { useMemo, useState, type KeyboardEvent } from "react";
import { RiRefreshLine } from "@remixicon/react";
import type { ApiError } from "@/api/client";
import type { CompanyExposure } from "@/api/types";
import { useAnalysis } from "@/app/analysis";
import { AsOfBadge } from "@/app/ui/as-of-badge";
import { etfVisual } from "@/app/ui/etf-color";
import { formatPct, Pct } from "@/app/ui/pct";
import { Button, ButtonLink } from "@/components/base/buttons/button";
import { Chip } from "@/components/base/badges/chip";
import { SegmentedControl, SegmentedControlItem } from "@/components/base/segmented-control/segmented-control";
import { buildGraph, truncate, WIDTH, type EtfNode, type Graph } from "./graph";

const LIMITS = [10, 20, 50];
const DEFAULT_LIMIT = 20;

const humanise = (value: string) => value.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

function errorCopy(error: ApiError): string {
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

function Dot({ index }: { index: number }) {
  return (
    <span
      aria-hidden
      className="inline-block size-2.5 shrink-0 rounded-full"
      style={{ background: etfVisual(index).color }}
    />
  );
}

function CompanyDetail({ company, graph }: { company: CompanyExposure; graph: Graph }) {
  const colors = new Map(graph.etfs.map((etf) => [etf.id, etf.colorIndex]));
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-headline-medium text-text-primary">{company.company_name}</h2>
        {company.symbols.map((symbol) => (
          <Chip key={symbol} variant="caption" color="neutral">
            {symbol}
          </Chip>
        ))}
      </div>
      <p className="text-body-regular text-text-secondary">
        <Pct value={company.exposure} className="text-text-primary" /> of your portfolio
        {company.sector ? `, ${humanise(company.sector)}` : ""}
      </p>
      {company.identity_status !== "resolved" && (
        <p className="text-body-regular text-text-secondary">
          {company.identity_status === "partial"
            ? "Matched by ticker only, so other share classes may be listed separately."
            : "Not matched to a known company. This is the name the fund reported."}
        </p>
      )}
      <ul className="flex flex-col gap-1">
        {company.contributions.map((item) => (
          <li key={item.etf_ticker} className="flex flex-wrap items-center gap-2 text-body-regular text-text-secondary">
            <Dot index={colors.get(item.etf_ticker) ?? 0} />
            <span className="text-text-primary">{item.etf_ticker}</span>
            <span>
              adds <Pct value={item.contribution} className="text-text-primary" /> ({formatPct(item.weight_in_etf)} of
              that ETF)
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}

function EtfDetail({ node, graph }: { node: EtfNode; graph: Graph }) {
  const edges = graph.edges.filter((edge) => edge.etf === node.id).sort((a, b) => b.contribution - a.contribution);
  const names = new Map(graph.companies.map((item) => [item.id, item.company.company_name]));
  const { report } = node;
  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        <Dot index={node.colorIndex} />
        <h2 className="text-headline-medium text-text-primary">{report.ticker}</h2>
        {report.status === "unavailable" ? (
          <Chip variant="caption" color="rose">
            No data
          </Chip>
        ) : (
          <AsOfBadge date={report.as_of} />
        )}
      </div>
      <p className="text-body-regular text-text-secondary">
        {report.name ? `${report.name}: ` : ""}
        <Pct value={report.allocation} className="text-text-primary" /> of your portfolio
      </p>
      {edges.length === 0 ? (
        <p className="text-body-regular text-text-secondary">None of the companies shown here come through this ETF.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {edges.map((edge) => (
            <li key={edge.id} className="text-body-regular text-text-secondary">
              <span className="text-text-primary">{names.get(edge.company)}</span>:{" "}
              <Pct value={edge.contribution} className="text-text-primary" />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function Diagram({ graph, active, onHover, onPin }: {
  graph: Graph;
  active: string | null;
  onHover: (id: string | null) => void;
  onPin: (id: string | null) => void;
}) {
  const touches = (edge: Graph["edges"][number]) => edge.etf === active || edge.company === active;
  const linked = useMemo(() => {
    const ids = new Set<string>();
    for (const edge of graph.edges) {
      if (touches(edge)) {
        ids.add(edge.etf);
        ids.add(edge.company);
      }
    }
    if (active) ids.add(active);
    return ids;
    // `touches` only reads `active`.
  }, [graph, active]); // eslint-disable-line react-hooks/exhaustive-deps

  const nodeProps = (id: string, label: string) => ({
    role: "button",
    tabIndex: 0,
    "aria-label": label,
    "aria-pressed": active === id,
    className: "cursor-pointer outline-none [&:focus-visible>circle:first-child]:stroke-accent-500",
    style: { opacity: active && !linked.has(id) ? 0.25 : 1, transition: "opacity 120ms" },
    onMouseEnter: () => onHover(id),
    onMouseLeave: () => onHover(null),
    onFocus: () => onHover(id),
    onBlur: () => onHover(null),
    onClick: () => onPin(id),
    onKeyDown: (event: KeyboardEvent) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onPin(id);
      }
    },
  });

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${WIDTH} ${graph.height}`}
        role="group"
        aria-label="Network of your ETFs and their largest companies"
        className="block w-full min-w-[640px]"
        onClick={(event) => {
          if (event.target === event.currentTarget) onPin(null);
        }}
      >
        <g fill="none" aria-hidden>
          {graph.edges.map((edge) => {
            const visual = etfVisual(edge.colorIndex);
            return (
              <path
                key={edge.id}
                d={edge.path}
                stroke={visual.color}
                strokeWidth={edge.width}
                strokeDasharray={visual.dash}
                strokeOpacity={active ? (touches(edge) ? 0.95 : 0.06) : 0.5}
                style={{ transition: "stroke-opacity 120ms" }}
              />
            );
          })}
        </g>
        {graph.etfs.map((node) => {
          const missing = node.report.status === "unavailable";
          return (
            <g
              key={node.id}
              {...nodeProps(
                node.id,
                `${node.id}, ${formatPct(node.report.allocation)} of your portfolio${missing ? ", no data" : ""}`,
              )}
            >
              <circle
                cx={node.x}
                cy={node.y}
                r={node.r}
                fill={missing ? "var(--color-background-tertiary-default)" : etfVisual(node.colorIndex).color}
                stroke="var(--color-background-primary-default)"
                strokeWidth={2}
              />
              <text x={node.x - node.r - 8} y={node.y - 2} textAnchor="end" className="fill-text-primary text-body-medium">
                {node.id}
              </text>
              <text x={node.x - node.r - 8} y={node.y + 14} textAnchor="end" className="fill-text-secondary text-caption-1-regular">
                {missing ? "no data" : formatPct(node.report.allocation, 1)}
              </text>
            </g>
          );
        })}
        {graph.companies.map((node) => (
          <g
            key={node.id}
            {...nodeProps(node.id, `${node.company.company_name}, ${formatPct(node.company.exposure)} of your portfolio`)}
          >
            <circle
              cx={node.x}
              cy={node.y}
              r={node.r}
              fill="var(--color-text-primary)"
              stroke="var(--color-background-primary-default)"
              strokeWidth={2}
            />
            <text x={node.x + 26} y={node.y + 4} className="fill-text-primary text-body-2-regular">
              <title>{node.company.company_name}</title>
              {truncate(node.company.company_name, 30)}
              <tspan dx={8} className="fill-text-secondary">
                {formatPct(node.company.exposure)}
              </tspan>
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function DataTable({ graph }: { graph: Graph }) {
  return (
    <details>
      <summary className="cursor-pointer text-body-medium text-text-primary">Show as a table</summary>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-start text-body-regular text-text-secondary">
          <thead>
            <tr className="border-b border-separator-border text-text-primary">
              <th scope="col" className="py-2 pe-4 text-start font-medium">Company</th>
              <th scope="col" className="py-2 pe-4 text-start font-medium">Exposure</th>
              <th scope="col" className="py-2 text-start font-medium">Through</th>
            </tr>
          </thead>
          <tbody>
            {graph.companies.map(({ id, company }) => (
              <tr key={id} className="border-b border-separator-border">
                <td className="py-2 pe-4 text-text-primary">{company.company_name}</td>
                <td className="py-2 pe-4"><Pct value={company.exposure} /></td>
                <td className="py-2">
                  {company.contributions.map((item) => `${item.etf_ticker} ${formatPct(item.contribution)}`).join(", ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export default function NetworkPage() {
  const { analysis, status, stale, error, retry } = useAnalysis();
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [hovered, setHovered] = useState<string | null>(null);
  const [pinned, setPinned] = useState<string | null>(null);

  const graph = useMemo(() => (analysis ? buildGraph(analysis, limit) : null), [analysis, limit]);

  if (!analysis || !graph) {
    if (status === "error" && error) {
      return (
        <section className="suite-card" role="alert">
          <p className="text-body-regular text-text-error-primary">{errorCopy(error)}</p>
          <div className="flex flex-wrap items-center gap-2">
            {error.code !== "UNKNOWN_TICKER" && (
              <Button variant="secondary" size="small" leadingIcon={RiRefreshLine} onClick={retry}>
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
    if (status === "loading") {
      return (
        <section className="suite-card" aria-busy="true">
          <p className="text-body-regular text-text-secondary">Analysing your portfolio…</p>
        </section>
      );
    }
    return (
      <section className="suite-card">
        <p className="text-body-regular text-text-secondary">Enter a portfolio to see the companies behind each ETF.</p>
        <div>
          <ButtonLink href="#/portfolio" size="small">
            Go to your portfolio
          </ButtonLink>
        </div>
      </section>
    );
  }

  const exists = (id: string | null) =>
    id !== null && (graph.etfs.some((node) => node.id === id) || graph.companies.some((node) => node.id === id));
  const active = exists(hovered) ? hovered : exists(pinned) ? pinned : null;
  const activeCompany = graph.companies.find((node) => node.id === active)?.company;
  const activeEtf = graph.etfs.find((node) => node.id === active);
  const options = LIMITS.filter((value) => value < graph.total);
  const selectedKey = limit >= graph.total ? "all" : String(limit);

  return (
    <div className="flex flex-col gap-6" onKeyDown={(event) => event.key === "Escape" && setPinned(null)}>
      <section className="suite-card" aria-label="Company network">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-body-regular text-text-secondary">
            These {graph.companies.length} companies are{" "}
            <Pct value={graph.shownExposure} className="text-text-primary" /> of your portfolio.
          </p>
          {options.length > 0 && (
            <SegmentedControl
              aria-label="Number of companies to show"
              selectedKeys={[selectedKey]}
              onSelectionChange={(keys) => {
                const [key] = [...keys];
                setLimit(key === "all" ? graph.total : Number(key));
              }}
            >
              {options.map((value) => (
                <SegmentedControlItem key={value} id={String(value)}>
                  {`Top ${value}`}
                </SegmentedControlItem>
              ))}
              <SegmentedControlItem id="all">{`All ${graph.total}`}</SegmentedControlItem>
            </SegmentedControl>
          )}
        </div>
        {(status === "loading" || (stale && status !== "error")) && (
          <p role="status" className="text-body-regular text-text-secondary">
            {status === "loading"
              ? "Updating…"
              : "This shows your last valid portfolio. Fix your allocations to update it."}
          </p>
        )}
        {status === "error" && error && (
          <p role="alert" className="text-body-regular text-text-error-primary">
            Couldn't update, so this shows your last result: {errorCopy(error)}
          </p>
        )}
        {graph.companies.length === 0 ? (
          <p className="text-body-regular text-text-secondary">No company holdings are available for this portfolio.</p>
        ) : (
          <div style={{ opacity: stale ? 0.55 : 1 }}>
            <Diagram
              graph={graph}
              active={active}
              onHover={setHovered}
              onPin={(id) => setPinned((current) => (id === null || current === id ? null : id))}
            />
          </div>
        )}
        <p className="text-caption-1-regular text-text-tertiary">
          Line thickness = how much of your money is in that company through that ETF. Bigger circles mean bigger
          positions. Select a circle for details, and press Esc to clear it.
        </p>
      </section>
      <section className="suite-card" aria-label="Details" aria-live="polite">
        {activeCompany ? (
          <CompanyDetail company={activeCompany} graph={graph} />
        ) : activeEtf ? (
          <EtfDetail node={activeEtf} graph={graph} />
        ) : (
          <p className="text-body-regular text-text-secondary">Hover over or select a circle to see the details.</p>
        )}
      </section>
      {graph.companies.length > 0 && (
        <section className="suite-card" aria-label="Network as a table">
          <DataTable graph={graph} />
        </section>
      )}
    </div>
  );
}
