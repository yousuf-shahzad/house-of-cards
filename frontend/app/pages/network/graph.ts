// Pure data and layout for the network page: no React and no DOM.
import type { AnalysisResponse, CompanyExposure, EtfReport } from "@/api/types";

export const WIDTH = 760;
const ETF_X = 140;
const COMPANY_X = 470;
const ROW = 40;
const MIN_ETF_ROW = 72;
const PAD_Y = 36;

export type EtfNode = { id: string; report: EtfReport; colorIndex: number; x: number; y: number; r: number };
export type CompanyNode = { id: string; company: CompanyExposure; x: number; y: number; r: number };
export type Edge = {
  id: string;
  etf: string;
  company: string;
  contribution: number;
  width: number;
  colorIndex: number;
  path: string;
};
export type Graph = {
  etfs: EtfNode[];
  companies: CompanyNode[];
  edges: Edge[];
  height: number;
  /** Companies available to show, before the limit. */
  total: number;
  /** Share of the whole portfolio held through the companies shown. */
  shownExposure: number;
};

const scaled = (value: number, max: number) => (max > 0 ? Math.sqrt(Math.max(value, 0) / max) : 0);

export function buildGraph(analysis: AnalysisResponse, limit: number): Graph {
  const top = analysis.exposures.slice(0, Math.max(limit, 0));
  const rows = Math.max(top.length * ROW, analysis.etfs.length * MIN_ETF_ROW);
  const height = rows + PAD_Y * 2;

  // Colours follow the response order, so they don't change when sizes do.
  const ordered = analysis.etfs
    .map((report, colorIndex) => ({ report, colorIndex }))
    .sort((a, b) => b.report.allocation - a.report.allocation || a.report.ticker.localeCompare(b.report.ticker));
  const maxAllocation = Math.max(0, ...ordered.map(({ report }) => report.allocation));
  const etfs: EtfNode[] = ordered.map(({ report, colorIndex }, i) => ({
    id: report.ticker,
    report,
    colorIndex,
    x: ETF_X,
    y: PAD_Y + ((i + 0.5) * rows) / ordered.length,
    r: 10 + 16 * scaled(report.allocation, maxAllocation),
  }));
  const etfById = new Map(etfs.map((node) => [node.id, node]));

  const maxExposure = Math.max(0, ...top.map((company) => company.exposure));
  const companies: CompanyNode[] = top.map((company, i) => ({
    id: company.company_key,
    company,
    x: COMPANY_X,
    y: PAD_Y + (i + 0.5) * ROW,
    r: 4 + 14 * scaled(company.exposure, maxExposure),
  }));

  const contributions = companies.flatMap((node) =>
    node.company.contributions
      .filter((item) => item.contribution > 0 && etfById.has(item.etf_ticker))
      .map((item) => ({ node, item })),
  );
  const maxContribution = Math.max(0, ...contributions.map(({ item }) => item.contribution));
  const edges: Edge[] = contributions.map(({ node, item }) => {
    const from = etfById.get(item.etf_ticker) as EtfNode;
    const mid = (from.x + node.x) / 2;
    return {
      id: `${item.etf_ticker}|${node.id}`,
      etf: item.etf_ticker,
      company: node.id,
      contribution: item.contribution,
      width: maxContribution > 0 ? Math.max(1.25, (10 * item.contribution) / maxContribution) : 1.25,
      colorIndex: from.colorIndex,
      path: `M ${from.x} ${from.y} C ${mid} ${from.y}, ${mid} ${node.y}, ${node.x} ${node.y}`,
    };
  });

  return {
    etfs,
    companies,
    edges,
    height,
    total: analysis.exposures.length,
    shownExposure: top.reduce((sum, company) => sum + company.exposure, 0),
  };
}

export function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}
