// FIX-63: Failure simulator on the Compare screen ("Try a change", Full + Simple views).
// "If one industry, country or supplier fails, what happens to my money?"
// Shows before -> after money for Your portfolio and Your new mix, using historical
// 21-trading-day worst-month ETF drops when available, or a simulated 10% fall.

import { useEffect, useMemo, useRef, useState } from "react";
import { RiAlertLine, RiArrowRightLine, RiShieldFlashLine } from "@remixicon/react";
import { api, ApiError } from "@/api/client";
import {
  DEFAULT_SHOCK_DROP,
  type AffectedCompany,
  type AnalysisResponse,
  type DependencyResult,
  type EdgeType,
  type Sector,
  type ShockKind,
  type ShockSpec,
  type StressResponse,
  type StressSide,
} from "@/api/types";
import { useAnalysis } from "@/app/analysis";
import { useDependencies } from "@/app/dependencies-state";
import { useScenario } from "@/app/scenario";
import { ServerError } from "@/app/ui/draft-editor";
import { formatPct } from "@/app/ui/pct";
import { Chip } from "@/components/base/badges/chip";
import {
  SegmentedControl,
  SegmentedControlItem,
} from "@/components/base/segmented-control/segmented-control";
import { Spinner } from "@/components/base/spinner/spinner";

const tabular = { fontVariantNumeric: "tabular-nums" } as const;
const NOTIONAL_DOLLARS = 10_000;
const STRESS_DEBOUNCE_MS = 250;

const SECTOR_LABELS: Record<Sector, string> = {
  information_technology: "Information Technology",
  financials: "Financials",
  health_care: "Health Care",
  consumer_discretionary: "Consumer Discretionary",
  communication_services: "Communication Services",
  industrials: "Industrials",
  consumer_staples: "Consumer Staples",
  energy: "Energy",
  utilities: "Utilities",
  real_estate: "Real Estate",
  materials: "Materials",
  unknown: "Unknown",
};

const SUPPLY_EDGE_TYPES = new Set<EdgeType>([
  "supplier",
  "foundry",
  "contract_manufacturer",
  "key_input",
]);

const REGION_DISPLAY =
  typeof Intl !== "undefined" && typeof Intl.DisplayNames === "function"
    ? new Intl.DisplayNames(["en"], { type: "region" })
    : null;

function countryName(code: string): string {
  const upper = code.trim().toUpperCase();
  if (!upper) return code;
  try {
    return REGION_DISPLAY?.of(upper) ?? upper;
  } catch {
    return upper;
  }
}

export interface SimulatorOption {
  key: string;
  label: string;
  weight: number;
  companyKeys?: string[];
}

/**
 * Extracts top-15 supplier shock options from a finished DependencyResult.
 * Uses verified supplier/foundry/contract_manufacturer/key_input edges;
 * `companyKeys` = dependent portfolio companies + the supplier itself if held.
 */
export function buildSupplierOptions(
  result: DependencyResult | null | undefined,
  exposures: readonly AnalysisResponse["exposures"][number][] = [],
): SimulatorOption[] {
  if (!result || !result.edges.length) return [];

  const weightByCompany = new Map<string, number>();
  for (const comp of result.companies) {
    weightByCompany.set(comp.company_key, comp.exposure);
  }
  for (const exp of exposures) {
    weightByCompany.set(exp.company_key, exp.exposure);
  }

  const groups = new Map<
    string,
    { key: string; label: string; dependentKeys: Set<string>; allKeys: Set<string> }
  >();

  for (const edge of result.edges) {
    if (!SUPPLY_EDGE_TYPES.has(edge.edge_type)) continue;
    if (edge.target_kind && edge.target_kind !== "company") continue;
    const rawKey = (edge.target_key?.trim() || edge.target_name.trim());
    if (!rawKey) continue;
    let group = groups.get(rawKey);
    if (!group) {
      group = {
        key: rawKey,
        label: edge.target_name.trim() || rawKey,
        dependentKeys: new Set<string>(),
        allKeys: new Set<string>(),
      };
      groups.set(rawKey, group);
    }
    if (edge.source_company_key) {
      group.dependentKeys.add(edge.source_company_key);
      group.allKeys.add(edge.source_company_key);
    }
    if (edge.target_key && weightByCompany.has(edge.target_key)) {
      group.allKeys.add(edge.target_key);
    }
  }

  const options: SimulatorOption[] = [];
  for (const group of groups.values()) {
    let depWeight = 0;
    for (const k of group.dependentKeys) {
      depWeight += weightByCompany.get(k) ?? 0;
    }
    if (group.allKeys.size === 0) continue;
    options.push({
      key: group.key,
      label: group.label,
      weight: depWeight,
      companyKeys: [...group.allKeys].sort(),
    });
  }

  return options
    .sort((a, b) => b.weight - a.weight || a.label.localeCompare(b.label))
    .slice(0, 15);
}

