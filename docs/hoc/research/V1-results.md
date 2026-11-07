# V1 cross-check: us-core-tilt vs TickerInside

Lookthrough funds: IVV, QQQ, XLK (left out: EEM)

## Holdings dates

| ETF | ours | theirs |
|---|---|---|
| IVV | 2026-11-05 | 2026-11-05 |
| QQQ | 2026-06-30 | 2026-06-30 |
| XLK | 2026-11-05 | 2026-11-05 |
| EEM | 2026-11-05 | 2026-11-05 |

## Top exposures (% of portfolio)

| | theirs | ours | diff pp | why |
|---|---:|---:|---:|---|
| AAPL | 7.3656 | 7.3659 | 0.0003 | rounding |
| NVDA | 6.8856 | 6.8855 | -0.0001 | rounding |
| MSFT | 5.6024 | 5.6021 | -0.0003 | rounding |
| AMZN | 2.6168 | 2.6168 | -0.0000 | rounding |
| MU | 2.3728 | 2.3726 | -0.0002 | rounding |
| AVGO | 2.2760 | 2.2762 | 0.0002 | rounding |
| AMD | 2.0440 | 2.0442 | 0.0002 | rounding |
| GOOGL | 1.8624 | 3.4632 | 1.6008 | we merge GOOG+GOOGL into one company (CIK:0001652044) |
| GOOG | 1.6008 | 3.4632 | 1.8624 | we merge GOOG+GOOGL into one company (CIK:0001652044) |
| META | 1.4960 | 1.4960 | -0.0000 | rounding |
| TSLA | 1.4352 | 1.4351 | -0.0001 | rounding |
| INTC | 1.1888 | 1.1885 | -0.0003 | rounding |
| CSCO | 1.1240 | 1.1241 | 0.0001 | rounding |
| AMAT | 1.0400 | 1.0400 | -0.0000 | rounding |
| LRCX | 0.9696 | 0.9694 | -0.0002 | rounding |
| WMT | 0.9576 | 0.9573 | -0.0003 | rounding |
| PLTR | 0.8784 | 0.8787 | 0.0003 | rounding |
| COST | 0.7472 | 0.7475 | 0.0003 | rounding |
| PANW | 0.7248 | 0.7247 | -0.0001 | rounding |
| TXN | 0.7128 | 0.7131 | 0.0003 | rounding |

## Coverage

| | theirs | ours | diff  | why |
|---|---:|---:|---:|---|
| share of IVV+QQQ+XLK looked through (%) | 100 | 99.9375 | -0.0625 | theirs counts every holdings line; we exclude cash, derivatives and FX |
| distinct companies (lookthrough funds) | 520 | - | - | theirs counts tickers (GOOG and GOOGL are two); see ours below for the whole portfolio |
| our distinct companies / securities (whole portfolio) | - | 1667 | - | 1683 securities |
| our covered / excluded / missing (% of portfolio) | - | 99.9304 | - | excluded -0.0016, missing 0.0000, unexplained 0.0711 |
| top-10 weight (% of the looked-through funds) | 42.7000 | 44.4470 | 1.7470 | ours ranks merged companies, theirs ranks tickers |

## Pairwise overlap, by weight (%)

| | theirs | ours | diff pp | why |
|---|---:|---:|---:|---|
| QQQ / XLK | 50.1000 | 50.1063 | 0.0063 | companies in both: theirs 35, ours 35 (35 securities); security level ours 50.11 |
| IVV / QQQ | 48.8000 | 48.8247 | 0.0247 | companies in both: theirs 86, ours 85 (86 securities); security level ours 48.82 |
| IVV / XLK | 35.5000 | 35.5222 | 0.0222 | companies in both: theirs 76, ours 76 (76 securities); security level ours 35.52 |
| QQQ / EEM | 0.2000 | 0.2207 | 0.0207 | companies in both: theirs 1, ours 1 (1 securities); security level ours 0.22 |
| IVV / EEM | 0 | 0.0000 | 0.0000 | companies in both: theirs 0, ours 0 (0 securities); security level ours 0.00 |
| XLK / EEM | 0 | 0.0000 | 0.0000 | companies in both: theirs 0, ours 0 (0 securities); security level ours 0.00 |

## Notes

