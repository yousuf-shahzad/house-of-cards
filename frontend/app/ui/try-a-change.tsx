// F6 (v3.1): "Try a change". Edit a copy of the current portfolio; it is compared automatically
// (POST /api/compare, cache-only) and the result is four before -> after rows plus "More details".
// Used by the Compare page (Full view) and the guide's step-5 sub-screen (Simple view).
import { useEffect, useState, type ReactNode } from "react";
import { RiArrowDownLine, RiArrowRightLine, RiArrowUpLine, RiRefreshLine } from "@remixicon/react";
import type { CompareResponse, ConcentrationDelta, ConcentrationName, MetricDelta, MetricFact } from "@/api/types";
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
    out.push({ label: "Company dependencies", before: "", after: "", direction: 0, higherIsBetter: false });
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
            no change
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
            {formatPct(unanalysedWeight, 1)} of it), so {unanalysed.length === 1 ? "its" : "their"} dependencies aren't
            counted.
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