function formatDollars(amount: number): string {
  const rounded = Math.round(Math.abs(amount));
  return `$${rounded.toLocaleString("en-US")}`;
}

/** Local fallback when a running backend predates POST /api/stress (404). */
function computeLocalFallbackStress(
  analysis: AnalysisResponse,
  shock: ShockSpec,
  companyKeys: readonly string[] | undefined,
  hasCandidate: boolean,
): StressResponse {
  const drop = shock.drop ?? DEFAULT_SHOCK_DROP;
  const keyUpper = shock.key.trim().toUpperCase();
  const keyLower = shock.key.trim().toLowerCase();
  const keySet = new Set((companyKeys ?? []).map((k) => k.trim()));

  const matched = analysis.exposures.filter((c) => {
    if (shock.kind === "sector") return c.sector.toLowerCase() === keyLower;
    if (shock.kind === "country") return (c.country ?? "").trim().toUpperCase() === keyUpper;
    return keySet.has(c.company_key);
  });

  const sectorEntry =
    shock.kind === "sector"
      ? analysis.sectors.find((s) => s.sector.toLowerCase() === keyLower)
      : undefined;
  const affectedWeight =
    sectorEntry !== undefined
      ? sectorEntry.weight
      : matched.reduce((sum, c) => sum + c.exposure, 0);

  const affected: AffectedCompany[] = matched
    .map((c) => ({
      company_key: c.company_key,
      company_name: c.company_name,
      exposure: c.exposure,
      loss: c.exposure * drop,
    }))
    .sort((a, b) => b.loss - a.loss || a.company_key.localeCompare(b.company_key))
    .slice(0, 10);

  const side: StressSide = {
    affected_weight: affectedWeight,
    loss_fraction: affectedWeight * drop,
    affected_count: matched.length,
    affected,
  };

  return {
    status: "ok",
    shock,
    basis: {
      source: "simulated",
      drop,
      proxy: null,
      window_start: null,
      window_end: null,
      description: `Simulated ${Math.round(drop * 100)}% fall across affected companies.`,
    },
    baseline: side,
    candidate: hasCandidate ? side : null,
    notes: [],
  };
}

