// Beginner guide, step 5: what could you do?
// The AI's top two suggestions (from the background check), then three ways to continue.

import { useDependencies } from "@/app/dependencies-state";
import { useExperience } from "@/app/experience";
import { Button } from "@/components/base/buttons/button";
import { ClaimCards, type RiskStepProps, topClaims } from "./step-4-risks";
import { NEXT_COPY } from "./copy";

export default function NextStep({ onJumpToStep, onStartOver, onTryChange }: RiskStepProps & { onTryChange?: () => void }) {
  const { status, job, stale } = useDependencies();
  const { openExpertPage, setStep } = useExperience();
  const result = !stale && status === "done" ? job?.result ?? null : null;
  const suggestions = result?.insights.status === "ok" ? topClaims(result.insights.suggestions) : [];

  return (
    <div className="flex flex-col gap-5">
      <p className="text-body-2-regular text-text-secondary">{NEXT_COPY.intro}</p>
      {result ? (
        <ClaimCards claims={suggestions} empty={NEXT_COPY.none} />
      ) : (
        <p className="text-body-2-regular text-text-secondary">{NEXT_COPY.waiting}</p>
      )}
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
        <Button
          variant="primary"
          onClick={() => (onTryChange ? onTryChange() : openExpertPage("#/compare"))}
          title={NEXT_COPY.tryChangeNote}
        >
          {NEXT_COPY.tryChange}
        </Button>
        <Button variant="secondary" onClick={() => openExpertPage("#/dependencies")} title={NEXT_COPY.seeEverythingNote}>
          {NEXT_COPY.seeEverything}
        </Button>
        <Button variant="ghost" onClick={() => (onStartOver ? onStartOver() : onJumpToStep ? onJumpToStep(1) : setStep(1))}>
          {NEXT_COPY.startOver}
        </Button>
      </div>
    </div>
  );
}
