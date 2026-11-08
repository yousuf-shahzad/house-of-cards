// X-UI (v3) + F6 (v3.1): Compare page. The current portfolio next to "Try a change" (app/ui/try-a-change.tsx),
// which compares automatically through POST /api/compare (cache-only, no Gemini). Owner: Yousuf's Claude.
import { RiArrowRightLine } from "@remixicon/react";
import { useAnalysis } from "@/app/analysis";
import { normTicker, ServerError } from "@/app/ui/draft-editor";
import { TryAChange } from "@/app/ui/try-a-change";
import { ButtonLink } from "@/components/base/buttons/button";
import { Spinner } from "@/components/base/spinner/spinner";

const tabular = { fontVariantNumeric: "tabular-nums" } as const;

function CurrentSummary() {
  const { rows, effectivePct, status, stale, error, retry, valuation } = useAnalysis();
  const currentError = error ?? valuation.error;
  return (
    <section className="suite-card" aria-label="Current portfolio">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-headline-small text-text-primary">Current</h2>
        <ButtonLink href="#/portfolio" variant="ghost" size="small">
          Edit on Portfolio
        </ButtonLink>
      </div>
      {rows.length === 0 ? (
        <p className="text-body-regular text-text-secondary">No portfolio yet.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((row) => {
            const pct = effectivePct[row.id];
            return (
              <li key={row.id} className="flex items-center justify-between gap-3 text-body-regular text-text-primary">
                <span>{normTicker(row.ticker) || "—"}</span>
                <span style={tabular}>{pct === null || pct === undefined ? "—" : `${pct.toFixed(2)}%`}</span>
              </li>
            );
          })}
        </ul>
      )}
      {currentError ? (
        <ServerError error={currentError} retry={retry} />
      ) : status === "loading" ? (
        <div role="status" className="flex items-center gap-2 text-body-2-regular text-text-secondary">
          <Spinner size="sm" aria-label="Checking current portfolio" /> Checking your current portfolio…
        </div>
      ) : (status !== "ready" || stale) && rows.length > 0 ? (
        <p role="status" className="text-body-2-regular text-text-secondary">
          Your current portfolio isn't ready to compare. Finish it on the Portfolio page first.
        </p>
      ) : null}
    </section>
  );
}

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

  return (
    <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
      <CurrentSummary />
      <TryAChange />
    </div>
  );
}
