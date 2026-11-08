// Pure helpers for Simple-view valuation issue copy (FIX-64) and coverage-gap banner gating (FIX-65).

import type { AnalysisResponse, ValuationIssue } from "@/api/types";

export interface PlainValuationIssueOptions {
  withTicker?: boolean;
}

/**
 * Map a backend `ValuationIssue` to plain-English copy for shares-only / Simple views (FIX-64).
 * Never mentions pinning or percentages, since Simple view has no pin control.
 * Keyed strictly on `issue.code`.
 */
export function plainValuationIssue(
  issue: ValuationIssue,
  options: PlainValuationIssueOptions = {},
): string {
  const { withTicker = true } = options;
  const ticker = issue.ticker?.trim() || null;
  const prefix = withTicker && ticker ? `${ticker}: ` : "";

  switch (issue.code) {
    case "no_price":
    case "price_unavailable":
      return ticker
        ? `We couldn't find ${ticker}. Check the ticker, or remove it.`
        : "We couldn't find this ETF. Check the ticker, or remove it.";
    case "missing_shares":
      return `${prefix}Enter how many shares you hold.`;
    case "invalid_price":
      return `${prefix}We couldn't price this ETF. Check the ticker and share count, or remove it.`;
    case "non_usd_price":
      return `${prefix}This ETF isn't priced in US dollars. Choose a USD-listed ETF, or remove it.`;
    case "stale_price":
      return `${prefix}${issue.message}`;
    case "nothing_to_rescale":
      return "Enter a share count above 0 for at least one ETF.";
    case "pinned_over_100":
    case "allocation_sum_invalid":
      return "Enter how many shares you hold of each ETF.";
    case "duplicate_ticker":
    case "too_many_etfs":
      return `${prefix}${issue.message}`;
  }
}

/**
 * Whether Simple view should show the "Some holdings or company details are missing" banner (FIX-65).
 * Normal excluded cash/futures (e.g. 99.93% covered on the sample portfolio) must not trigger it;
 * only real gaps (covered < 95%, missing ETF allocation, or unexplained allocation) do.
 */
export function hasMaterialCoverageGap(
  analysis: Pick<AnalysisResponse, "coverage" | "gaps">,
): boolean {
  const { coverage, gaps } = analysis;
  return (
    coverage.covered_weight < 0.95 ||
    coverage.missing_allocation > 0.0001 ||
    Math.abs(coverage.unexplained_weight) > 0.005 ||
    gaps.some((gap) => gap.kind === "low_coverage" || gap.kind === "missing_etf")
  );
}
