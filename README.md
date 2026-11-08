# House of Cards

**See which companies you really own through your ETFs.** Enter a few ETF tickers and how much of your
portfolio is in each. House of Cards fetches each fund's **real, published holdings**, works out your
effective exposure to every underlying company, and shows where your ETFs overlap and how concentrated
the portfolio really is.

Version 2 adds two things: you can enter **shares** instead of percentages, and **Find dependencies**
reads your largest companies' SEC annual reports with AI sub-agents to show who they depend on (suppliers,
foundries, customers, facilities), keeping only facts quoted word for word from the filings.

Version 3 turns the dependency graph into a decision and verification workflow: **Compare** tests a
before/after ETF swap against cached filings in one click (no new AI calls), **Relationship importance**
scores every edge (`critical` / `high` / `medium` / `low`) and computes `critical.*` exposure, **Interpretation
checks** (deterministic rules on ±300 chars of filing context + an independent Flash judge on rules-flagged
edges and a 20% sample of unflagged edges) catch negated, competitor or tentative mentions, **Coverage
reporting** accounts for 100% of portfolio weight across five buckets plus per-ETF verified shares and
plain-English gaps, **Investigate gaps** (`A-RES`) runs a bounded multi-step agentic research loop over SEC
filings, and an offline/live **Eval harness** measures precision and recall against an adjudicated 10-company
gold benchmark.

This is a proof of concept, not investment advice, and it does not trade or simulate risk.

## What it shows

- **Beginner mode (guided view, v3.1)**: on every load, a welcome dialog asks *"Have you analysed an ETF portfolio
  before?"* Choosing **"I'm new: guide me"** opens a 5-step plain-English walkthrough (`#/guide`, no sidebar,
  no jargon) that triggers the agentic AI supply-chain check automatically in the background from Step 2:
  1. **Pick your ETFs** (shares-only on Screen 1 with read-only `%` — sample portfolios load as whole shares worth ~$10,000, e.g. `IVV 5 / QQQ 4 / XLK 9 / EEM 34 = $9,817.68`),
  2. **What you really own** (top 5 companies as plain sentences + the highest-overlap ETF pair, e.g. `QQQ` and `XLK` at `50.11%`),
  3. **How spread out is it?** (combined company + industry verdict chip via `diversificationVerdict` — e.g. **"Concentrated in one industry"** when the top industry is $\ge 40\%$ — top-10 share, effective equal holdings, top 3 industries),
  4. **Hidden risks** (monotonic phased progress bar *"Reading reports → Double-checking findings → Writing summary"* + **Go deeper** option, top supplier dependency, top non-US factory country, checked portfolio share, and concise `plain_title`/`plain_text` AI flaws with **Read more**),
  5. **What could you do?** (concise `plain_title`/`plain_text` AI suggestions, concrete one-click **Change ideas**, real-time **Try a change** inside the guide, **See everything** -> `#/dependencies`, or **Start over**).
  Choosing **"I'm experienced: show everything"** opens the full dashboard, and a **Simple view / Full view**
  switch in the top bar toggles between both views at any time while keeping your portfolio and current step.
- **Portfolio builder**: add or remove ETFs (defaults to **shares**, with a `%` toggle), set allocations, or load
  a verified example portfolio (valued as whole shares worth ~$10,000 at latest exchange closes). Every change
  re-runs the analysis.
- **Shares input** (v2): switch to **Shares**, enter how many shares you hold (fractions allowed), and each
  ETF is valued at its latest **exchange close** (from TickerInside; not NAV) to give its %. Typing a % on a
  row **pins** it, and the other rows rescale by value to fill the rest. A missing, invalid or non-USD price
  blocks that row until you pin it; a price more than 4 days old shows a warning.
- **What you really own**: the top company exposures, with each ETF's contribution, share classes merged
  (GOOG + GOOGL = Alphabet), and a searchable, filterable holdings table.
- **ETF overlap**: a heatmap of weighted overlap between every pair of ETFs (the sum of the smaller weight of
  each shared company), plus the shared companies behind each pair.
- **Network**: each ETF linked to the largest companies it gives you.
- **Risk & data**: top-5 and top-10 concentration, the effective number of companies, sector allocation,
  how much of the portfolio the data covers, each fund's source and disclosure date, and any data gaps.
