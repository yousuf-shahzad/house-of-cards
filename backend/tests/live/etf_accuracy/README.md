# ETF accuracy study - 8 November 2026

Issue #250. This folder contains a dated, read-only diagnostic study, not a new
production model or an automatically collected live test. The backend baseline
for the saved results is `9bdf21f`; see `results/2026-11-08/frozen_manifest.json`
for its full commit and the fixed cohort.

The two application defaults and ten new non-tech combinations cover 22 funds
and 23 distinct pairs. "New" means outside the defaults as combinations, not an
LLM training holdout. XLF/VFH was also used for API reconnaissance.

## Findings

- All twelve API responses reconcile to independent listing arithmetic. All
  23 listing-overlap calculations reconcile. Company arithmetic checks are
  conditional on the application's entity memberships.
- Same-date issuer controls cover 11 funds and 2,120 equity rows within published
  rounding. Complete independent QQQ holdings were not obtained. Vanguard's
  independently downloaded holdings have different dates from TickerInside.
- Independently rebuilt weekly adjusted-return correlations differ from
  TickerInside's raw-return calculations by at most 0.0003071 across 156 aligned
  weeks. The production API itself has no historical return-correlation output.
- Company overlap can exceed listing overlap: QQQ/VXUS is 1.4203% versus 0.5629%,
  explained by ASML and Ferrovial cross-listings.
- Existing extraction evaluation replay gives 88.4% blind precision and 57.4%
  core recall. This is stored-prediction evaluation, not fresh non-tech inference.
  No new gold labels or live LLM extraction were run for these portfolios.

TickerInside is an upstream source, so parity with its files is not independent
truth. Separate issuer and adjusted-price controls are reported separately.

## Run the dated study

Use a dedicated environment with the desired backend baseline installed:

```powershell
python -m pip install -e ./backend
python -m pip install -r backend/tests/live/etf_accuracy/requirements-report.txt
python backend/tests/live/etf_accuracy/run_benchmark.py all
python -m hoc.eval --replay --gold-dir backend/tests/eval/gold --recorded-dir docs/hoc/eval/recorded --out-md backend/tests/live/etf_accuracy/artifacts/eval-replay.md --out-json backend/tests/live/etf_accuracy/artifacts/eval-replay.json
python backend/tests/live/etf_accuracy/analyze_results.py
python backend/tests/live/etf_accuracy/build_pdf.py --output-dir output/pdf
```

`collect` and `measure` can replace `all` to run those phases separately. All
network requests use public endpoints without keys. HTTP bodies and status,
retrieval time and SHA-256 metadata are cached once per URL under ignored
`artifacts/raw/`. The real API is exercised using TestClient with only its HTTP
input seam replaced by recorded public bytes. The Decimal oracle does not call
production portfolio helpers. Pearson arithmetic is checked against NumPy.

`analyze_results.py` preserves the first snapshot of the existing extraction
cache; this is an availability inventory, not a fresh scan. In a worktree it
locates the primary checkout via the common git directory. An empty cache is
valid and does not mean there are no relationships.

This study has dated index-futures exclusions, source-specific identifier
normalization, and a dated PDF narrative. It is not a generic timeless benchmark.
Do not replace archived inputs with newer data while retaining the old run label.
A new source collection requires a separately dated study and scope review.

## Saved results and reproducibility limits

`results/2026-11-08/` contains derived results, evaluation replay, the fixed
manifest and public source URL/hash references. To rebuild the PDF alone, copy
those files into `artifacts/`, then run `build_pdf.py`. That needs no network.

Exact arithmetic remeasurement additionally requires the locally retained raw
responses, `funds.json`, `issuer_holdings.json`, `external_prices.json`,
`tickerinside_pairs.json`, and full API responses. These raw issuer holdings are
not redistributed. The source manifest permits integrity checks and new source
retrieval, but cannot promise that an upstream URL still serves the old bytes.

The companion delivery `ETF-benchmark-evidence.zip` contains the scripts, saved
derived results and source manifest. It excludes raw holdings and local caches.
The PDF is delivered separately under `output/pdf/` and was rendered and visually
checked on all thirteen pages.

Focused baseline verification:

```powershell
python -m pytest -q backend/tests/portfolio backend/tests/sources/tickerinside backend/tests/eval --basetemp=backend/tests/live/etf_accuracy/artifacts/pytest-tmp
```

Result: 152 passed, one skipped live test. The task-local temp directory avoids a
Windows permission failure encountered with the shared pytest temp directory.

## Attribution

TickerInside holdings/returns through 6 November 2026, used under CC BY 4.0:
https://tickerinside.com/api/ and
https://tickerinside.com/how-the-numbers-are-produced/.
Official holdings checks use iShares, State Street SPDR and Vanguard. Independent
price checks use Yahoo Finance adjusted daily closes. Each requested URL, source
date where available, retrieval timestamp and body hash is inspectable in the
saved evidence. No second human auditor reviewed these calculations.
