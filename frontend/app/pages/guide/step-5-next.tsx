// Beginner guide, step 5: what could you do?
// The AI's top two suggestions (from the background check), then three ways to continue.

import { useDependencies } from "@/app/dependencies-state";
import { useExperience } from "@/app/experience";
import { Button } from "@/components/base/buttons/button";
import { ClaimCards, type RiskStepProps, topClaims } from "./step-4-risks";

export const NEXT_COPY = {
  intro: "A few ideas to make your portfolio less dependent on the same places and companies.",
  waiting: "The ideas will appear here when the check on the previous step has finished.",
  none: "The AI didn't suggest any specific changes.",
  tryChange: "Try a change",
  tryChangeNote: "Compare your portfolio with a different mix side by side.",
  seeEverything: "See everything",
  seeEverythingNote: "Open the full view with every detail and source.",
  startOver: "Start over",
} as const;

export default function NextStep({ onJumpToStep }: RiskStepProps) {
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
        <Button variant="primary" onClick={() => openExpertPage("#/compare")} title={NEXT_COPY.tryChangeNote}>
          {NEXT_COPY.tryChange}
        </Button>
        <Button variant="secondary" onClick={() => openExpertPage("#/dependencies")} title={NEXT_COPY.seeEverythingNote}>
          {NEXT_COPY.seeEverything}
        </Button>
        <Button variant="ghost" onClick={() => (onJumpToStep ? onJumpToStep(1) : setStep(1))}>
          {NEXT_COPY.startOver}
        </Button>
      </div>
    </div>
  );
}
