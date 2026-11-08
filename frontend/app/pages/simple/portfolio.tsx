import { useEffect, useState } from "react";
import { api } from "@/api/client";
import type { ExamplePortfolio } from "@/api/types";
import { useAnalysis } from "@/app/analysis";
import { useExperience } from "@/app/experience";
import { DraftEditor, normTicker, ServerError } from "@/app/ui/draft-editor";
import { RiArrowRightLine } from "@remixicon/react";
import { Button, ButtonLink } from "@/components/base/buttons/button";
import { Spinner } from "@/components/base/spinner/spinner";

/** Shares-only editor over the same draft and sample-loading path as the existing guide. */
export function SimplePortfolio() {
  const { draft, rows, setRows, analysis, status, stale, error, retry } = useAnalysis();
  const { openExpertPage } = useExperience();
  const [examples, setExamples] = useState<ExamplePortfolio[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    api.examples(controller.signal).then((result) => {
      setExamples(result.examples.filter((example) => example.verified));
      setLoading(false);
    }).catch((cause: unknown) => {
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setFailed(true);
      setLoading(false);
    });
    return () => controller.abort();
  }, []);
  const loadSample = (example = examples[0]) => {
    setRows(example ? example.holdings.map((item) => ({ ticker: item.ticker, allocationPct: Math.round(item.allocation * 1e6) / 1e4 })) : [
      { ticker: "IVV", allocationPct: 40 }, { ticker: "QQQ", allocationPct: 25 },
      { ticker: "XLK", allocationPct: 15 }, { ticker: "EEM", allocationPct: 20 },
    ]);
  };
  const reports = new Map(!stale && analysis ? analysis.etfs.map((etf) => [etf.ticker.toUpperCase(), etf]) : []);
  const unknown = error?.code === "UNKNOWN_TICKER" ? ((error.details as { tickers?: string[] })?.tickers ?? []).map(normTicker) : [];
  const flagged = new Set(rows.filter((row) => unknown.includes(normTicker(row.ticker))).map((row) => row.id));
  const unavailable = !stale ? analysis?.etfs.filter((etf) => etf.status === "unavailable") ?? [] : [];
  const ready = status === "ready" && analysis !== null && !stale;
  const waitingReason = status === "loading" ? "Opening your ETFs…"
    : status === "error" ? "Fix the problem above to continue."
      : rows.length === 0 ? "Use a sample or add an ETF to continue."
        : "Finish your ETFs and shares above to continue.";
  return <div className="flex flex-col gap-5">
    <section className="suite-card flex flex-col gap-3" aria-label="Choose how to start">
      <div><Button disabled={loading} onClick={() => loadSample()}>Use a sample portfolio</Button></div>
      <p className="text-body-2-regular text-text-secondary">Or add your ETFs and shares below.</p>
      {examples.length > 1 && <details className="text-body-2-regular text-text-secondary"><summary className="cursor-pointer">Other samples</summary><div className="mt-2 flex flex-wrap gap-2">{examples.map((example) => <Button key={example.id} variant="ghost" size="small" onClick={() => loadSample(example)}>{example.name}</Button>)}</div></details>}
      {failed && <p className="text-body-2-regular text-text-secondary">Sample presets could not load. The button uses our four-ETF sample.</p>}
    </section>
    <DraftEditor draft={draft} label="Your ETFs" sharesOnly reports={reports} flaggedIds={flagged}
      emptyText={{ shares: "Use a sample above, or add an ETF and the number of shares you hold.", percent: "Use a sample above, or add your ETFs." }}
      status={status === "loading" ? <span className="flex items-center gap-2"><Spinner size="sm" aria-label="Analysing" />Opening ETF baskets…</span> : status === "ready" && analysis && !stale ? <span>Ready — {analysis.concentration.distinct_companies.toLocaleString()} companies found</span> : null}
      messages={<>
        {status === "error" && error && <ServerError error={error} retry={retry} />}
        {unavailable.length > 0 && <p role="status">Holdings are unavailable for {unavailable.map((etf) => etf.ticker).join(", ")}. Results leave out that part of your portfolio.</p>}
      </>}
    />
    {/* FIX-53: a clear next step once the portfolio is ready; the full builder stays a quieter secondary link. */}
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-col gap-1">
        {ready
          ? <ButtonLink href="#/exposures" trailingIcon={RiArrowRightLine}>Next: what you really own</ButtonLink>
          : <Button disabled trailingIcon={RiArrowRightLine}>Next: what you really own</Button>}
        {!ready && <p className="text-caption-1-regular text-text-secondary">{waitingReason}</p>}
      </div>
      <Button variant="ghost" size="small" onClick={() => openExpertPage("#/portfolio")}>See the full Portfolio builder</Button>
    </div>
  </div>;
}
