// X-UI (v3) + F6 (v3.1) + FIX-69: Compare page. "Try a change" (app/ui/try-a-change.tsx) shows the current portfolio
// (read-only) beside the editable new mix and compares them through POST /api/compare (cache-only, no Gemini).
// Owner: Yousuf's Claude.
import { RiArrowRightLine } from "@remixicon/react";
import { useAnalysis } from "@/app/analysis";
import { TryAChange } from "@/app/ui/try-a-change";
import { ButtonLink } from "@/components/base/buttons/button";

export default function ComparePage() {
  const { rows: currentRows } = useAnalysis();

  if (currentRows.length === 0) {
    return (
      <section className="suite-card" aria-label="Compare needs a portfolio">
        <p className="text-body-regular text-text-primary">Build your portfolio first, then try a change here.</p>
        <div>
          <ButtonLink href="#/portfolio" size="small" trailingIcon={RiArrowRightLine}>
            Go to Portfolio
          </ButtonLink>
        </div>
      </section>
    );
  }

  return <TryAChange />;
}
