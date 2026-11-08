import { useState } from "react";
import { useDependencies } from "@/app/dependencies-state";
import { Button } from "@/components/base/buttons/button";
import { Chip } from "@/components/base/badges/chip";
import type { EdgeType, ImportanceTier } from "@/api/types";
import RisksStep from "../guide/step-4-risks";

const RELATION: Record<EdgeType, string> = {
  supplier: "buys from", foundry: "uses chip manufacturing at", contract_manufacturer: "uses manufacturing at",
  key_input: "uses", customer: "sells to",
  jv_partner: "partners with", facility: "has facilities in",
};
const TIER: Record<ImportanceTier, string> = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };

function formatSimpleSection(section: string): string {
  const trimmed = section.trim();
  if (!trimmed) return "Annual report";
  if (/^item\s+/i.test(trimmed)) return trimmed;
  if (/^concentration_\d+$/i.test(trimmed)) return "Concentration note";
  if (/^(\d+[A-Z]?|\d+\.[A-Z])\b/i.test(trimmed)) return `Item ${trimmed}`;
  return trimmed;
}

/** Same scan/progress as the guide, with filing evidence available on this page. */
export function SimpleDependencies() {
  const { job, stale } = useDependencies();
  const [expanded, setExpanded] = useState(false);
  const result = !stale ? job?.result : null;
  const allEdges = [...(result?.edges ?? [])].sort((a, b) => (b.importance?.score ?? 0) - (a.importance?.score ?? 0));
  const edges = expanded ? allEdges : allEdges.slice(0, 5);
  return <div className="flex flex-col gap-5">
    <RisksStep showLearnMore={false} onNext={() => { window.location.hash = "#/compare"; }} onBack={() => { window.location.hash = "#/portfolio"; }} />
    {edges.length > 0 && <section className="suite-card flex flex-col gap-3" aria-label="Filing evidence">
      <h2 className="text-headline-medium text-text-primary">See what the reports say</h2>
      <p className="text-body-2-regular text-text-secondary">Links ranked by how much they matter to the company. This is a judgement from the report, not a share of your money.</p>
      <ul className="flex flex-col gap-3">
        {edges.map((edge) => <li key={edge.edge_id} className="rounded-2xl border border-separator-border p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-body-medium text-text-primary">{edge.source_company_name} {RELATION[edge.edge_type] ?? "has a link with"} {edge.target_name}</p>
            {edge.importance && <span title="How much this link matters to the company, judged from its filing"><Chip variant="caption" color={edge.importance.tier === "critical" ? "rose" : edge.importance.tier === "high" ? "orange" : "neutral"}>{TIER[edge.importance.tier]}</Chip></span>}
          </div>
          {edge.interpretation?.status === "flagged" && <p className="mt-2 text-body-2-regular text-text-secondary">Meaning needs care: {edge.interpretation.reason ?? "the filing leaves this link uncertain."}</p>}
          {!edge.source_in_portfolio && <p className="mt-2 text-caption-1-regular text-text-secondary">Reported by a company outside your portfolio.</p>}
          <details className="mt-2 text-body-2-regular text-text-secondary">
            <summary className="cursor-pointer text-text-primary">Read filing evidence</summary>
            <blockquote className="my-3 border-s-4 border-separator-border ps-3 text-text-primary">{edge.evidence_quote}</blockquote>
            {edge.importance && <p className="my-2">Why this matters: {edge.importance.reasons.join(" · ")}</p>}
            <a href={edge.filing.url} target="_blank" rel="noreferrer" className="underline">Annual report ({edge.filing.form}), {formatSimpleSection(edge.section)}, filed {edge.filing.filed}</a>
          </details>
        </li>)}
      </ul>
      {allEdges.length > 5 && <Button variant="ghost" size="small" className="self-start" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? "Show five links" : `Show all ${allEdges.length} links`}</Button>}
    </section>}
  </div>;
}
