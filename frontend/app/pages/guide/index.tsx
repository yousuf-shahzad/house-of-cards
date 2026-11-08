"use client";
// B-GUIDE: 5-step beginner guided view (#/guide).
// Owner: Yousuf's Gemini.
// Integrates with B-SHELL's useExperience() (app/experience.tsx) so the top-bar "Step N of 5"
// and the stepper stay in sync and preserve the active step across Simple/Full view switches.

import { useCallback, useEffect, useId, useState, type ComponentType } from "react";
import { RiArrowLeftLine, RiArrowRightLine, RiInformationLine } from "@remixicon/react";
import { useAnalysis } from "@/app/analysis";
import { TOTAL_GUIDE_STEPS, useExperience } from "@/app/experience";
import { Button } from "@/components/base/buttons/button";
import { TryAChange } from "@/app/ui/try-a-change";
import { ProgressBar } from "@/components/base/progress/progress";
import {
  GUIDE_STEP_INFO,
  GUIDE_STEP_META,
  TRY_CHANGE_INFO,
  type GuideStepMeta,
  type TabInfoGuide,
} from "./copy";
import RisksStep from "./step-4-risks";
import NextStep from "./step-5-next";
import { StepOwn } from "./steps/own";
import { StepPick } from "./steps/pick";
import { StepSpread } from "./steps/spread";

export interface GuideStepProps {
  onNext: () => void;
  onBack: () => void;
  onStartOver?: () => void;
  onJumpToStep?: (step: number) => void;
  /** Step 5: opens the "Try a change" sub-screen (F6). */
  onTryChange?: () => void;
}

export interface GuideStepEntry {
  meta: GuideStepMeta;
  Component: ComponentType<GuideStepProps>;
}

export const GUIDE_STEPS: readonly GuideStepEntry[] = [
  { meta: GUIDE_STEP_META[0], Component: StepPick },
  { meta: GUIDE_STEP_META[1], Component: StepOwn },
  { meta: GUIDE_STEP_META[2], Component: StepSpread },
  { meta: GUIDE_STEP_META[3], Component: RisksStep },
  { meta: GUIDE_STEP_META[4], Component: NextStep },
] as const;

export { TOTAL_GUIDE_STEPS };

export function TabInfoBanner({
  info,
  buttonLabel = "What's here & why",
}: {
  info: TabInfoGuide;
  buttonLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center">
        <Button
          variant="secondary"
          size="xs"
          leadingIcon={RiInformationLine}
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((prev) => !prev)}
        >
          {open ? "Hide guide" : buttonLabel}
        </Button>
      </div>
      {open && (
        <aside
          id={panelId}
          aria-label={info.title}
          className="flex flex-col gap-3 rounded-2xl border border-border-button-default bg-background-secondary-default p-4 text-body-2-regular text-text-secondary"
        >
          <p className="text-body-2-semibold text-text-primary">{info.title}</p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1">
              <span className="text-caption-1-semibold text-text-primary">
                What is on this screen
              </span>
              <p>{info.whatsHere}</p>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-caption-1-semibold text-text-primary">
                Why it matters
              </span>
              <p>{info.whyItMatters}</p>
            </div>
          </div>
          {info.keyDetails.length > 0 && (
            <div className="flex flex-col gap-1 border-t border-separator-border pt-2.5">
              <span className="text-caption-1-semibold text-text-primary">
                Key details & how to read it
              </span>
              <ul className="list-disc space-y-1 pl-4">
                {info.keyDetails.map((detail, idx) => (
                  <li key={idx}>{detail}</li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      )}
    </div>
  );
}

export default function GuidePage() {
  const { step, totalSteps: total, setStep } = useExperience();
  const { status, analysis, stale } = useAnalysis();
  // FIX-59: only move on once the current draft is analysed (not an older portfolio's results).
  const canProceedFromStep1 = status === "ready" && !stale && Boolean(analysis);

  // F6: step 5's "Try a change" sub-screen. Leaving step 5 (Start over, the stepper) closes it.
  const [tryingChange, setTryingChange] = useState(false);
  const showTryChange = tryingChange && step === 5;
  useEffect(() => {
    if (step !== 5) setTryingChange(false);
  }, [step]);

  const entry = GUIDE_STEPS[step - 1] ?? GUIDE_STEPS[0];
  const StepComponent = entry.Component;

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [step, showTryChange]);

  const handleNext = useCallback(() => {
    if (step === 1 && !canProceedFromStep1) return;
    setStep(step + 1);
  }, [step, canProceedFromStep1, setStep]);

  const handleBack = useCallback(() => {
    setStep(step - 1);
  }, [step, setStep]);

  const handleStartOver = useCallback(() => {
    setStep(1);
  }, [setStep]);

  const progressPct = Math.round((step / total) * 100);

  return (
    <div className="mx-auto flex w-full max-w-[720px] flex-col gap-6">
      {/* Step header & progress bar */}
      <header className="flex flex-col gap-3" aria-label="Guided walkthrough progress">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-caption-1-medium text-text-secondary tabular-nums">
            Step {step} of {total}
          </span>
          <span className="text-caption-1-regular text-text-tertiary">{entry.meta.shortLabel}</span>
        </div>
        <ProgressBar
          aria-label={`Step ${step} of ${total}: ${entry.meta.shortLabel}`}
          value={progressPct}
          showValueLabel={false}
          size="md"
        />
        <div className="flex flex-col gap-2 pt-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h1 className="text-display-4-medium text-text-primary">
              {showTryChange ? "Try a change" : entry.meta.title}
            </h1>
          </div>
          <p className="text-body-regular text-text-secondary">
            {showTryChange
              ? "Change your ETFs below. The comparison with your portfolio updates each time you change a value."
              : entry.meta.subtitle}
          </p>
          <TabInfoBanner
            key={showTryChange ? "try-change" : entry.meta.id}
            info={showTryChange ? TRY_CHANGE_INFO : GUIDE_STEP_INFO[entry.meta.id]}
          />
        </div>
      </header>

      {/* Active step body */}
      {showTryChange ? (
        <TryAChange editorTitle="Your changed portfolio" />
      ) : (
        <StepComponent
          onNext={handleNext}
          onBack={handleBack}
          onStartOver={handleStartOver}
          onJumpToStep={setStep}
          onTryChange={() => setTryingChange(true)}
        />
      )}

      {/* Big Back / Next navigation footer */}
      <nav
        aria-label="Step navigation"
        className="flex flex-wrap items-center justify-between gap-3 border-t border-separator-border pt-4"
      >
        <div>
          {showTryChange ? (
            <Button variant="secondary" size="medium" leadingIcon={RiArrowLeftLine} onClick={() => setTryingChange(false)}>
              Back to the ideas
            </Button>
          ) : (
            step > 1 && (
              <Button
                variant="secondary"
                size="medium"
                leadingIcon={RiArrowLeftLine}
                onClick={handleBack}
              >
                Back
              </Button>
            )
          )}
        </div>

        <div className="flex items-center gap-3">
          {step === 1 && !canProceedFromStep1 && (
            <span className="text-caption-1-regular text-text-secondary">
              {stale ? "Finish or fix your ETFs above to continue" : "Load a sample or enter your ETFs to continue"}
            </span>
          )}
          {step < total && (
            <Button
              variant="primary"
              size="medium"
              trailingIcon={RiArrowRightLine}
              disabled={step === 1 && !canProceedFromStep1}
              onClick={handleNext}
            >
              Next: {GUIDE_STEPS[step]?.meta.shortLabel ?? "Continue"}
            </Button>
          )}
        </div>
      </nav>
    </div>
  );
}
