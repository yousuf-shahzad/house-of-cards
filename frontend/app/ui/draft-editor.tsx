// Editor for one PortfolioDraft: the "Enter as: Shares | %" toggle, the ETF rows, totals and every
// validation and valuation message. Used by the Portfolio page (the Current portfolio) and the
// Compare page (the Scenario), so both follow the same rules. Owner: Yousuf's Claude.
import { createContext, useContext, useEffect, type ReactNode } from "react";
import { RiAddLine, RiEqualizerLine, RiPushpinLine, RiRefreshLine, RiUnpinLine } from "@remixicon/react";
import type { ApiError } from "@/api/client";
import { MAX_ETFS, PRICE_STALE_DAYS, type EtfReport, type ValuationIssue, type ValuationRowResult } from "@/api/types";
import { plainValuationIssue } from "@/app/pages/simple/issues";
import { validShares, type DraftRow, type InputMode, type PortfolioDraft, type RowIssue } from "@/app/portfolio-draft";

export { plainValuationIssue };
import { AsOfBadge } from "@/app/ui/as-of-badge";
import { Button } from "@/components/base/buttons/button";
import { CloseButton } from "@/components/base/buttons/close-button";
import { Chip } from "@/components/base/badges/chip";
import { Input } from "@/components/base/input/input";
import { NumberField } from "@/components/base/number-field/number-field";
import { SegmentedControl, SegmentedControlItem } from "@/components/base/segmented-control/segmented-control";
import { Slider } from "@/components/base/slider/slider";
import { Spinner } from "@/components/base/spinner/spinner";

export const normTicker = (ticker: string) => ticker.trim().toUpperCase();
const tabular = { fontVariantNumeric: "tabular-nums" } as const;

/** Equal percentages to 2 decimal places that total exactly 100. */
export function evenSplit(count: number): number[] {
  if (count <= 0) return [];
  const hundredths = Math.floor(10000 / count);
  const remainder = 10000 - hundredths * count;
  return Array.from({ length: count }, (_, i) => (hundredths + (i < remainder ? 1 : 0)) / 100);
}

export function money(value: number, currency = "USD"): string {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      notation: Math.abs(value) >= 1_000_000_000 ? "compact" : "standard",
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
}
const shareCount = (value: number) =>
  new Intl.NumberFormat("en-US", {
    notation: Math.abs(value) >= 1_000_000_000 ? "compact" : "standard",
    maximumFractionDigits: 6,
  }).format(value);

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
    "invalid-allocation": "Give every ETF fixed at a % a percentage between 0 and 100.",
    "invalid-shares": "Enter how many shares you hold of each ETF (up to 1,000,000,000), or type a % to fix that row.",
    "pinned-over-100": "Fixed percentages add up to more than 100%. Lower a %, or switch a row back to shares.",
    "nothing-to-rescale":
      "Enter shares for the ETFs without a fixed %, or set fixed percentages that total 100%.",
  },
};

/** Shares-only editors (the guided view) have no % inputs or pins, so their messages don't mention them. */
const SHARES_ONLY_TEXT: Partial<Record<ShownIssue, string>> = {
  "invalid-shares": "Enter how many shares you hold of every ETF (up to 1,000,000,000).",
  "nothing-to-rescale": "Enter a share count above 0 for at least one ETF.",
};

function sumMessage(totalPct: number, mode: InputMode): string {
  const gap = Math.abs(100 - totalPct).toFixed(2);
  const what = mode === "shares" ? "fixed percentages" : "allocations";
  return totalPct < 100 ? `Add ${gap}% more to your ${what} to reach 100%.` : `Remove ${gap}% to get back to 100%.`;
}

/** A backend error in plain words, with a retry button unless retrying can't help. */
export function ServerError({ error, retry }: { error: ApiError; retry: () => void }) {
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
  const sharesOnly = useContext(SharesOnlyContext);
  const shown = issues
    .filter((issue) => issue.ticker === null)
    .sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "blocking" ? -1 : 1));
  if (blocked && !shown.some((issue) => issue.severity === "blocking")) {
    return (
      <p className="text-body-regular text-text-error-primary">
        Some ETFs can't be valued yet. Fix the rows marked above{sharesOnly ? "" : ", or type a % to fix their share of the portfolio"}.
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
          {sharesOnly ? (
            plainValuationIssue(issue, { withTicker: true })
          ) : (
            <>
              {issue.ticker ? `${issue.ticker}: ` : ""}
              {issue.message}
            </>
          )}
        </p>
      ))}
    </>
  );
}

