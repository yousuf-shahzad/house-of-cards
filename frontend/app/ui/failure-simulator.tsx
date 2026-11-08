// FIX-63: Failure simulator on the Compare screen ("Try a change", Full + Simple views).
// "If one industry, country or supplier fails, what happens to my money?"
// The maths is Python's (POST /api/stress); this file only turns fractions into money.

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { RiAlertLine, RiArrowRightLine, RiShieldFlashLine } from "@remixicon/react";
import { api, ApiError } from "@/api/client";
import type { AffectedCompany, ShockKind, ShockSpec, StressResponse, StressSide } from "@/api/types";
import { useAnalysis } from "@/app/analysis";
import { useDependencies } from "@/app/dependencies-state";
import { useScenario } from "@/app/scenario";
import { ServerError } from "@/app/ui/draft-editor";
import {
  countryOptions,
  formatDollars,
  lossDifference,
  moneyRow,
  NOTIONAL_DOLLARS,
  parseShockHash,
  portfolioValue,
  sectorOptions,
  tidyNotes,
  type MoneyRow,
  type SimulatorOption,
} from "@/app/ui/failure-model";
import { supplierOptions } from "@/app/ui/failure-suppliers";
import { formatPct } from "@/app/ui/pct";
import { Chip } from "@/components/base/badges/chip";
import { SegmentedControl, SegmentedControlItem } from "@/components/base/segmented-control/segmented-control";
import { Spinner } from "@/components/base/spinner/spinner";

const tabular = { fontVariantNumeric: "tabular-nums" } as const;
const STRESS_DEBOUNCE_MS = 250;

const isMissingRoute = (error: ApiError) =>
  error.status === 404 && (error.code === "HTTP_ERROR" || error.code === "NOT_FOUND");

