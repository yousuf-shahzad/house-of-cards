"use client";
// FIX-47/FIX-59: what guide steps 2-5 show when there's no current analysis to display. They never show an
// earlier portfolio's results as current: a failed analysis shows the error, and an edited but unfinished
// portfolio says so and points back to Step 1.

import type { ReactNode } from "react";
import { useAnalysis } from "@/app/analysis";
import { useExperience } from "@/app/experience";
import { ServerError } from "@/app/ui/draft-editor";
import { Button } from "@/components/base/buttons/button";
import { Spinner } from "@/components/base/spinner/spinner";
import { guideAnalysisView } from "./auto-run";

/** Returns the screen to show instead of the step's results, or null when the current analysis is ready. */
export function useGuideAnalysisGate(loadingText: string): ReactNode | null {
  const { analysis, status, stale, error, retry, valuation } = useAnalysis();
  const { setStep } = useExperience();
  // Every "Back to Step 1" button really goes to Step 1 (the stepper's Back only goes one step back).
  const onBack = () => setStep(1);
  // Shares mode: an ETF that can't be priced or found blocks the analysis, so say that rather than "unfinished".
  const cantPrice = valuation.status === "blocked" || valuation.status === "error";
  const view = guideAnalysisView({ status, stale, hasAnalysis: analysis !== null, hasError: error !== null });

  if (view === "loading") {
    return (
      <section className="suite-card flex flex-col items-center justify-center gap-3 py-10 text-center" aria-live="polite">
        <Spinner size="md" aria-label="Loading" />
        <p className="text-body-medium text-text-primary">{loadingText}</p>
      </section>
    );
  }
  if (view === "error" && error) {
    return (
      <section className="suite-card flex flex-col items-start gap-3" aria-live="polite">
        <p className="text-body-medium text-text-primary">We couldn't check this portfolio.</p>
        <ServerError error={error} retry={retry} />
        <Button variant="secondary" size="small" onClick={onBack}>
          Back to Step 1
        </Button>
      </section>
    );
  }
  if (view === "changed") {
    return (
      <section className="suite-card flex flex-col items-start gap-3" aria-live="polite">
        <p className="text-body-medium text-text-primary">
          {cantPrice
            ? "We couldn't price or find one of your ETFs."
            : "Your portfolio has changed but isn't finished yet."}
        </p>
        <p className="text-body-2-regular text-text-secondary">
          {cantPrice ? "Check the tickers in Step 1" : "Finish it in Step 1"} and these results will update. We won't
          show the old portfolio's numbers here.
        </p>
        <Button variant="secondary" size="small" onClick={onBack}>
          Back to Step 1
        </Button>
      </section>
    );
  }
  if (view === "empty") {
    return (
      <section className="suite-card flex flex-col items-start gap-3">
        <p className="text-body-medium text-text-primary">Pick or enter a valid portfolio totaling 100% in Step 1 first.</p>
        <Button variant="secondary" size="small" onClick={onBack}>
          Back to Step 1
        </Button>
      </section>
    );
  }
  return null;
}