- Ours: fractions of the whole portfolio, never renormalised (cash and failed ETFs stay visible). Theirs: lookthrough weight_pct is of the funds looked through; scaled here by portfolio_value/100.
- Overlap: both are the sum over shared holdings of the smaller weight. Ours merges share classes into companies (company level) and also gives the security level; theirs keys by ticker.
- Lookthrough refused the whole portfolio (too large); EEM left out, so exposures compare only the contributions of the other funds.

Source: TickerInside (https://tickerinside.com/), CC BY 4.0. Measurement, not investment advice.

## Run provenance and assessment

Yousuf's Codex ran the unchanged `scripts/crosscheck_tickerinside.py` on
2026-11-07 against main `fb78968cd23b60d08e35010d9f9c583d23af67b0` (including
aliases, company sectors, and parser fixes), with `HOC_SOURCE_ORDER=tickerinside`.
Command from the repository root, using the backend virtualenv Python:

```text
python scripts/crosscheck_tickerinside.py --output docs/hoc/research/V1-results.md
```

The three comparison responses were fetched once each at 19:21:28 UTC and
retained in the production disk cache: full-portfolio lookthrough (400,
`too_large`), IVV+QQQ+XLK lookthrough (200), and four-fund overlap (200).
These are distinct queries; no query was retried. The analysis uses production
EtfService and portfolio maths. Follow-up checks used `HOC_OFFLINE=1` and the
same cache, without further endpoint requests. Raw upstream files are uncommitted.
The earlier V1-crosscheck.md records the previous run; this report verifies the
subsequent merged changes on this machine.

**No difference in this comparison points to a bug in our portfolio maths.**
All differences exceeding 0.05 percentage points are explained below:

- **GOOGL +1.6008 pp and GOOG +1.8624 pp:** the two upstream rows map to one
  Alphabet company through CIK 0001652044. Its exact exposure is 3.463225%
  (GOOGL 1.862325% + GOOG 1.600900%). The table deliberately repeats that
  company total beside each upstream security; those two rows must not be added.
  Their rounded security rows sum to 3.4632%, matching our merged total.
- **Top ten +1.7470 pp:** our 35.557595% contribution from the three included
  ETFs divided by their 80% allocation is 44.44699375%. We rank companies,
  so Alphabet occupies one place and another company enters the top ten;
  upstream ranks GOOG and GOOGL separately and reports 42.7% to one decimal.
  Thus the top-ten comparison combines a different grouping with upstream rounding.
- **Looked-through share -0.0625 pp:** the generated table's explanation is
  incomplete. IVV+QQQ+XLK contribute 79.950030% covered against 80% allocation,
  or 99.9375375% of that allocation. The shortfall is primarily reported fund
  weights below 100%, not excluded cash alone. For this subset, unexplained
  weight contributes +0.06443125 percentage points of the subset allocation;
  excluded net short derivatives contribute -0.00196875 pp. Their sum is
  0.0624625 pp. Upstream reports 100% looked through; our calculation retains
  the original weights and keeps that residual visible.

Every other exposure difference is at most 0.0003 pp after displayed rounding.
Upstream lookthrough weights have three decimal places in percent of the 80%
subset; scaling by 0.8 gives a rounding tolerance of 0.0004 pp. All six overlap
pairs differ by less than 0.05 pp, consistent with upstream's one-decimal output.
There are no mismatched disclosure dates: QQQ is 130 days old on the run date,
but both sides use the same June filing. Sectors label exposures without changing
exposure or overlap weights.

**Aliases and scope:** Samsung common and preferred now merge to
1.433940% of the full portfolio (1.261620% + 0.172320%), entirely from EEM.
EEM is omitted only from the upstream exposure comparison, so Samsung cannot
cause any discrepancy in its top-20 table. It remains included in all six
overlap comparisons and whole-portfolio coverage. Full-portfolio counts are now
1,667 companies and 1,683 securities, versus the earlier report's 1,680 companies;
company aliases merge listings without removing securities or exposure. The
upstream count of 520 concerns only three funds and counts ticker rows, so it
is not directly comparable to the four-fund company count.

Whole-portfolio coverage reconciles exactly at the retained precision:
99.930430% covered - 0.001575% excluded + 0.071145% unexplained + 0% missing
= 100%. The negative excluded value is the net short derivative weight in XLK,
not negative equity exposure. No covered equity weights are renormalised.
