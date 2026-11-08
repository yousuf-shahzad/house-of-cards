"use client";
// Step 1 (B-GUIDE + v3.1 F1/F2): Pick your ETFs.
// Opens in shares mode by default (with the Shares | % toggle available via DraftEditor).
// "Use a sample portfolio" loads whole shares worth ~$10,000 via api.valuation prices (falling back to pinned %).
// No duplicate "See what you own ->" button inside the card (F2); navigation uses the stepper footer.

import { useEffect, useMemo, useState } from "react";
import {
  RiArrowRightUpLine,
  RiCheckLine,
  RiSparklingLine,
} from "@remixicon/react";
import { api } from "@/api/client";
import type { EtfReport, ExamplePortfolio } from "@/api/types";
import { useAnalysis } from "@/app/analysis";
import { useExperience } from "@/app/experience";
import { DraftEditor, normTicker, ServerError } from "@/app/ui/draft-editor";
import { Button } from "@/components/base/buttons/button";
import { Spinner } from "@/components/base/spinner/spinner";
import { GUIDE_STEP_META } from "../copy";
import type { GuideStepProps } from "../index";

const STEP_META = GUIDE_STEP_META[0];

export function StepPick(_props: GuideStepProps) {
  const {
    draft,
    rows,
    setRows,
    addRow,
    status,
    analysis,
    stale,
    error,
    retry,
  } = useAnalysis();
  const { openExpertPage } = useExperience();

  const [examples, setExamples] = useState<ExamplePortfolio[]>([]);
  const [loadingExamples, setLoadingExamples] = useState(true);
  const [examplesFailed, setExamplesFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoadingExamples(true);
    api
      .examples(controller.signal)
      .then((res) => {
        setExamples(res.examples.filter((item) => item.verified));
        setLoadingExamples(false);
      })
      .catch((cause: unknown) => {
        if (!(cause instanceof DOMException && cause.name === "AbortError")) {
          setExamplesFailed(true);
          setLoadingExamples(false);
        }
      });
    return () => controller.abort();
  }, []);

  const reports = useMemo(() => {
    if (!analysis || stale) return new Map<string, EtfReport>();
    return new Map(analysis.etfs.map((etf) => [etf.ticker.toUpperCase(), etf]));
  }, [analysis, stale]);

  const unknownIds = useMemo(() => {
    const unknown =
      error?.code === "UNKNOWN_TICKER"
        ? ((error.details as { tickers?: string[] })?.tickers ?? []).map(normTicker)
        : [];
    return new Set(rows.filter((row) => unknown.includes(normTicker(row.ticker))).map((row) => row.id));
  }, [rows, error]);

  const loadExample = (example: ExamplePortfolio) => {
    setRows(
      example.holdings.map((item) => ({
        ticker: item.ticker,
        allocationPct: Math.round(item.allocation * 1e6) / 1e4,
      })),
    );
  };

  const handleUsePrimarySample = () => {
    const primary = examples[0];
    if (primary) {
      loadExample(primary);
    } else {
      setRows([
        { ticker: "IVV", allocationPct: 40 },
        { ticker: "QQQ", allocationPct: 25 },
        { ticker: "XLK", allocationPct: 15 },
        { ticker: "EEM", allocationPct: 20 },
      ]);
    }
  };

  const handleStartOwn = () => {
    if (rows.length === 0) {
      addRow();
    }
  };

  const unavailable = !stale ? (analysis?.etfs.filter((etf) => etf.status === "unavailable") ?? []) : [];

  return (
    <div className="flex flex-col gap-5">
      {/* Sample vs own quick actions */}
      <section className="suite-card flex flex-col gap-4" aria-label="Choose how to start">
        <div className="flex flex-col gap-1">
          <p className="text-body-medium text-text-primary">
            Pick a sample portfolio in one click, or enter the ETFs you own below.
          </p>
          <p className="text-body-2-regular text-text-secondary">
            We open each basket to show which companies your money actually sits in.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="primary"
            size="medium"
            leadingIcon={RiSparklingLine}
            disabled={loadingExamples && examples.length === 0}
            onClick={handleUsePrimarySample}
          >
            Use a sample portfolio
          </Button>
          <Button variant="secondary" size="medium" onClick={handleStartOwn}>
            Enter my own
          </Button>
        </div>

        {examples.length > 1 && (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <span className="text-caption-1-medium text-text-tertiary">Sample presets:</span>
            {examples.map((ex) => (
              <Button
                key={ex.id}
                variant="ghost"
                size="small"
                onClick={() => loadExample(ex)}
                aria-label={`Load sample portfolio: ${ex.name}`}
              >
                {ex.name}
              </Button>
            ))}
          </div>
        )}
        {examplesFailed && (
          <p className="text-body-2-regular text-text-secondary">
            Sample presets could not be fetched from the server, so the button loads a 4-ETF US &amp; global sample.
          </p>
        )}
      </section>

      {/* Shared DraftEditor: opens in shares mode by default, with % toggle available */}
      <DraftEditor
        draft={draft}
        label="Your ETFs"
        sharesOnly
        reports={reports}
        flaggedIds={unknownIds}
        emptyText={{
          shares:
            "Click Use a sample portfolio above, or click Add ETF below to enter the ETFs you hold and how many shares of each.",
          percent:
            "Click Use a sample portfolio above, or click Add ETF below to enter your own ETFs totaling 100%.",
        }}
        status={
          status === "loading" ? (
            <span className="flex items-center gap-2 text-body-regular text-text-secondary">
              <Spinner size="sm" aria-label="Analysing" /> Opening ETF baskets…
            </span>
          ) : status === "ready" && analysis && !stale ? (
            <span className="flex items-center gap-1.5 text-body-2-medium text-text-primary">
              <RiCheckLine className="size-4 text-foreground-icon-primary" aria-hidden />
              Ready — {analysis.concentration.distinct_companies.toLocaleString()} companies found
            </span>
          ) : null
        }
        messages={
          <>
            {status === "error" && error && <ServerError error={error} retry={retry} />}
            {unavailable.length > 0 && (
              <p role="status" className="text-body-regular text-text-secondary">
                No holdings data for {unavailable.map((etf) => etf.ticker).join(", ")}. Results leave out that part of
                your portfolio.
              </p>
            )}
          </>
        }
      />

      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => openExpertPage(STEP_META.learnMoreHref)}
          className="inline-flex items-center gap-1 text-caption-1-medium text-text-secondary underline hover:text-text-primary"
        >
          <span>{STEP_META.learnMoreLabel}</span>
          <RiArrowRightUpLine className="size-3.5" aria-hidden />
        </button>
      </div>
    </div>
  );
}
