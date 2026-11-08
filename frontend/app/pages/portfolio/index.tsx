// F1 + S-UI: portfolio builder, in percentages or in shares. Owner: Yousuf's Claude.
// The row editor itself is the shared DraftEditor (also used by the Compare page's Scenario).
import { useEffect, useMemo, useState } from "react";
import { RiArrowRightLine } from "@remixicon/react";
import { api } from "@/api/client";
import type { EtfReport, ExamplePortfolio } from "@/api/types";
import { useAnalysis } from "@/app/analysis";
import { DraftEditor, normTicker, ServerError } from "@/app/ui/draft-editor";
import { Button, ButtonLink } from "@/components/base/buttons/button";
import { Spinner } from "@/components/base/spinner/spinner";

// Kept for existing imports: the even split now lives with the shared editor.
export { evenSplit } from "@/app/ui/draft-editor";

function useExamples() {
  const [examples, setExamples] = useState<ExamplePortfolio[]>([]);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    api
      .examples(controller.signal)
      .then((result) => setExamples(result.examples.filter((example) => example.verified)))
      .catch((cause: unknown) => {
        if (!(cause instanceof DOMException && cause.name === "AbortError")) setFailed(true);
      });
    return () => controller.abort();
  }, []);
  return { examples, failed };
}

export default function PortfolioPage() {
  const { draft, rows, setRows, analysis, stale, status, error, retry } = useAnalysis();
  const { examples, failed } = useExamples();

  const reports = useMemo(() => {
    if (!analysis || stale) return new Map<string, EtfReport>();
    return new Map(analysis.etfs.map((etf) => [etf.ticker.toUpperCase(), etf]));
  }, [analysis, stale]);

  const unknownIds = useMemo(() => {
    const unknown =
      error?.code === "UNKNOWN_TICKER" ? ((error.details as { tickers?: string[] })?.tickers ?? []).map(normTicker) : [];
    return new Set(rows.filter((row) => unknown.includes(normTicker(row.ticker))).map((row) => row.id));
  }, [rows, error]);

  const unavailable = !stale ? (analysis?.etfs.filter((etf) => etf.status === "unavailable") ?? []) : [];

  return (
    <div className="flex flex-col gap-6">
      <DraftEditor
        draft={draft}
        label="Your ETFs"
        reports={reports}
        flaggedIds={unknownIds}
        emptyText={{
          percent: "Add the ETFs you hold, or start from an example. Your allocations need to total 100%.",
          shares: "Add the ETFs you hold and how many shares of each. We price them and work out the percentages.",
        }}
        status={
          status === "loading" ? (
            <span className="flex items-center gap-2 text-body-regular text-text-secondary">
              <Spinner size="sm" aria-label="Analysing" /> Analysing your portfolio…
            </span>
          ) : status === "ready" && !stale ? (
            <ButtonLink href="#/exposures" size="small" trailingIcon={RiArrowRightLine}>
              See what you really own
            </ButtonLink>
          ) : null
        }
        messages={
          <>
            {status === "error" && error && <ServerError error={error} retry={retry} />}
            {unavailable.length > 0 && (
              <p role="status" className="text-body-regular text-text-secondary">
                No holdings data for {unavailable.map((etf) => etf.ticker).join(", ")}. Results leave out that part of
                your portfolio: see Risk &amp; data.
              </p>
            )}
          </>
        }
      />
      {(examples.length > 0 || failed) && (
        <section className="suite-card" aria-label="Examples">
          <h2 className="text-headline-medium text-text-primary">Start from an example</h2>
          {failed && (
            <p className="text-body-regular text-text-secondary">
              Examples aren't available right now. You can still enter your own ETFs.
            </p>
          )}
          <div className="flex flex-col gap-3">
            {examples.map((example) => (
              <div key={example.id} className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-body-medium text-text-primary">{example.name}</p>
                  <p className="text-body-regular text-text-secondary">{example.description}</p>
                </div>
                <Button
                  variant="secondary"
                  size="small"
                  aria-label={`Load example: ${example.name}`}
                  onClick={() =>
                    setRows(
                      example.holdings.map((item) => ({
                        ticker: item.ticker,
                        // Rounded so 0.07 * 100 doesn't show as 7.000000000000001.
                        allocationPct: Math.round(item.allocation * 1e6) / 1e4,
                      })),
                    )
                  }
                >
                  Load
                </Button>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
