"use client";
// Step 3 (B-GUIDE): How spread out is it?
// One verdict chip (Diversified / Moderately concentrated / Highly concentrated),
// "Your 10 biggest companies are 37.14% of your money",
// "It behaves like about 50 equal holdings", and the top 3 industries (sectors).

import { RiArrowRightUpLine, RiPieChart2Line, RiScales3Line } from "@remixicon/react";
import { useAnalysis } from "@/app/analysis";
import { useExperience } from "@/app/experience";
import { diversificationVerdict } from "@/app/ui/concentration";
import { Pct } from "@/app/ui/pct";
import { Chip } from "@/components/base/badges/chip";
import {
  GUIDE_STEP_META,
  plainSectorName,
} from "../copy";
import type { GuideStepProps } from "../index";
import { useGuideAnalysisGate } from "../analysis-gate";

const STEP_META = GUIDE_STEP_META[2];

export function StepSpread({ onBack }: GuideStepProps) {
  const { analysis } = useAnalysis();
  const { openExpertPage } = useExperience();
  // FIX-47: never show an earlier portfolio's results as current (loading, error, unfinished edit, empty).
  const gate = useGuideAnalysisGate(onBack, "Checking how spread out your money is…");
  if (gate || !analysis) return gate;

  const { concentration, sectors } = analysis;
  const verdict = diversificationVerdict({ hhi: concentration.hhi, sectors });
  const equalHoldingsCount = Math.max(1, Math.round(concentration.effective_companies));
  const topThreeSectors = sectors.filter((item) => item.sector !== "unknown").slice(0, 3);
  const topSector = verdict.topSector ?? topThreeSectors[0] ?? null;
  const sectorConcentrated = verdict.sectorConcentrated;
  const maxSectorWeight = Math.max(0.01, topSector?.weight ?? 0.01);

  return (
    <div className="flex flex-col gap-5">
      {/* Verdict + 2 headline concentration sentences */}
      <section className="suite-card flex flex-col gap-4" aria-label="Concentration summary">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <RiScales3Line className="size-5 shrink-0 text-foreground-icon-secondary" aria-hidden />
            <h2 className="text-headline-medium text-text-primary">Overall balance</h2>
          </div>
          <Chip variant="subtle" color={verdict.color}>
            {verdict.label}
          </Chip>
        </div>

        <div className="flex flex-col gap-1.5">
          <p className="text-body-regular text-text-secondary">{verdict.summary}</p>
          {sectorConcentrated && topSector && (
            <p className="text-body-medium text-text-primary">
              But about half your money (<Pct value={topSector.weight} digits={2} className="font-semibold" />) is in
              one industry: <strong>{plainSectorName(topSector.sector)}</strong>.
            </p>
          )}
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5 rounded-2xl border border-separator-border bg-background-primary-default p-4">
            <p className="text-body-medium text-text-primary">
              Your 10 biggest companies are{" "}
              <Pct value={concentration.top10} digits={2} className="font-semibold" /> of your money.
            </p>
            <p className="text-caption-1-regular text-text-secondary">
              Your top 5 alone account for <Pct value={concentration.top5} digits={2} />.
            </p>
          </div>

          <div className="flex flex-col gap-1.5 rounded-2xl border border-separator-border bg-background-primary-default p-4">
            <p className="text-body-medium text-text-primary">
              It behaves like about <strong>{equalHoldingsCount.toLocaleString()}</strong> equal holdings.
            </p>
            <p className="text-caption-1-regular text-text-secondary">
              Even though your ETFs hold {concentration.distinct_companies.toLocaleString()} separate companies in total.
            </p>
          </div>
        </div>
      </section>

      {/* Top 3 industries */}
      <section className="suite-card flex flex-col gap-4" aria-label="Top 3 industries">
        <div className="flex items-center gap-2">
          <RiPieChart2Line className="size-5 shrink-0 text-foreground-icon-secondary" aria-hidden />
          <h2 className="text-headline-medium text-text-primary">Your top 3 industries</h2>
        </div>

        {topThreeSectors.length === 0 ? (
          <p className="text-body-regular text-text-secondary">
            Industry data is not available for the selected ETFs.
          </p>
        ) : (
          <ol className="flex flex-col gap-3">
            {topThreeSectors.map((sector) => {
              const widthPct = Math.min(100, Math.max(4, (sector.weight / maxSectorWeight) * 100));
              return (
                <li
                  key={sector.sector}
                  className="flex flex-col gap-1.5 rounded-2xl border border-separator-border bg-background-primary-default p-3.5"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-body-medium text-text-primary">
                      {plainSectorName(sector.sector)}
                    </span>
                    <Pct
                      value={sector.weight}
                      digits={2}
                      className="text-body-semibold text-text-primary"
                    />
                  </div>
                  <div
                    className="h-2 w-full overflow-hidden rounded-full bg-background-tertiary-default"
                    aria-hidden
                  >
                    <div
                      className="h-full rounded-full bg-accent-500 transition-[width] duration-300"
                      style={{ width: `${widthPct}%` }}
                    />
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </section>

      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => openExpertPage(STEP_META.learnMoreHref)}
          className="inline-flex items-center gap-1 text-caption-1-medium text-text-secondary underline hover:text-text-primary"
        >
          <span>{STEP_META.learnMoreLabel}</span>
          <RiArrowRightUpLine className="size-3.5" aria-hidden />
        </button>
      </div>
    </div>
  );
}
