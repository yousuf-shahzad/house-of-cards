# House of Cards PoC: plan and work packages

> Lead: Gawyn's Claude (`@whitehawk9571 (Claude)`). Tracking issue: #28 (one checklist item per package). Branch per package: `28-<package>-<slug>`; PRs say `Refs #28` and name the package.

## Context
Gawyn, the sole lead, wants a working PoC of **House of Cards**. The user enters ETF tickers and allocations, the backend fetches **real** holdings, and the UI shows the companies they really own:
- effective exposure,
- ETF overlap,
- concentration and sectors,
- data coverage and disclosure dates.

The UI is built on Yousuf's `telos-boardui`; the backend is Python FastAPI. Nine agents are online, all paused by Gawyn's stop. This plan splits the work into packages that can be built in parallel without two agents editing the same file. I (Gawyn's Claude) own the contract and the integration, and I also develop.

Decisions (Gawyn):
- **Repo:** `hackathon-test` monorepo, with top-level `backend/` and `frontend/`.
- **Data:** TickerInside is the primary source, SEC N-PORT is used for ISIN and LEI, and iShares CSV is a fresher issuer source.
- **People:** all nine agents get work.

### Facts verified on 2026-11-07, which drive the design
- **TickerInside** (`tickerinside.com/api/v1/`):
  - No key, licensed CC BY 4.0. Each file has a `cite_as` line we must show, and they ask for at most one fetch per nightly build.
  - The fund path must be lowercase. `holdings` is `{symbol: percent}` with no names. Names come from `securities.json`, and CIK and FIGI from `identifiers.json`.
  - `holdings_as_of` is the disclosure date. Funds are either issuer-sourced (IVV, SPY, ACWI, EEM, XLK, dated 11-05) or N-PORT-sourced (QQQ, VOO, VTI dated 06-30, VXUS 07-31).
  - GOOG and GOOGL share a CIK. A futures line appears in XLK.
  - Do not use its `/overlap` or `/lookthrough` endpoints: the maths must be ours.
- **iShares:** the old ajax CSV URL returns HTML. Use `latest-holdings.csv`, whose URL is in the product page's JSON-LD `contentUrl`. Columns vary by fund, and there is no ISIN. **SEC N-PORT** XML has ISIN, LEI and CUSIP but no sector, and lags about 60 days. **Invesco** downloads are blocked. **OpenFIGI** is keyless at 25 requests/min and is security-level, so it can't merge companies.
- **telos-boardui:**
  - Vite, React 19 and strict TS 5.9, Tailwind v4, Board UI source copied into `components/`. Flat layout with no `src/`, Recharts 3 included, no tests or lint.
  - Hotspots: `suite/workspace.tsx` (all state and the route switch) and `main.tsx` (router plus marketing pages).
  - The scripted fake assistant is `suite/assistant.tsx`; sample data is in `suite/model.ts`.
  - There's no slider, heatmap or graph component, and `vite` is pinned to `"latest"`.
- **This Mac:** Python 3.9 only, and no `uv`.

## Architecture and contract (the full contract is frozen in Wave 0)
**Backend package `backend/hoc/`:**

| Module | Responsibility |
|---|---|
| `contract/` | All Pydantic models and errors; the only import shared across layers |
| `sources/base.py` | `SourceAdapter` / `ReferenceProvider` protocols |
| `sources/registry.py` | Fallback order `tickerinside → ishares → sec_nport` |
| `sources/{tickerinside,sec_nport,ishares}/` | One adapter per source |
| `sources/fake.py` | Fake adapter for tests |
| `core/{http,cache}.py` | Disk cache, user agent, rate limits, offline and stale-if-error |
| `normalise/` and `identity/` | Normalisation and company resolution, plus `aliases.json` |
| `portfolio/` | Pure maths: validation, exposure, overlap, concentration, sectors, coverage, `analyse` |
| `service.py`, `api/`, `examples.py`, `cli.py` | Wiring, routes, examples and the command line |
| `graph/README.md` | Placeholder for the later corporate-dependency graph |

**Rules:**
- **Weights:** every weight is a `float` fraction of 1, summed with `math.fsum`, with deterministic tie-breaks, and serialised to 10 decimal places.
- **Exposure:** `E_c = Σ_e A_e · w_{e,c}`, never renormalised. `Σ E_c` equals the covered weight.
- **Coverage:** coverage, excluded, missing and unexplained always add up to 1. A failed ETF counts as missing allocation and gets a critical gap.
- **Weighted overlap:** `Σ_c min(w_ic, w_jc)` at company level, with a security-level variant too. There's no renormalisation after cash is removed.
- **Concentration:** top 5, 10 and 20, HHI, effective number of companies, and distinct securities (always at least distinct companies).
- **Sectors:** from line-level data if it covers at least 95% of the ETF, otherwise the fund-reported breakdown, otherwise none.
- **Identity:**
  - `security_key`: the TickerInside symbol convention (`BRK.B`, `2330.TW`) first, then ISIN, CUSIP, name.
  - `company_key`: the alias map first (TSM ↔ 2330.TW, Samsung common and preferred), then CIK (merges GOOG/GOOGL and BRK.A/B), LEI, ISIN issuer prefix (US/CA only), symbol (*partial*), name (*unmatched*).
  - Unmatched lines are kept, counted and flagged as a gap.
- **API:**
  - Endpoints: `GET /api/health`, `GET /api/etfs/{t}`, `POST /api/analysis` (body `{holdings:[{ticker, allocation}]}`), `GET /api/examples`.
  - Errors use one shape, `{error:{code, message, details}}`. Codes: `ALLOCATION_SUM_INVALID`, `DUPLICATE_TICKER`, `TOO_MANY_ETFS` and `UNKNOWN_TICKER` (422), and `SOURCES_UNAVAILABLE` (503). A partial failure still returns 200.
- **Example portfolio:** `us-core-tilt` = IVV 40 / QQQ 25 / XLK 15 / EEM 20. `examples.py` holds only tickers and allocations. Weights are always fetched live, and an example is offered only once it is verified.
- **Cache:** `backend/.cache/` (gitignored). Fund and reference files expire after 24 hours, and N-PORT filings never expire. `HOC_OFFLINE=1` serves only from the cache. Raw issuer files are never committed.
- **Tooling:** uv with CPython 3.12 (`requires-python >= 3.11`). Dependencies: fastapi, uvicorn, httpx, pydantic 2, defusedxml; dev: pytest, ruff. If `uv` can't be installed, fall back to the python.org installer plus `requirements.txt`.
- **Tests:** pytest with the network blocked by an autouse fixture. Synthetic fixtures live only in `backend/tests/fixtures/synthetic/`, use `ZZ` tickers and CIKs starting with 999, and carry a README saying they are synthetic. Live smoke tests run only with `HOC_LIVE=1`.

**Frontend `frontend/`** (telos-boardui copied in, without its `.git`):
- **Pages:** `app/registry.tsx` (frozen) lists the pages `portfolio | exposures | overlap | risk`. `workspace.tsx` looks pages up from the registry, so page owners never edit shared files.
- **State:** `useAnalysis()` keeps the draft rows, debounces requests by 400 ms, cancels stale requests, and only calls the API when the inputs are valid.
- **API layer:** a hand-written `api/types.ts` mirrors the Pydantic models; a backend snapshot test catches drift. `api/client.ts` is the only place percent is converted to a fraction.
- **Dev setup:** a Vite proxy forwards `/api` to `127.0.0.1:8000`. `VITE_API_MOCK=1` serves a synthetic fixture with a "SYNTHETIC" banner, so views can be built before the backend exists; it's off by default.
- **telos-boardui cleanup:** the scripted assistant and the mock-data wiring are **unrouted, not deleted**, to respect "don't remove working UI unnecessarily". `vite` is pinned to 8.3.5.
- **No new npm dependencies.** The slider is react-aria, the heatmap is a CSS grid, and the network graph is plain SVG.

## Agent assignments
Each package is one checklist item in #28 and one branch (`28-<package>-<slug>`). The owner edits only their own paths.

| # | Package | Owner | Owns (paths) | Starts after |
|---|---|---|---|---|
| W0-B | Backend skeleton and **frozen contract**: `contract/`, `sources/base.py`, working `registry`, `core/http` and `core/cache` stubs with final signatures, `fake.py`, `conftest`, synthetic fixtures, OpenAPI snapshot, `pyproject`/lock, `frontend/api/types.ts`, the synthetic analysis fixture, `docs/hoc/CONTRACT.md`, `.gitignore`, the AGENTS.md owner table, the issues | **Gawyn's Claude** | `backend/hoc/contract`, `backend/pyproject.toml`, `frontend/api/types.ts`, `docs/hoc/` | now |
| W0-F | Frontend shell: copy telos-boardui, page registry, `AnalysisProvider`/`useAnalysis`, `api/client.ts`, mock mode, Vite proxy, version pins, stub pages, shared `app/ui/` (EtfChip, Pct, AsOfBadge), unroute the assistant | **Yousuf's Claude** | `frontend/` except `api/types.ts`; sole owner of `package.json`/lockfile | now, in parallel; rebases on W0-B |
| a | TickerInside adapter and reference provider (critical path) | **Gawyn's Gemini** | `backend/hoc/sources/tickerinside/`, `tests/sources/tickerinside/` | W0-B merged |
| b → c | SEC N-PORT adapter (EDGAR lookup, parser, OpenFIGI), then the iShares adapter (JSON-LD discovery, CSV parser) | **Kendrick's Gemini** | `sources/sec_nport/`, `sources/ishares/` and their tests | W0-B |
| d | Normalisation, identity resolution, `aliases.json`, real `core/http` and `core/cache` | **Kendrick's Claude** | `normalise/`, `identity/`, `core/`, their tests | W0-B |
| e | Portfolio maths and the full test list (validation, exposure, overlap, concentration, coverage, golden) | **Yousuf's Codex** | `backend/hoc/portfolio/`, `tests/portfolio/` | W0-B |
| f | Service, FastAPI app, routes, errors, examples, CLI (`analyse`, `warm`), API integration tests | **Bekarys's Claude** | `service.py`, `api/`, `examples.py`, `cli.py`, `tests/api/` | W0-B |
| F1 | Portfolio builder page and react-aria slider: add/remove ETFs, allocation inputs, 100% validation display, load example, server errors | **Yousuf's Claude** (after W0-F) | `frontend/app/pages/portfolio/`, `components/base/slider/` | W0-F merged |
| F2 | Exposures page: top-20 stacked bar of per-ETF contributions (Recharts) and a tanstack holdings table with search and expandable contributions | **Yousuf's Gemini** | `frontend/app/pages/exposures/` | W0-F (mock), then real API |
| F3 | Overlap page: heatmap matrix, pair detail (shared securities and companies, weighted overlap, top shared), stretch goal: an SVG ETF → company network | **Bekarys's Gemini** | `frontend/app/pages/overlap/`, `components/application/heatmap/` | W0-F |
| F4 | Risk & data page: top-5/10 StatCards, distinct counts, HHI, sector bars, coverage stacked bar, source and as-of table with attribution, gaps list | **Gawyn's Gemini** (after `a`) | `frontend/app/pages/risk/` | `a` merged |

**Research during Wave 0.** These agents are waiting for W0-B anyway, so each starts a research item now. Each item produces one file in `docs/hoc/research/`, owned by the researcher:
- **R1** (identity edge cases): Kendrick's Claude.
- **R2** (source freshness): Kendrick's Gemini.
- **R3** (sector mapping): Gawyn's Gemini.

**My role as lead, after W0-B:**
- Review any PR that touches a frozen file.
- Control the merge order.
- Manage the work queue below.
- Run the end-to-end integration.
- Write the top-level README.
- Do the final success-criteria pass.

## Work queue: reassigning freed agents, and delegating research
The table above is only the starting allocation. When an agent posts that it has merged, or that it's free, I give it the **highest-priority unblocked item** that touches no file someone else currently owns. I post the reassignment on the board (`@login (Agent) take <item>`), add it to #28, and update the AGENTS.md owner table. **Research goes to agents too.** A research item ends in a short dated finding, posted to the board and committed to `docs/hoc/research/`, which I fold into the contract or the queue. I don't do the research myself.

Queue, in priority order. Each item is added to #28 when it is assigned.

| Priority | Kind | Item | Best fit |
|---|---|---|---|
| 1 | Research | **R1: identity edge cases.** Check `aliases.json` candidates against live TickerInside `securities.json` and `identifiers.json` (ADR ↔ local listings, Samsung preferred, BRK classes, dual-listed companies such as Shell or Unilever), with evidence per entry | Whoever frees up first; feeds d |
| 2 | Research | **R2: source freshness and fallback.** For the example ETFs and other common ones (SPY, VOO, VTI, VXUS, SCHD, VEA), record which source is freshest and whether iShares or N-PORT beats TickerInside, and recommend `HOC_SOURCE_ORDER` per issuer | Kendrick's Gemini after b, or anyone free |
| 3 | Build | **c: iShares adapter**: **assigned to Yousuf's Codex** (b's owner still busy) | Yousuf's Codex |
| 4 | Verify | **V1: numeric cross-check.** Script our analysis against TickerInside `/lookthrough` and `/overlap` for the example portfolio, and explain any differences (dates, identity, cash). Kept in `scripts/`, never used by the app | Next free agent with Python |
| 5 | Build | **Network graph:** SVG ETF → top companies, inside F3's folder once F3 is merged, or a new `pages/network/` registered through me | Next free frontend agent |
| 6 | Research | **R3: sector mapping.** Map TickerInside `breakdown.sectors_pct` ids and iShares sector labels to our `Sector` enum, and list gaps | Anyone; feeds d |
| 7 | Test | **T1: live smoke tests** (`@pytest.mark.live`) for each adapter and the example portfolio, plus an offline-mode test | Next free backend agent |
| 8 | Polish | **P1: UX and accessibility pass** across pages (loading and empty states, keyboard use, dark mode, number formatting) | Next free frontend agent |
| ~~9~~ | ~~Build~~ | ~~SPDR and Vanguard adapters~~: **dropped**. R2 (`docs/hoc/research/R2-sources.md`) found TickerInside matches the issuers' freshness, so they add nothing. | n/a |

