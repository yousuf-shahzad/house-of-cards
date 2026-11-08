// X-UI (v3): Compare page. Current portfolio next to an editable Scenario, then the change in
// dependencies and concentration, from POST /api/compare (cache-only, no Gemini). Owner: Yousuf's Claude.
import { useState, type ReactNode } from "react";
import { RiArrowDownLine, RiArrowLeftRightLine, RiArrowRightLine, RiArrowUpLine, RiRefreshLine } from "@remixicon/react";
import type { ConcentrationDelta, ConcentrationName, MetricDelta, MetricFact } from "@/api/types";
import { useAnalysis } from "@/app/analysis";
import { metricCitationLabel } from "@/app/pages/dependencies/metrics";
import { useScenario } from "@/app/scenario";
import { DraftEditor, normTicker, ServerError } from "@/app/ui/draft-editor";
import { formatPct } from "@/app/ui/pct";
import { Chip } from "@/components/base/badges/chip";
import { Button, ButtonLink } from "@/components/base/buttons/button";
import { Spinner } from "@/components/base/spinner/spinner";

const tabular = { fontVariantNumeric: "tabular-nums" } as const;
const DELTAS_SHOWN = 6;

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

/** "12.39% → 8.10% (−4.29 pts)", or "new in the scenario: 6.00%" / "no longer found in the scenario (was 3.10%)". */
function deltaSentence(delta: MetricDelta): string {
  const { baseline, candidate, unit } = delta;
  if (baseline === null && candidate !== null) return `new in the scenario: ${formatValue(candidate, unit)}`;
  if (candidate === null && baseline !== null) return `no longer found in the scenario (was ${formatValue(baseline, unit)})`;
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

function DeltaList({
  title,
  icon,
  deltas,
  empty,
}: {
  title: string;
  icon: ReactNode;
  deltas: MetricDelta[];
  empty: string;
}) {
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
};

function ConcentrationTable({ deltas }: { deltas: ConcentrationDelta[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[22rem] text-start">
        <thead>
          <tr className="text-caption-1-regular text-text-tertiary">
            <th className="py-2 text-start font-normal">Measure</th>
            <th className="py-2 text-end font-normal">Current</th>
            <th className="py-2 text-end font-normal">Scenario</th>
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

function CurrentSummary() {
  const { rows, effectivePct, validation } = useAnalysis();
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
      {!validation.valid && rows.length > 0 && (
        <p className="text-body-2-regular text-text-error-primary">
          Your current portfolio isn't complete yet. Fix it on the Portfolio page first.
        </p>
      )}
    </section>
  );
}

export default function ComparePage() {
  const { draft: current, rows: currentRows } = useAnalysis();
  const { scenario, resetToCurrent, compare, compareStatus, result, error, stale } = useScenario();
  const canCompare = current.inputs !== null && scenario.inputs !== null && compareStatus !== "loading";

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

  // Only portfolio shares (fractions) are ranked: a count changing by 3 is not "bigger" than a 7.7-point
  // drop, and the ".companies" counts repeat the share metric they belong to.
  const shares = (result?.dependency_deltas ?? []).filter((delta) => delta.unit === "fraction");
  const decreases = shares
    .filter((delta) => signedChange(delta) < 0)
    .sort((a, b) => signedChange(a) - signedChange(b));
  const increases = shares
    .filter((delta) => signedChange(delta) > 0)
    .sort((a, b) => signedChange(b) - signedChange(a));

  const makeScenarioCurrent = () => {
    current.copyFrom(scenario.rows, scenario.mode);
    window.location.hash = "#/dependencies";
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <CurrentSummary />
        <div className="flex flex-col gap-2">
          <h2 className="text-headline-small text-text-primary">Scenario</h2>
          <DraftEditor
            draft={scenario}
            label="Scenario ETFs"
            emptyText={{
              percent: "Add the ETFs for your scenario. The allocations need to total 100%.",
              shares: "Add the ETFs for your scenario and how many shares of each.",
            }}
          />
        </div>
      </div>

      <section className="suite-card" aria-label="Run the comparison">
        <div className="flex flex-wrap items-center gap-3">
          <Button leadingIcon={RiArrowLeftRightLine} disabled={!canCompare} onClick={compare}>
            Compare
          </Button>
          <Button variant="ghost" size="small" leadingIcon={RiRefreshLine} onClick={resetToCurrent}>
            Reset scenario to current
          </Button>
          {compareStatus === "loading" && (
            <span className="flex items-center gap-2 text-body-regular text-text-secondary">
              <Spinner size="sm" aria-label="Comparing" /> Comparing…
            </span>
          )}
        </div>
        <p className="text-body-2-regular text-text-secondary">
          Uses only the company filings already analysed, so it's instant and makes no AI calls.
        </p>
        {!canCompare && compareStatus !== "loading" && (
          <p className="text-body-2-regular text-text-tertiary">
            Both portfolios need to be complete (totalling 100%) before you can compare them.
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
      </section>

      {result && (
        <>
          {stale && (
            <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-border-button-default p-4">
              <p className="text-body-regular text-text-secondary">
                You've changed a portfolio since this comparison. Compare again to update it.
              </p>
              <Button variant="secondary" size="small" disabled={!canCompare} onClick={compare}>
                Compare again
              </Button>
            </div>
          )}

          <section className="suite-card" aria-label="Change in dependencies">
            <div className="flex flex-col gap-1">
              <h2 className="text-headline-small text-text-primary">What changes in your dependencies</h2>
              <p className="text-body-2-regular text-text-secondary" style={tabular}>
                Counts the largest companies in each portfolio: {formatPct(result.baseline_top_n_weight, 1)} of the
                current portfolio and {formatPct(result.candidate_top_n_weight, 1)} of the scenario. Each % is the share
                of your portfolio in companies that rely on it.
              </p>
            </div>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <DeltaList
                title="Biggest decreases"
                icon={<RiArrowDownLine className="size-4 text-text-primary" aria-hidden />}
                deltas={decreases}
                empty="Nothing your portfolio depends on goes down in this scenario."
              />
              <DeltaList
                title="Biggest increases"
                icon={<RiArrowUpLine className="size-4 text-text-primary" aria-hidden />}
                deltas={increases}
                empty="Nothing your portfolio depends on goes up in this scenario."
              />
            </div>
          </section>

          <section className="suite-card" aria-label="Change in concentration">
            <h2 className="text-headline-small text-text-primary">Concentration before and after</h2>
            <ConcentrationTable deltas={result.concentration_deltas} />
          </section>

          {(result.status === "partial" || result.notes.length > 0) && (
            <section className="suite-card" aria-label="What this comparison doesn't cover">
              <h2 className="text-headline-small text-text-primary">What this comparison doesn't cover</h2>
              {result.notes.map((note) => (
                <p key={note} className="text-body-regular text-text-secondary">
                  {note}
                </p>
              ))}
              {result.candidate_unanalysed.length > 0 && (
                <>
                  <p className="text-body-regular text-text-secondary">
                    These scenario companies haven't been analysed yet, so their dependencies aren't counted:
                  </p>
                  <ul className="flex flex-wrap gap-2">
                    {result.candidate_unanalysed.map((company) => (
                      <li key={company.company_key}>
                        <Chip variant="caption" color="neutral">
                          {company.company_name} ({formatPct(company.exposure, 2)})
                        </Chip>
                      </li>
                    ))}
                  </ul>
                  <div>
                    <Button variant="secondary" size="small" trailingIcon={RiArrowRightLine} onClick={makeScenarioCurrent}>
                      Make this scenario my portfolio and find its dependencies
                    </Button>
                  </div>
                </>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}
