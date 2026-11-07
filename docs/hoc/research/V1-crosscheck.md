# V1: numeric cross-check against TickerInside

*Bekarys's Claude, 2026-11-07. Refs #28, work queue item 4.*

**Status: done.** Ran live on 2026-11-07 against main after a, d and d-core merged. **Our maths reconciles with
TickerInside's.** Every difference comes from a stated cause (see "Live results"):
- the GOOG/GOOGL identity merge,
- their rounding,
- our exclusion of cash and derivatives.

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

## Live results (2026-11-07, us-core-tilt, all four ETFs from TickerInside)

**Holdings dates match on both sides:** IVV, XLK and EEM 2026-11-05 (issuer files); QQQ 2026-06-30 (N-PORT).

**Top exposures (% of the whole portfolio, contributions of IVV + QQQ + XLK; EEM left out by `too_large`)**

| | theirs | ours | diff pp | why |
|---|---:|---:|---:|---|
| AAPL | 7.3656 | 7.3659 | 0.0003 | rounding |
| NVDA | 6.8856 | 6.8855 | -0.0001 | rounding |
| MSFT | 5.6024 | 5.6021 | -0.0003 | rounding |
| AMZN | 2.6168 | 2.6168 | 0.0000 | rounding |
| MU | 2.3728 | 2.3726 | -0.0002 | rounding |
| AVGO | 2.2760 | 2.2762 | 0.0002 | rounding |
| AMD | 2.0440 | 2.0442 | 0.0002 | rounding |
| GOOGL | 1.8624 | 3.4632 | 1.6008 | we merge GOOG+GOOGL (CIK 0001652044) |
| GOOG | 1.6008 | 3.4632 | 1.8624 | we merge GOOG+GOOGL (CIK 0001652044) |
| META | 1.4960 | 1.4960 | 0.0000 | rounding |
| TSLA | 1.4352 | 1.4351 | -0.0001 | rounding |
| INTC | 1.1888 | 1.1885 | -0.0003 | rounding |
| CSCO | 1.1240 | 1.1241 | 0.0001 | rounding |
| AMAT | 1.0400 | 1.0400 | 0.0000 | rounding |
| LRCX | 0.9696 | 0.9694 | -0.0002 | rounding |
| WMT | 0.9576 | 0.9573 | -0.0003 | rounding |
| PLTR | 0.8784 | 0.8787 | 0.0003 | rounding |
| COST | 0.7472 | 0.7475 | 0.0003 | rounding |
| PANW | 0.7248 | 0.7247 | -0.0001 | rounding |
| TXN | 0.7128 | 0.7131 | 0.0003 | rounding |

- **Rounding:** every non-merged row agrees within 0.0003 pp. Their `weight_pct` has 3 decimals of a percentage of
  the 80% looked through, so one unit is 0.0008 pp of the whole portfolio. Rounding fully explains these.
- **Identity:** our Alphabet row is exactly their GOOGL plus their GOOG (1.8624 + 1.6008 = 3.4632). This is the
  share-class merge on CIK that the contract asks for.

**Coverage**

| | theirs | ours | why |
|---|---:|---:|---|
| share of IVV+QQQ+XLK looked through | 100% | 99.9375% | theirs is 100% by construction. Our 0.0625 pp gap is mostly the funds' own reported weights falling short of 100% (+0.0644 pp unexplained), partly offset by net short derivative/cash lines we exclude (-0.0020 pp). Corrected after Yousuf's Codex's review; see V1-results.md |
| top-10 weight (% of the looked-through funds) | 42.7 | 44.447 | Alphabet enters our top 10 as one company (3.46); they rank GOOGL and GOOG separately. Recomputed from the rows above, theirs is 42.65 and ours 44.447 |
| distinct companies | 520 tickers (3 funds) | 1,680 companies, 1,683 securities (4 funds) | different scope; they count tickers, we merge share classes |

Our whole-portfolio coverage: covered 99.9304%, excluded -0.0016% (short derivative lines net slightly negative),
missing 0, unexplained 0.0711%. Unexplained is the part where the funds' own reported weights fall short of
100%. Nothing is renormalised, so it stays visible.

**Pairwise overlap, by weight (%)**

| pair | theirs | ours | diff pp | companies in both (theirs / ours) |
|---|---:|---:|---:|---|
| QQQ / XLK | 50.1 | 50.1063 | 0.0063 | 35 / 35 |
| IVV / QQQ | 48.8 | 48.8247 | 0.0247 | 86 / 85 companies (86 securities) |
| IVV / XLK | 35.5 | 35.5222 | 0.0222 | 76 / 76 |
| QQQ / EEM | 0.2 | 0.2207 | 0.0207 | 1 / 1 |
| IVV / EEM | 0 | 0.0000 | 0.0000 | 0 / 0 |
| XLK / EEM | 0 | 0.0000 | 0.0000 | 0 / 0 |

- **Overlap:** all six pairs agree within their 1-decimal rounding (at most 0.05 pp). Our security-level figure
  equals our company-level figure to 2 decimals here, because the shared names are mostly single-class.
- **IVV / QQQ:** the pair shares 86 tickers but 85 companies, again because GOOG and GOOGL merge.

**Conclusion:** no unexplained difference. Our exposure, coverage and overlap maths reproduces TickerInside's
independent figures on real data. The deliberate differences are the identity merge, keeping cash and gaps
visible instead of renormalising, and finer precision.

Source: TickerInside (https://tickerinside.com/), CC BY 4.0. Measurement, not investment advice.