export function FailureSimulator() {
  const { draft: current, analysis, status: analysisStatus, stale: analysisStale, error: analysisError } = useAnalysis();
  const { scenario } = useScenario();
  const { job: depJob, stale: depStale } = useDependencies();

  const baselineReady =
    analysisStatus === "ready" && analysis !== null && !analysisStale && !analysisError && current.inputs !== null;

  const sectors = useMemo(() => sectorOptions(analysis), [analysis]);
  const countries = useMemo(() => countryOptions(analysis), [analysis]);
  const depResult = depStale ? null : depJob?.result;
  const suppliers = useMemo<SimulatorOption[]>(() => supplierOptions(depResult), [depResult]);

  const hasSuppliers = suppliers.length > 0;
  const [kind, setKind] = useState<ShockKind>("sector");
  const [picked, setPicked] = useState<Record<ShockKind, string>>({ sector: "", country: "", supplier: "" });

  // Links such as #/compare?shock=sector:energy (Risk, Dependencies) preselect the tab and option.
  // A supplier link waits on the Industry tab until the dependency scan supplies the options.
  const [hashShock, setHashShock] = useState(() => parseShockHash(window.location.hash));
  useEffect(() => {
    const onHashChange = () => setHashShock(parseShockHash(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  useEffect(() => {
    if (!hashShock) return;
    setKind(hashShock.kind);
    setPicked((prev) => ({ ...prev, [hashShock.kind]: hashShock.key }));
  }, [hashShock]);
  const sectionRef = useRef<HTMLElement | null>(null);
  const scrolledFor = useRef<typeof hashShock>(null);

  const effectiveKind: ShockKind = kind === "supplier" && !hasSuppliers ? "sector" : kind;
  const options = effectiveKind === "sector" ? sectors : effectiveKind === "country" ? countries.options : suppliers;
  const option = options.find((o) => o.key === picked[effectiveKind]) ?? options[0] ?? null;

  const [result, setResult] = useState<StressResponse | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [error, setError] = useState<ApiError | null>(null);
  const [retryTick, setRetryTick] = useState(0);
  const controllerRef = useRef<AbortController | null>(null);

  const baselineInputs = current.inputs;
  const candidateInputs = scenario.inputs;
  const requestKey =
    baselineReady && option
      ? JSON.stringify([current.key, candidateInputs ? scenario.key : null, effectiveKind, option.key, option.companyKeys ?? []])
      : null;

  useEffect(() => {
    if (!requestKey || !baselineInputs || !option) {
      controllerRef.current?.abort();
      setStatus("idle");
      setError(null);
      return;
    }
    const shock: ShockSpec = { kind: effectiveKind, key: option.key, label: option.label };
    const companyKeys = effectiveKind === "supplier" ? option.companyKeys : undefined;

    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setStatus("loading");
    setError(null);

    const timer = window.setTimeout(() => {
      api
        .stress(baselineInputs, candidateInputs, shock, companyKeys, controller.signal)
        .then((res) => {
          if (controller.signal.aborted) return;
          setResult(res);
          setStatus("ready");
        })
        .catch((cause: unknown) => {
          if (controller.signal.aborted) return;
          if (cause instanceof DOMException && cause.name === "AbortError") return;
          // Never leave another shock's numbers on screen under an error.
          setResult(null);
          setError(
            cause instanceof ApiError ? cause : new ApiError("UNEXPECTED_ERROR", "Could not run the failure simulation.", 0),
          );
          setStatus("error");
        });
    }, STRESS_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
    // requestKey captures every input that changes the request.
  }, [requestKey, retryTick]);

  // Bring the simulator into view once per link. The workspace scrolls to the top on every hash change and
  // the cards above it are still loading, so wait for the first result, then re-check while the layout settles.
  // Any scroll, tap or key from the user ends it.
  const scrollTimers = useRef<number[]>([]);
  const stopScrolling = useRef<() => void>(() => {});
  useEffect(() => {
    if (!hashShock || status !== "ready" || scrolledFor.current === hashShock) return;
    scrolledFor.current = hashShock;
    stopScrolling.current();
    const events = ["wheel", "touchstart", "keydown", "pointerdown"] as const;
    const stop = () => {
      scrollTimers.current.forEach((t) => window.clearTimeout(t));
      scrollTimers.current = [];
      events.forEach((name) => window.removeEventListener(name, stop));
    };
    stopScrolling.current = stop;
    events.forEach((name) => window.addEventListener(name, stop, { passive: true }));
    const bringIntoView = () => {
      const top = sectionRef.current?.getBoundingClientRect().top;
      if (top !== undefined && Math.abs(top) > 24) sectionRef.current?.scrollIntoView({ block: "start" });
    };
    scrollTimers.current = [0, 300, 800, 1600].map((ms) => window.setTimeout(bringIntoView, ms));
    scrollTimers.current.push(window.setTimeout(stop, 1700));
  }, [hashShock, status]);
  useEffect(() => () => stopScrolling.current(), []);

  if (!baselineReady || !analysis) return null;

  // Money (CONTRACT.md §11): the portfolio's value in shares mode, else the notional $10,000.
  // The new mix starts from the same amount, so "loses $X less" compares equal-sized pots even when an idea adds shares.
  const baseValue = portfolioValue(current.mode, current.valuation.result);
  const baseBefore = baseValue ?? NOTIONAL_DOLLARS;
  const candBefore = baseBefore;

  const baseRow = result ? moneyRow(baseBefore, result.baseline.loss_fraction) : null;
  const candSide = result?.candidate ?? null;
  const candRow = candSide ? moneyRow(candBefore, candSide.loss_fraction) : null;
  const diff = baseRow && candRow ? lossDifference(baseRow.loss, candRow.loss) : null;

  const notes = tidyNotes(result?.notes ?? []);
  const countryNoteShown = notes.shown.some((n) => /country/i.test(n));

  return (
    <section
      ref={sectionRef}
      id="failure-simulator"
      className="suite-card scroll-mt-4"
      aria-label="Failure simulator"
      aria-busy={status === "loading"}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <div className="flex items-center gap-2">
            <RiShieldFlashLine className="size-5 text-text-primary" aria-hidden />
            <h2 className="text-headline-small text-text-primary">What if one part fails?</h2>
          </div>
          <p className="text-body-2-regular text-text-secondary">
            See what happens to your money if a single industry, country, or supplier drops.
            {baseValue === null && " Shown per $10,000 invested."}
          </p>
        </div>
        {status === "loading" && (
          <span className="flex items-center gap-2 text-body-2-regular text-text-secondary">
            <Spinner size="sm" aria-label="Simulating failure" /> Updating…
          </span>
        )}
      </div>

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
          {hasSuppliers && <SegmentedControlItem id="supplier">Supplier</SegmentedControlItem>}
        </SegmentedControl>

        {option && (
          <label className="flex min-w-0 items-center gap-2 text-body-2-regular text-text-secondary">
            <span>If</span>
            <select
              aria-label={`Choose the ${effectiveKind === "sector" ? "industry" : effectiveKind} that fails`}
              value={option.key}
              onChange={(e) => {
                const next = e.target.value;
                setPicked((prev) => ({ ...prev, [effectiveKind]: next }));
              }}
              className="min-w-0 max-w-64 rounded-xl border border-border-button-default bg-background-primary-default px-3 py-1.5 text-body-2-medium text-text-primary focus-visible:outline-2 focus-visible:outline-border-focus-ring"
            >
              {options.map((opt) => (
                <option key={opt.key} value={opt.key}>
                  {opt.label} ({formatPct(opt.weight, 1)})
                </option>
              ))}
            </select>
            <span>fails</span>
          </label>
        )}
      </div>

      {!option && (
        <p className="text-body-2-regular text-text-secondary">
          {effectiveKind === "country"
            ? "No country is known for the companies in this portfolio."
            : "Nothing to test here for this portfolio."}
        </p>
      )}

      {effectiveKind === "country" && countries.unknownWeight > 0.0005 && !countryNoteShown && (
        <p className="text-caption-1-regular text-text-secondary">
          We don&apos;t know the country for {formatPct(countries.unknownWeight, 1)} of your portfolio, so it isn&apos;t
          counted.
        </p>
      )}

      {status === "error" &&
        error &&
        (isMissingRoute(error) ? (
          <p role="alert" className="text-body-regular text-text-error-primary">
            This backend doesn&apos;t have the failure simulator yet. Update and restart it, then try again.
          </p>
        ) : (
          <ServerError error={error} retry={() => setRetryTick((t) => t + 1)} />
        ))}

      {result && option && baseRow && (
        <div className={`flex flex-col gap-3 ${status === "loading" ? "opacity-60" : ""}`} style={tabular}>
          <ul className="flex flex-col divide-y divide-separator-border rounded-2xl border border-separator-border bg-background-primary-default px-4">
            <SideRow label="Your portfolio" side={result.baseline} money={baseRow} />
            {candSide && candRow ? (
              <SideRow
                label="Your new mix"
                hint={`Same ${formatDollars(candBefore)} in your new mix`}
                side={candSide}
                money={candRow}
                badge={
                  diff && (
                    <Chip
                      variant="caption"
                      color={diff.tone === "better" ? "lime" : diff.tone === "worse" ? "orange" : "neutral"}
                    >
                      {diff.text}
                    </Chip>
                  )
                }
              />
            ) : (
              <li className="py-3 text-body-2-regular text-text-tertiary">
                Finish the changed portfolio above to see what happens to your new mix.
              </li>
            )}
          </ul>

          <div className="flex flex-wrap items-center gap-2 text-caption-1-regular text-text-secondary">
            <Chip variant="caption" color={result.basis.source === "historical" ? "blue" : "neutral"}>
              {result.basis.source === "historical"
                ? `Historical${result.basis.proxy ? ` · ${result.basis.proxy}` : ""}`
                : `Simulated −${formatPct(result.basis.drop, 0)}`}
            </Chip>
            <span>{result.basis.description}</span>
          </div>

          {notes.shown.map((note) => (
            <p key={note} className="flex items-start gap-1.5 text-caption-1-regular text-text-secondary">
              <RiAlertLine className="mt-0.5 size-3.5 shrink-0 text-foreground-icon-secondary" aria-hidden />
              <span>{note}</span>
            </p>
          ))}
          {notes.folded.length > 0 && (
            <details className="text-caption-1-regular text-text-secondary">
              <summary className="cursor-pointer text-caption-1-medium text-text-primary">
                Why the loss may be understated
              </summary>
              <ul className="mt-1.5 flex list-disc flex-col gap-1 pl-5">
                {notes.folded.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </details>
          )}

          {(result.baseline.affected.length > 0 || (candSide?.affected.length ?? 0) > 0) && (
            <details className="rounded-2xl border border-separator-border bg-background-primary-default px-4 py-2.5">
              <summary className="cursor-pointer text-caption-1-medium text-text-primary">
                Affected companies ({result.baseline.affected_count} in your portfolio
                {candSide ? ` · ${candSide.affected_count} in your new mix` : ""})
              </summary>
              <div className="mt-3 grid grid-cols-1 gap-4 lg:grid-cols-2">
                <AffectedList label="Your portfolio" companies={result.baseline.affected} before={baseBefore} />
                {candSide && <AffectedList label="Your new mix" companies={candSide.affected} before={candBefore} />}
              </div>
            </details>
          )}
        </div>
      )}
    </section>
  );
}

function SideRow({
  label,
  hint,
  side,
  money,
  badge,
}: {
  label: string;
  hint?: string;
  side: StressSide;
  money: MoneyRow;
  badge?: ReactNode;
}) {
  return (
    <li className="flex flex-wrap items-baseline justify-between gap-2 py-3">
      <div className="flex flex-col gap-0.5">
        <span className="text-body-medium text-text-primary">{label}</span>
        <span className="text-caption-1-regular text-text-tertiary">
          {hint && `${hint} · `}
          {formatPct(side.affected_weight, 1)} exposed · loses {formatPct(side.loss_fraction, 1)}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-body-medium">
        <span className="text-text-secondary">{formatDollars(money.before)}</span>
        <RiArrowRightLine className="size-4 text-foreground-icon-secondary" aria-label="falls to" />
        <span className="text-text-primary">{formatDollars(money.after)}</span>
        <span className="text-text-secondary">(−{formatDollars(money.loss)})</span>
        {badge}
      </div>
    </li>
  );
}

function AffectedList({ label, companies, before }: { label: string; companies: AffectedCompany[]; before: number }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-caption-1-semibold text-text-primary">
        {label} (top {companies.length})
      </span>
      {companies.length === 0 ? (
        <span className="text-caption-1-regular text-text-secondary">No named companies affected.</span>
      ) : (
        <ul className="flex flex-col gap-1">
          {companies.map((comp) => (
            <li key={comp.company_key} className="flex items-baseline justify-between gap-2 text-caption-1-regular">
              <span className="truncate text-text-primary">
                {comp.company_name} ({formatPct(comp.exposure, 2)})
              </span>
              <span className="shrink-0 text-text-secondary">
                −{formatDollars(before * comp.loss)} (−{formatPct(comp.loss, 2)})
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