export function FailureSimulator() {
  const {
    draft: current,
    analysis,
    status: analysisStatus,
    stale: analysisStale,
    error: analysisError,
  } = useAnalysis();
  const { scenario } = useScenario();
  const { job: depJob, stale: depStale } = useDependencies();

  const baselineReady =
    analysisStatus === "ready" &&
    analysis !== null &&
    !analysisStale &&
    !analysisError &&
    current.inputs !== null;

  const sectorOptions = useMemo<SimulatorOption[]>(() => {
    if (!analysis) return [];
    const fromSectors = analysis.sectors
      .filter((s) => s.sector !== "unknown" && s.weight > 0)
      .map((s) => ({
        key: s.sector,
        label: SECTOR_LABELS[s.sector] ?? s.sector,
        weight: s.weight,
      }))
      .sort((a, b) => b.weight - a.weight || a.label.localeCompare(b.label));
    if (fromSectors.length > 0) return fromSectors;

    const bySector = new Map<Sector, number>();
    for (const c of analysis.exposures) {
      if (c.sector === "unknown" || c.exposure <= 0) continue;
      bySector.set(c.sector, (bySector.get(c.sector) ?? 0) + c.exposure);
    }
    return [...bySector.entries()]
      .map(([sector, weight]) => ({
        key: sector,
        label: SECTOR_LABELS[sector] ?? sector,
        weight,
      }))
      .sort((a, b) => b.weight - a.weight || a.label.localeCompare(b.label));
  }, [analysis]);

  const { countryOptions, unknownCountryWeight } = useMemo(() => {
    if (!analysis) return { countryOptions: [] as SimulatorOption[], unknownCountryWeight: 0 };
    const byCountry = new Map<string, number>();
    let unknownWeight = 0;
    for (const c of analysis.exposures) {
      if (c.exposure <= 0) continue;
      const code = c.country?.trim().toUpperCase() ?? "";
      if (!code) {
        unknownWeight += c.exposure;
      } else {
        byCountry.set(code, (byCountry.get(code) ?? 0) + c.exposure);
      }
    }
    const opts: SimulatorOption[] = [...byCountry.entries()]
      .map(([code, weight]) => ({
        key: code,
        label: countryName(code),
        weight,
      }))
      .sort((a, b) => b.weight - a.weight || a.label.localeCompare(b.label));
    return { countryOptions: opts, unknownCountryWeight: unknownWeight };
  }, [analysis]);

  const depResult = !depStale ? depJob?.result : null;
  const supplierOpts = useMemo<SimulatorOption[]>(
    () => buildSupplierOptions(depResult, analysis?.exposures ?? []),
    [depResult, analysis?.exposures],
  );

  const hasSuppliers = supplierOpts.length > 0;
  const [kind, setKind] = useState<ShockKind>("sector");
  const [selectedSector, setSelectedSector] = useState<string>("");
  const [selectedCountry, setSelectedCountry] = useState<string>("");
  const [selectedSupplier, setSelectedSupplier] = useState<string>("");

  const effectiveKind: ShockKind =
    kind === "supplier" && !hasSuppliers ? "sector" : kind;

  const activeOptions =
    effectiveKind === "sector"
      ? sectorOptions
      : effectiveKind === "country"
        ? countryOptions
        : supplierOpts;

  const rawSelectedKey =
    effectiveKind === "sector"
      ? selectedSector
      : effectiveKind === "country"
        ? selectedCountry
        : selectedSupplier;

  const activeOption =
    activeOptions.find((o) => o.key === rawSelectedKey) ?? activeOptions[0] ?? null;

  const setSelectedKey = (nextKey: string) => {
    if (effectiveKind === "sector") setSelectedSector(nextKey);
    else if (effectiveKind === "country") setSelectedCountry(nextKey);
    else setSelectedSupplier(nextKey);
  };

  const [stressResult, setStressResult] = useState<StressResponse | null>(null);
  const [stressStatus, setStressStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [stressError, setStressError] = useState<ApiError | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  const controllerRef = useRef<AbortController | null>(null);

  const candidateReady = scenario.inputs !== null;
  const requestKey = baselineReady && activeOption
    ? `${current.key}|${candidateReady ? scenario.key : "none"}|${effectiveKind}|${activeOption.key}|${(activeOption.companyKeys ?? []).join(",")}`
    : null;

  useEffect(() => {
    if (!baselineReady || !current.inputs || !activeOption || !analysis) {
      controllerRef.current?.abort();
      setStressStatus("idle");
      setStressError(null);
      return;
    }

    const shock: ShockSpec = {
      kind: effectiveKind,
      key: activeOption.key,
      label: activeOption.label,
    };
    const companyKeys = effectiveKind === "supplier" ? activeOption.companyKeys : undefined;
    const candidateInputs = scenario.inputs;

    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setStressStatus("loading");
    setStressError(null);

    const timer = window.setTimeout(() => {
      api
        .stress(current.inputs!, candidateInputs, shock, companyKeys, controller.signal)
        .then((res) => {
          if (controller.signal.aborted) return;
          setStressResult(res);
          setStressStatus("ready");
        })
        .catch((cause: unknown) => {
          if (controller.signal.aborted) return;
          if (cause instanceof DOMException && cause.name === "AbortError") return;
          if (
            cause instanceof ApiError &&
            cause.status === 404 &&
            (cause.code === "HTTP_ERROR" || cause.code === "NOT_FOUND")
          ) {
            setStressResult(
              computeLocalFallbackStress(
                analysis,
                shock,
                companyKeys,
                Boolean(candidateInputs && candidateInputs.length > 0),
              ),
            );
            setStressStatus("ready");
            return;
          }
          setStressError(
            cause instanceof ApiError
              ? cause
              : new ApiError("UNEXPECTED_ERROR", "Could not run the failure simulation.", 0),
          );
          setStressStatus("error");
        });
    }, STRESS_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [
    baselineReady,
    requestKey,
    retryTick,
    current.inputs,
    scenario.inputs,
    effectiveKind,
    activeOption,
    analysis,
  ]);

  if (!baselineReady || !analysis) {
    return null;
  }

  // Money calculation (CONTRACT.md §11):
  // Shares mode = valuation total (rescaled if pinned rows exist); % mode = notional $10,000.
  const unpinnedValue = current.valuation.result?.total_value ?? 0;
  const pinnedTotal = current.valuation.result?.pinned_total ?? 0;
  const sharesTotal =
    unpinnedValue > 0 && pinnedTotal < 1
      ? unpinnedValue / (1 - pinnedTotal)
      : unpinnedValue;
  const isSharesValue = current.mode === "shares" && sharesTotal > 0;
  const beforeDollars = isSharesValue ? sharesTotal : NOTIONAL_DOLLARS;

  const baseLossDollars = stressResult ? beforeDollars * stressResult.baseline.loss_fraction : 0;
  const baseAfterDollars = Math.max(0, beforeDollars - baseLossDollars);

  const candSide = stressResult?.candidate ?? null;
  const candLossDollars = candSide ? beforeDollars * candSide.loss_fraction : 0;
  const candAfterDollars = Math.max(0, beforeDollars - candLossDollars);
  const savedDollars = Math.round(baseLossDollars) - Math.round(candLossDollars);

  const hasCountryNoteInResponse = Boolean(
    stressResult?.notes.some((n) => /country/i.test(n)),
  );

  return (
    <section
      className="suite-card"
      aria-label="Failure simulator"
      aria-busy={stressStatus === "loading"}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <div className="flex items-center gap-2">
            <RiShieldFlashLine className="size-5 text-text-primary" aria-hidden />
            <h2 className="text-headline-small text-text-primary">
              What if one part fails?
            </h2>
          </div>
          <p className="text-body-2-regular text-text-secondary">
            See what happens to your money if a single industry, country, or supplier drops.
            {!isSharesValue && " Shown per $10,000 invested."}
          </p>
        </div>
        {stressStatus === "loading" && (
          <span className="flex items-center gap-2 text-body-2-regular text-text-secondary">
            <Spinner size="sm" aria-label="Simulating failure" /> Updating…
          </span>
        )}
      </div>

      {/* Tabs: Industry (default), Country, and Supplier (only when dependency scan exists) */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SegmentedControl
          aria-label="Failure type"
          selectedKeys={new Set([effectiveKind])}
          onSelectionChange={(keys) => {
            const first = [...keys][0];
            if (first) setKind(String(first) as ShockKind);
          }}
        >
          <SegmentedControlItem id="sector">Industry</SegmentedControlItem>
          <SegmentedControlItem id="country">Country</SegmentedControlItem>
          {hasSuppliers && (
            <SegmentedControlItem id="supplier">Supplier</SegmentedControlItem>
          )}
        </SegmentedControl>

        {activeOptions.length > 0 && activeOption && (
          <label className="flex items-center gap-2 text-body-2-regular text-text-secondary">
            <span>If</span>
            <select
              aria-label={
                effectiveKind === "sector"
                  ? "Select industry to stress-test"
                  : effectiveKind === "country"
                    ? "Select country to stress-test"
                    : "Select supplier to stress-test"
              }
              value={activeOption.key}
              onChange={(e) => setSelectedKey(e.target.value)}
              className="rounded-xl border border-border-button-default bg-background-primary-default px-3 py-1.5 text-body-2-medium text-text-primary focus-visible:outline-2 focus-visible:outline-border-focus-ring"
            >
              {activeOptions.map((opt) => (
                <option key={opt.key} value={opt.key}>
                  {opt.label} ({formatPct(opt.weight, 1)})
                </option>
              ))}
            </select>
            <span>fails</span>
          </label>
        )}
      </div>

      {activeOptions.length === 0 && (
        <p className="text-body-2-regular text-text-secondary">
          {effectiveKind === "country"
            ? "No country codes were reported for the companies in this portfolio."
            : "No items available to test for this tab."}
        </p>
      )}

      {effectiveKind === "country" &&
        unknownCountryWeight > 0.0005 &&
        !hasCountryNoteInResponse && (
          <p className="text-caption-1-regular text-text-secondary">
            We don&apos;t know the country for {formatPct(unknownCountryWeight, 1)} of your
            portfolio, so it isn&apos;t counted.
          </p>
        )}

      {stressStatus === "error" && stressError && (
        <ServerError
          error={stressError}
          retry={() => setRetryTick((t) => t + 1)}
        />
      )}

      {stressResult && activeOptions.length > 0 && (
        <div
          className={`flex flex-col gap-3 ${stressStatus === "loading" ? "opacity-60" : ""}`}
          style={tabular}
        >
          <ul className="flex flex-col divide-y divide-separator-border rounded-2xl border border-separator-border bg-background-primary-default px-4">
            {/* Row 1: Your portfolio */}
            <li className="flex flex-wrap items-baseline justify-between gap-2 py-3">
              <div className="flex flex-col gap-0.5">
                <span className="text-body-medium text-text-primary">Your portfolio</span>
                <span className="text-caption-1-regular text-text-tertiary">
                  {formatPct(stressResult.baseline.affected_weight, 1)} exposed · loses{" "}
                  {formatPct(stressResult.baseline.loss_fraction, 1)}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-2 text-body-medium">
                <span className="text-text-secondary">{formatDollars(beforeDollars)}</span>
                <RiArrowRightLine className="size-4 text-foreground-icon-secondary" aria-hidden />
                <span className="text-text-primary">{formatDollars(baseAfterDollars)}</span>
                <span className="text-text-secondary">
                  (−{formatDollars(baseLossDollars)})
                </span>
              </div>
            </li>

            {/* Row 2: Your new mix */}
            {candSide ? (
              <li className="flex flex-wrap items-baseline justify-between gap-2 py-3">
                <div className="flex flex-col gap-0.5">
                  <span className="text-body-medium text-text-primary">Your new mix</span>
                  <span className="text-caption-1-regular text-text-tertiary">
                    {formatPct(candSide.affected_weight, 1)} exposed · loses{" "}
                    {formatPct(candSide.loss_fraction, 1)}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-body-medium">
                  <span className="text-text-secondary">{formatDollars(beforeDollars)}</span>
                  <RiArrowRightLine className="size-4 text-foreground-icon-secondary" aria-hidden />
                  <span className="text-text-primary">{formatDollars(candAfterDollars)}</span>
                  <span className="text-text-secondary">
                    (−{formatDollars(candLossDollars)})
                  </span>
                  {savedDollars > 0 ? (
                    <Chip variant="caption" color="lime">
                      loses {formatDollars(savedDollars)} less
                    </Chip>
                  ) : savedDollars < 0 ? (
                    <Chip variant="caption" color="orange">
                      loses {formatDollars(Math.abs(savedDollars))} more
                    </Chip>
                  ) : (
                    <Chip variant="caption" color="neutral">
                      same loss
                    </Chip>
                  )}
                </div>
              </li>
            ) : (
              <li className="py-3 text-body-2-regular text-text-tertiary">
                Finish the changed portfolio above to compare what happens to your new mix.
              </li>
            )}
          </ul>

          {/* Basis line */}
          <div className="flex flex-wrap items-center gap-2 text-caption-1-regular text-text-secondary">
            <Chip
              variant="caption"
              color={stressResult.basis.source === "historical" ? "blue" : "neutral"}
            >
              {stressResult.basis.source === "historical"
                ? `Historical${stressResult.basis.proxy ? ` · ${stressResult.basis.proxy}` : ""}`
                : `Simulated −${formatPct(stressResult.basis.drop, 0)}`}
            </Chip>
            <span>{stressResult.basis.description}</span>
          </div>

          {/* Notes */}
          {stressResult.notes.length > 0 && (
            <div className="flex flex-col gap-1">
              {stressResult.notes.map((note) => (
                <p
                  key={note}
                  className="flex items-start gap-1.5 text-caption-1-regular text-text-secondary"
                >
                  <RiAlertLine
                    className="mt-0.5 size-3.5 shrink-0 text-foreground-icon-secondary"
                    aria-hidden
                  />
                  <span>{note}</span>
                </p>
              ))}
            </div>
          )}

          {/* Affected companies in a details */}
          {(stressResult.baseline.affected.length > 0 ||
            (candSide && candSide.affected.length > 0)) && (
            <details className="rounded-2xl border border-separator-border bg-background-primary-default px-4 py-2.5">
              <summary className="cursor-pointer text-caption-1-medium text-text-primary">
                Affected companies ({stressResult.baseline.affected_count} in your portfolio
                {candSide ? ` · ${candSide.affected_count} in new mix` : ""})
              </summary>
              <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <span className="text-caption-1-semibold text-text-primary">
                    Your portfolio (top {stressResult.baseline.affected.length})
                  </span>
                  {stressResult.baseline.affected.length === 0 ? (
                    <span className="text-caption-1-regular text-text-secondary">
                      No named companies affected.
                    </span>
                  ) : (
                    <ul className="flex flex-col gap-1">
                      {stressResult.baseline.affected.map((comp) => (
                        <li
                          key={comp.company_key}
                          className="flex items-baseline justify-between gap-2 text-caption-1-regular"
                        >
                          <span className="truncate text-text-primary">
                            {comp.company_name} ({formatPct(comp.exposure, 2)})
                          </span>
                          <span className="shrink-0 text-text-secondary">
                            −{formatDollars(beforeDollars * comp.loss)} (
                            −{formatPct(comp.loss, 2)})
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                {candSide && (
                  <div className="flex flex-col gap-1.5">
                    <span className="text-caption-1-semibold text-text-primary">
                      Your new mix (top {candSide.affected.length})
                    </span>
                    {candSide.affected.length === 0 ? (
                      <span className="text-caption-1-regular text-text-secondary">
                        No named companies affected.
                      </span>
                    ) : (
                      <ul className="flex flex-col gap-1">
                        {candSide.affected.map((comp) => (
                          <li
                            key={comp.company_key}
                            className="flex items-baseline justify-between gap-2 text-caption-1-regular"
                          >
                            <span className="truncate text-text-primary">
                              {comp.company_name} ({formatPct(comp.exposure, 2)})
                            </span>
                            <span className="shrink-0 text-text-secondary">
                              −{formatDollars(beforeDollars * comp.loss)} (
                              −{formatPct(comp.loss, 2)})
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
