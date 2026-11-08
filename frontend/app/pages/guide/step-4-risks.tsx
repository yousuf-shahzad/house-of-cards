// Beginner guide, step 4: hidden risks (B-RISKS + v3.1 K1: F5, #151, F7).
//
// The supply-chain check has been running in the background since step 2 (useAutoDependencies).
// This step shows its phased progress ("Reading reports -> Double-checking findings -> Writing summary"),
// then three plain findings, the AI's top two concerns (plain_title + plain_text with full text under "Read more"),
// and a single "Go deeper" button after a light run whose results replace in place.

import { useRef, useState } from "react";
import { useAnalysis } from "@/app/analysis";
import { useDependencies } from "@/app/dependencies-state";
import { useExperience } from "@/app/experience";
import { buildMetricCards, metricKind, metricSubject } from "@/app/pages/dependencies/metrics";
import { formatPct } from "@/app/ui/pct";
import { scanBarIndeterminate } from "@/app/ui/scan-activity";
import { ScanActivity } from "@/app/ui/scan-activity-view";
import { Chip, type ChipColor } from "@/components/base/badges/chip";
import { Button } from "@/components/base/buttons/button";
import { ProgressBar } from "@/components/base/progress/progress";
import type {
  DependencyResult,
  EdgeType,
  InsightClaim,
  InsightsStatus,
  MetricFact,
  ResearchFinding,
  ResearchOutcome,
} from "@/api/types";
import { useAutoDependencies } from "./use-auto-dependencies";
import { useGuideAnalysisGate } from "./analysis-gate";
import { RISKS_COPY } from "./copy";
import {
  formatFindingOneLiner,
  monotonicProgressPct,
  plainCounterpartyText,
  splitFirstSentence,
} from "./sentence";

export { formatFindingOneLiner, splitFirstSentence };

/** Props from the guide stepper (pages/guide/index.tsx). */
export interface RiskStepProps {
  onNext: () => void;
  onBack: () => void;
  onJumpToStep?: (step: number) => void;
  onStartOver?: () => void;
  onTryChange?: () => void;
  showLearnMore?: boolean;
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

export interface Finding {
  key: string;
  text: string;
  note?: string;
}

/** True when the run could not analyse companies on this computer (missing AI key or SEC contact). */
export function isCoverageNotAnalysed(result: DependencyResult): boolean {
  const verifiedWeight =
    result.coverage?.buckets.find((bucket) => bucket.kind === "verified")?.weight ??
    result.metrics.find((metric) => metric.metric_id === "summary.analysed_weight")?.value ??
    0;
  const notAnalysedWeight =
    result.coverage?.buckets.find((bucket) => bucket.kind === "not_analysed")?.weight ?? 0;
  const allCompaniesBlocked =
    result.companies.length > 0 &&
    result.counts.companies_analysed === 0 &&
    result.companies.some(
      (c) =>
        c.status === "missing_api_key" ||
        c.status === "sec_contact_missing" ||
        c.status === "error",
    );
  return (notAnalysedWeight > 0 && verifiedWeight <= 0) || allCompaniesBlocked;
}

/** Up to three plain findings: biggest dependency, biggest factory country abroad, and how much we could check. */
export function buildFindings(result: DependencyResult): Finding[] {
  if (isCoverageNotAnalysed(result)) {
    return [
      {
        key: "could-not-run",
        text: RISKS_COPY.couldNotRun,
        note: RISKS_COPY.couldNotRunNote,
      },
    ];
  }

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
    const notAnalysedWeight =
      result.coverage?.buckets.find((bucket) => bucket.kind === "not_analysed")?.weight ?? 0;
    const unfiledWeight =
      (result.coverage?.buckets.find((bucket) => bucket.kind === "no_disclosures")?.weight ?? 0) +
      (result.coverage?.buckets.find((bucket) => bucket.kind === "no_sec_filing")?.weight ?? 0);
    const note =
      notAnalysedWeight > 0 && unfiledWeight === 0
        ? RISKS_COPY.couldNotRunNote
        : RISKS_COPY.checkedNote;
    findings.push({ key: "checked", text: RISKS_COPY.checked(formatPct(verified, 0)), note });
  }
  return findings;
}

