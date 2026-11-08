import type { ChipColor } from "@/components/base/badges/chip";

export type ConcentrationRating = {
  label: "Diversified" | "Moderately concentrated" | "Highly concentrated";
  color: ChipColor;
};

export function hhiRating(hhi: number): ConcentrationRating {
  if (hhi >= 0.18) return { label: "Highly concentrated", color: "rose" };
  if (hhi >= 0.1) return { label: "Moderately concentrated", color: "yellow" };
  return { label: "Diversified", color: "lime" };
}