const DraftContext = createContext<PortfolioDraft | null>(null);
/** True inside a shares-only editor: no Shares | % switch, % shown as text, no pins. */
const SharesOnlyContext = createContext(false);
/** True inside a read-only editor (Try a change's "Your portfolio (now)"): the same rows as text, no controls. */
const ReadOnlyContext = createContext(false);

/** A read-only stand-in for an input: same height and padding, so read-only and editable rows line up. */
function ReadOnlyCell({ children, label, className = "" }: { children: ReactNode; label?: string; className?: string }) {
  return (
    <span
      aria-label={label}
      // 38px = the inputs' 36px field plus their 1px border top and bottom.
      className={`flex h-[2.375rem] min-w-0 items-center truncate rounded-lg px-2 text-body-regular text-text-primary ${className}`}
      style={tabular}
    >
      {children}
    </span>
  );
}

/** Keeps the remove button's column (and so the row layout) without showing a control. */
function RemoveSlot({ className }: { className: string }) {
  return <span aria-hidden className={`size-8 ${className}`} />;
}

function useDraft(): PortfolioDraft {
  const draft = useContext(DraftContext);
  if (!draft) throw new Error("Draft rows must be rendered inside <DraftEditor>.");
  return draft;
}

/** Totals, pricing state and every draft-level message. `extra` adds the caller's own status (e.g. analysis). */
function DraftStatus({ extra, extraMessages }: { extra?: ReactNode; extraMessages?: ReactNode }) {
  const { rows, mode, validation, valuation, retryValuation } = useDraft();
  const sharesOnly = useContext(SharesOnlyContext);
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
              {rows.some((row) => row.pinned) ? "Value from share counts (USD):" : "Total portfolio value (USD):"} {money(totalValue)}
              {rows.some((row) => row.pinned) && " (excludes rows fixed at a %)"}
            </span>
          )}
        </div>
        {pricing ? (
          <span className="flex items-center gap-2 text-body-regular text-text-secondary">
            <Spinner size="sm" aria-label="Pricing" /> Pricing your shares…
          </span>
        ) : (
          extra
        )}
      </div>
      {sumWrong && (
        <p className="text-body-regular text-text-error-primary">{sumMessage(validation.totalPct, mode)}</p>
      )}
      {issues.map((issue) => (
        <p key={issue} className="text-body-regular text-text-error-primary">
          {(sharesOnly && SHARES_ONLY_TEXT[issue]) || ISSUE_TEXT[mode][issue]}
        </p>
      ))}
      {mode === "shares" && valuation.result && (blocked || valuation.status === "usable") && (
        <ValuationIssues issues={valuation.result.issues} blocked={blocked} />
      )}
      {valuation.status === "error" && valuation.error && (
        <ServerError error={valuation.error} retry={retryValuation} />
      )}
      {extraMessages}
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
  const { updateRow } = useDraft();
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

// Row grids follow the editor's own width (container queries), not the window, so two editors side by side
// in Try a change keep the same columns as one full-width editor on the Portfolio page.
const PERCENT_GRID =
  "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 @md:grid-cols-[minmax(5rem,8rem)_minmax(5rem,7rem)_minmax(0,1fr)_auto]";
const SHARES_GRID =
  "@md:grid-cols-[minmax(5rem,8rem)_minmax(6rem,9rem)_minmax(5rem,8rem)_minmax(0,1fr)_auto]";

