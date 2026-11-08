// F1 + S-UI: portfolio builder, in percentages or in shares. Owner: Yousuf's Claude.
import { useEffect, useMemo, useState } from "react";
import {
  RiAddLine,
  RiArrowRightLine,
  RiEqualizerLine,
  RiPushpinLine,
  RiRefreshLine,
  RiUnpinLine,
} from "@remixicon/react";
import { api, ApiError } from "@/api/client";
import {
  MAX_ETFS,
  PRICE_STALE_DAYS,
  type EtfReport,
  type ExamplePortfolio,
  type ValuationIssue,
  type ValuationRowResult,
} from "@/api/types";
import { useAnalysis, type DraftRow, type InputMode, type RowIssue, type Validation } from "@/app/analysis";
import { AsOfBadge } from "@/app/ui/as-of-badge";
import { Button, ButtonLink } from "@/components/base/buttons/button";
import { CloseButton } from "@/components/base/buttons/close-button";
import { Chip } from "@/components/base/badges/chip";
import { Input } from "@/components/base/input/input";
import { NumberField } from "@/components/base/number-field/number-field";
import { SegmentedControl, SegmentedControlItem } from "@/components/base/segmented-control/segmented-control";
import { Slider } from "@/components/base/slider/slider";
import { Spinner } from "@/components/base/spinner/spinner";

const norm = (ticker: string) => ticker.trim().toUpperCase();
const tabular = { fontVariantNumeric: "tabular-nums" } as const;

/** Equal percentages to 2 decimal places that total exactly 100. */
export function evenSplit(count: number): number[] {
  if (count <= 0) return [];
  const hundredths = Math.floor(10000 / count);
  const remainder = 10000 - hundredths * count;
  return Array.from({ length: count }, (_, i) => (hundredths + (i < remainder ? 1 : 0)) / 100);
}

function money(value: number, currency = "USD"): string {
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency, maximumFractionDigits: 2 }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
}
const shareCount = (value: number) => new Intl.NumberFormat("en-US", { maximumFractionDigits: 6 }).format(value);

type ShownIssue = Exclude<RowIssue, "allocation-sum" | "valuation-blocked" | "valuation-error">;
const ISSUE_TEXT: Record<InputMode, Record<ShownIssue, string>> = {
  percent: {
    empty: "Enter a ticker for every ETF.",
    "too-many-etfs": `Use at most ${MAX_ETFS} ETFs.`,
    "invalid-ticker": "Tickers use letters, numbers, dots or dashes, up to 12 characters.",
    "duplicate-ticker": "Each ETF can appear only once.",
    "invalid-allocation": "Give every ETF an allocation.",
    "invalid-shares": "",
    "pinned-over-100": "",
    "nothing-to-rescale": "",
  },
  shares: {
    empty: "Enter a ticker for every ETF.",
    "too-many-etfs": `Use at most ${MAX_ETFS} ETFs.`,
    "invalid-ticker": "Tickers use letters, numbers, dots or dashes, up to 12 characters.",
    "duplicate-ticker": "Each ETF can appear only once.",
    "invalid-allocation": "Give every pinned ETF a percentage between 0 and 100.",
    "invalid-shares": "Enter how many shares you hold of every unpinned ETF, or type a % to pin it.",
    "pinned-over-100": "Pinned ETFs add up to more than 100%. Lower a pinned %, or unpin a row.",
    "nothing-to-rescale":
      "The unpinned ETFs have no value to fill the rest of 100%. Enter some shares, or pin rows to total 100%.",
  },
};

