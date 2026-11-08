// Beginner guide, step 4: hidden risks.
//
// The supply-chain check has been running in the background since step 2 (useAutoDependencies).
// This step shows its progress, then three plain findings and the AI's top two concerns. It never
// blocks: if the check is unavailable or fails, it says so and the user can carry on.
// Every number is a backend metric or coverage figure, formatted with formatPct.

import { useState } from "react";
import { useAnalysis } from "@/app/analysis";
import { useDependencies } from "@/app/dependencies-state";
import { useExperience } from "@/app/experience";
import { buildMetricCards } from "@/app/pages/dependencies/metrics";
import { formatPct } from "@/app/ui/pct";
import { Button } from "@/components/base/buttons/button";
import { ProgressBar } from "@/components/base/progress/progress";
import type { DependencyResult, EdgeType, InsightClaim } from "@/api/types";
import { useAutoDependencies } from "./use-auto-dependencies";
import { RISKS_COPY } from "./copy";

/** Props from the guide stepper (pages/guide/index.tsx). */
export interface RiskStepProps {
  onNext: () => void;
  onBack: () => void;
  onJumpToStep?: (step: number) => void;
  onStartOver?: () => void;
}

const SUPPLY_EDGE_TYPES = new Set<EdgeType>(["supplier", "foundry", "contract_manufacturer", "key_input"]);

const SEVERITY_ORDER: Record<InsightClaim["severity"], number> = { critical: 0, warning: 1, info: 2 };

/** The AI's most important claims first (critical, then warning, then info), keeping its own order within a level. */
export function topClaims(claims: readonly InsightClaim[], count = 2): InsightClaim[] {
  return [...claims]
    .map((claim, index) => ({ claim, index }))
    .sort((a, b) => SEVERITY_ORDER[a.claim.severity] - SEVERITY_ORDER[b.claim.severity] || a.index - b.index)
    .slice(0, count)
    .map(({ claim }) => claim);
}

interface Finding {
  key: string;
  text: string;
  note?: string;
}

/** Up to three plain findings: biggest dependency, biggest factory country, how much we could check. */
export function buildFindings(result: DependencyResult): Finding[] {
  const cards = buildMetricCards(result.metrics);
  const findings: Finding[] = [];
  // "Relies on" only for real supply links: a partner or customer (e.g. OpenAI as a JV partner) isn't a dependency
  // a beginner would recognise, even when its metric is the largest.
  const supplyEdges = new Set(result.edges.filter((e) => SUPPLY_EDGE_TYPES.has(e.edge_type)).map((e) => e.edge_id));
  const dependency = cards.find(
    (card) =>
      (card.kind === "depends_on" || card.kind === "critical") &&
      card.supportingEdgeIds.some((id) => supplyEdges.has(id)),
  );
  if (dependency) {
    findings.push({
      key: "dependency",
      text: RISKS_COPY.relies(formatPct(dependency.share.value, 0), dependency.subject),
      note: dependency.companies ? RISKS_COPY.reliesThrough(dependency.companies) : undefined,
    });
  }
  // Country metrics only (facility.<ISO2>); named sites are not countries. The home market (US) isn't a
  // hidden risk for a US investor, so show the biggest country abroad.
  const country = cards.find(
    (card) =>
      card.kind === "facility" && /^facility\.[A-Z]{2}$/.test(card.share.metric_id) && card.share.metric_id !== "facility.US",
  );
  if (country) {
    findings.push({ key: "country", text: RISKS_COPY.country(formatPct(country.share.value, 0), country.subject) });
  }
  const verified =
    result.coverage?.buckets.find((bucket) => bucket.kind === "verified")?.weight ??
    result.metrics.find((metric) => metric.metric_id === "summary.analysed_weight")?.value;
  if (typeof verified === "number" && Number.isFinite(verified)) {
    findings.push({ key: "checked", text: RISKS_COPY.checked(formatPct(verified, 0)), note: RISKS_COPY.checkedNote });
  }
  return findings;
}

