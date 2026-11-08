import type { SectorExposure } from "@/api/types";
import type { ChipColor } from "@/components/base/badges/chip";

export type ConcentrationRating = {
  label: "Diversified" | "Moderately concentrated" | "Highly concentrated";
  color: ChipColor;
};

export type IndustryConcentrationRating = {
  label: "Diversified" | "Moderately concentrated" | "Concentrated in one industry";
  color: ChipColor;
};

export type DiversificationVerdictLabel =
  | ConcentrationRating["label"]
  | IndustryConcentrationRating["label"];

export type DiversificationVerdict = {
  label: DiversificationVerdictLabel;
  color: ChipColor;
  companyRating: ConcentrationRating;
  industryRating: IndustryConcentrationRating;
  topSector: SectorExposure | null;
  sectorConcentrated: boolean;
  summary: string;
};

export function hhiRating(hhi: number): ConcentrationRating {
  if (hhi >= 0.18) return { label: "Highly concentrated", color: "rose" };
  if (hhi >= 0.1) return { label: "Moderately concentrated", color: "yellow" };
  return { label: "Diversified", color: "lime" };
}

function industryRatingForTopWeight(weight: number): {
  level: 0 | 1 | 2;
  rating: IndustryConcentrationRating;
} {
  if (weight >= 0.4) {
    return {
      level: 2,
      rating: { label: "Concentrated in one industry", color: "yellow" },
    };
  }
  if (weight >= 0.25) {
    return {
      level: 1,
      rating: { label: "Moderately concentrated", color: "yellow" },
    };
  }
  return {
    level: 0,
    rating: { label: "Diversified", color: "lime" },
  };
}

/**
 * Combined company + industry diversification verdict (v3.1 F4).
 * - Industry rating: top known industry >= 40% -> "Concentrated in one industry";
 *   >= 25% -> at most "Moderately concentrated".
 * - Final verdict: whichever of the company and industry ratings is less diversified.
 */
export function diversificationVerdict({
  hhi,
  sectors = [],
}: {
  hhi: number;
  sectors?: readonly SectorExposure[];
}): DiversificationVerdict {
  const companyRating = hhiRating(hhi);
  const companyLevel: 0 | 1 | 2 =
    companyRating.label === "Highly concentrated"
      ? 2
      : companyRating.label === "Moderately concentrated"
        ? 1
        : 0;

  const knownSectors = sectors.filter((item) => item.sector !== "unknown");
  const topSector =
    knownSectors.length > 0
      ? [...knownSectors].sort((a, b) => b.weight - a.weight)[0] ?? null
      : null;

  const { level: industryLevel, rating: industryRating } = industryRatingForTopWeight(
    topSector?.weight ?? 0,
  );

  const chosen = industryLevel > companyLevel ? industryRating : companyRating;

  const summary =
    companyRating.label === "Highly concentrated"
      ? "A small handful of big companies drives most of this portfolio."
      : companyRating.label === "Moderately concentrated"
        ? "Your largest holdings carry meaningful weight, though no single stock dominates alone."
        : "Your money is spread across many companies without extreme single-company weight.";

  return {
    label: chosen.label,
    color: chosen.color,
    companyRating,
    industryRating,
    topSector,
    sectorConcentrated: Boolean(topSector && topSector.weight >= 0.4),
    summary,
  };
}
