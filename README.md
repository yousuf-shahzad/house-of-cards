# House of Cards

**See which companies you really own through your ETFs.** Enter a few ETF tickers and how much of your
portfolio is in each. House of Cards fetches each fund's **real, published holdings**, works out your
effective exposure to every underlying company, and shows where your ETFs overlap and how concentrated
the portfolio really is.

This is a proof of concept. It validates ETF ingestion and portfolio look-through, which are the
foundations for the eventual goal: recursive corporate-dependency analysis. It does not yet model
supply chains, run AI agents or simulate risk.

## What it shows

- **Portfolio builder**: add or remove ETFs, set allocations with inputs or sliders (they must total 100%),
  or load a verified example portfolio. Every change re-runs the analysis.
- **What you really own**: the top company exposures, with each ETF's contribution, share classes merged
  (GOOG + GOOGL = Alphabet), and a searchable, filterable holdings table.
- **ETF overlap**: a heatmap of weighted overlap between every pair of ETFs (the sum of the smaller weight of
  each shared company), plus the shared companies behind each pair.
- **Network**: each ETF linked to the largest companies it gives you.
- **Risk & data**: top-5 and top-10 concentration, the effective number of companies, sector allocation,
  how much of the portfolio the data covers, each fund's source and disclosure date, and any data gaps.

Every number comes from deterministic Python on the backend. The browser only displays results, and no
LLM is involved.

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

Optional settings live in [`backend/.env.example`](backend/.env.example); none are secrets. To enable the
SEC N-PORT fallback, set `HOC_SEC_CONTACT="Your Name you@example.com"` in your own environment, because SEC
requires a contact in the User-Agent. To work without the network, set `HOC_OFFLINE=1` (cache only).

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

The exact definitions, identity rules, API and error codes are in
[`docs/hoc/CONTRACT.md`](docs/hoc/CONTRACT.md). The backend is laid out so a corporate dependency graph can
plug in after identity resolution without touching ingestion ([`backend/hoc/graph/`](backend/hoc/graph/README.md)).

## Data sources

| Source | Used for | Notes |
|---|---|---|
| [TickerInside](https://tickerinside.com/api/) | Primary: holdings, names, CIK/FIGI identifiers | **CC BY 4.0.** Its citation for each fund is shown in the app. It republishes issuer files (daily) or SEC N-PORT filings (quarterly). |
| [iShares](https://www.ishares.com) holdings CSV | Fallback for iShares funds, with sectors | Fetched at runtime and never redistributed. |
| [SEC EDGAR N-PORT](https://www.sec.gov/edgar) | Fallback, plus ISIN and LEI identifiers | Public domain. Quarterly, published about 60 days after quarter end. |

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
