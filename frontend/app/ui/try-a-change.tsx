// F6 (v3.1): "Try a change". Edit a copy of the current portfolio; it is compared automatically
// (POST /api/compare, cache-only) and the result is four before -> after rows plus "More details".
// Used by the Compare page (Full view) and the guide's step-5 sub-screen (Simple view).
// FIX-17: "Ideas" (POST /api/change-ideas, cache-only, no AI) on top, also shown on guide step 5.
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { RiArrowDownLine, RiArrowRightLine, RiArrowUpLine, RiRefreshLine } from "@remixicon/react";
import { api } from "@/api/client";
import type {
  ChangeIdea,
  ChangeIdeasResponse,
  CompareResponse,
  ConcentrationDelta,
  ConcentrationName,
  MetricDelta,
  MetricFact,
} from "@/api/types";
import { useAnalysis } from "@/app/analysis";
import { metricCitationLabel } from "@/app/pages/dependencies/metrics";
import { useScenario } from "@/app/scenario";
import { DraftEditor, ServerError } from "@/app/ui/draft-editor";
import { formatPct } from "@/app/ui/pct";
import { Chip } from "@/components/base/badges/chip";
import { Button } from "@/components/base/buttons/button";
import { Spinner } from "@/components/base/spinner/spinner";

const tabular = { fontVariantNumeric: "tabular-nums" } as const;
const DELTAS_SHOWN = 6;
const AUTO_COMPARE_MS = 500;

/** A delta's label in plain words, e.g. "Depends on Taiwan Semiconductor Manufacturing Co., Ltd.". */
function deltaLabel(delta: MetricDelta): string {
  const asMetric: MetricFact = {
    metric_id: delta.metric_id,
    label: delta.label,
    value: delta.candidate ?? delta.baseline ?? 0,
    unit: delta.unit,
    subject_key: null,
    supporting_edge_ids: [],
  };
  return metricCitationLabel(asMetric);
}

function formatValue(value: number, unit: MetricDelta["unit"]): string {
  if (unit === "fraction") return formatPct(value, 2);
  if (unit === "count") return `${Math.round(value)}`;
  if (unit === "days") return `${Math.round(value)} days`;
  return value.toFixed(2);
}

function formatChange(delta: number, unit: MetricDelta["unit"]): string {
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "±";
  const size = Math.abs(delta);
  if (unit === "fraction") return `${sign}${(size * 100).toFixed(2)} pts`;
  if (unit === "count") return `${sign}${Math.round(size)}`;
  return `${sign}${size.toFixed(2)}`;
}

/** "12.39% → 8.10% (−4.29 pts)", or "new in the new mix: 6.00%" / "no longer found in the new mix (was 3.10%)". */
function deltaSentence(delta: MetricDelta): string {
  const { baseline, candidate, unit } = delta;
  if (baseline === null && candidate !== null) return `new in the new mix: ${formatValue(candidate, unit)}`;
  if (candidate === null && baseline !== null) return `no longer found in the new mix (was ${formatValue(baseline, unit)})`;
  if (baseline === null || candidate === null) return "no data";
  return `${formatValue(baseline, unit)} → ${formatValue(candidate, unit)} (${formatChange(candidate - baseline, unit)})`;
}

/** Signed change used for sorting into decreases and increases; a new exposure counts as an increase. */
function signedChange(delta: MetricDelta): number {
  if (delta.delta !== null) return delta.delta;
  if (delta.baseline === null && delta.candidate !== null) return delta.candidate;
  if (delta.candidate === null && delta.baseline !== null) return -delta.baseline;
  return 0;
}

