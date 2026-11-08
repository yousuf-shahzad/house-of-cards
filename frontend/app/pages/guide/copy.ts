// Beginner mode copy and plain-English helpers (B-GUIDE).
// Keep all language simple and accessible for first-time ETF investors.

import type { Sector, SectorExposure } from "@/api/types";
import {
  diversificationVerdict,
  type DiversificationVerdict,
} from "@/app/ui/concentration";

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
    subtitle: "See which suppliers, customers, or factory locations your biggest companies share.",
    learnMoreHref: "#/dependencies",
    learnMoreLabel: "Learn more on the full Dependencies page",
  },
  {
    step: 5,
    id: "next",
    shortLabel: "What could you do?",
    title: "5. What could you do next?",
    subtitle: "Ways to spread out your risk and test a different ETF mix.",
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

export function concentrationVerdict(
  indexValue: number,
  sectors: readonly SectorExposure[] = [],
): DiversificationVerdict {
  return diversificationVerdict({ hhi: indexValue, sectors });
}

/** Switches from Simple view (#/guide) to Full view on the target route. */
export function openInFullView(href: string): void {
  if (typeof window === "undefined") return;
  window.location.hash = href;
}

export const RISKS_COPY = {
  title: "Hidden risks",
  intro: "From your biggest companies' annual reports, here is who they rely on.",
  reading: (n: number) => `Reading ${n} company annual reports…`,
  phasedProgress: "Reading reports → Double-checking findings → Writing summary",
  phaseReading: "Reading reports",
  phaseResearching: "Double-checking findings",
  phaseSynthesising: "Writing summary",
  readingNote: "This can take a minute or two the first time. You can go back and come back.",
  waiting: "Waiting for your portfolio to finish loading…",
  unavailable: "The supply-chain check isn't available right now. You can still carry on.",
  couldNotRun: "The AI check couldn't run on this computer",
  couldNotRunNote: "An AI key or SEC contact isn't set up here, so the annual reports couldn't be read.",
  noAiKey: "The AI part of this check isn't switched on here, so we can only show what's already been checked.",
  relies: (pct: string, who: string) => `${pct} of your money relies on ${who}`,
  dependsOn: (pct: string, who: string) => `${pct} of your money depends on ${who}`,
  reliesThrough: (n: number) => (n === 1 ? "through 1 of your companies" : `through ${n} of your companies`),
  country: (pct: string, where: string) => `${pct} of your money is in companies with key factories in ${where}`,
  readMore: "Read more",
  showLess: "Show less",
  goDeeper: "Go deeper",
  goingDeeper: "Going deeper…",
  checked: (pct: string) => `We could check ${pct} of your portfolio`,
  checkedNote: "The rest belongs to companies that don't publish this kind of detail.",
  concernsTitle: "What the AI noticed",
  noConcerns: "The AI didn't point out any specific problems.",
  doubleCheckedTitle: (n: number) =>
    n === 1 ? "How we double-checked (1 item)" : `How we double-checked (${n} items)`,
  learnMore: "Learn more",
} as const;

export const NEXT_COPY = {
  intro: "Ways to rely less on the same companies and places.",
  waiting: "The ideas will appear here when the check on the previous step has finished.",
  none: "The AI didn't suggest any specific changes.",
  tryChange: "Try a change",
  tryChangeNote: "Compare your portfolio with a different mix side by side.",
  seeEverything: "See everything",
  seeEverythingNote: "Open the full view with every detail and source.",
  startOver: "Start over",
} as const;

export interface TabInfoGuide {
  title: string;
  whatsHere: string;
  whyItMatters: string;
  keyDetails: readonly string[];
}

export const GUIDE_STEP_INFO: Readonly<Record<GuideStepMeta["id"], TabInfoGuide>> = {
  pick: {
    title: "About Step 1 · Pick your ETFs",
    whatsHere:
      "Enter the ETFs you own by number of shares (or load our sample portfolio). We fetch each fund's latest USD price and published holdings list.",
    whyItMatters:
      "Most people know which ETFs they bought, but not which individual companies sit inside each basket or how much money lands in each stock.",
    keyDetails: [
      "Shares vs %: Enter share counts and we calculate each ETF's dollar value and portfolio share automatically.",
      "Official sources: Holdings come from SEC N-PORT filings and iShares disclosures.",
    ],
  },
  own: {
    title: "About Step 2 · What you really own",
    whatsHere:
      "Your true combined share in every company after opening up all of your ETFs and adding overlapping stocks together, plus which two ETFs overlap the most.",
    whyItMatters:
      "Buying several different ETFs can still leave a large share of your money in the same giant companies if those funds track similar indexes.",
    keyDetails: [
      "Combined share: If a company sits inside several of your ETFs, we add all of those slices together.",
      "Split tickers merged: Dual share classes (like Alphabet's GOOG and GOOGL) are combined into one company.",
    ],
  },
  spread: {
    title: "About Step 3 · How spread out is it?",
    whatsHere:
      "A plain-English verdict on whether your money is well spread out or heavily tilted toward one industry or a small group of companies.",
    whyItMatters:
      "Even if you hold hundreds of stocks on paper, if a large share of your money sits in one industry (such as Technology), a single sector downturn hits much of your portfolio at once.",
    keyDetails: [
      "Behaves-like count: Shows how many equally sized companies your portfolio behaves like.",
      "Industry breakdown: Highlights when a single industry makes up a heavy share of your money.",
    ],
  },
  risks: {
    title: "About Step 4 · Hidden supply-chain risks",
    whatsHere:
      "Suppliers, chip foundries, customers, and factory locations that your largest companies rely on, extracted from their official SEC annual reports (10-K / 20-F).",
    whyItMatters:
      "Companies that look separate in your portfolio—like Nvidia, AMD, Broadcom, and Intel—can all rely on the same single supplier (like TSMC) or manufacturing region.",
    keyDetails: [
      "Verified quotes only: Every link is kept only if its exact quote appears word-for-word in the SEC filing.",
      "No false comfort: Companies that don't name suppliers in their annual report (like Apple) are shown as 'not disclosed', never 'safe'.",
    ],
  },
  next: {
    title: "About Step 5 · What could you do next?",
    whatsHere:
      "Concrete diversification ideas checked against your actual portfolio numbers, plus 'Try a change' to test any ETF swap side by side.",
    whyItMatters:
      "Before changing anything, you can see exactly how adding or swapping an ETF would shift your top-company concentration, biggest industry, and supplier reliance.",
    keyDetails: [
      "Python-verified math: Every before → after change is calculated by deterministic Python code, never guessed by AI.",
      "Not financial advice: Ideas are educational comparisons only and never place trades.",
    ],
  },
} as const;

export const TRY_CHANGE_INFO: TabInfoGuide = {
  title: "About Try a change",
  whatsHere:
    "An interactive sandbox where you can add an ETF or adjust share counts and immediately compare the new mix against your current portfolio.",
  whyItMatters:
    "Lets you verify whether a candidate ETF actually reduces your top-company weight, largest industry share, or single-supplier exposure before making a decision.",
  keyDetails: [
    "Same-company comparison: Dependency changes are measured on the same underlying companies for a fair apples-to-apples check.",
    "Safe sandbox: Editing numbers here does not overwrite your main portfolio unless you click Apply.",
  ],
};

export const PAGE_INFO_COPY: Readonly<Record<string, TabInfoGuide>> = {
  portfolio: {
    title: "About the Portfolio tab",
    whatsHere:
      "Build or edit your ETF portfolio using share counts (default) or percentage weights, or load a pre-verified starter portfolio.",
    whyItMatters:
      "Sets the baseline weights used across every other tab to calculate your look-through company exposures, ETF overlap, and supply-chain risks.",
    keyDetails: [
      "Share valuation: Uses cached USD share prices to turn share counts into exact portfolio percentages.",
      "Coverage & dates: Shows each fund's filing source (SEC N-PORT or iShares) and reporting date.",
    ],
  },
  exposures: {
    title: "About the Exposures tab · What's here & why",
    whatsHere:
      "A complete look-through breakdown of every individual company you own across all of your ETFs, ranked by your true combined portfolio percentage.",
    whyItMatters:
      "ETFs hide individual stocks inside a fund wrapper. This tab opens every ETF basket so you can see where your money actually lands and which funds contribute to each stock.",
    keyDetails: [
      "Per-ETF stacked bars & rows: Click any company row to see how much each of your ETFs contributes to that holding.",
      "Entity resolution: Merges split share classes (e.g. GOOG + GOOGL) by ISIN/CIK so a company's true weight isn't split in two.",
      "True coverage: If an ETF has unmapped cash or missing data, we report the exact coverage rather than silently scaling weights.",
    ],
  },
  overlap: {
    title: "About the Overlap tab",
    whatsHere:
      "A pairwise overlap matrix and shared-holdings inspector showing how much any two of your ETFs invest in the exact same companies.",
    whyItMatters:
      "High overlap between two ETFs means funds with different names and tickers are largely buying the same underlying stocks.",
    keyDetails: [
      "Weighted overlap formula: Sum of min(weight in ETF A, weight in ETF B) across every shared company.",
      "Click any cell: Inspect the shared companies driving the overlap between that pair of ETFs.",
    ],
  },
  network: {
    title: "About the Network tab",
    whatsHere:
      "A visual flow map connecting your portfolio to each ETF and from each ETF into your largest underlying company holdings.",
    whyItMatters:
      "Makes it easy to spot when multiple ETFs funnel your money into the same mega-cap companies at the center of the network.",
    keyDetails: [
      "Line thickness: Proportional to how much of your total portfolio flows through that ETF-to-company link.",
      "Interactive filtering: Click an ETF or company node to highlight its specific connections.",
    ],
  },
  dependencies: {
    title: "About the Dependencies tab · What's here & why",
    whatsHere:
      "An X-ray of who your largest companies rely on—suppliers, chip foundries, customers, and factory locations—extracted from official SEC Form 10-K and 20-F annual reports.",
    whyItMatters:
      "Standard portfolio trackers stop at stock tickers. Even when you own several separate chip or hardware stocks, SEC filings can reveal that they all rely on the same foundry or supplier.",
    keyDetails: [
      "Verbatim evidence: Click any percentage, graph line, or citation chip to open the exact word-for-word sentence from the SEC filing.",
      "Coverage bar: Shows how much of your portfolio has verified disclosures vs. companies that file annual reports without naming suppliers (like Apple) or sit outside the scan window.",
      "Light vs. Go deeper: Light double-checks the riskiest links in each report; Go deeper investigates more of them, for longer, including other companies' filings.",
    ],
  },
  compare: {
    title: "About the Compare tab",
    whatsHere:
      "Side-by-side comparison of your current portfolio against a candidate mix, plus AI-proposed, Python-verified ETF change ideas.",
    whyItMatters:
      "Shows the exact before → after impact on your top-company concentration, effective holdings count, largest sector, and top supply-chain bottleneck.",
    keyDetails: [
      "Verified deltas: Every candidate idea is tested by Python's compare_portfolios engine; any idea that worsens a key risk is rejected.",
      "One-click apply: Test an idea in the draft editor or apply it to your main portfolio when ready.",
    ],
  },
  risk: {
    title: "About the Risk & data tab",
    whatsHere:
      "Portfolio-wide concentration metrics (HHI and effective holdings count), GICS sector breakdown, and filing freshness/staleness audit.",
    whyItMatters:
      "Summarises how concentrated your portfolio is by company and industry, and flags ageing ETF holdings reports (noted after 35 days, staleness warning after 100 days).",
    keyDetails: [
      "Effective holdings (1/HHI): Shows how many equally weighted stocks your portfolio behaves like.",
      "Audit trail: Lists every data source, filing date, and coverage share.",
    ],
  },
} as const;