function PercentRow({ row, report, flagged }: { row: DraftRow; report?: EtfReport; flagged: boolean }) {
  const { updateRow, removeRow } = useDraft();
  const readOnly = useContext(ReadOnlyContext);
  const label = normTicker(row.ticker) || "this ETF";
  if (readOnly) {
    const pct = row.allocationPct;
    return (
      <li className={PERCENT_GRID}>
        <ReadOnlyCell className="col-start-1 font-medium">{normTicker(row.ticker) || "—"}</ReadOnlyCell>
        <RemoveSlot className="col-start-2 row-start-1 @md:col-start-4" />
        <ReadOnlyCell
          label={`${label} is ${pct === null ? "not set" : `${pct}%`} of your portfolio`}
          className="col-span-2 @md:col-span-1 @md:col-start-2 @md:row-start-1"
        >
          {pct === null ? "—" : `${pct.toFixed(2)}%`}
        </ReadOnlyCell>
        <div aria-hidden className="col-span-2 h-1.5 overflow-hidden rounded-full bg-background-tertiary-default @md:col-span-1 @md:col-start-3 @md:row-start-1">
          <div className="h-full rounded-full bg-text-tertiary" style={{ width: `${Math.min(Math.max(pct ?? 0, 0), 100)}%` }} />
        </div>
        {report && (
          <div className="col-span-2 flex flex-wrap items-center gap-2 @md:col-span-4">
            <ReportLine report={report} />
          </div>
        )}
      </li>
    );
  }
  return (
    <li className={PERCENT_GRID}>
      <TickerField row={row} flagged={flagged} />
      <CloseButton
        aria-label={`Remove ${label}`}
        onClick={() => removeRow(row.id)}
        className="col-start-2 row-start-1 @md:col-start-4"
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
        className="col-span-2 @md:col-span-1 @md:col-start-2 @md:row-start-1"
      />
      <Slider
        aria-label={`Allocation slider for ${label}`}
        minValue={0}
        maxValue={100}
        step={1}
        value={row.allocationPct ?? 0}
        onChange={(pct) => updateRow(row.id, { allocationPct: pct })}
        className="col-span-2 @md:col-span-1 @md:col-start-3 @md:row-start-1"
      />
      {report && (
        <div className="col-span-2 flex flex-wrap items-center gap-2 @md:col-span-4">
          <ReportLine report={report} />
        </div>
      )}
    </li>
  );
}

/** "10 sh × $738.68 = $7,386.80 · close 2026-11-06", plus stale and per-row issues. */
function PriceLine({ row, priced }: { row: DraftRow; priced?: ValuationRowResult }) {
  const sharesOnly = useContext(SharesOnlyContext);
  if (row.pinned) {
    return (
      <span className="text-body-2-regular text-text-secondary">
        {sharesOnly
          ? "Fixed at this % until you enter how many shares you hold."
          : "Fixed at this %. The other ETFs split the remaining % by their share values."}
      </span>
    );
  }
  if (!priced) return null;
  const quote = priced.price;
  const rowIssues = priced.issues.filter((issue) => issue.code !== "stale_price");
  return (
    <>
      {quote && priced.shares !== null && (
        <span className="min-w-0 break-words text-body-2-regular text-text-secondary" style={tabular}>
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
          {sharesOnly ? plainValuationIssue(issue, { withTicker: false }) : issue.message}
        </span>
      ))}
    </>
  );
}