**Rules:**
- An item is "unblocked" when its dependencies are merged and its paths are free.
- If no item fits a free agent, it reviews an open PR (read-only, comments on the PR) rather than idling.
- New work discovered mid-build goes onto this queue, not straight to an agent.

## Waves and milestones
1. **Kickoff (me):**
   - Open #28 with every package, its owner, paths and start condition.
   - Fill in the AGENTS.md owner table.
   - Post to `@all` on the board: the stop is lifted *only for the assigned packages*, each package is linked to its issue, and the worktree rule below applies.
2. **Wave 0:** W0-B (me) and W0-F (Yousuf's Claude) run in parallel. W0-B merges first because it's small and everything depends on it; W0-F then rebases. **M0** = both merged.
3. **Wave 1:** a, b, d, e and f in parallel on the backend, and F1, F2 and F3 on the frontend using mock mode.
   - **M1:** `uv run python -m hoc.cli analyse --example us-core-tilt` prints real exposures (critical path: a ∥ d ∥ e → f).
4. **Wave 2:** F4 starts (Gawyn's Gemini); c (iShares) starts (Kendrick's Gemini); F1–F3 switch to the real API.
   - **M2:** the UI shows live data and updates when allocations change.
5. **Wave 3 (me):** integration, the end-to-end checklist, the README, final merges and a board announcement. **M3** = every success criterion met.

The waves only set the order of dependencies. In practice, every merge frees an agent, and that agent immediately takes the next queue item.

## Coordination rules (posted at kickoff, and added to AGENTS.md by W0-B)
- **Worktrees:** every agent works in its **own git worktree**, created with `git worktree add ../hoc-<agent> -b 28-<package>-<slug> origin/main`. Same-human agents share one checkout, and a branch switch by one would otherwise clobber the other.
- **Frozen files** need a board request to me, and I change them in a single PR: `backend/hoc/contract/**`, `sources/base.py`, `frontend/api/types.ts`, `frontend/app/registry.tsx`, `docs/hoc/CONTRACT.md`.
  - Python dependencies: request from me.
  - npm dependencies: request from Yousuf's Claude.
- **PR rules:** small commits, explicit paths only, `Refs #28` plus the package name, fetch and rebase, never force-push. Tick your box in #28 when merged.
- **Before merging:** `cd backend && uv run pytest` and/or `cd frontend && npm run build` must pass locally. The author merges their own PR, except that PRs touching frozen files wait for my review.
- **Board posts:**
  - Post when you start, when you merge, and when you're blocked.
  - Set `BOARD_AGENT=<Tool>` for any agent that isn't Claude.
  - Mention by `@login (Agent)`.
  - Post only on a mention, a merge or a blocker, to avoid noise.
- **No financial data in code:** none hardcoded or committed. Real data is fetched and cached in the gitignored `.cache/`. Synthetic data is allowed only in `tests/fixtures/synthetic/` and `frontend/api/__fixtures__/`, and must be labelled.
- **Attribution:** show TickerInside's `cite_as` and the licence in the UI and the README. Respect each source's terms: one fetch per day, SEC User-Agent with contact details, and no republishing of issuer files.
- **`.gitignore`:** add negations so fixtures stay tracked even if PR #25's ignore rules (`*.csv`, `*.jsonl`, `data/`) are merged.

## Verification (Wave 3, by me)
- **Backend:**
  - `cd backend && uv run pytest`: all tests pass, with the network blocked.
  - `HOC_LIVE=1 uv run pytest -m live`: live smoke tests against TickerInside, SEC and iShares.
  - `uv run python -m hoc.cli analyse --example us-core-tilt`: real numbers, reconciled against TickerInside `/lookthrough` and `/overlap`.
- **Frontend:** `cd frontend && npm ci && npm run build` must pass with no type errors.
- **End to end:** run `uvicorn hoc.api.app:app --port 8000` and `npm run dev`, then in the in-app browser:
  - load the example and see real data;
  - change one allocation and see the analysis update;
  - set a total other than 100% and see a validation error;
  - enter an unknown ticker and see an `UNKNOWN_TICKER` error;
  - check the top-20, the contributions, the overlap matrix, the concentration and sector views, coverage %, and the source, as-of date and attribution per ETF;
  - confirm GOOG and GOOGL merge into one company;
  - confirm no SYNTHETIC banner appears;
  - confirm `HOC_OFFLINE=1` serves from the cache.
- **Success criteria:** go through every bullet in the brief and record the evidence in the final board post and the PR.
