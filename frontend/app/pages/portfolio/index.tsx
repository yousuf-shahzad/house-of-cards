// F1: portfolio builder. Owner: Yousuf's Claude.
import { useEffect, useMemo, useState } from "react";
import { RiAddLine, RiArrowRightLine, RiEqualizerLine, RiRefreshLine } from "@remixicon/react";
import { api, ApiError } from "@/api/client";
import { MAX_ETFS, type EtfReport, type ExamplePortfolio } from "@/api/types";
import { useAnalysis, type DraftRow, type RowIssue, type Validation } from "@/app/analysis";
import { AsOfBadge } from "@/app/ui/as-of-badge";
import { Button, ButtonLink } from "@/components/base/buttons/button";
import { CloseButton } from "@/components/base/buttons/close-button";
import { Chip } from "@/components/base/badges/chip";
import { Input } from "@/components/base/input/input";
import { NumberField } from "@/components/base/number-field/number-field";
import { Slider } from "@/components/base/slider/slider";
import { Spinner } from "@/components/base/spinner/spinner";

const norm = (ticker: string) => ticker.trim().toUpperCase();

/** Equal percentages to 2 decimal places that total exactly 100. */
export function evenSplit(count: number): number[] {
  if (count <= 0) return [];
  const hundredths = Math.floor(10000 / count);
  const remainder = 10000 - hundredths * count;
  return Array.from({ length: count }, (_, i) => (hundredths + (i < remainder ? 1 : 0)) / 100);
}

const ISSUE_TEXT: Record<Exclude<RowIssue, "allocation-sum">, string> = {
  empty: "Enter a ticker for every ETF.",
  "too-many-etfs": `Use at most ${MAX_ETFS} ETFs.`,
  "invalid-ticker": "Tickers use letters, numbers, dots or dashes, up to 12 characters.",
  "duplicate-ticker": "Each ETF can appear only once.",
  "invalid-allocation": "Give every ETF an allocation.",
};

function sumMessage(totalPct: number): string {
  const gap = Math.abs(100 - totalPct).toFixed(2);
  return totalPct < 100 ? `Add ${gap}% more to reach 100%.` : `Remove ${gap}% to get back to 100%.`;
}

function ServerError({ error, retry }: { error: ApiError; retry: () => void }) {
  const tickers = (error.details as { tickers?: string[] } | undefined)?.tickers;
  const message =
    error.code === "UNKNOWN_TICKER" && tickers?.length
      ? `We couldn't find ${tickers.join(", ")} in any data source. Check the ticker.`
      : error.code === "SOURCES_UNAVAILABLE"
        ? "None of the data sources could be reached, so we have no holdings to show."
        : error.code === "NETWORK_ERROR"
          ? "We couldn't reach the analysis service. Is the backend running?"
          : error.message;
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-body-regular text-text-error-primary">{message}</p>
      {error.code !== "UNKNOWN_TICKER" && (
        <Button variant="secondary" size="small" leadingIcon={RiRefreshLine} onClick={retry}>
          Try again
        </Button>
      )}
    </div>
  );
}

