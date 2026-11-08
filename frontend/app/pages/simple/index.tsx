import { useState, type ReactNode } from "react";
import type { AnalysisResponse, CompanyExposure } from "@/api/types";
import { useAnalysis } from "@/app/analysis";
import { useExperience } from "@/app/experience";
import type { PageKey } from "@/app/registry";
import { diversificationVerdict } from "@/app/ui/concentration";
import { etfVisual } from "@/app/ui/etf-color";
import { ServerError } from "@/app/ui/draft-editor";
import { Pct } from "@/app/ui/pct";
import { TryAChange } from "@/app/ui/try-a-change";
import { Chip } from "@/components/base/badges/chip";
import { Button, ButtonLink } from "@/components/base/buttons/button";
import { Spinner } from "@/components/base/spinner/spinner";
import { plainSectorName } from "../guide/copy";
import { SimplePortfolio } from "./portfolio";
import { buildGraph, truncate, WIDTH } from "../network/graph";
import { SimpleDependencies } from "./dependencies";
import { useAutoDependencies } from "../guide/use-auto-dependencies";

function Card({ title, children }: { title: string; children: ReactNode }) {
  return <section className="suite-card flex flex-col gap-4" aria-label={title}>
    <h2 className="text-headline-medium text-text-primary">{title}</h2>
    {children}
  </section>;
}

function Companies({ analysis, network = false }: { analysis: AnalysisResponse; network?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const companies = expanded ? analysis.exposures : analysis.exposures.slice(0, 5);
  return <Card title={network ? "Your ETFs → your companies" : "Your biggest companies"}>
    {network && <MoneyFlow analysis={analysis} />}
    {companies.length === 0 && <p>No company holdings were available for this portfolio.</p>}
    <ol className="flex flex-col gap-3">
      {companies.map((company) => <CompanyRow key={company.company_key} company={company} network={network} />)}
    </ol>
    {analysis.exposures.length > 5 && <Button variant="ghost" size="small" className="self-start" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? "Show five" : `Show all ${analysis.exposures.length} loaded companies`}</Button>}
    <p className="text-caption-1-regular text-text-secondary">Percentages are shares of your whole portfolio, using the holdings we could load.</p>
  </Card>;
}

function MoneyFlow({ analysis }: { analysis: AnalysisResponse }) {
  const graph = buildGraph(analysis, 5);
  return <figure className="flex flex-col gap-2">
    <div className="overflow-x-auto rounded-2xl border border-separator-border" tabIndex={0} role="region" aria-label="Scrollable money-flow diagram">
      <svg viewBox={`0 0 ${WIDTH} ${graph.height}`} className="w-full min-w-[600px]" role="img" aria-label="Your ETFs connected to your five biggest companies">
        <title>Your ETFs connected to your five biggest companies</title>
        {graph.edges.map((edge) => <path key={edge.id} d={edge.path} fill="none" stroke={etfVisual(edge.colorIndex).color} strokeWidth={edge.width} strokeDasharray={etfVisual(edge.colorIndex).dash} opacity={0.55} />)}
        {graph.etfs.map((node) => <g key={node.id}><circle cx={node.x} cy={node.y} r={node.r} fill={etfVisual(node.colorIndex).color} /><text x={node.x - node.r - 10} y={node.y + 5} textAnchor="end" fill="currentColor" fontSize="14">{node.id}</text></g>)}
        {graph.companies.map((node) => <g key={node.id}><circle cx={node.x} cy={node.y} r={node.r} fill="var(--color-text-primary)" /><text x={node.x + node.r + 10} y={node.y + 5} fill="currentColor" fontSize="14">{truncate(node.company.company_name, 29)}</text></g>)}
      </svg>
    </div>
    <figcaption className="text-caption-1-regular text-text-secondary">Thicker lines mean more of your money reaches that company through the ETF. Scroll sideways on small screens; open the rows below for exact amounts.</figcaption>
  </figure>;
}