function DeltaList({ title, icon, deltas, empty }: { title: string; icon: ReactNode; deltas: MetricDelta[]; empty: string }) {
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? deltas : deltas.slice(0, DELTAS_SHOWN);
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-separator-border bg-background-primary-default p-4">
      <div className="flex items-center gap-2">
        {icon}
        <h3 className="text-body-semibold text-text-primary">
          {title} ({deltas.length})
        </h3>
      </div>
      {deltas.length === 0 ? (
        <p className="text-body-2-regular text-text-secondary">{empty}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {shown.map((delta) => (
            <li key={delta.metric_id} className="flex flex-col gap-0.5">
              <span className="text-body-medium text-text-primary">{deltaLabel(delta)}</span>
              <span className="text-body-2-regular text-text-secondary" style={tabular}>
                {deltaSentence(delta)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {deltas.length > DELTAS_SHOWN && (
        <div>
          <Button variant="ghost" size="small" onClick={() => setShowAll((value) => !value)}>
            {showAll ? "Show only the largest" : `Show all ${deltas.length}`}
          </Button>
        </div>
      )}
    </div>
  );
}

const CONCENTRATION_META: Record<ConcentrationName, { label: string; kind: "fraction" | "number"; higherIsBetter: boolean }> = {
  top5: { label: "Top 5 companies", kind: "fraction", higherIsBetter: false },
  top10: { label: "Top 10 companies", kind: "fraction", higherIsBetter: false },
  top20: { label: "Top 20 companies", kind: "fraction", higherIsBetter: false },
  effective_n: { label: "Effective number of companies", kind: "number", higherIsBetter: true },
  largest_company: { label: "Largest single company", kind: "fraction", higherIsBetter: false },
  top_sector: { label: "Largest industry", kind: "fraction", higherIsBetter: false },
};

function ConcentrationTable({ deltas }: { deltas: ConcentrationDelta[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[22rem] text-start">
        <thead>
          <tr className="text-caption-1-regular text-text-tertiary">
            <th className="py-2 text-start font-normal">Measure</th>
            <th className="py-2 text-end font-normal">Now</th>
            <th className="py-2 text-end font-normal">After</th>
            <th className="py-2 text-end font-normal">Change</th>
          </tr>
        </thead>
        <tbody>
          {deltas.map((row) => {
            const meta = CONCENTRATION_META[row.name] ?? { label: row.name, kind: "number", higherIsBetter: false };
            const show = (value: number) => (meta.kind === "fraction" ? formatPct(value, 2) : value.toFixed(1));
            const change =
              meta.kind === "fraction"
                ? formatChange(row.delta, "fraction")
                : `${row.delta > 0 ? "+" : row.delta < 0 ? "−" : "±"}${Math.abs(row.delta).toFixed(1)}`;
            const better = row.delta === 0 ? null : meta.higherIsBetter ? row.delta > 0 : row.delta < 0;
            return (
              <tr key={row.name} className="border-t border-separator-border text-body-2-regular text-text-primary">
                <td className="py-2">{meta.label}</td>
                <td className="py-2 text-end" style={tabular}>
                  {show(row.baseline)}
                </td>
                <td className="py-2 text-end" style={tabular}>
                  {show(row.candidate)}
                </td>
                <td className="py-2 text-end" style={tabular}>
                  {better === null ? (
                    change
                  ) : (
                    <Chip variant="caption" color={better ? "lime" : "orange"}>
                      {change} {better ? "less concentrated" : "more concentrated"}
                    </Chip>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

type Headline = {
  label: string;
  before: string;
  after: string;
  /** Sign of after - before; 0 = unchanged after rounding. */
  direction: -1 | 0 | 1;
  /** Whether going up is the safer direction (only "behaves like N holdings"). */
  higherIsBetter: boolean;
  /** Replaces "no change" when there is nothing to compare. */
  note?: string;
};

const direction = (change: number, epsilon: number): -1 | 0 | 1 => (Math.abs(change) < epsilon ? 0 : change > 0 ? 1 : -1);

/** The four F6 rows: biggest dependency change, largest industry, top 10, "behaves like N holdings". */
function headlines(result: CompareResponse): Headline[] {
  const out: Headline[] = [];
  // A company the portfolio depends on ("dep."), known on both sides: one-sided values usually mean "not
  // analysed yet" (not zero), and country/facility shares aren't a company dependency.
  const biggest = result.dependency_deltas
    .filter(
      (delta) =>
        delta.unit === "fraction" &&
        delta.metric_id.startsWith("dep.") &&
        delta.delta !== null &&
        Math.abs(delta.delta) >= 0.00005,
    )
    .reduce<MetricDelta | null>((best, delta) => (!best || Math.abs(delta.delta!) > Math.abs(best.delta!) ? delta : best), null);
  if (biggest && biggest.baseline !== null && biggest.candidate !== null) {
    out.push({
      label: deltaLabel(biggest),
      before: formatPct(biggest.baseline, 2),
      after: formatPct(biggest.candidate, 2),
      direction: direction(biggest.delta!, 0.00005),
      higherIsBetter: false,
    });
  } else {
    const known = result.dependency_deltas.some(
      (delta) => delta.unit === "fraction" && delta.metric_id.startsWith("dep.") && delta.delta !== null,
    );
    out.push({
      label: "Company dependencies",
      before: "",
      after: "",
      direction: 0,
      higherIsBetter: false,
      note: known ? undefined : "not checked yet",
    });
  }
  const byName = new Map(result.concentration_deltas.map((row) => [row.name, row]));
  for (const [name, label] of [
    ["top_sector", "Largest industry"],
    ["top10", "Top 10 companies"],
  ] as const) {
    const row = byName.get(name);
    if (row) {
      out.push({
        label,
        before: formatPct(row.baseline, 1),
        after: formatPct(row.candidate, 1),
        direction: direction(row.delta, 0.0005),
        higherIsBetter: false,
      });
    }
  }
  const effective = byName.get("effective_n");
  if (effective) {
    out.push({
      label: "Behaves like",
      before: `${Math.round(effective.baseline)} holdings`,
      after: `${Math.round(effective.candidate)} holdings`,
      direction: direction(Math.round(effective.candidate) - Math.round(effective.baseline), 0.5),
      higherIsBetter: true,
    });
  }
  return out;
}

function HeadlineRow({ row }: { row: Headline }) {
  const better = row.direction === 0 ? null : row.higherIsBetter ? row.direction > 0 : row.direction < 0;
  const Arrow = row.direction > 0 ? RiArrowUpLine : RiArrowDownLine;
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 border-t border-separator-border py-3 first:border-t-0">
      <span className="text-body-medium text-text-primary">{row.label}</span>
      <span className="flex items-center gap-2 text-body-regular text-text-primary" style={tabular}>
        {row.before !== "" && (
          <>
            {row.before} <RiArrowRightLine className="size-4 text-text-tertiary" aria-label="to" /> {row.after}
          </>
        )}
        {better === null ? (
          <Chip variant="caption" color="neutral">
            {row.note ?? "no change"}
          </Chip>
        ) : (
          <Chip variant="caption" color={better ? "lime" : "orange"}>
            <span className="flex items-center gap-1">
              <Arrow className="size-3.5" aria-hidden />
              {row.direction > 0 ? "up" : "down"}
            </span>
          </Chip>
        )}
      </span>
    </li>
  );
}

// ---------- FIX-17: change ideas ----------

const IDEAS_RETRY_MS = 5000;
const AI_POLL_MS = 3000;
const AI_POLL_LIMIT_MS = 90_000;
/** Finished answers per portfolio key, shared by step 5 and Try a change (the backend memoises too). */
const ideasCache = new Map<string, ChangeIdeasResponse>();

type IdeasState = { key: string; status: "loading" | "ready" | "error"; response: ChangeIdeasResponse | null };

function useChangeIdeas(): { ideas: IdeasState | null; retry: () => void } {
  const { draft: current } = useAnalysis();
  const { inputs, key } = current;
  const [state, setState] = useState<IdeasState | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!inputs) return;
    const done = ideasCache.get(key);
    if (done) {
      setState({ key, status: "ready", response: done });
      return;
    }
    const controller = new AbortController();
    const started = Date.now();
    let timer: number | undefined;
    let retried = false;
    let shown = false;
    const load = () => {
      if (!shown) setState({ key, status: "loading", response: null });
      api
        .changeIdeas(inputs, undefined, controller.signal)
        .then((response) => {
          // A cold backend answers "partial" with no ideas while the candidate ETFs load: ask once more.
          if (response.status === "partial" && response.ideas.length === 0 && !retried && !shown) {
            retried = true;
            timer = window.setTimeout(load, IDEAS_RETRY_MS);
            return;
          }
          // The AI proposer runs in the background (about 45 s): show the rules' ideas now and ask again
          // every few seconds, then swap in the checked AI ideas when they're ready.
          const pending = response.ai_status === "pending" && Date.now() - started < AI_POLL_LIMIT_MS;
          if (response.status === "ok" && response.ai_status !== "pending") ideasCache.set(key, response);
          shown = true;
          setState({ key, status: "ready", response: pending ? response : { ...response, ai_status: response.ai_status === "pending" ? "timeout" : response.ai_status } });
          if (pending) timer = window.setTimeout(load, AI_POLL_MS);
        })
        .catch((cause: unknown) => {
          if (cause instanceof DOMException && cause.name === "AbortError") return;
          // A failed poll while the AI was still checking keeps the cards already on screen.
          setState((prev) =>
            shown && prev?.key === key && prev.response
              ? { ...prev, response: { ...prev.response, ai_status: "failed" } }
              : { key, status: "error", response: null },
          );
        });
    };
    load();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [key, inputs, attempt]);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { ideas: inputs && state?.key === key ? state : null, retry };
}

/** Loads an idea into Try a change. An add keeps your shares and buys whole shares of the new ETF worth
 * f / (1 - f) of your portfolio, which gives it the idea's share. A swap sells f of the portfolio's value from
 * `swap_from` and buys the new ETF with it. Falls back to the idea's own percentages when prices aren't usable. */
function useLoadIdea(): (idea: ChangeIdea) => Promise<void> {
  const { draft: current } = useAnalysis();
  const { scenario } = useScenario();
  return useCallback(
    async (idea: ChangeIdea) => {
      const valued = current.mode === "shares" && !current.rows.some((row) => row.pinned) ? current.valuation.result : null;
      if (valued && valued.total_value > 0) {
        try {
          const quote = (await api.valuation([{ ticker: idea.ticker, shares: 1, overridePct: null }])).rows[0]?.price;
          const currency = valued.rows.find((row) => row.price)?.price?.currency;
          if (quote && quote.price > 0 && quote.currency === currency) {
            const swap = idea.action === "swap" && idea.swap_from ? idea.swap_from.toUpperCase() : null;
            const moved = valued.total_value * idea.add_fraction;
            const value = swap ? moved : moved / (1 - idea.add_fraction);
            const added = { id: "", ticker: idea.ticker, allocationPct: null, shares: Math.max(1, Math.round(value / quote.price)), pinned: false };
            const source = swap ? valued.rows.find((row) => row.ticker.toUpperCase() === swap) : null;
            if (!swap) {
              scenario.copyFrom([...current.rows, added], "shares");
              return;
            }
            if (source?.price && source.value !== null && source.value >= moved * 0.99) {
              const left = Math.max(0, Math.round((source.value - moved) / source.price.price));
              const rows = current.rows
                .map((row) => (row.ticker.trim().toUpperCase() === swap ? { ...row, shares: left } : row))
                .filter((row) => row.shares !== 0);
              scenario.copyFrom([...rows, added], "shares");
              return;
            }
          }
        } catch {
          // No price: use the idea's percentages below.
        }
      }
      scenario.setRows(idea.holdings.map((row) => ({ ticker: row.ticker, allocationPct: row.allocation * 100 })));
    },
    [current, scenario],
  );
}

/** "Add RSP: largest industry 51.0% → 42.8%", from the measure the idea addresses (Python's numbers). */
function ideaHeadline(idea: ChangeIdea): string {
  const row = (name: ConcentrationName) => idea.concentration_deltas.find((delta) => delta.name === name);
  const dep = idea.biggest_dependency_delta;
  let what: string | null = null;
  if (idea.addresses === "dependency" && dep && dep.baseline !== null && dep.candidate !== null) {
    const label = deltaLabel(dep).replace(/^Depends on /, "depends on ");
    what = `${label} ${formatPct(dep.baseline, 1)} → ${formatPct(dep.candidate, 1)}`;
  } else if (idea.addresses === "effective_n") {
    const n = row("effective_n");
    if (n) what = `behaves like ${Math.round(n.baseline)} → ${Math.round(n.candidate)} holdings`;
  } else {
    const name = idea.addresses === "top10" ? "top10" : "top_sector";
    const delta = row(name);
    if (delta) {
      const label = name === "top10" ? "top 10 companies" : "largest industry";
      what = `${label} ${formatPct(delta.baseline, 1)} → ${formatPct(delta.candidate, 1)}`;
    }
  }
  const verb = idea.action === "swap" && idea.swap_from ? `Swap ${idea.swap_from} for ${idea.ticker}` : `Add ${idea.ticker}`;
  return what ? `${verb}: ${what}` : verb;
}

/** "AI suggested 5 ideas; 2 passed the check with your numbers", with each rejection's reason under a toggle.
 * The ideas the AI proposed are the kept AI cards plus the rejected proposals. */
function AiCheckSummary({ response }: { response: ChangeIdeasResponse }) {
  const rejected = response.rejected_proposals ?? [];
  const kept = response.ideas.filter((idea) => idea.proposed_by === "ai").length;
  if (response.ai_status !== "ok" || kept + rejected.length === 0) return null;
  const proposed = kept + rejected.length;
  const summary = `AI suggested ${proposed} ${proposed === 1 ? "idea" : "ideas"}; ${kept} passed the check with your numbers.`;
  if (rejected.length === 0) return <p className="text-body-2-regular text-text-secondary">{summary}</p>;
  return (
    <details className="text-body-2-regular text-text-secondary">
      <summary className="cursor-pointer">{summary} Why the others were dropped</summary>
      <ul className="flex flex-col gap-1 pt-2">
        {rejected.map((proposal, index) => (
          <li key={`${proposal.ticker}-${proposal.action}-${index}`}>
            {proposal.action === "swap" ? "Swap to" : "Add"} {proposal.ticker}: {proposal.reason}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** Up to three ETF ideas with "Try this". `onTried` runs after an idea is loaded into Try a change. */
export function ChangeIdeas({ heading = "Ideas to try", onTried }: { heading?: string; onTried?: () => void }) {
  const { ideas, retry } = useChangeIdeas();
  const loadIdea = useLoadIdea();
  const [loading, setLoading] = useState<string | null>(null);
  if (!ideas) return null;
  const list = ideas.response?.ideas ?? [];
  const tryIdea = (idea: ChangeIdea) => {
    setLoading(idea.idea_id);
    void loadIdea(idea).finally(() => {
      setLoading(null);
      onTried?.();
    });
  };
  return (
    <section className="flex flex-col gap-3" aria-label={heading} aria-busy={ideas.status === "loading"}>
      <h2 className="text-headline-small text-text-primary">{heading}</h2>
      {ideas.status === "loading" && (
        <p className="flex items-center gap-2 text-body-2-regular text-text-secondary">
          <Spinner size="sm" aria-label="Looking for ideas" /> Looking for ETFs that would spread your money more…
        </p>
      )}
      {ideas.status === "error" && (
        <p className="text-body-2-regular text-text-secondary">
          Ideas couldn't load right now. You can still try your own change.
        </p>
      )}
      {ideas.status === "ready" && list.length === 0 && ideas.response?.status === "ok" && (
        <p className="text-body-2-regular text-text-secondary">
          None of the ETFs we can check would clearly improve your mix right now.
        </p>
      )}
      {ideas.status === "ready" && list.length === 0 && ideas.response?.status === "partial" && (
        // "partial" with nothing yet means the backend is still loading the candidate ETFs, not "no gain".
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-body-2-regular text-text-secondary">Still checking the ETFs. Try again in a moment.</p>
          <Button variant="ghost" size="small" leadingIcon={RiRefreshLine} onClick={retry}>
            Try again
          </Button>
        </div>
      )}
      {ideas.response && <AiCheckSummary response={ideas.response} />}
      {ideas.response?.ai_status === "pending" && (
        <p className="flex items-center gap-2 text-body-2-regular text-text-secondary">
          <Spinner size="sm" aria-label="AI is checking more ideas" /> AI is checking more ideas…
        </p>
      )}
      {list.length > 0 && (
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {list.map((idea) => (
            <li
              key={idea.idea_id}
              className="flex flex-col gap-2 rounded-2xl border border-separator-border bg-background-primary-default p-4"
            >
              {idea.proposed_by && (
                <div>
                  <Chip variant="caption" color={idea.proposed_by === "ai" ? "lime" : "neutral"}>
                    {idea.proposed_by === "ai" ? "AI idea, checked with your numbers" : "Idea from our rules"}
                  </Chip>
                </div>
              )}
              <span className="text-body-semibold text-text-primary" style={tabular}>
                {ideaHeadline(idea)}
              </span>
              <span className="text-body-2-regular text-text-secondary">{idea.rationale || idea.reason}</span>
              <span className="text-caption-1-regular text-text-tertiary" style={tabular}>
                {idea.etf_name},{" "}
                {idea.action === "swap" && idea.swap_from
                  ? `${formatPct(idea.add_fraction, 0)} of your portfolio moved from ${idea.swap_from}`
                  : `${formatPct(idea.add_fraction, 0)} of the new mix`}
              </span>
              <div className="mt-auto pt-1">
                <Button variant="secondary" size="small" disabled={loading !== null} onClick={() => tryIdea(idea)}>
                  {loading === idea.idea_id ? "Loading…" : "Try this"}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** The editable copy of the portfolio, the four headline rows and "More details". */
export function TryAChange({ editorTitle = "Your new mix" }: { editorTitle?: string }) {
  const { draft: current } = useAnalysis();
  const { scenario, resetToCurrent, compare, compareStatus, result, error, stale } = useScenario();
  const ready = current.inputs !== null && scenario.inputs !== null;

  // Auto-compare once the edits settle. compare() aborts the previous request, so a stale answer never lands;
  // a failed comparison is retried only by the user or the next edit.
  useEffect(() => {
    if (!ready || (result && !stale)) return;
    const timer = window.setTimeout(compare, AUTO_COMPARE_MS);
    return () => window.clearTimeout(timer);
  }, [ready, result, stale, compare]);

  const makeScenarioCurrent = () => {
    current.copyFrom(scenario.rows, scenario.mode);
    window.location.hash = "#/dependencies";
  };

  // Only portfolio shares (fractions) are ranked: a count changing by 3 is not "bigger" than a 7.7-point
  // drop, and the ".companies" counts repeat the share metric they belong to.
  const shares = (result?.dependency_deltas ?? []).filter((delta) => delta.unit === "fraction");
  const decreases = shares.filter((delta) => signedChange(delta) < 0).sort((a, b) => signedChange(a) - signedChange(b));
  const increases = shares.filter((delta) => signedChange(delta) > 0).sort((a, b) => signedChange(b) - signedChange(a));
  const unanalysed = result?.candidate_unanalysed ?? [];
  const unanalysedWeight = unanalysed.reduce((sum, company) => sum + company.exposure, 0);
  const busy = compareStatus === "loading" || (ready && (result === null || stale) && compareStatus !== "error");

  return (
    <div className="flex flex-col gap-6">
      <ChangeIdeas heading="Ideas" />
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-headline-small text-text-primary">{editorTitle}</h2>
          <Button variant="ghost" size="small" leadingIcon={RiRefreshLine} onClick={resetToCurrent}>
            Reset to my portfolio
          </Button>
        </div>
        <DraftEditor
          draft={scenario}
          label="Changed portfolio ETFs"
          emptyText={{
            percent: "Add the ETFs you'd like to try. The allocations need to total 100%.",
            shares: "Add the ETFs you'd like to try and how many shares of each.",
          }}
        />
      </div>

      <section className="suite-card" aria-label="What changes" aria-busy={busy}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-headline-small text-text-primary">What changes</h2>
          {busy && (
            <span className="flex items-center gap-2 text-body-2-regular text-text-secondary">
              <Spinner size="sm" aria-label="Updating" /> Updating…
            </span>
          )}
        </div>
        {!ready && (
          <p className="text-body-2-regular text-text-tertiary">
            {current.inputs === null
              ? "Your portfolio isn't complete yet. Finish it first."
              : "Finish the changed portfolio above and the comparison updates by itself."}
          </p>
        )}
        {compareStatus === "error" && error && error.status === 404 && error.code === "HTTP_ERROR" ? (
          // FastAPI's own 404 (no error body): the running backend predates POST /api/compare.
          <p role="alert" className="text-body-regular text-text-error-primary">
            This backend doesn't have comparisons yet. Update and restart it, then try again.
          </p>
        ) : (
          compareStatus === "error" && error && <ServerError error={error} retry={compare} />
        )}
        {result && (
          <ul className={`flex flex-col ${stale ? "opacity-60" : ""}`} style={tabular}>
            {headlines(result).map((row) => (
              <HeadlineRow key={row.label} row={row} />
            ))}
          </ul>
        )}
        {result && unanalysed.length > 0 && (
          <p className="text-body-2-regular text-text-secondary">
            Not checked yet: {unanalysed.length} {unanalysed.length === 1 ? "company" : "companies"} in the new mix (
            {formatPct(unanalysedWeight, 1)} of it) {unanalysed.length === 1 ? "has" : "have"} no analysed filing, so{" "}
            {unanalysed.length === 1 ? "its" : "their"} dependencies aren't counted.
          </p>
        )}
      </section>

      {result && (
        <details className="rounded-2xl border border-separator-border bg-background-primary-default px-4 py-3">
          <summary className="cursor-pointer text-body-medium text-text-primary">More details</summary>
          <div className="flex flex-col gap-6 pt-4">
            <div className="flex flex-col gap-3">
              <h3 className="text-body-semibold text-text-primary">What changes in your dependencies</h3>
              <p className="text-body-2-regular text-text-secondary" style={tabular}>
                Counts the largest companies in each portfolio: {formatPct(result.baseline_top_n_weight, 1)} of your
                portfolio and {formatPct(result.candidate_top_n_weight, 1)} of the new mix. Each % is the share of the
                portfolio in companies that rely on it. Uses only filings already analysed, so it makes no AI calls.
              </p>
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <DeltaList
                  title="Biggest decreases"
                  icon={<RiArrowDownLine className="size-4 text-text-primary" aria-hidden />}
                  deltas={decreases}
                  empty="Nothing your portfolio depends on goes down."
                />
                <DeltaList
                  title="Biggest increases"
                  icon={<RiArrowUpLine className="size-4 text-text-primary" aria-hidden />}
                  deltas={increases}
                  empty="Nothing your portfolio depends on goes up."
                />
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <h3 className="text-body-semibold text-text-primary">Concentration before and after</h3>
              <ConcentrationTable deltas={result.concentration_deltas} />
            </div>
            {(result.notes.length > 0 || unanalysed.length > 0) && (
              <div className="flex flex-col gap-2">
                <h3 className="text-body-semibold text-text-primary">What this doesn't cover</h3>
                {result.notes.map((note) => (
                  <p key={note} className="text-body-2-regular text-text-secondary">
                    {note}
                  </p>
                ))}
                {unanalysed.length > 0 && (
                  <>
                    <ul className="flex flex-wrap gap-2">
                      {unanalysed.map((company) => (
                        <li key={company.company_key}>
                          <Chip variant="caption" color="neutral">
                            {company.company_name} ({formatPct(company.exposure, 2)})
                          </Chip>
                        </li>
                      ))}
                    </ul>
                    <div>
                      <Button variant="secondary" size="small" trailingIcon={RiArrowRightLine} onClick={makeScenarioCurrent}>
                        Make this my portfolio and find its dependencies
                      </Button>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </details>
      )}
    </div>
  );
}