function SharesRow({ row, report, flagged }: { row: DraftRow; report?: EtfReport; flagged: boolean }) {
  const { updateRow, removeRow, effectivePct, priced } = useDraft();
  const sharesOnly = useContext(SharesOnlyContext);
  const readOnly = useContext(ReadOnlyContext);
  const label = normTicker(row.ticker) || "this ETF";
  const pct = effectivePct[row.id];
  // The field shows 2 dp, so give it the 2-dp value: blur then commits exactly what is shown.
  const shownPct = pct === null || pct === undefined ? null : Math.round(pct * 100) / 100;
  if (readOnly) {
    return (
      <li className={`grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 ${SHARES_GRID}`}>
        <ReadOnlyCell className="col-start-1 font-medium">{normTicker(row.ticker) || "—"}</ReadOnlyCell>
        <RemoveSlot className="col-start-2 row-start-1 @md:col-start-5" />
        <div className="col-span-2 grid grid-cols-2 gap-3 @md:col-span-2 @md:col-start-2 @md:row-start-1">
          <ReadOnlyCell label={`Shares of ${label}`}>
            {row.pinned || row.shares === null ? "—" : shareCount(row.shares)}
          </ReadOnlyCell>
          <ReadOnlyCell label={`${label} is ${shownPct === null ? "not priced yet" : `${shownPct}%`} of your portfolio`}>
            {shownPct === null ? "—" : `${shownPct.toFixed(2)}%`}
          </ReadOnlyCell>
        </div>
        {/* Holds the space of the editable row's pin hint or "Use shares" button, so rows stay level. */}
        <div aria-hidden className="col-span-2 flex items-center @md:col-span-1 @md:col-start-4 @md:row-start-1">
          {sharesOnly ? null : row.pinned ? (
            <span className="invisible h-8 w-28" />
          ) : (
            <span className="invisible flex items-center gap-1 text-body-2-regular">
              <RiPushpinLine className="size-4" /> Or type a % to fix this row
            </span>
          )}
        </div>
        <div className="col-span-2 flex flex-wrap items-center gap-2 @md:col-span-5">
          <PriceLine row={row} priced={priced[row.id]} />
          {report && <ReportLine report={report} />}
        </div>
      </li>
    );
  }
  return (
    <li className={`grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 ${SHARES_GRID}`}>
      <TickerField row={row} flagged={flagged} />
      <CloseButton
        aria-label={`Remove ${label}`}
        onClick={() => removeRow(row.id)}
        className="col-start-2 row-start-1 @md:col-start-5"
      />
      <div className="col-span-2 grid grid-cols-2 gap-3 @md:col-span-2 @md:col-start-2 @md:row-start-1">
        <NumberField
          aria-label={`Shares of ${label}`}
          isInvalid={!row.pinned && row.shares !== null && !validShares(row.shares)}
          placeholder="Shares"
          hideSteppers
          fieldClassName="border border-border-button-default"
          minValue={0}
          formatOptions={{ maximumFractionDigits: 6 }}
          value={row.shares ?? Number.NaN}
          // Typing shares hands the row back to the valuation.
          onChange={(shares) => updateRow(row.id, { shares: Number.isNaN(shares) ? null : shares, pinned: false })}
        />
        {sharesOnly ? (
          <span
            className="flex items-center text-body-regular text-text-primary"
            style={tabular}
            aria-label={`${label} is ${shownPct === null ? "not priced yet" : `${shownPct}%`} of your portfolio`}
          >
            {shownPct === null ? "—" : `${shownPct.toFixed(2)}%`}
          </span>
        ) : (
        <NumberField
          aria-label={`Allocation for ${label}, percent${row.pinned ? ", fixed" : ", from shares"}`}
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
        )}
      </div>
      <div className="col-span-2 flex items-center @md:col-span-1 @md:col-start-4 @md:row-start-1">
        {sharesOnly ? null : row.pinned ? (
          <Button
            variant="ghost"
            size="small"
            leadingIcon={RiUnpinLine}
            aria-label={`Use shares for ${label}`}
            onClick={() => updateRow(row.id, { pinned: false })}
          >
            Use shares
          </Button>
        ) : (
          <span className="flex items-center gap-1 text-body-2-regular text-text-tertiary">
            <RiPushpinLine aria-hidden className="size-4" /> Or type a % to fix this row
          </span>
        )}
      </div>
      <div className="col-span-2 flex flex-wrap items-center gap-2 @md:col-span-5">
        <PriceLine row={row} priced={priced[row.id]} />
        {report && <ReportLine report={report} />}
      </div>
    </li>
  );
}

/** Shares-only editors: rows still pinned at a % (a sample whose prices failed, or rows typed as % in
 * the full view) can't be edited as %, so offer to turn them into share counts. */
function PinnedRowsPrompt() {
  const { rows, sharesFill, fillShares } = useDraft();
  const pinned = rows.filter((row) => row.pinned).map((row) => normTicker(row.ticker) || "One ETF");
  if (pinned.length === 0) return null;
  const one = pinned.length === 1;
  const names = pinned.join(", ");
  if (sharesFill === "pricing") {
    return (
      <div role="status" className="flex items-center gap-2 text-body-regular text-text-secondary">
        <Spinner size="sm" aria-label="Pricing" /> Working out share counts…
      </div>
    );
  }
  const failed = sharesFill === "failed";
  return (
    <div role="status" className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-body-regular text-text-secondary">
        {failed
          ? `Prices are unavailable right now, so ${names} ${one ? "uses a fixed percentage" : "use fixed percentages"}. Try again, or enter how many shares you hold.`
          : `${names} ${one ? "is set as a fixed percentage" : "are set as fixed percentages"}. Turn ${one ? "it" : "them"} into shares to edit here.`}
      </p>
      <Button variant="secondary" size="small" leadingIcon={failed ? RiRefreshLine : undefined} onClick={fillShares}>
        {failed ? "Try again" : "Use shares"}
      </Button>
    </div>
  );
}