function CompanyRow({ company, network }: { company: CompanyExposure; network: boolean }) {
  return <li className="rounded-2xl border border-separator-border bg-background-secondary-default p-4">
    <div className="flex flex-wrap items-baseline justify-between gap-2 text-body-medium text-text-primary">
      <span>{company.company_name}</span><Pct value={company.exposure} digits={2} />
    </div>
    <div className="mt-2 h-2 overflow-hidden rounded-full bg-background-tertiary-default" aria-hidden>
      <div className="h-full rounded-full bg-accent-500" style={{ width: `${Math.max(0, Math.min(100, company.exposure * 100))}%` }} />
    </div>
    <p className="mt-2 text-body-2-regular text-text-secondary">Held through {company.contributions.map((c) => c.etf_ticker).join(", ")}.</p>
    <details className="mt-2 text-body-2-regular text-text-secondary">
      <summary className="cursor-pointer text-text-primary">{network ? "Follow the money" : "Where this comes from"}</summary>
      <ul className="mt-3 flex flex-col gap-2">
        {company.contributions.map((c) => <li key={c.etf_ticker} className="flex flex-wrap items-center justify-between gap-2">
          <span>{c.etf_ticker} → {company.company_name}</span>
          <span><Pct value={c.contribution} digits={2} /> of your money</span>
        </li>)}
      </ul>
    </details>
  </li>;
}

function Overlap({ analysis }: { analysis: AnalysisResponse }) {
  const [expanded, setExpanded] = useState(false);
  const allPairs = [...analysis.overlap.pairs].sort((a, b) => b.weighted_overlap - a.weighted_overlap);
  const pairs = expanded ? allPairs : allPairs.slice(0, 5);
  return <Card title="Your most similar ETF pairs">
    {pairs.length === 0 ? <p className="text-body-regular text-text-secondary">There are no pairs to compare yet. Add at least two ETFs with available holdings on Portfolio.</p> : <>
      <p className="text-body-regular text-text-secondary">These funds repeat the most company holdings. The percentage compares the funds themselves.</p>
      <ol className="flex flex-col gap-3">
        {pairs.map((pair) => <li key={`${pair.etf_a}-${pair.etf_b}`} className="rounded-2xl border border-separator-border p-4">
          <p className="text-body-medium text-text-primary">{pair.etf_a} + {pair.etf_b}: <Pct value={pair.weighted_overlap} digits={2} /> overlap</p>
          <div className="my-2 h-2 overflow-hidden rounded-full bg-background-tertiary-default" aria-hidden><div className="h-full rounded-full bg-accent-500" style={{ width: `${Math.max(0, Math.min(100, pair.weighted_overlap * 100))}%` }} /></div>
          <p className="mt-1 text-body-2-regular text-text-secondary">{pair.shared_companies.toLocaleString()} companies in common.</p>
          {pair.top_shared.length > 0 && <details className="mt-2 text-body-2-regular text-text-secondary"><summary className="cursor-pointer">See shared companies</summary><ul className="mt-2 space-y-1">
            {pair.top_shared.slice(0, 5).map((company) => <li key={company.company_key}>{company.company_name}: <Pct value={company.weight_a} digits={2} /> of {pair.etf_a}, <Pct value={company.weight_b} digits={2} /> of {pair.etf_b}</li>)}
          </ul></details>}
        </li>)}
      </ol>
      {allPairs.length > 5 && <Button variant="ghost" size="small" className="self-start" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? "Show five pairs" : `Show all ${allPairs.length} pairs`}</Button>}
    </>}
  </Card>;
}

