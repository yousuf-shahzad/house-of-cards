import assert from "node:assert/strict";
import test from "node:test";

import { hasMaterialCoverageGap, plainValuationIssue } from "./issues.ts";

test("FIX-64: plainValuationIssue maps unknown/unpriced tickers and missing shares without 'pin'", () => {
  const noPrice = plainValuationIssue({
    code: "no_price",
    severity: "blocking",
    ticker: "ZZZZ",
    message: "No price is published; pin this row to a percentage.",
  });
  assert.equal(noPrice, "We couldn't find ZZZZ. Check the ticker, or remove it.");
  assert.equal(/pin/i.test(noPrice), false);

  const unavailable = plainValuationIssue(
    {
      code: "price_unavailable",
      severity: "blocking",
      ticker: "ZZZZ",
      message: "Price could not be loaded; pin this row to a percentage.",
    },
    { withTicker: false },
  );
  assert.equal(unavailable, "We couldn't find ZZZZ. Check the ticker, or remove it.");
  assert.equal(/pin/i.test(unavailable), false);

  const missingSharesCard = plainValuationIssue(
    {
      code: "missing_shares",
      severity: "blocking",
      ticker: "IVV",
      message: "Enter a share count or pin this row to a percentage.",
    },
    { withTicker: true },
  );
  assert.equal(missingSharesCard, "IVV: Enter how many shares you hold.");
  assert.equal(/pin/i.test(missingSharesCard), false);

  const missingSharesRow = plainValuationIssue(
    {
      code: "missing_shares",
      severity: "blocking",
      ticker: "IVV",
      message: "Enter a share count or pin this row to a percentage.",
    },
    { withTicker: false },
  );
  assert.equal(missingSharesRow, "Enter how many shares you hold.");

  const invalidPrice = plainValuationIssue(
    {
      code: "invalid_price",
      severity: "blocking",
      ticker: "QQQ",
      message: "Price is invalid; pin this row to a percentage.",
    },
    { withTicker: true },
  );
  assert.equal(
    invalidPrice,
    "QQQ: We couldn't price this ETF. Check the ticker and share count, or remove it.",
  );
  assert.equal(/pin/i.test(invalidPrice), false);
});

test("FIX-65: hasMaterialCoverageGap ignores normal excluded cash (99.93% covered) and flags <95% or unexplained", () => {
  // Sample portfolio: 99.93% covered, 0.07% excluded cash/futures, 0 unexplained
  assert.equal(
    hasMaterialCoverageGap({
      coverage: {
        total_allocation: 1,
        loaded_allocation: 1,
        missing_allocation: 0,
        covered_weight: 0.9993,
        excluded_weight: 0.0007,
        unexplained_weight: 0,
        sector_known_weight: 0.916,
        unmatched_weight: 0.001,
      },
      gaps: [
        {
          kind: "excluded_lines",
          severity: "info",
          etf_ticker: "IVV",
          subject: null,
          portfolio_weight: 0.0007,
          message: "Excluded cash and futures.",
        },
      ],
    }),
    false,
  );

  // Low coverage (< 95%) triggers the banner
  assert.equal(
    hasMaterialCoverageGap({
      coverage: {
        total_allocation: 1,
        loaded_allocation: 1,
        missing_allocation: 0,
        covered_weight: 0.91,
        excluded_weight: 0.09,
        unexplained_weight: 0,
        sector_known_weight: 0.91,
        unmatched_weight: 0,
      },
      gaps: [],
    }),
    true,
  );

  // Unexplained allocation triggers the banner
  assert.equal(
    hasMaterialCoverageGap({
      coverage: {
        total_allocation: 1,
        loaded_allocation: 1,
        missing_allocation: 0,
        covered_weight: 0.98,
        excluded_weight: 0,
        unexplained_weight: 0.02,
        sector_known_weight: 0.98,
        unmatched_weight: 0,
      },
      gaps: [],
    }),
    true,
  );
});