/** "First sentence." and the rest, so beginners see a short summary with the detail one click away. */
export function splitFirstSentence(text: string): [string, string] {
  const match = /^(.+?[.!?])\s+(?=[A-Z0-9"'(])/.exec(text.trim());
  return match ? [match[1], text.trim().slice(match[0].length)] : [text.trim(), ""];
}

function ClaimCard({ claim }: { claim: InsightClaim }) {
  const [open, setOpen] = useState(false);
  const [first, rest] = splitFirstSentence(claim.text);
  return (
    <li className="flex flex-col gap-1 rounded-2xl border border-border-button-default bg-background-secondary-default p-4">
      <span className="text-body-semibold text-text-primary">{claim.title}</span>
      <span className="text-body-2-regular text-text-secondary">{open && rest ? `${first} ${rest}` : first}</span>
      {rest ? (
        <Button variant="ghost" size="xs" className="self-start" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? RISKS_COPY.showLess : RISKS_COPY.readMore}
        </Button>
      ) : null}
    </li>
  );
}

export function ClaimCards({ claims, empty }: { claims: readonly InsightClaim[]; empty: string }) {
  if (claims.length === 0) return <p className="text-body-2-regular text-text-secondary">{empty}</p>;
  return (
    <ul className="flex flex-col gap-3">
      {claims.map((claim) => (
        <ClaimCard key={claim.claim_id} claim={claim} />
      ))}
    </ul>
  );
}

export default function RisksStep(_props: RiskStepProps) {
  useAutoDependencies(); // safety net if step 2 was skipped
  const { status: analysisStatus } = useAnalysis();
  const { status, job, stale, error } = useDependencies();
  const { openExpertPage } = useExperience();
  const result = !stale && status === "done" ? job?.result ?? null : null;
  const running = !result && !error && (status === "starting" || status === "polling" || stale);

  let body;
  if (result) {
    const claims = result.insights.status === "ok" ? topClaims(result.insights.flaws) : [];
    const noKey = result.insights.status === "missing_api_key";
    body = (
      <>
        <ul className="flex flex-col gap-3">
          {buildFindings(result).map((finding) => (
            <li
              key={finding.key}
              className="flex flex-col gap-1 rounded-2xl border border-border-button-default bg-background-secondary-default p-4"
            >
              <span className="text-headline-medium text-text-primary">{finding.text}</span>
              {finding.note ? <span className="text-body-2-regular text-text-secondary">{finding.note}</span> : null}
            </li>
          ))}
        </ul>
        <section className="flex flex-col gap-3" aria-labelledby="guide-risks-concerns">
          <h3 id="guide-risks-concerns" className="text-body-semibold text-text-primary">
            {RISKS_COPY.concernsTitle}
          </h3>
          <ClaimCards claims={claims} empty={noKey ? RISKS_COPY.noAiKey : RISKS_COPY.noConcerns} />
        </section>
      </>
    );
  } else if (running) {
    const total = job?.progress_total || job?.companies.length || 15;
    body = (
      <ProgressBar
        label={RISKS_COPY.reading(total)}
        description={RISKS_COPY.readingNote}
        isIndeterminate={!job?.progress_total}
        value={job?.progress_done ?? 0}
        maxValue={total}
      />
    );
  } else if (status === "error" || error) {
    body = <p className="text-body-2-regular text-text-secondary">{RISKS_COPY.unavailable}</p>;
  } else {
    body = (
      <p className="text-body-2-regular text-text-secondary">
        {analysisStatus === "ready" ? RISKS_COPY.reading(15) : RISKS_COPY.waiting}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <p className="text-body-2-regular text-text-secondary">{RISKS_COPY.intro}</p>
      <div aria-live="polite" className="flex flex-col gap-5">
        {body}
      </div>
      <Button variant="ghost" size="small" className="self-start" onClick={() => openExpertPage("#/dependencies")}>
        {RISKS_COPY.learnMore}
      </Button>
    </div>
  );
}