export function DraftEditor({
  draft,
  label,
  reports,
  flaggedIds,
  emptyText,
  status,
  messages,
  sharesOnly = false,
  readOnly = false,
}: {
  draft: PortfolioDraft;
  /** Accessible name of the editor section, e.g. "Your ETFs" or "Scenario ETFs". */
  label: string;
  /** ETF reports by upper-case ticker, shown under each row (only when they match the draft). */
  reports?: ReadonlyMap<string, EtfReport>;
  /** Row ids to mark invalid (e.g. tickers the backend didn't recognise). Duplicates are always marked. */
  flaggedIds?: ReadonlySet<string>;
  emptyText?: { percent: string; shares: string };
  /** Caller's own status shown at the end of the totals line, e.g. "Analysing…". */
  status?: ReactNode;
  /** Caller's own messages under the draft's messages. */
  messages?: ReactNode;
  /** Shares only (the guided view): hides the Shares | % switch, shows each % as text and drops pins. */
  sharesOnly?: boolean;
  /**
   * Read-only (Try a change's "Your portfolio (now)"): the same rows and totals as text, with no switch,
   * inputs, Add ETF, remove or pins. It never changes the draft.
   */
  readOnly?: boolean;
}) {
  const { rows, mode, setMode, updateRow, addRow, notice, dismissNotice } = draft;
  // A draft left in % mode by the full view switches to shares, keeping every %.
  useEffect(() => {
    if (sharesOnly && !readOnly && mode === "percent") setMode("shares");
  }, [sharesOnly, readOnly, mode, setMode]);
  const counts = new Map<string, number>();
  for (const row of rows) counts.set(normTicker(row.ticker), (counts.get(normTicker(row.ticker)) ?? 0) + 1);
  const isFlagged = (row: DraftRow) => (counts.get(normTicker(row.ticker)) ?? 0) > 1 || (flaggedIds?.has(row.id) ?? false);
  const RowView = mode === "shares" ? SharesRow : PercentRow;
  const splitEvenly = () => {
    const pcts = evenSplit(rows.length);
    rows.forEach((row, i) => updateRow(row.id, { allocationPct: pcts[i] }));
  };
  return (
    <DraftContext.Provider value={draft}>
     <SharesOnlyContext.Provider value={sharesOnly}>
     <ReadOnlyContext.Provider value={readOnly}>
      <section className="suite-card @container" aria-label={label}>
        {!sharesOnly && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-body-medium text-text-primary">{readOnly ? "Entered as" : "Enter as"}</span>
          {/* Read-only shows the same control, disabled, so both cards keep the same height. */}
          <SegmentedControl
            aria-label={readOnly ? "Holdings entered as" : "Enter holdings as"}
            isDisabled={readOnly}
            selectedKeys={new Set([mode])}
            onSelectionChange={(keys) => {
              if (readOnly) return;
              const next = [...keys][0];
              if (next === "percent" || next === "shares") setMode(next);
            }}
          >
            <SegmentedControlItem id="shares">Shares</SegmentedControlItem>
            <SegmentedControlItem id="percent">%</SegmentedControlItem>
          </SegmentedControl>
        </div>
        )}
        {notice && !readOnly && (
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
              ? (emptyText?.shares ??
                "Add the ETFs you hold and how many shares of each. We price them and work out the percentages.")
              : (emptyText?.percent ?? "Add the ETFs you hold. Your allocations need to total 100%.")}
          </p>
        ) : (
          <ul className="flex flex-col gap-4">
            {mode === "shares" && (
              <li
                aria-hidden
                className={`hidden gap-x-3 text-body-2-medium text-text-secondary @md:grid ${SHARES_GRID}`}
              >
                <span>ETF</span>
                <span>Shares held</span>
                <span>% of portfolio</span>
              </li>
            )}
            {rows.map((row) => (
              <RowView
                key={row.id}
                row={row}
                report={reports?.get(normTicker(row.ticker))}
                flagged={isFlagged(row)}
              />
            ))}
          </ul>
        )}
        {!readOnly && (
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
        )}
        {sharesOnly && !readOnly && mode === "shares" && <PinnedRowsPrompt />}
        <DraftStatus extra={status} extraMessages={messages} />
        {mode === "shares" && (
          <p className="text-body-2-regular text-text-tertiary">
            Prices are the latest exchange close (not NAV) from the ETF's data source.
          </p>
        )}
      </section>
     </ReadOnlyContext.Provider>
     </SharesOnlyContext.Provider>
    </DraftContext.Provider>
  );
}
