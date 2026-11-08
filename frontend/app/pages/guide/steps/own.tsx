"use client";
// Step 2 (B-GUIDE): What you really own.
// Top 5 companies as plain sentences ("7.37% of your money ends up in Apple Inc., through 3 of your ETFs"),
// plus one overlap sentence for the most-overlapping ETF pair.
// Also starts the background AI supply-chain check via useAutoDependencies().

import { RiArrowRightUpLine, RiGridLine } from "@remixicon/react";
import { useAnalysis } from "@/app/analysis";
import { EtfChip } from "@/app/ui/etf-chip";
import { Pct } from "@/app/ui/pct";
import { Button } from "@/components/base/buttons/button";
import { GUIDE_STEP_META, openInFullView } from "../copy";
import type { GuideStepProps } from "../index";
import { pickMostOverlappingPair } from "../sentence";
import { useAutoDependencies } from "../use-auto-dependencies";
import { useGuideAnalysisGate } from "../analysis-gate";

const STEP_META = GUIDE_STEP_META[1];

export function StepOwn({ onBack }: GuideStepProps) {
  const { analysis } = useAnalysis();
  // Always-run AI supply-chain check in the background as soon as step 2 renders ready.
  useAutoDependencies();
  // FIX-47: never show an earlier portfolio's results as current (loading, error, unfinished edit, empty).
  const gate = useGuideAnalysisGate(onBack, "Adding up the companies inside your ETFs…");
  if (gate) return gate;

  if (!analysis || analysis.exposures.length === 0) {
    return (
      <section className="suite-card flex flex-col items-start gap-3">
        <p className="text-body-medium text-text-primary">
          Pick or enter a valid portfolio totaling 100% in Step 1 first.
        </p>
        <Button variant="secondary" size="small" onClick={onBack}>
          Back to Step 1
        </Button>
      </section>
    );
  }

  const topFive = analysis.exposures.slice(0, 5);
  const topScore = Math.max(0.01, topFive[0]?.exposure ?? 0.01);
  const topPair = pickMostOverlappingPair(analysis.overlap.pairs);

  return (
    <div className="flex flex-col gap-5">
      {/* Top 5 companies as plain-English sentences */}
      <section className="suite-card flex flex-col gap-4" aria-label="Your top 5 companies">
        <div className="flex flex-col gap-1">
          <h2 className="text-headline-medium text-text-primary">Your 5 biggest companies</h2>
          <p className="text-body-2-regular text-text-secondary">
            Several ETFs often hold the exact same company. Adding those slices together shows your real stake.
          </p>
        </div>

        <ol className="flex flex-col gap-3">
          {topFive.map((company) => {
            const etfCount = company.contributions.length;
            const barWidth = Math.min(100, Math.max(4, (company.exposure / topScore) * 100));
            return (
              <li
                key={company.company_key}
                className="flex flex-col gap-2 rounded-2xl border border-separator-border bg-background-primary-default p-4"
              >
                <p className="text-body-medium text-text-primary">
                  <Pct value={company.exposure} digits={2} className="font-semibold text-text-primary" /> of your money
                  ends up in <strong>{company.company_name}</strong>, through{" "}
                  <strong>{etfCount} of your ETFs</strong>.
                </p>

                <div
                  className="h-2 w-full overflow-hidden rounded-full bg-background-tertiary-default"
                  aria-hidden
                >
                  <div
                    className="h-full rounded-full bg-accent-500 transition-[width] duration-300"
                    style={{ width: `${barWidth}%` }}
                  />
                </div>

                <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                  <span className="text-caption-1-regular text-text-tertiary">Held inside:</span>
                  {company.contributions.map((contrib) => (
                    <span
                      key={contrib.etf_ticker}
                      className="inline-flex items-center gap-1 rounded-md border border-separator-border px-2 py-0.5 text-caption-1-regular text-text-secondary"
                    >
                      <EtfChip ticker={contrib.etf_ticker} />
                      <Pct value={contrib.contribution} digits={2} />
                    </span>
                  ))}
                </div>
              </li>
            );
          })}
        </ol>
      </section>

      {/* Single overlap sentence for the most-overlapping ETF pair */}
      <section className="suite-card flex flex-col gap-2" aria-label="ETF overlap summary">
        <div className="flex items-center gap-2">
          <RiGridLine className="size-5 shrink-0 text-foreground-icon-secondary" aria-hidden />
          <h2 className="text-headline-medium text-text-primary">Do your ETFs own the same companies?</h2>
        </div>
        {topPair ? (
          <p className="text-body-regular text-text-primary">
            <strong>{topPair.etf_a}</strong> and <strong>{topPair.etf_b}</strong> overlap by{" "}
            <Pct value={topPair.weighted_overlap} digits={2} className="font-semibold" /> — they share{" "}
            <strong>{topPair.shared_companies.toLocaleString()}</strong> of the same companies.
          </p>
        ) : (
          <p className="text-body-regular text-text-secondary">
            You currently hold one ETF, so there is no overlap between separate funds.
          </p>
        )}
      </section>

      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => openInFullView(STEP_META.learnMoreHref)}
          className="inline-flex items-center gap-1 text-caption-1-medium text-text-secondary underline hover:text-text-primary"
        >
          <span>{STEP_META.learnMoreLabel}</span>
          <RiArrowRightUpLine className="size-3.5" aria-hidden />
        </button>
      </div>
    </div>
  );
}