function sumMessage(totalPct: number, mode: InputMode): string {
  const gap = Math.abs(100 - totalPct).toFixed(2);
  const what = mode === "shares" ? "pinned ETFs" : "allocations";
  return totalPct < 100 ? `Add ${gap}% more to your ${what} to reach 100%.` : `Remove ${gap}% to get back to 100%.`;
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

/** Portfolio-level valuation issues (blocking first). Issues naming a ticker already show on their row. */
function ValuationIssues({ issues, blocked }: { issues: ValuationIssue[]; blocked: boolean }) {
  const shown = issues
    .filter((issue) => issue.ticker === null)
    .sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "blocking" ? -1 : 1));
  if (blocked && !shown.some((issue) => issue.severity === "blocking")) {
    return (
      <p className="text-body-regular text-text-error-primary">
        Some ETFs can't be valued yet. Fix the rows marked above, or type a % to pin them.
      </p>
    );
  }
  return (
    <>
      {shown.map((issue, i) => (
        <p
          key={`${issue.code}-${issue.ticker ?? ""}-${i}`}
          className={issue.severity === "blocking" ? "text-body-regular text-text-error-primary" : "text-body-regular text-text-secondary"}
        >
          {issue.ticker ? `${issue.ticker}: ` : ""}
          {issue.message}
        </p>
      ))}
    </>
  );
}

function Status({ validation }: { validation: Validation }) {
  const { rows, mode, status, error, retry, analysis, stale, valuation } = useAnalysis();
  const unavailable = !stale ? (analysis?.etfs.filter((etf) => etf.status === "unavailable") ?? []) : [];
  const issues = validation.issues
    .filter((issue): issue is ShownIssue =>
      issue !== "allocation-sum" && issue !== "valuation-blocked" && issue !== "valuation-error",
    )
    .filter((issue) => issue !== "empty" || rows.length > 0);
  const sumWrong = validation.issues.includes("allocation-sum") && rows.length > 0;
  const blocked = validation.issues.includes("valuation-blocked");
  const totalOk = rows.length > 0 && validation.valid;
  const pricing = valuation.status === "pricing";
  // Without a usable valuation the unpinned rows have no %, so a partial total would mislead.
  const totalKnown = !(mode === "shares" && (pricing || blocked || valuation.status === "error"));
  const totalValue = valuation.result?.total_value;
  return (
    <div className="flex flex-col gap-2" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="flex items-center gap-2">
            <span className="text-body-medium text-text-primary">Total</span>
            <span className="text-title-3-semibold text-text-primary" style={tabular}>
              {totalKnown ? `${validation.totalPct.toFixed(2)}%` : "—"}
            </span>
            {rows.length > 0 && totalKnown && (
              <Chip variant="caption" color={totalOk ? "lime" : "rose"}>
                {totalOk ? "100%" : "Must total 100%"}
              </Chip>
            )}
          </span>
          {mode === "shares" && valuation.status !== "off" && typeof totalValue === "number" && totalValue > 0 && (
            <span className="text-body-regular text-text-secondary" style={tabular}>
              {/* The backend's total_value covers unpinned rows only. */}
              {rows.some((row) => row.pinned) ? "Unpinned shares worth" : "Shares worth"} {money(totalValue)}
            </span>
          )}
        </div>
        {(pricing || status === "loading") && (
          <span className="flex items-center gap-2 text-body-regular text-text-secondary">
            <Spinner size="sm" aria-label={pricing ? "Pricing" : "Analysing"} />
            {pricing ? "Pricing your shares…" : "Analysing your portfolio…"}
          </span>
        )}
        {status === "ready" && !pricing && (
          <ButtonLink href="#/exposures" size="small" trailingIcon={RiArrowRightLine}>
            See what you really own
          </ButtonLink>
        )}
      </div>
      {sumWrong && (
        <p className="text-body-regular text-text-error-primary">{sumMessage(validation.totalPct, mode)}</p>
      )}
      {issues.map((issue) => (
        <p key={issue} className="text-body-regular text-text-error-primary">
          {ISSUE_TEXT[mode][issue]}
        </p>
      ))}
      {mode === "shares" && valuation.result && (blocked || valuation.status === "usable") && (
        <ValuationIssues issues={valuation.result.issues} blocked={blocked} />
      )}
      {valuation.status === "error" && valuation.error && <ServerError error={valuation.error} retry={retry} />}
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

function ReportLine({ report }: { report: EtfReport }) {
  return (
    <>
      <span className="text-body-2-regular text-text-secondary">{report.name ?? report.ticker}</span>
      {report.status !== "unavailable" && <AsOfBadge date={report.as_of} />}
      {report.status === "unavailable" && (
        <Chip variant="caption" color="rose">
          No data
        </Chip>
      )}
    </>
  );
}

function TickerField({ row, flagged }: { row: DraftRow; flagged: boolean }) {
  const { updateRow } = useAnalysis();
  return (
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
  );
}

function PercentRow({ row, report, flagged }: { row: DraftRow; report?: EtfReport; flagged: boolean }) {
  const { updateRow, removeRow } = useAnalysis();
  const label = norm(row.ticker) || "this ETF";
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 sm:grid-cols-[8rem_7rem_minmax(0,1fr)_auto]">
      <TickerField row={row} flagged={flagged} />
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
          <ReportLine report={report} />
        </div>
      )}
    </li>
  );
}

