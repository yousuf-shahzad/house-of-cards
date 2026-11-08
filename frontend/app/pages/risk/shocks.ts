// Pure helpers for FIX-63 item B (Risk page "What if it fails?" links to #/compare?shock=...).

import type { CompanyExposure, Sector, SectorExposure } from "@/api/types";

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
  unknown: "Unknown / Unclassified",
};

const COUNTRY_NAMES: Record<string, string> = {
  AT: "Austria",
  AU: "Australia",
  BE: "Belgium",
  BR: "Brazil",
  CA: "Canada",
  CH: "Switzerland",
  CL: "Chile",
  CN: "China",
  CO: "Colombia",
  CZ: "Czechia",
  DE: "Germany",
  DK: "Denmark",
  EG: "Egypt",
  ES: "Spain",
  FI: "Finland",
  FR: "France",
  GB: "United Kingdom",
  GR: "Greece",
  HK: "Hong Kong",
  HU: "Hungary",
  ID: "Indonesia",
  IE: "Ireland",
  IL: "Israel",
  IN: "India",
  IT: "Italy",
  JP: "Japan",
  KR: "South Korea",
  KW: "Kuwait",
  LU: "Luxembourg",
  MX: "Mexico",
  MY: "Malaysia",
  NL: "Netherlands",
  NO: "Norway",
  NZ: "New Zealand",
  PE: "Peru",
  PH: "Philippines",
  PL: "Poland",
  PT: "Portugal",
  QA: "Qatar",
  RO: "Romania",
  SA: "Saudi Arabia",
  SE: "Sweden",
  SG: "Singapore",
  TH: "Thailand",
  TR: "Turkey",
  TW: "Taiwan",
  UA: "Ukraine",
  US: "United States",
  VN: "Vietnam",
  ZA: "South Africa",
};

export function countryName(code: string): string {
  const upper = code.trim().toUpperCase();
  if (COUNTRY_NAMES[upper]) return COUNTRY_NAMES[upper];
  try {
    const intl = new Intl.DisplayNames(["en"], { type: "region" }).of(upper);
    if (intl && intl !== upper) return intl;
  } catch {
    // ignore invalid region codes
  }
  return upper;
}

export interface LargestIndustryShock {
  key: Sector;
  label: string;
  weight: number;
  href: `#/compare?shock=sector:${Sector}`;
}

export interface LargestCountryShock {
  code: string;
  label: string;
  weight: number;
  companyCount: number;
  unknownWeight: number;
  href: `#/compare?shock=country:${string}`;
}

/** Find the largest known industry (excluding "unknown") and build its failure-simulator link. */
export function largestIndustryShock(
  sectors: readonly SectorExposure[] | null | undefined,
): LargestIndustryShock | null {
  if (!sectors || sectors.length === 0) return null;
  const known = sectors.filter((s) => s.sector !== "unknown" && s.weight > 0);
  if (known.length === 0) return null;

  const sorted = [...known].sort((a, b) => {
    if (Math.abs(b.weight - a.weight) > 1e-12) return b.weight - a.weight;
    return a.sector.localeCompare(b.sector);
  });

  const top = sorted[0];
  return {
    key: top.sector,
    label: SECTOR_LABELS[top.sector] ?? top.sector,
    weight: top.weight,
    href: `#/compare?shock=sector:${top.sector}`,
  };
}

/** Find the largest known country from company exposures (excluding null/empty country codes). */
export function largestCountryShock(
  exposures: readonly CompanyExposure[] | null | undefined,
): LargestCountryShock | null {
  if (!exposures || exposures.length === 0) return null;

  const byCode = new Map<string, { weight: number; count: number }>();
  let knownWeight = 0;

  for (const exp of exposures) {
    if (!(exp.exposure > 0)) continue;
    const rawCode = exp.country?.trim().toUpperCase();
    if (!rawCode) continue;

    knownWeight += exp.exposure;
    const prev = byCode.get(rawCode);
    if (prev) {
      prev.weight += exp.exposure;
      prev.count += 1;
    } else {
      byCode.set(rawCode, { weight: exp.exposure, count: 1 });
    }
  }

  if (byCode.size === 0) return null;

  const sorted = [...byCode.entries()].sort((a, b) => {
    if (Math.abs(b[1].weight - a[1].weight) > 1e-12) return b[1].weight - a[1].weight;
    return a[0].localeCompare(b[0]);
  });

  const [code, stats] = sorted[0];
  const weight = Number(stats.weight.toFixed(10));
  const unknownWeight = Math.max(0, Number((1 - knownWeight).toFixed(10)));

  return {
    code,
    label: countryName(code),
    weight,
    companyCount: stats.count,
    unknownWeight,
    href: `#/compare?shock=country:${code}`,
  };
}
