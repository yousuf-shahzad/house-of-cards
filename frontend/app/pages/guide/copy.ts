// Beginner mode copy and plain-English helpers (B-GUIDE).
// Keep all language simple and accessible for first-time ETF investors.

import type { Sector } from "@/api/types";
import { hhiRating, type ConcentrationRating } from "@/app/ui/concentration";

export interface GuideStepMeta {
  step: 1 | 2 | 3 | 4 | 5;
  id: "pick" | "own" | "spread" | "risks" | "next";
  shortLabel: string;
  title: string;
  subtitle: string;
  learnMoreHref: string;
  learnMoreLabel: string;
}

export const GUIDE_STEP_META: readonly GuideStepMeta[] = [
  {
    step: 1,
    id: "pick",
    shortLabel: "Pick your ETFs",
    title: "1. Pick your ETFs",
    subtitle: "An ETF is a basket of companies. Start with our sample portfolio or enter your own ETFs as percentages.",
    learnMoreHref: "#/portfolio",
    learnMoreLabel: "Learn more in the full Portfolio builder",
  },
  {
    step: 2,
    id: "own",
    shortLabel: "What you really own",
    title: "2. What you really own",
    subtitle: "When we open up each ETF basket and add the companies together, here is where the largest share of your money lands.",
    learnMoreHref: "#/exposures",
    learnMoreLabel: "Learn more on the full Exposures page",
  },
  {
    step: 3,
    id: "spread",
    shortLabel: "How spread out is it?",
    title: "3. How spread out is it?",
    subtitle: "Holding several ETFs does not always mean your money is spread evenly across companies or industries.",
    learnMoreHref: "#/risk",
    learnMoreLabel: "Learn more on the full Risk & data page",
  },
  {
    step: 4,
    id: "risks",
    shortLabel: "Hidden risks",
    title: "4. Hidden supply-chain risks",
    subtitle: "Your companies can still depend on the same key suppliers, customers, or factory locations.",
    learnMoreHref: "#/dependencies",
    learnMoreLabel: "Learn more on the full Dependencies page",
  },
  {
    step: 5,
    id: "next",
    shortLabel: "What could you do?",
    title: "5. What could you do next?",
    subtitle: "Ideas to reduce concentration and test how a change in your ETFs would shift your risks.",
    learnMoreHref: "#/compare",
    learnMoreLabel: "Learn more on the full Compare page",
  },
] as const;

export const PLAIN_SECTOR_LABELS: Record<Sector, string> = {
  information_technology: "Technology",
  financials: "Financial Services",
  health_care: "Healthcare",
  consumer_discretionary: "Consumer Goods & Retail",
  communication_services: "Media & Telecom",
  industrials: "Industrials & Aerospace",
  consumer_staples: "Everyday Essentials",
  energy: "Energy",
  utilities: "Utilities",
  real_estate: "Real Estate",
  materials: "Basic Materials",
  unknown: "Other / Unclassified",
};

export function plainSectorName(sector: Sector): string {
  return PLAIN_SECTOR_LABELS[sector] ?? "Other";
}

export function concentrationVerdict(indexValue: number): ConcentrationRating & { summary: string } {
  const rating = hhiRating(indexValue);
  if (rating.label === "Highly concentrated") {
    return {
      ...rating,
      summary: "A small handful of big companies drives most of this portfolio.",
    };
  }
  if (rating.label === "Moderately concentrated") {
    return {
      ...rating,
      summary: "Your largest holdings carry meaningful weight, though no single stock dominates alone.",
    };
  }
  return {
    ...rating,
    summary: "Your money is spread across many companies without extreme single-company weight.",
  };
}

/** Switches from Simple view (#/guide) to Full view on the target route. */
export function openInFullView(href: string): void {
  if (typeof window === "undefined") return;
  window.location.hash = href;
}

export const RISKS_COPY = {
  title: "Hidden risks",
  intro: "We read the annual reports of your biggest companies to see who they rely on.",
  reading: (n: number) => `Reading ${n} company annual reports…`,
  readingNote: "This can take a minute or two the first time. You can go back and come back.",
  waiting: "Waiting for your portfolio to finish loading…",
  unavailable: "The supply-chain check isn't available right now. You can still carry on.",
  noAiKey: "The AI part of this check isn't switched on here, so we can only show what's already been checked.",
  relies: (pct: string, who: string) => `${pct} of your money relies on ${who}`,
  reliesThrough: (n: number) => (n === 1 ? "through 1 of your companies" : `through ${n} of your companies`),
  country: (pct: string, where: string) => `${pct} of your money is in companies with key factories in ${where}`,
  readMore: "Read more",
  showLess: "Show less",
  checked: (pct: string) => `We could check ${pct} of your portfolio`,
  checkedNote: "The rest belongs to companies that don't publish this kind of detail.",
  concernsTitle: "What the AI noticed",
  noConcerns: "The AI didn't point out any specific problems.",
  learnMore: "Learn more",
} as const;

export const NEXT_COPY = {
  intro: "A few ideas to make your portfolio less dependent on the same places and companies.",
  waiting: "The ideas will appear here when the check on the previous step has finished.",
  none: "The AI didn't suggest any specific changes.",
  tryChange: "Try a change",
  tryChangeNote: "Compare your portfolio with a different mix side by side.",
  seeEverything: "See everything",
  seeEverythingNote: "Open the full view with every detail and source.",
  startOver: "Start over",
} as const;
