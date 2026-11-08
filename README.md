# House of Cards

**See which companies you really own through your ETFs.** Enter a few ETF tickers and how much of your
portfolio is in each. House of Cards fetches each fund's **real, published holdings**, works out your
effective exposure to every underlying company, and shows where your ETFs overlap and how concentrated
the portfolio really is.

Version 2 adds two things: you can enter **shares** instead of percentages, and **Find dependencies**
reads your largest companies' SEC annual reports with AI sub-agents to show who they depend on (suppliers,
foundries, customers, facilities), keeping only facts quoted word for word from the filings.

This is a proof of concept, not investment advice, and it does not trade or simulate risk.

## What it shows

- **Portfolio builder**: add or remove ETFs, set allocations with inputs or sliders (they must total 100%),
  or load a verified example portfolio. Every change re-runs the analysis.
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
- **Dependencies** (v2): **Find dependencies** takes your 15 largest company exposures, fetches each one's
  latest SEC 10-K or 20-F, and shows a supplier/customer graph, the portfolio weight that depends on each
  supplier (e.g. "12.39% of your portfolio depends on TSMC, through 4 companies"), facility concentration by
  country, single points of failure, and an AI synthesis of critical flaws and diversification ideas. Every
  edge opens its evidence: the verbatim quote, the section, the form and filing date, and a link to the filing.

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
- Filings and AI results are cached on disk (filings by accession, forever; extractions per company,
  filing and prompt version), so a repeat click replays without new AI calls.

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

## Tests

```bash
cd backend && uv run pytest              # offline: the network is blocked in tests
cd backend && HOC_LIVE=1 uv run pytest   # also runs live smoke tests against the real sources
cd frontend && npm run build             # type-checks and builds the UI
```

The tests cover weighted exposure, duplicate and overlapping holdings, share-class merging, allocation
validation, weighted overlap, incomplete and missing data, the source adapters' parsing, and the API
contract. They use synthetic fixtures only.

## Known limits

- Holdings are only as fresh as each fund's latest disclosure, which can be up to a quarter for N-PORT-only funds.
- Identity resolution merges share classes through SEC CIK/LEI and a curated list of 48 aliases
  (e.g. TSM and 2330.TW, Samsung common and preferred, Shell, Unilever). Cross-listings outside that list
  may still show as separate companies.
- Company sectors come from TickerInside's per-stock files for each fund's heaviest ~150 holdings; local
  non-US listings have no such file, so they show as Unknown. Portfolio sector allocation falls back to each
  fund's own reported breakdown when line-level sectors cover less than 95% of a fund.
- **Dependencies only see what companies disclose.** In the live us-core-tilt run, 14 of the top 15 companies
  had a 10-K or 20-F. Samsung has no SEC filing, so it appears only through other filers' links (e.g.
  Qualcomm's 10-K). About 45% of the portfolio is covered by verified disclosures; the rest is not analysed.
- **Big customers are usually anonymous** in filings ("one customer was 22% of revenue"), so they show as
  undisclosed customers, not named companies. Some large companies (Apple, Microsoft) name no suppliers at all.
- **Annual reports can be up to a year old**, so every edge shows its form and filing date.
- **Named sites aren't mapped to countries.** Facility concentration by country counts only facilities a filing
  states by country; a named site (e.g. Gigafactory Shanghai) is listed under its company but isn't in China's %.
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