/**
 * Deterministic one-liner fallback built from the claim's first cited fraction metric
 * (e.g. "12% of your money depends on Taiwan Semiconductor Manufacturing Co., Ltd.")
 * when `claim.plain_text` is null.
 */
export function claimMetricOneLiner(claim: InsightClaim, metrics: readonly MetricFact[]): string | null {
  if (!claim.cited_metric_ids.length || !metrics.length) return null;
  const byId = new Map(metrics.map((m) => [m.metric_id, m]));
  for (const metricId of claim.cited_metric_ids) {
    const metric = byId.get(metricId);
    if (!metric || metric.unit !== "fraction") continue;
    const kind = metricKind(metric.metric_id);
    if (kind === "summary") continue;
    const pct = formatPct(metric.value, 0);
    const subject = metricSubject(metric);
    if (kind === "facility") {
      return `${RISKS_COPY.country(pct, subject)}.`;
    }
    return `${RISKS_COPY.dependsOn(pct, subject)}.`;
  }
  return null;
}

function ClaimCard({ claim, metrics }: { claim: InsightClaim; metrics: readonly MetricFact[] }) {
  const [open, setOpen] = useState(false);
  const title = claim.plain_title?.trim() || claim.title;
  const fullText = claim.text.trim();

  let shortText: string;
  let restText: string;
  if (claim.plain_text?.trim()) {
    shortText = claim.plain_text.trim();
    restText = fullText && fullText !== shortText ? fullText : "";
  } else {
    const oneLiner = claimMetricOneLiner(claim, metrics);
    if (oneLiner) {
      shortText = oneLiner;
      restText = fullText && fullText !== shortText ? fullText : "";
    } else {
      const [first, rest] = splitFirstSentence(fullText);
      shortText = first;
      restText = rest;
    }
  }

  const expandedText =
    claim.plain_text?.trim() || claimMetricOneLiner(claim, metrics)
      ? fullText
      : restText
        ? `${shortText} ${restText}`
        : shortText;

  return (
    <li className="flex flex-col gap-1 rounded-2xl border border-border-button-default bg-background-secondary-default p-4">
      <span className="text-body-semibold text-text-primary">{title}</span>
      <span className="text-body-2-regular text-text-secondary">{open && restText ? expandedText : shortText}</span>
      {restText ? (
        <Button variant="ghost" size="xs" className="self-start" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? RISKS_COPY.showLess : RISKS_COPY.readMore}
        </Button>
      ) : null}
    </li>
  );
}

export function ClaimCards({
  claims,
  empty,
  metrics,
  insightsStatus,
}: {
  claims: readonly InsightClaim[];
  empty?: string;
  metrics?: readonly MetricFact[];
  insightsStatus?: InsightsStatus;
}) {
  const { job } = useDependencies();
  const effectiveMetrics = metrics ?? job?.result?.metrics ?? [];
  const effectiveStatus = insightsStatus ?? job?.result?.insights.status;

  if (claims.length === 0) {
    // #151: Never show a "no problems" / "no suggestions" line unless insights.status === "ok".
    if (effectiveStatus && effectiveStatus !== "ok") {
      if (effectiveStatus === "missing_api_key") {
        return <p className="text-body-2-regular text-text-secondary">{RISKS_COPY.noAiKey}</p>;
      }
      return null;
    }
    if (!empty) return null;
    return <p className="text-body-2-regular text-text-secondary">{empty}</p>;
  }
  return (
    <ul className="flex flex-col gap-3">
      {claims.map((claim) => (
        <ClaimCard key={claim.claim_id} claim={claim} metrics={effectiveMetrics} />
      ))}
    </ul>
  );
}