- **Dependencies** (v2/v3): **Find dependencies** takes your 15 largest company exposures, fetches each one's
  latest SEC 10-K or 20-F, and shows a supplier/customer graph, the portfolio weight that depends on each
  supplier (e.g. "12.39% of your portfolio depends on TSMC, through 4 companies"), **critical dependency**
  exposure (`critical.*`), facility concentration by country, single points of failure, a 5-bucket **coverage
  breakdown** (summing to 100% of the portfolio, with per-ETF verified shares and plain-English coverage gaps),
  and an AI synthesis of critical flaws and diversification ideas. Every edge carries a deterministic
  **importance tier** (`critical`, `high`, `medium`, `low`) and an **interpretation check** (`confirmed` or
  `flagged`), and opens its evidence: the verbatim quote, the section, the form and filing date, the
  importance reasons, and a link to the filing. Clicking **Investigate gaps** runs a bounded multi-step
  agentic research loop across SEC filings to follow up on flagged edges, unnamed customers, single-source
  bottlenecks, and zero-disclosure holdings.
- **Compare / Try a change** (v3/v3.1): edit a candidate **Scenario** (defaults to **shares**, seeded from your
  current portfolio, with concrete one-click **Change ideas**) in real time (~500 ms auto-compare with no
  Compare button, both on `#/compare` and inside the guided view's **Try a change** screen) to see four headline
  before/after rows — biggest dependency change, top industry share (`top_sector`), top-10 concentration, and
  effective equal holdings — plus full deltas under **More details** (e.g. swapping 15 pts of QQQ + 15 pts of XLK
  into 30% VTV cuts TSMC dependency from **12.39% to 6.30%, -6.10 pts**, and top-10 concentration from **37.14% to
  24.98%**), using cached verified extractions with zero Gemini calls.

Every number comes from deterministic Python on the backend. The only LLM use is the Dependencies page,
and even there the model never produces a number or a company match (see "How it works").

## Run it locally

You need [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you) and Node.js 22.12 or newer.
On macOS, `brew install uv`; on Windows, `winget install astral-sh.uv`.

```bash
# Terminal 1: API on http://127.0.0.1:8000
cd backend
uv sync
uv run uvicorn hoc.api.app:app --host 127.0.0.1 --port 8000
```

```bash
# Terminal 2: UI on http://127.0.0.1:5173 (proxies /api to the backend)
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:5173, press **Load** on an example portfolio, then explore the pages.
Two examples are included: **US core with a tech tilt** (IVV 40 / QQQ 25 / XLK 15 / EEM 20) and
**global-core** (VTI 50 / VXUS 30 / QQQ 20). Each is offered only after its funds' real holdings load.

The API warms its cache in the background when it starts, and fetched files stay in a local cache
(`backend/.cache/`, 24 h for most files), so changing allocations is instant. **Before a demo**, warm the
cache once so the first load is instant even on a fresh machine:

```bash
cd backend
uv run python -m hoc.cli warm
uv run python -m hoc.cli warm --example global-core
```

A three-minute walkthrough with the real numbers is in [`docs/hoc/DEMO.md`](docs/hoc/DEMO.md).

Command-line version of the same analysis:

```bash
cd backend
uv run python -m hoc.cli analyse --example us-core-tilt
uv run python -m hoc.cli analyse IVV=60 QQQ=40
```

Optional settings live in [`backend/.env.example`](backend/.env.example). Set them in your own environment,
never in the repository:

| Variable | Needed for | Default |
|---|---|---|
| `HOC_SEC_CONTACT` | Anything from SEC EDGAR (the N-PORT fallback and every 10-K/20-F on the Dependencies page). SEC requires a contact in the User-Agent, e.g. `"Your Name you@example.com"` | unset: those companies show `sec_contact_missing` |
| `GEMINI_API_KEY` | **Secret.** Live AI extraction and synthesis. Sent only in a request header, never in a URL, cache file or log | unset: cached results only, otherwise `missing_api_key` |
| `HOC_GEMINI_EXTRACTOR_MODEL` / `HOC_GEMINI_ORCHESTRATOR_MODEL` | The sub-agents / the synthesis | `gemini-3.8-flash` / `gemini-4-argon` (Argon falls back to Flash on rate limits) |
| `HOC_DEPS_TOP_N` | How many top companies Find dependencies reads | 15 |
| `HOC_DEPS_REVERSE_LIMIT` | Other companies' filings searched per company for reverse links (0 = off) | 3 |
| `HOC_OFFLINE` | `1` = serve only from the local cache, no network | 0 |

Without the key or the SEC contact, nothing fails: the app shows any cached results and says which
setting is missing.

## How it works

```
 ETF ticker ──> source adapters ──> normalisation ──> identity resolution ──> portfolio maths ──> API ──> UI
               TickerInside        weights as         same company across     exposure, overlap,   FastAPI  React
               iShares CSV         fractions, cash    ETFs (CIK, LEI,         concentration,
               SEC N-PORT          and derivatives    ISIN, curated           sectors, coverage,
               (first that works)  excluded           aliases)                data gaps
```

- **Effective exposure** to company *c* = Σ over ETFs (allocation × the company's weight in that ETF).
  It is never rescaled, so data the sources can't cover stays visible as a gap.
- **Coverage** splits the portfolio into covered, excluded (cash and derivatives), missing (ETFs that
  failed to load) and unexplained. The four always add up to 100%.
- **Weighted overlap** between two ETFs = Σ over shared companies of min(weight in A, weight in B).
- **Concentration**: the sum of the top 5, 10 and 20 exposures, and the Herfindahl index (HHI) with its
  effective number of companies.

**Dependencies (v2)**, one click on the top 15 companies:

```
 company --> SEC 10-K / 20-F --> Gemini Flash --> Python checks --> Python metrics --> Gemini Argon --> Python checks
             newest from EDGAR,   one sub-agent    each quote must   dependency %,     synthesis of     a claim with a
             sections 1/1A/2 or   per company:     be verbatim in    facilities by     critical flaws   number not from a
             3/4/5, plus reverse  edges, each      the filing;       country, single   and              cited metric, an
             links from other     with a quote     names resolved    points of         diversification unknown id or an
             filers                                exactly           failure           ideas            outside name: dropped
```

- **No hallucinated facts.** An edge survives only if its quote appears word for word in the filing text
  (after normalising spaces, quotes and dashes). Rejected edges are counted on the page, never drawn.
- **The model never picks a company.** Counterparty names resolve by exact match against the portfolio,
  the curated aliases and SEC company titles, so "TSMC" and "Taiwan Semiconductor Manufacturing Company
  Limited" are one node. Anything else stays an unresolved name.
- **Python owns every number.** The synthesis may only write `{{metric:id}}` placeholders, which Python
  fills in. A claim with any other number, an unknown id, or a company outside the portfolio and the
  verified edges is dropped.
- **Reverse links.** EDGAR full-text search finds other companies' current annual reports that name a
  holding (e.g. Qualcomm's 10-K naming Samsung as a foundry), so companies without SEC filings still appear.
- **Interpretation verification (v3 `V-INT`).** Verbatim quotes can still be misread (a competitor list, a
  negated sentence, a divestiture, or a tentative deal). Python rules scan the quote and ±300 characters of
  surrounding filing text for `competitor_mention`, `negated`, `hypothetical`, `direction_mismatch`,
  `generic_reference`, and `subject_mismatch`, then an independent `gemini-3.8-flash` judge (`hoc-v3-judge-1`)
  reviews every rules-flagged edge plus a deterministic 20% sample of unflagged edges. Contradicted or competitor
  edges are removed and counted in `interpretation_rejected` (e.g. rejecting `AMD -> Sanmina` as a
  `contract_manufacturer` on `us-core-tilt` because *"we sold the ZT Manufacturing Business to Sanmina"* is a
  divestiture, not supply), while uncertain edges stay `flagged` (e.g. `Nvidia -> OpenAI`: *"agreement being
  finalized... no assurance"*).
- **Relationship importance (v3 `R-IMP`).** Python deterministically scores every edge in `[0, 1]` and assigns
  a tier (`critical >= 0.8`, `high >= 0.6`, `medium >= 0.4`, `low < 0.4`) from the relationship type, customer
  revenue share (`>=20%` critical, `10-20%` high), facility role (production vs HQ/office/R&D), and verbatim
  concentration cues (`sole`, `substantially all`, `one of several`). Any edge marked `flagged` by V-INT is
  capped at `medium` so tentative disclosures never inflate `critical.<key>` portfolio exposure.
- **Honest coverage reporting (v3 `C-COV`).** Python partitions 100% of portfolio weight into five mutually
  exclusive buckets (`verified`, `no_disclosures`, `no_sec_filing`, `not_analysed`, `outside_top_n`), computes
  each ETF's verified share (`by_etf`), lists the top 10 unanalysed companies outside the cutoff, and generates
  plain-English `CoverageGap`s (`outside_top_n`, `unnamed_customers`, `non_sec_counterparties`, `old_filings`,
  `region_only_facilities`).
- **Agentic research loop (v3 `A-RES`).** Clicking **Investigate gaps** (`POST /api/dependencies/{job_id}/research`)
  picks up to 6 open questions from the dependency result and runs a bounded tool loop (`search_filings`,
  `read_section`, `find_in_filing`, `conclude`; at most 4 steps per item). Every candidate edge proposed by the
  research agent passes through the exact same `verify_quote`, `V-INT` interpretation check, and `R-IMP`
  importance scoring before merging into the graph and recomputing metrics.
- **Before/after scenario comparison (v3 `X-API` / `X-UI`).** `POST /api/compare` runs look-through analyses on
  both the baseline and candidate portfolios, loads cached verified edges for the union of their top-N
  holdings, re-resolves counterparty keys per portfolio, and computes before/after deltas for supplier
  dependencies (`dep.*`), critical dependencies (`critical.*`), facility countries (`facility.*`), and
  concentration without making any SEC or Gemini calls.
- Filings and AI results are cached on disk (filings by accession, forever; extractions per company,
  filing and prompt version; judge verdicts per edge), so a repeat click replays without new AI calls.

The exact definitions, identity rules, API and error codes are in
[`docs/hoc/CONTRACT.md`](docs/hoc/CONTRACT.md). The backend is laid out so a corporate dependency graph can
plug in after identity resolution without touching ingestion ([`backend/hoc/graph/`](backend/hoc/graph/README.md)).

## Data sources

| Source | Used for | Notes |
|---|---|---|
| [TickerInside](https://tickerinside.com/api/) | Primary: holdings, names, CIK/FIGI identifiers | **CC BY 4.0.** Its citation for each fund is shown in the app. It republishes issuer files (daily) or SEC N-PORT filings (quarterly). |
| [iShares](https://www.ishares.com) holdings CSV | Fallback for iShares funds, with sectors | Fetched at runtime and never redistributed. |
| [SEC EDGAR N-PORT](https://www.sec.gov/edgar) | Fallback, plus ISIN and LEI identifiers | Public domain. Quarterly, published about 60 days after quarter end. |
| SEC EDGAR 10-K / 20-F and full-text search | Dependencies: suppliers, customers, facilities (v2) | Public domain. Needs `HOC_SEC_CONTACT`; at most 10 requests per second. |
| Google Gemini API | Dependencies: extraction (Flash) and synthesis (Argon) (v2) | Needs `GEMINI_API_KEY`. Python checks its output before any of it is shown. |

Each ETF shows its source and **disclosure date**. Funds that only file quarterly (for example QQQ via
N-PORT) can be months old, and the app flags that as a data gap. No financial data is committed to this
repository: holdings are downloaded at runtime and cached locally. The only data in the repo is clearly
labelled synthetic test data (`backend/tests/fixtures/synthetic/`, `frontend/api/__fixtures__/`).
Data-source research notes are in [`docs/hoc/research/`](docs/hoc/research/).

## Tests & Evaluation

```bash
cd backend && uv run pytest              # offline: the network is blocked in tests
cd backend && HOC_LIVE=1 uv run pytest   # also runs live smoke tests against the real sources
cd frontend && npm run build             # type-checks and builds the UI
```

### Gold Extraction & Verification Benchmark (v3 `E-GOLD` / `E-RUN`)

House of Cards includes an adjudicated benchmark of **10 held-out SEC 10-K filings** outside the default demo
top-15 (`NKE`, `F`, `GM`, `BA`, `SWKS`, `QRVO`, `GLW`, `PFE`, `DE`, `SBUX`) in
[`backend/tests/eval/gold/`](backend/tests/eval/gold/) (documented in
[`docs/hoc/eval/ADJUDICATION.md`](docs/hoc/eval/ADJUDICATION.md)): **115 core** relationships (`81` agreed by both
independent annotators, `26` Annotator A, `8` Annotator B; **inter-annotator F1 = 0.49**), **107 extended**
relationships (`97` blind + `10` pooled; **222 total**), and **79 hard negatives** (competitor lists, negated
claims, hypotheticals, generic groups).

Run the evaluation harness from `backend/`:

```bash
# Offline replay (default: deterministic verifier + V-INT + R-IMP against recorded predictions; zero API calls)
cd backend && uv run hoc eval

# Live (runs Gemini extractor + V-INT Flash judge on the 10 held-out 10-Ks and updates docs/hoc/EVAL.md)
cd backend && uv run hoc eval --live
```

- **Benchmark results ([`docs/hoc/EVAL.md`](docs/hoc/EVAL.md)):**
  - **Micro precision:** **88.4% [83.2%, 92.5%]** blind (114/129; **Micro F1 = 69.6% [51.9%, 82.7%]**) and **96.1% [89.6%, 100.0%]** after blind pooled adjudication (124/129; **Micro F1 = 71.9% [53.3%, 85.1%]**, with 10 of 14 unmatched predictions confirmed verbatim in the filings as extended relationships).
  - **Core recall (`tier='core'`, blind denominator):** **57.4% [35.3%, 76.0%]** (66/115 core relationships; misses are mainly multi-site facility countries, 23/49, and Pfizer co-development alliances, 18/49).
  - **Hard-negative false-positive rate:** **1.3% [0.0%, 3.9%]** (**1/79** across 27 competitor, 11 negated, 9 hypothetical, 7 unrelated, and 25 generic passages), **100.0% [100.0%, 100.0%] direction accuracy** (124/124), **100.0% [100.0%, 100.0%] facility-country accuracy** (**39/39**), and **importance-tier agreement** quadratic weighted Cohen's $\kappa = \mathbf{0.475\ [0.382,\ 0.631]}$ (54/79).
  - **Honest V-INT note:** On the 10 held-out filings, the extractor + verbatim quote check already rejected 78/79 hard negatives so **V-INT filtered 0 edges on the held-out set** (`129 -> 129`); on the live `us-core-tilt` portfolio run, V-INT rejected **1** misread divestiture (`AMD -> Sanmina`, *"we sold the ZT Manufacturing Business to Sanmina"*) and flagged **1** tentative overclaim (`Nvidia -> OpenAI`). Supplier precision is the weakest relationship type (16.7% blind / 50.0% pooled, 3/6).

The unit tests cover weighted exposure, duplicate and overlapping holdings, share-class merging, allocation
validation, weighted overlap, incomplete and missing data, the source adapters' parsing, relationship
importance, interpretation rules and judge decisions, 5-bucket coverage reporting, portfolio comparison, and
the API contract.

## Known limits

- Holdings are only as fresh as each fund's latest disclosure, which can be up to a quarter for N-PORT-only funds.
- Identity resolution merges share classes through SEC CIK/LEI and a curated list of 48 aliases
  (e.g. TSM and 2330.TW, Samsung common and preferred, Shell, Unilever). Cross-listings outside that list
  may still show as separate companies.
- Company sectors come from TickerInside's per-stock files for each fund's heaviest ~150 holdings; local
  non-US listings have no such file, so they show as Unknown. Portfolio sector allocation falls back to each
  fund's own reported breakdown when line-level sectors cover less than 95% of a fund.
- **Dependencies only see what companies disclose.** In the live `us-core-tilt` run (top 15 holdings), 13
  companies (`40.43%` of portfolio weight) have verified dependencies, 1 (`1.50%`, Meta) has a 10-K that names
  no counterparties, 1 (`1.43%`, Samsung) has no SEC filing of its own and appears through reverse links from
  other filers, and `56.64%` sits outside the top-15 cutoff (the coverage bar and per-ETF verified shares —
  **XLK 63% / QQQ 52% / IVV 37% / EEM 15%** — show this directly on screen).
- **Big customers are usually anonymous** in filings ("one customer was 22% of revenue"), so they show as
  undisclosed customers (`unnamed_customers` coverage gap), not named companies.
- **Annual reports can be up to a year old**, so every edge shows its form and filing date, and filings older
  than 15 months trigger an `old_filings` coverage gap.
- **Region-only facility disclosures stay unplaced.** Named sites, US states, Canadian provinces, major cities,
  and single-country evidence quotes resolve deterministically to ISO-2 countries (`188 / 189` cached facility
  edges across the example portfolios), while broad macro-region disclosures (e.g. `"Asia"`) are counted in
  `facility.unplaced.count` and flagged under `region_only_facilities` rather than assigned to a guessed country.
- **A first, uncached Find dependencies click takes about 2 minutes** (about 15 filings, the AI calls and the
  reverse search). Run it once before a demo; after that it replays from the cache.
- **Share prices are exchange closes**, not NAV, and only USD-priced ETFs can be valued by shares; others
  must be pinned to a %.
- This is a local PoC: no accounts, no database, no trading, and not investment advice.

## Repository layout

| Path | What |
|---|---|
| [`backend/`](backend/README.md) | FastAPI service: sources, normalisation, identity, maths, API, CLI |
| [`frontend/`](frontend/README.md) | React UI built on [telos-boardui](https://github.com/yousuf-shahzad/telos-boardui) |
| [`docs/hoc/`](docs/hoc/) | Plan, frozen contract and research notes |
| [`scripts/`](scripts/) | Verification tools (e.g. cross-checking against TickerInside's own figures) |
| [`tools/board`](docs/AGENT_BOARD.md) | The agent message board the team used to build this |

Built at a hackathon by a team of humans and coding agents coordinating on a GitHub-issue message board:
see [`docs/AGENT_BOARD.md`](docs/AGENT_BOARD.md) and [`docs/hoc/PLAN.md`](docs/hoc/PLAN.md).
