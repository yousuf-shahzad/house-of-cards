"use client";
// B-GUIDE: 5-step beginner guided view (#/guide).
// Owner: Yousuf's Gemini.
// Integrates with B-SHELL's useExperience() (app/experience.tsx) so the top-bar "Step N of 5"
// and the stepper stay in sync and preserve the active step across Simple/Full view switches.

import { useCallback, useEffect, type ComponentType } from "react";
import { RiArrowLeftLine, RiArrowRightLine } from "@remixicon/react";
import { useAnalysis } from "@/app/analysis";
import { TOTAL_GUIDE_STEPS, useExperience } from "@/app/experience";
import { Button } from "@/components/base/buttons/button";
import { ProgressBar } from "@/components/base/progress/progress";
import { GUIDE_STEP_META, type GuideStepMeta } from "./copy";
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

export default function GuidePage() {
  const { step, totalSteps: total, setStep } = useExperience();
  const { status, analysis } = useAnalysis();
  const canProceedFromStep1 = status === "ready" && Boolean(analysis);

  const entry = GUIDE_STEPS[step - 1] ?? GUIDE_STEPS[0];
  const StepComponent = entry.Component;

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [step]);

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
        <div className="flex flex-col gap-1 pt-1">
          <h1 className="text-display-4-medium text-text-primary">{entry.meta.title}</h1>
          <p className="text-body-regular text-text-secondary">{entry.meta.subtitle}</p>
        </div>
      </header>

      {/* Active step body */}
      <StepComponent onNext={handleNext} onBack={handleBack} onStartOver={handleStartOver} onJumpToStep={setStep} />

      {/* Big Back / Next navigation footer */}
      <nav
        aria-label="Step navigation"
        className="flex flex-wrap items-center justify-between gap-3 border-t border-separator-border pt-4"
      >
        <div>
          {step > 1 && (
            <Button
              variant="secondary"
              size="medium"
              leadingIcon={RiArrowLeftLine}
              onClick={handleBack}
            >
              Back
            </Button>
          )}
        </div>

        <div className="flex items-center gap-3">
          {step === 1 && !canProceedFromStep1 && (
            <span className="text-caption-1-regular text-text-secondary">
              Load a sample or enter your ETFs to continue
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