function Status({ validation }: { validation: Validation }) {
  const { rows, status, error, retry, analysis, stale } = useAnalysis();
  const unavailable = !stale ? (analysis?.etfs.filter((etf) => etf.status === "unavailable") ?? []) : [];
  const issues = validation.issues
    .filter((issue): issue is Exclude<RowIssue, "allocation-sum"> => issue !== "allocation-sum")
    .filter((issue) => issue !== "empty" || rows.length > 0);
  const sumWrong = validation.issues.includes("allocation-sum") && rows.length > 0;
  return (
    <div className="flex flex-col gap-2" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-body-medium text-text-primary">Total</span>
          <span className="text-title-3-semibold text-text-primary" style={{ fontVariantNumeric: "tabular-nums" }}>
            {validation.totalPct.toFixed(2)}%
          </span>
          {rows.length > 0 && (
            <Chip variant="caption" color={sumWrong ? "rose" : "lime"}>
              {sumWrong ? "Must total 100%" : "100%"}
            </Chip>
          )}
        </div>
        {status === "loading" && (
          <span className="flex items-center gap-2 text-body-regular text-text-secondary">
            <Spinner size="sm" aria-label="Analysing" /> Analysing your portfolio…
          </span>
        )}
        {status === "ready" && (
          <ButtonLink href="#/exposures" size="small" trailingIcon={RiArrowRightLine}>
            See what you really own
          </ButtonLink>
        )}
      </div>
      {sumWrong && <p className="text-body-regular text-text-error-primary">{sumMessage(validation.totalPct)}</p>}
      {issues.map((issue) => (
        <p key={issue} className="text-body-regular text-text-error-primary">
          {ISSUE_TEXT[issue]}
        </p>
      ))}
      {status === "error" && error && <ServerError error={error} retry={retry} />}
      {unavailable.length > 0 && (
        <p role="status" className="text-body-regular text-text-secondary">
          No holdings data for {unavailable.map((etf) => etf.ticker).join(", ")}. Results leave out that part of your
          portfolio: see Risk &amp; data.
        </p>
      )}
    </div>
  );
}

function Row({ row, report, flagged }: { row: DraftRow; report?: EtfReport; flagged: boolean }) {
  const { updateRow, removeRow } = useAnalysis();
  const value = row.allocationPct ?? 0;
  const label = norm(row.ticker) || "this ETF";
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 sm:grid-cols-[8rem_7rem_minmax(0,1fr)_auto]">
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
        className="col-start-1 sm:col-start-2 sm:row-start-1"
      />
      <Slider
        aria-label={`Allocation slider for ${label}`}
        minValue={0}
        maxValue={100}
        step={1}
        value={value}
        onChange={(pct) => updateRow(row.id, { allocationPct: pct })}
        className="col-span-2 sm:col-span-1 sm:col-start-3 sm:row-start-1"
      />
      {report && (
        <div className="col-span-2 flex flex-wrap items-center gap-2 sm:col-span-4">
          <span className="text-body-2-regular text-text-secondary">{report.name ?? report.ticker}</span>
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
}

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
  const { rows, setRows, addRow, validation, analysis, stale, error } = useAnalysis();
  const { examples, failed } = useExamples();

  const reports = useMemo(() => {
    if (!analysis || stale) return new Map<string, EtfReport>();
    return new Map(analysis.etfs.map((etf) => [etf.ticker.toUpperCase(), etf]));
  }, [analysis, stale]);

  const flagged = useMemo(() => {
    const counts = new Map<string, number>();
    for (const row of rows) counts.set(norm(row.ticker), (counts.get(norm(row.ticker)) ?? 0) + 1);
    const unknown =
      error?.code === "UNKNOWN_TICKER" ? ((error.details as { tickers?: string[] })?.tickers ?? []) : [];
    return new Set(
      rows
        .filter((row) => (counts.get(norm(row.ticker)) ?? 0) > 1 || unknown.map(norm).includes(norm(row.ticker)))
        .map((row) => row.id),
    );
  }, [rows, error]);

  function splitEvenly() {
    const shares = evenSplit(rows.length);
    setRows(rows.map((row, i) => ({ ticker: row.ticker, allocationPct: shares[i] })));
  }

  return (
    <div className="flex flex-col gap-6">
      <section className="suite-card" aria-label="Your ETFs">
        {rows.length === 0 ? (
          <p className="text-body-regular text-text-secondary">
            Add the ETFs you hold, or start from an example. Your allocations need to total 100%.
          </p>
        ) : (
          <ul className="flex flex-col gap-4">
            {rows.map((row) => (
              <Row key={row.id} row={row} report={reports.get(norm(row.ticker))} flagged={flagged.has(row.id)} />
            ))}
          </ul>
        )}
        <div className="flex flex-wrap gap-2">
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
            <Button variant="ghost" size="small" leadingIcon={RiEqualizerLine} onClick={splitEvenly}>
              Split evenly
            </Button>
          )}
        </div>
        <Status validation={validation} />
      </section>
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