/** "10 sh × $738.68 = $7,386.80 · close 2026-11-06", plus stale and per-row issues. */
function PriceLine({ row, priced }: { row: DraftRow; priced?: ValuationRowResult }) {
  if (row.pinned) {
    return (
      <span className="text-body-2-regular text-text-secondary">
        Pinned: the other ETFs rescale by value around this %.
      </span>
    );
  }
  if (!priced) return null;
  const quote = priced.price;
  const rowIssues = priced.issues.filter((issue) => issue.code !== "stale_price");
  return (
    <>
      {quote && priced.shares !== null && (
        <span className="text-body-2-regular text-text-secondary" style={tabular}>
          {shareCount(priced.shares)} sh × {money(quote.price, quote.currency)}
          {priced.value !== null && <> = {money(priced.value, quote.currency)}</>}
        </span>
      )}
      {quote && (
        <Chip
          variant="caption"
          color={priced.price_stale ? "yellow" : "neutral"}
          title={
            priced.price_stale
              ? `This price is more than ${PRICE_STALE_DAYS} days old. It still counts, but check it.`
              : undefined
          }
        >
          {quote.kind === "close" ? "Close" : "NAV"} {quote.as_of}
          {priced.price_stale && priced.price_age_days !== null ? ` · ${priced.price_age_days} days old` : ""}
        </Chip>
      )}
      {rowIssues.map((issue, i) => (
        <span
          key={`${issue.code}-${i}`}
          className={issue.severity === "blocking" ? "text-body-2-regular text-text-error-primary" : "text-body-2-regular text-text-secondary"}
        >
          {issue.message}
        </span>
      ))}
    </>
  );
}

