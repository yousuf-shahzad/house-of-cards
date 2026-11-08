"use client";
// Step 1 (B-GUIDE): Pick your ETFs.
// "Use a sample portfolio" (one click) or "Enter my own" in percent mode only, with "Split evenly".
// Shares mode is hidden. Includes a one-line explainer: "An ETF is a basket of companies".

import { useEffect, useMemo, useState } from "react";
import {
  RiAddLine,
  RiArrowRightUpLine,
  RiCheckLine,
  RiEqualizerLine,
  RiSparklingLine,
} from "@remixicon/react";
import { api } from "@/api/client";
import { MAX_ETFS, type EtfReport, type ExamplePortfolio } from "@/api/types";
import { useAnalysis, type DraftRow, type RowIssue } from "@/app/analysis";
import { AsOfBadge } from "@/app/ui/as-of-badge";
import { evenSplit, normTicker, ServerError } from "@/app/ui/draft-editor";
import { Chip } from "@/components/base/badges/chip";
import { Button } from "@/components/base/buttons/button";
import { CloseButton } from "@/components/base/buttons/close-button";
import { Input } from "@/components/base/input/input";
import { NumberField } from "@/components/base/number-field/number-field";
import { Slider } from "@/components/base/slider/slider";
import { Spinner } from "@/components/base/spinner/spinner";
import { GUIDE_STEP_META, openInFullView } from "../copy";
import type { GuideStepProps } from "../index";

const STEP_META = GUIDE_STEP_META[0];
const tabular = { fontVariantNumeric: "tabular-nums" } as const;

type ShownPercentIssue = Exclude<
  RowIssue,
  "allocation-sum" | "valuation-blocked" | "valuation-error" | "invalid-shares" | "pinned-over-100" | "nothing-to-rescale"
>;

const PERCENT_ISSUE_TEXT: Record<ShownPercentIssue, string> = {
  empty: "Enter a ticker symbol for every ETF.",
  "too-many-etfs": `Use at most ${MAX_ETFS} ETFs.`,
  "invalid-ticker": "Tickers use letters, numbers, dots or dashes, up to 12 characters.",
  "duplicate-ticker": "Each ETF can appear only once.",
  "invalid-allocation": "Give every ETF a percentage between 0 and 100.",
};

function sumGapMessage(totalPct: number): string {
  const gap = Math.abs(100 - totalPct).toFixed(2);
  return totalPct < 100
    ? `Add ${gap}% more across your ETFs so the total reaches 100%.`
    : `Remove ${gap}% so the total comes back to 100%.`;
}

