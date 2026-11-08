import assert from "node:assert/strict";
import test from "node:test";
import { splitFirstSentence } from "./sentence.ts";

test("splitFirstSentence does not split on Co., Ltd.", () => {
  const input =
    "Taiwan Semiconductor Manufacturing Co., Ltd. (4 companies: NVDA, AAPL, AVGO, AMD) is a critical single-source foundry. A disruption in Taiwan would halt chip production across your top holdings.";
  const [first, rest] = splitFirstSentence(input);
  assert.equal(
    first,
    "Taiwan Semiconductor Manufacturing Co., Ltd. (4 companies: NVDA, AAPL, AVGO, AMD) is a critical single-source foundry.",
  );
  assert.equal(
    rest,
    "A disruption in Taiwan would halt chip production across your top holdings.",
  );
});

test("splitFirstSentence does not split on Inc.", () => {
  const input =
    "Apple Inc. and Broadcom Inc. depend heavily on overseas assembly. Shifting capacity would take years.";
  const [first, rest] = splitFirstSentence(input);
  assert.equal(
    first,
    "Apple Inc. and Broadcom Inc. depend heavily on overseas assembly.",
  );
  assert.equal(rest, "Shifting capacity would take years.");
});

test("splitFirstSentence does not split on U.S. or No.", () => {
  const input =
    "Under U.S. export controls, Plant No. 12 faces stricter licensing rules. Second sentence explains the portfolio impact.";
  const [first, rest] = splitFirstSentence(input);
  assert.equal(
    first,
    "Under U.S. export controls, Plant No. 12 faces stricter licensing rules.",
  );
  assert.equal(rest, "Second sentence explains the portfolio impact.");
});

test("splitFirstSentence returns single sentence unchanged when no second sentence exists", () => {
  const input =
    "12% of your money depends on Taiwan Semiconductor Manufacturing Co., Ltd.";
  const [first, rest] = splitFirstSentence(input);
  assert.equal(first, input);
  assert.equal(rest, "");
});