function SharesRow({ row, report, flagged }: { row: DraftRow; report?: EtfReport; flagged: boolean }) {
  const { updateRow, removeRow, effectivePct, priced } = useAnalysis();
  const label = norm(row.ticker) || "this ETF";
  const pct = effectivePct[row.id];
  // The field shows 2 dp, so give it the 2-dp value: blur then commits exactly what is shown.
  const shownPct = pct === null || pct === undefined ? null : Math.round(pct * 100) / 100;
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 sm:grid-cols-[8rem_9rem_8rem_minmax(0,1fr)_auto]">
      <TickerField row={row} flagged={flagged} />
      <CloseButton
        aria-label={`Remove ${label}`}
        onClick={() => removeRow(row.id)}
        className="col-start-2 row-start-1 sm:col-start-5"
      />
      <div className="col-span-2 grid grid-cols-2 gap-3 sm:col-span-2 sm:col-start-2 sm:row-start-1">
        <NumberField
          aria-label={`Shares of ${label}`}
          placeholder="Shares"
          hideSteppers
          fieldClassName="border border-border-button-default"
          minValue={0}
          formatOptions={{ maximumFractionDigits: 6 }}
          value={row.shares ?? Number.NaN}
          // Typing shares hands the row back to the valuation.
          onChange={(shares) => updateRow(row.id, { shares: Number.isNaN(shares) ? null : shares, pinned: false })}
        />
        <NumberField
          aria-label={`Allocation for ${label}, percent${row.pinned ? ", pinned" : ", from shares"}`}
          placeholder="%"
          hideSteppers
          fieldClassName={row.pinned ? "border border-border-button-active" : "border border-border-button-default"}
          minValue={0}
          maxValue={100}
          formatOptions={{ style: "unit", unit: "percent", maximumFractionDigits: 2 }}
          value={shownPct ?? Number.NaN}
          // Typing a % pins the row at it. Blurring without a change commits the displayed (rounded)
          // value; that is not an edit, so an unpinned row stays unpinned.
          onChange={(next) => {
            if (!row.pinned && next === shownPct) return;
            updateRow(row.id, { allocationPct: Number.isNaN(next) ? null : next, pinned: true });
          }}
        />
      </div>
      <div className="col-span-2 flex items-center sm:col-span-1 sm:col-start-4 sm:row-start-1">
        {row.pinned ? (
          <Button
            variant="ghost"
            size="small"
            leadingIcon={RiUnpinLine}
            aria-label={`Unpin ${label}`}
            onClick={() => updateRow(row.id, { pinned: false })}
          >
            Unpin
          </Button>
        ) : (
          <span className="flex items-center gap-1 text-body-2-regular text-text-tertiary">
            <RiPushpinLine aria-hidden className="size-4" /> Type a % to pin
          </span>
        )}
      </div>
      <div className="col-span-2 flex flex-wrap items-center gap-2 sm:col-span-5">
        <PriceLine row={row} priced={priced[row.id]} />
        {report && <ReportLine report={report} />}
      </div>
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
  const { rows, setRows, addRow, validation, analysis, stale, error, mode, setMode, notice, dismissNotice } =
    useAnalysis();
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

  const RowView = mode === "shares" ? SharesRow : PercentRow;

  return (
    <div className="flex flex-col gap-6">
      <section className="suite-card" aria-label="Your ETFs">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-body-medium text-text-primary">Enter as</span>
          <SegmentedControl
            aria-label="Enter holdings as"
            selectedKeys={new Set([mode])}
            onSelectionChange={(keys) => {
              const next = [...keys][0];
              if (next === "percent" || next === "shares") setMode(next);
            }}
          >
            <SegmentedControlItem id="shares">Shares</SegmentedControlItem>
            <SegmentedControlItem id="percent">%</SegmentedControlItem>
          </SegmentedControl>
        </div>
        {notice && (
          <div role="status" className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-body-regular text-text-secondary">{notice}</p>
            <Button variant="ghost" size="small" onClick={dismissNotice}>
              Dismiss
            </Button>
          </div>
        )}
        {rows.length === 0 ? (
          <p className="text-body-regular text-text-secondary">
            {mode === "shares"
              ? "Add the ETFs you hold and how many shares of each. We price them and work out the percentages."
              : "Add the ETFs you hold, or start from an example. Your allocations need to total 100%."}
          </p>
        ) : (
          <ul className="flex flex-col gap-4">
            {mode === "shares" && (
              <li
                aria-hidden
                className="hidden gap-x-3 text-body-2-medium text-text-secondary sm:grid sm:grid-cols-[8rem_9rem_8rem_minmax(0,1fr)_auto]"
              >
                <span>ETF</span>
                <span>Shares held</span>
                <span>% of portfolio</span>
              </li>
            )}
            {rows.map((row) => (
              <RowView key={row.id} row={row} report={reports.get(norm(row.ticker))} flagged={flagged.has(row.id)} />
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
          {rows.length > 1 && mode === "percent" && (
            <Button variant="ghost" size="small" leadingIcon={RiEqualizerLine} onClick={splitEvenly}>
              Split evenly
            </Button>
          )}
        </div>
        <Status validation={validation} />
        {mode === "shares" && (
          <p className="text-body-2-regular text-text-tertiary">
            Prices are the latest exchange close (not NAV) from the ETF's data source.
          </p>
        )}
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