const OUTCOME_BADGE: Record<ResearchOutcome, { label: string; color: ChipColor }> = {
  confirmed: { label: "Confirmed", color: "lime" },
  new_evidence: { label: "New evidence", color: "cyan" },
  revised: { label: "Revised", color: "blue" },
  rejected: { label: "Rejected", color: "rose" },
  unresolved: { label: "Unresolved", color: "yellow" },
};

function ResearchFindingItem({ finding }: { finding: ResearchFinding }) {
  const [showTrace, setShowTrace] = useState(false);
  const badge = OUTCOME_BADGE[finding.outcome] ?? {
    label: finding.outcome,
    color: "neutral" as ChipColor,
  };
  const oneLiner = formatFindingOneLiner(
    finding.subject,
    finding.outcome,
    finding.explanation,
  );
  const hasDetails = Boolean(finding.explanation?.trim() || finding.steps?.length);

  return (
    <li className="flex flex-col gap-1.5 rounded-xl border border-separator-border bg-background-primary-default p-3 text-caption-1-regular text-text-secondary">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-text-primary">{oneLiner}</span>
        <div className="flex items-center gap-2">
          <Chip variant="caption" color={badge.color}>
            {badge.label}
          </Chip>
          {hasDetails && (
            <Button
              variant="ghost"
              size="xs"
              aria-expanded={showTrace}
              onClick={() => setShowTrace((prev) => !prev)}
            >
              {showTrace ? RISKS_COPY.showLess : "Details"}
            </Button>
          )}
        </div>
      </div>
      {showTrace && (
        <div className="flex flex-col gap-1.5 border-t border-separator-border pt-2">
          {finding.explanation && <p>{plainCounterpartyText(finding.explanation)}</p>}
          {finding.steps.length > 0 && (
            <ol className="list-decimal space-y-1 pl-4 text-text-tertiary">
              {finding.steps.map((step) => (
                <li key={step.index}>
                  <span className="text-text-secondary">{plainCounterpartyText(step.summary)}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </li>
  );
}

function ResearchFindingsList({ findings }: { findings: readonly ResearchFinding[] }) {
  if (findings.length === 0) return null;
  return (
    <ul className="flex flex-col gap-2">
      {findings.map((finding) => (
        <ResearchFindingItem key={finding.finding_id} finding={finding} />
      ))}
    </ul>
  );
}

export default function RisksStep({ showLearnMore = true }: RiskStepProps) {
  useAutoDependencies(); // safety net if step 2 was skipped
  const { status: analysisStatus } = useAnalysis();
  const { status, job, stale, error, depth, goDeeper } = useDependencies();
  const { openExpertPage } = useExperience();
  // FIX-59: with an unfinished edit, a failed analysis or no portfolio, say so instead of an endless progress bar.
  const gate = useGuideAnalysisGate("Checking your portfolio…");

  // Keep existing result visible in place while "Go deeper" polls on the same portfolio.
  const result = !stale ? job?.result ?? null : null;
  const running = !error && (status === "starting" || status === "polling" || (stale && analysisStatus === "ready"));
  const liveResearch = job?.research ?? [];

  const activePhase = status === "starting" ? "reading" : (job?.phase ?? "reading");
  const stepsDone = status === "starting" ? 0 : (job?.steps_done || job?.progress_done || 0);
  const stepsTotal = job?.steps_total || job?.progress_total || job?.companies.length || 15;
  const rawPct =
    status === "starting"
      ? 0
      : job?.status === "done"
        ? 100
        : stepsTotal > 0
          ? (stepsDone / stepsTotal) * 100
          : 0;
  const progressRef = useRef<{ jobId: string | null; pct: number; status: string | null }>({
    jobId: null,
    pct: 0,
    status: null,
  });
  progressRef.current = monotonicProgressPct(
    progressRef.current.jobId,
    progressRef.current.pct,
    job?.job_id,
    rawPct,
    progressRef.current.status,
    status === "starting" ? "starting" : (job?.status ?? status),
  );
  const progressPct = progressRef.current.pct;
  const phases: Array<{ id: "reading" | "researching" | "synthesising"; label: string }> = [
    { id: "reading", label: RISKS_COPY.phaseReading },
    { id: "researching", label: RISKS_COPY.phaseResearching },
    { id: "synthesising", label: RISKS_COPY.phaseSynthesising },
  ];
  const phaseOrder = { queued: 0, reading: 0, researching: 1, synthesising: 2, done: 3 } as const;
  const currentPhaseIdx = phaseOrder[activePhase] ?? 0;

  const progressBlock = running ? (
    <div className="flex flex-col gap-3 rounded-2xl border border-border-button-default bg-background-secondary-default p-4">
      <div className="flex flex-wrap items-center gap-2">
        {phases.map((p, idx) => {
          const isActive = idx === currentPhaseIdx;
          const isDone = idx < currentPhaseIdx;
          return (
            <span key={p.id} className="inline-flex items-center gap-2">
              {idx > 0 && <span className="text-caption-1-regular text-text-tertiary">→</span>}
              <Chip variant="caption" color={isActive ? "blue" : isDone ? "lime" : "neutral"}>
                {p.label}
              </Chip>
            </span>
          );
        })}
      </div>
      <ProgressBar
        label={RISKS_COPY.phasedProgress}
        description={RISKS_COPY.readingNote}
        isIndeterminate={scanBarIndeterminate(
          stale ? null : job,
          progressPct,
          status === "starting" || (stale && analysisStatus === "ready"),
        )}
        value={progressPct}
        maxValue={100}
      />
      <ScanActivity
        job={stale ? null : job}
        starting={status === "starting" || (stale && analysisStatus === "ready")}
      />
      {liveResearch.length > 0 && (
        <div className="flex flex-col gap-2 pt-1">
          <span className="text-caption-1-semibold text-text-primary">
            {RISKS_COPY.doubleCheckedTitle(liveResearch.length)}
          </span>
          <ResearchFindingsList findings={liveResearch} />
        </div>
      )}
    </div>
  ) : null;

  if (gate) return gate;

  let body;
  if (result) {
    const notAnalysed = isCoverageNotAnalysed(result);
    const claims = result.insights.status === "ok" ? topClaims(result.insights.flaws) : [];
    const showConcernsSection =
      !notAnalysed && (result.insights.status === "ok" || result.insights.status === "missing_api_key");
    const canGoDeeper = !notAnalysed && result.research_depth !== "thorough";
    const completedResearch = result.research ?? [];

    body = (
      <>
        {canGoDeeper && (
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" size="small" disabled={running} onClick={() => goDeeper()}>
              {running && depth === "thorough" ? RISKS_COPY.goingDeeper : RISKS_COPY.goDeeper}
            </Button>
          </div>
        )}
        {progressBlock}
        {showConcernsSection && (
          <section className="flex flex-col gap-3" aria-labelledby="guide-risks-concerns">
            <h3 id="guide-risks-concerns" className="text-body-semibold text-text-primary">
              {RISKS_COPY.concernsTitle}
            </h3>
            <ClaimCards
              claims={claims}
              metrics={result.metrics}
              insightsStatus={result.insights.status}
              empty={result.insights.status === "ok" ? RISKS_COPY.noConcerns : undefined}
            />
          </section>
        )}
        {!running && completedResearch.length > 0 && (
          <details className="flex flex-col gap-2 rounded-2xl border border-border-button-default bg-background-secondary-default p-4">
            <summary className="cursor-pointer text-body-2-medium text-text-primary">
              {RISKS_COPY.doubleCheckedTitle(completedResearch.length)}
            </summary>
            <div className="pt-3">
              <ResearchFindingsList findings={completedResearch} />
            </div>
          </details>
        )}
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
      </>
    );
  } else if (running) {
    body = progressBlock;
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
      {showLearnMore && <Button variant="ghost" size="small" className="self-start" onClick={() => openExpertPage("#/dependencies")}>
        {RISKS_COPY.learnMore}
      </Button>}
    </div>
  );
}