function Risk({ analysis }: { analysis: AnalysisResponse }) {
  const { concentration, sectors, coverage } = analysis;
  const verdict = diversificationVerdict({ hhi: concentration.hhi, sectors });
  return <>
    <Card title="Your overall balance">
      <div><Chip variant="subtle" color={verdict.color}>{verdict.label}</Chip></div>
      <p className="text-body-regular text-text-secondary">{verdict.summary}</p>
      <div className="grid gap-4 sm:grid-cols-2">
        <p className="rounded-2xl bg-background-secondary-default p-4 text-body-medium text-text-primary">Your ten biggest companies hold <Pct value={concentration.top10} digits={2} /> of your money.</p>
        <p className="rounded-2xl bg-background-secondary-default p-4 text-body-medium text-text-primary">Your mix behaves like about {Math.max(1, Math.round(concentration.effective_companies)).toLocaleString()} equally sized company holdings.</p>
      </div>
    </Card>
    <Card title="Your biggest industries">
      <ul className="space-y-3 text-body-regular text-text-primary">
        {sectors.slice(0, 3).map((sector) => <li key={sector.sector} className="flex justify-between gap-3"><span>{plainSectorName(sector.sector)}</span><Pct value={sector.weight} digits={2} /></li>)}
      </ul>
      {verdict.sectorConcentrated && verdict.topSector && <p className="text-body-regular text-text-secondary"><Pct value={verdict.topSector.weight} digits={2} /> is in {plainSectorName(verdict.topSector.sector)}. That industry can move many of your companies together.</p>}
      {sectors.length === 0 && <p>Industry data is unavailable.</p>}
    </Card>
    <Card title="How much data did we find?">
      <p className="text-body-regular text-text-primary">We could trace <Pct value={coverage.covered_weight} digits={2} /> of your portfolio to company holdings.</p>
      <details className="text-body-2-regular text-text-secondary"><summary className="cursor-pointer">Holdings dates and gaps</summary>
        <ul className="mt-3 space-y-2">{analysis.etfs.map((etf) => <li key={etf.ticker}>{etf.ticker}: {etf.as_of ?? "date unavailable"}{etf.status === "unavailable" ? " — holdings unavailable" : ""}</li>)}</ul>
        {analysis.gaps.length > 0 && <ul className="mt-3 list-disc space-y-2 pl-4">{analysis.gaps.map((gap, i) => <li key={i}>{gap.message}</li>)}</ul>}
      </details>
    </Card>
  </>;
}

export default function SimplePage({ pageKey }: { pageKey: PageKey }) {
  const { analysis, status, stale, error, retry } = useAnalysis();
  const { openExpertPage } = useExperience();
  useAutoDependencies();
  if (pageKey === "portfolio") return <SimplePortfolio />;
  if (status === "error" && error) return <ServerError error={error} retry={retry} />;
  if (status === "loading") return <Card title="Updating your portfolio"><div role="status" className="flex items-center gap-3"><Spinner size="sm" aria-label="Loading portfolio" />Adding up the holdings inside your ETFs…</div></Card>;
  if (!analysis || stale || status !== "ready") return <Card title="Start with your portfolio"><p className="text-body-regular text-text-secondary">Load a sample or enter your ETFs to see this page's results.</p><div><ButtonLink href="#/portfolio" variant="secondary">Go to Portfolio</ButtonLink></div></Card>;

  return <div className="flex flex-col gap-5" data-testid={`simple-${pageKey}`}>
    {(analysis.coverage.covered_weight < analysis.coverage.total_allocation - 0.000001 || analysis.warnings.length > 0) && <div role="status" className="rounded-2xl border border-separator-border p-4 text-body-2-regular text-text-secondary">
      Some holdings or company details are missing. These results cover the data we could load. <a href="#/risk" className="underline">Check data coverage</a>.
    </div>}
    {(pageKey === "exposures" || pageKey === "network") && <Companies analysis={analysis} network={pageKey === "network"} />}
    {pageKey === "overlap" && <Overlap analysis={analysis} />}
    {pageKey === "risk" && <Risk analysis={analysis} />}
    {pageKey === "dependencies" && <SimpleDependencies />}
    {pageKey === "compare" && <TryAChange editorTitle="Your changed portfolio" />}
    <div><Button variant="secondary" size="small" onClick={() => openExpertPage(`#/${pageKey}`)}>{pageKey === "dependencies" ? "See every link and its evidence" : pageKey === "network" ? "Open the full network graph" : "See this page in Full view"}</Button></div>
  </div>;
}