export function StepPick({ onNext }: GuideStepProps) {
  const {
    rows,
    setRows,
    addRow,
    updateRow,
    removeRow,
    mode,
    setMode,
    validation,
    status,
    analysis,
    stale,
    error,
    retry,
  } = useAnalysis();

  const [examples, setExamples] = useState<ExamplePortfolio[]>([]);
  const [loadingExamples, setLoadingExamples] = useState(true);
  const [examplesFailed, setExamplesFailed] = useState(false);

  // Beginner mode always edits in percentages; hide shares mode completely.
  useEffect(() => {
    if (mode !== "percent") {
      setMode("percent");
    }
  }, [mode, setMode]);

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

  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of rows) {
      const key = normTicker(row.ticker);
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return map;
  }, [rows]);

  const isRowFlagged = (row: DraftRow) =>
    (counts.get(normTicker(row.ticker)) ?? 0) > 1 || unknownIds.has(row.id);

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
        { ticker: "XLK", allocationPct: 20 },
        { ticker: "EEM", allocationPct: 15 },
      ]);
    }
  };

  const handleStartOwn = () => {
    if (rows.length === 0) {
      setRows([
        { ticker: "IVV", allocationPct: 50 },
        { ticker: "QQQ", allocationPct: 50 },
      ]);
    }
  };

  const handleSplitEvenly = () => {
    const pcts = evenSplit(rows.length);
    setRows(rows.map((row, idx) => ({ ticker: row.ticker, allocationPct: pcts[idx] })));
  };

  const shownIssues = validation.issues
    .filter(
      (issue): issue is ShownPercentIssue =>
        issue === "empty" ||
        issue === "too-many-etfs" ||
        issue === "invalid-ticker" ||
        issue === "duplicate-ticker" ||
        issue === "invalid-allocation",
    )
    .filter((issue) => issue !== "empty" || rows.length > 0);

  const sumWrong = validation.issues.includes("allocation-sum") && rows.length > 0;
  const totalOk = rows.length > 0 && validation.valid;

  return (
    <div className="flex flex-col gap-5">
      {/* One-line explainer + sample vs own quick actions */}
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

      {/* Percent-only ETF rows editor */}
      <section className="suite-card flex flex-col gap-4" aria-label="Your ETFs">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-headline-medium text-text-primary">Your ETFs (in %)</h2>
          {rows.length > 1 && (
            <Button
              variant="secondary"
              size="small"
              leadingIcon={RiEqualizerLine}
              onClick={handleSplitEvenly}
            >
              Split evenly
            </Button>
          )}
        </div>

        {rows.length === 0 ? (
          <p className="text-body-regular text-text-secondary">
            Click <strong>Use a sample portfolio</strong> above, or click <strong>Add ETF</strong> below to enter your own tickers totaling 100%.
          </p>
        ) : (
          <ul className="flex flex-col gap-4">
            {rows.map((row) => {
              const label = normTicker(row.ticker) || "this ETF";
              const report = reports.get(normTicker(row.ticker));
              const flagged = isRowFlagged(row);
              return (
                <li
                  key={row.id}
                  className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 sm:grid-cols-[8rem_7rem_minmax(0,1fr)_auto]"
                >
                  <Input
                    aria-label="ETF ticker"
                    placeholder="Ticker, e.g. IVV"
                    value={row.ticker}
                    isInvalid={flagged}
                    maxLength={12}
                    fieldClassName="border border-border-button-default"
                    onChange={(ticker) => updateRow(row.id, { ticker: ticker.toUpperCase() })}
                    className="col-start-1"
                  />
                  <CloseButton
                    aria-label={`Remove ${label}`}
                    onClick={() => removeRow(row.id)}
                    className="col-start-2 row-start-1 sm:col-start-4"
                  />
                  <NumberField
                    aria-label={`Allocation for ${label}, percent`}
                    placeholder="%"
                    hideSteppers
                    fieldClassName="border border-border-button-default"
                    minValue={0}
                    maxValue={100}
                    formatOptions={{ maximumFractionDigits: 2 }}
                    value={row.allocationPct ?? Number.NaN}
                    onChange={(pct) => updateRow(row.id, { allocationPct: Number.isNaN(pct) ? null : pct })}
                    className="col-span-2 sm:col-span-1 sm:col-start-2 sm:row-start-1"
                  />
                  <Slider
                    aria-label={`Allocation slider for ${label}`}
                    minValue={0}
                    maxValue={100}
                    step={1}
                    value={row.allocationPct ?? 0}
                    onChange={(pct) => updateRow(row.id, { allocationPct: pct })}
                    className="col-span-2 sm:col-span-1 sm:col-start-3 sm:row-start-1"
                  />
                  {report && (
                    <div className="col-span-2 flex flex-wrap items-center gap-2 sm:col-span-4">
                      <span className="text-body-2-regular text-text-secondary">
                        {report.name ?? report.ticker}
                      </span>
                      {report.status !== "unavailable" && <AsOfBadge date={report.as_of} />}
                      {report.status === "unavailable" && (
                        <Chip variant="caption" color="rose">
                          No data
                        </Chip>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            size="small"
            leadingIcon={RiAddLine}
            disabled={rows.length >= MAX_ETFS}
            onClick={() => addRow()}
          >
            Add ETF
          </Button>
          {rows.length > 1 && (
            <Button
              variant="ghost"
              size="small"
              leadingIcon={RiEqualizerLine}
              onClick={handleSplitEvenly}
            >
              Split evenly
            </Button>
          )}
        </div>

        {/* Totals and validation status */}
        <div className="flex flex-col gap-2 border-t border-separator-border pt-3" aria-live="polite">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="flex items-center gap-2">
              <span className="text-body-medium text-text-primary">Total</span>
              <span className="text-title-3-semibold text-text-primary" style={tabular}>
                {validation.totalPct.toFixed(2)}%
              </span>
              {rows.length > 0 && (
                <Chip variant="caption" color={totalOk ? "lime" : "rose"}>
                  {totalOk ? "100%" : "Must total 100%"}
                </Chip>
              )}
            </span>

            {status === "loading" && (
              <span className="flex items-center gap-2 text-body-regular text-text-secondary">
                <Spinner size="sm" aria-label="Analysing" /> Opening ETF baskets…
              </span>
            )}
            {status === "ready" && analysis && !stale && (
              <span className="flex items-center gap-1.5 text-body-2-medium text-text-primary">
                <RiCheckLine className="size-4 text-foreground-icon-primary" aria-hidden />
                Ready — {analysis.concentration.distinct_companies.toLocaleString()} companies found
                <Button variant="ghost" size="small" onClick={onNext}>
                  See what you own →
                </Button>
              </span>
            )}
          </div>

          {sumWrong && (
            <p className="text-body-regular text-text-error-primary">
              {sumGapMessage(validation.totalPct)}
            </p>
          )}
          {shownIssues.map((issue) => (
            <p key={issue} className="text-body-regular text-text-error-primary">
              {PERCENT_ISSUE_TEXT[issue]}
            </p>
          ))}
          {status === "error" && error && <ServerError error={error} retry={retry} />}
        </div>
      </section>

      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => openInFullView(STEP_META.learnMoreHref)}
          className="inline-flex items-center gap-1 text-caption-1-medium text-text-secondary underline hover:text-text-primary"
        >
          <span>{STEP_META.learnMoreLabel}</span>
          <RiArrowRightUpLine className="size-3.5" aria-hidden />
        </button>
      </div>
    </div>
  );
}
