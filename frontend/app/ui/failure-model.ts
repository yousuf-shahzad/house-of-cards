// FIX-63: pure helpers for the failure simulator (app/ui/failure-simulator.tsx).
// Type-only imports, so `node --test` can load this file directly.

import type { AnalysisResponse, Sector, ValuationResponse } from "@/api/types";

/** % mode has no money, so the simulator shows losses per this many dollars. */
export const NOTIONAL_DOLLARS = 10_000;

/** Options below this weight would read "0.0%" in the picker, so they are left out. */
export const MIN_OPTION_WEIGHT = 0.0005;

export interface SimulatorOption {
  key: string;
  label: string;
  /** Look-through weight in the current portfolio (0..1). */
  weight: number;
  /** Supplier shocks only: the portfolio companies hit. */
  companyKeys?: string[];
}

export const SECTOR_LABELS: Record<Sector, string> = {
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

const byWeight = (a: SimulatorOption, b: SimulatorOption) => b.weight - a.weight || a.label.localeCompare(b.label);

/** Industries the portfolio holds, largest first. Uses the fund-reported sector totals, else sums companies. */
export function sectorOptions(analysis: Pick<AnalysisResponse, "sectors" | "exposures"> | null): SimulatorOption[] {
  if (!analysis) return [];
  const totals = new Map<Sector, number>();
  if (analysis.sectors.length > 0) {
    for (const row of analysis.sectors) totals.set(row.sector, row.weight);
  } else {
    for (const c of analysis.exposures) totals.set(c.sector, (totals.get(c.sector) ?? 0) + c.exposure);
  }
  return [...totals]
    .filter(([sector, weight]) => sector !== "unknown" && weight >= MIN_OPTION_WEIGHT)
    .map(([sector, weight]) => ({ key: sector, label: SECTOR_LABELS[sector] ?? sector, weight }))
    .sort(byWeight);
}

const REGION_NAMES =
  typeof Intl !== "undefined" && typeof Intl.DisplayNames === "function"
    ? new Intl.DisplayNames(["en"], { type: "region" })
    : null;

export function countryName(code: string): string {
  const upper = code.trim().toUpperCase();
  try {
    return REGION_NAMES?.of(upper) ?? upper;
  } catch {
    return upper;
  }
}

/** Countries with a known code, largest first, plus the weight whose country is unknown. */
export function countryOptions(analysis: Pick<AnalysisResponse, "exposures"> | null): {
  options: SimulatorOption[];
  unknownWeight: number;
} {
  if (!analysis) return { options: [], unknownWeight: 0 };
  const totals = new Map<string, number>();
  let unknownWeight = 0;
  for (const c of analysis.exposures) {
    if (c.exposure <= 0) continue;
    const code = c.country?.trim().toUpperCase() ?? "";
    if (code) totals.set(code, (totals.get(code) ?? 0) + c.exposure);
    else unknownWeight += c.exposure;
  }
  const options = [...totals]
    .filter(([, weight]) => weight >= MIN_OPTION_WEIGHT)
    .map(([code, weight]) => ({ key: code, label: countryName(code), weight }))
    .sort(byWeight);
  return { options, unknownWeight };
}

/**
 * The portfolio's money value, or null when it has none (% mode, or shares not priced yet).
 * The backend's total_value covers unpinned rows only, so pinned % rows scale it up.
 */
export function portfolioValue(
  mode: "percent" | "shares",
  valuation: Pick<ValuationResponse, "total_value" | "pinned_total"> | null | undefined,
): number | null {
  if (mode !== "shares" || !valuation || !(valuation.total_value > 0)) return null;
  const pinned = valuation.pinned_total ?? 0;
  return pinned > 0 && pinned < 1 ? valuation.total_value / (1 - pinned) : valuation.total_value;
}

export interface MoneyRow {
  before: number;
  after: number;
  loss: number;
}

/** CONTRACT.md §11: after = before × (1 − loss_fraction). */
export function moneyRow(before: number, lossFraction: number): MoneyRow {
  const loss = before * Math.min(Math.max(lossFraction, 0), 1);
  return { before, after: before - loss, loss };
}

export function formatDollars(amount: number): string {
  return `$${Math.round(Math.abs(amount)).toLocaleString("en-US")}`;
}

/** Compares the two losses in whole dollars, as shown on screen. */
export function lossDifference(baseLoss: number, candidateLoss: number): { tone: "better" | "worse" | "same"; text: string } {
  const diff = Math.round(baseLoss) - Math.round(candidateLoss);
  if (diff > 0) return { tone: "better", text: `loses ${formatDollars(diff)} less` };
  if (diff < 0) return { tone: "worse", text: `loses ${formatDollars(diff)} more` };
  return { tone: "same", text: "same loss" };
}

const SIDE_PREFIX = /^(your portfolio|your new mix):\s*/i;
const LEADING_PCT = /^(\d+(?:\.\d+)?)%/;
const ALWAYS_SHOWN = /unknown industry|don't know the country/i;

/**
 * Backend notes come once per side ("Your portfolio: …", "Your new mix: …").
 * Strips the prefix, keeps the first message of each kind (Your portfolio comes first),
 * drops "x% … not shocked" lines under 1%, and splits what to show from what to fold away.
 */
export function tidyNotes(notes: readonly string[]): { shown: string[]; folded: string[] } {
  const seen = new Set<string>();
  const shown: string[] = [];
  const folded: string[] = [];
  for (const raw of notes) {
    const text = raw.replace(SIDE_PREFIX, "").trim();
    if (!text) continue;
    const pct = LEADING_PCT.exec(text);
    if (pct && Number(pct[1]) < 1) continue;
    const kind = text.replace(/\d+(?:\.\d+)?%/g, "#");
    if (seen.has(kind)) continue;
    seen.add(kind);
    const sentence = text.charAt(0).toUpperCase() + text.slice(1);
    (ALWAYS_SHOWN.test(text) ? shown : folded).push(sentence);
  }
  return { shown, folded };
}

const SHOCK_KINDS = new Set(["sector", "country", "supplier"]);

/**
 * Reads `?shock=<kind>:<key>` from a hash such as `#/compare?shock=sector:information_technology`.
 * Supplier keys may contain colons (`supplier:ALIAS:TSMC`), so only the first colon splits.
 */
export function parseShockHash(hash: string): { kind: "sector" | "country" | "supplier"; key: string } | null {
  const query = hash.split("?")[1];
  if (!query) return null;
  let raw: string | null;
  try {
    raw = new URLSearchParams(query).get("shock");
  } catch {
    return null;
  }
  if (!raw) return null;
  const colon = raw.indexOf(":");
  if (colon <= 0) return null;
  const kind = raw.slice(0, colon).trim().toLowerCase();
  let key = raw.slice(colon + 1).trim();
  if (!SHOCK_KINDS.has(kind) || !key) return null;
  if (kind === "country") key = key.toUpperCase();
  if (kind === "sector") key = key.toLowerCase();
  return { kind: kind as "sector" | "country" | "supplier", key };
}
