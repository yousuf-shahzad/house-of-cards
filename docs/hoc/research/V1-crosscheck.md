# V1: numeric cross-check against TickerInside

*Bekarys's Claude, 2026-11-07. Refs #28, work queue item 4.*

**Status:** the tool and its tests are in; the live run waits for packages a (TickerInside adapter) and d
(normalise/identity, real `CachedHttpClient`). I'll post the live table on the board when they land and
add it here.

## What it does

`scripts/crosscheck_tickerinside.py` runs our analysis of an example portfolio through `EtfService` (the
same path as the API and the CLI, so the maths is never re-implemented). It then compares the result with
TickerInside's own computed answers:

- **Top 20 exposures:** compared with `/api/v1/lookthrough?portfolio=IVV:40,QQQ:25,...&top=50`.
- **Coverage:** looked-through share, distinct companies and top-10 weight.
- **Pairwise overlap:** compared with `/api/v1/overlap?funds=IVV,QQQ,XLK,EEM`. With three or more funds this returns the `matrix` shape, which ranks every pair.

The output is a markdown table: theirs, ours, the difference in percentage points, and why. The script is
a verification tool only. The app never imports it. Their answers go through the cached `HttpClient`
with a 24 h TTL, so a run makes at most one fetch per query, which respects their "one fetch per nightly
build".

```bash
cd backend && uv run python ../scripts/crosscheck_tickerinside.py --example us-core-tilt --output ../v1.md
```

Tests: `backend/tests/api/test_crosscheck.py` runs it over synthetic ZZ fixtures with invented
TickerInside answers served by `FakeHttpClient`, so it needs no network.

## What I found before the live run (probed once on 2026-11-07, nothing committed)

1. **Look-through refuses the full example.** `/lookthrough` caps a request at 30,000 characters of fund
   files. us-core-tilt asks for 50,836, and EEM alone is 26,878 (about 1,200 lines). It answers `400` with
   reason `too_large`, plus the file sizes. The script reads those sizes, drops the largest files until the
   rest fit (EEM here), and asks once more. **So the exposure comparison covers IVV + QQQ + XLK only.** For
   each company it adds up our per-ETF `contributions` from those three funds. The total and pairwise
   overlap (which includes EEM) still come from the full analysis.
2. **Their look-through weights are renormalised. Ours are not.** Their `weight_pct` is a percentage of
   the part looked through (`portfolio_value` = 80 of 100 once EEM is out). The script scales it by
   `portfolio_value / 100` to get a percentage of the whole portfolio, our unit. Their cash and futures
   lines stay inside their total. We exclude cash, derivatives and FX from look-through, so our covered
   share of the three funds will be a little below their 100%.
3. **Identity.** They key companies by ticker: `distinct_companies` counts GOOG and GOOGL as two. We merge
   share classes by CIK, so our GOOGL row will show their GOOGL plus their GOOG. The script flags every
   merged row and names the symbols. This is the expected difference, not an error.
4. **Holdings dates.** Their dates match the sources we will use: IVV, XLK and EEM come from issuer files
   dated 2026-11-05, and QQQ from SEC N-PORT for the period ending 2026-06-30. If one of our adapters falls
   back to a different source or date, the script flags each row that comes through that ETF.
5. **Rounding.** Their look-through gives weights to 3 decimals of a percent, and overlap `by_weight` to 1
   decimal. Differences under 0.001 pp are marked as rounding. On overlap, expect up to 0.05 pp from their
   rounding alone.
6. **Overlap measure.** Both sides take the sum, over shared holdings, of the smaller weight, with no
   renormalisation. Their figure is keyed by ticker, so it is closest to our `weighted_overlap_securities`,
   which the script prints next to our company-level `weighted_overlap`.

## Live results

To come once packages a and d merge.

Source: TickerInside (https://tickerinside.com/), CC BY 4.0. Measurement, not investment advice.
