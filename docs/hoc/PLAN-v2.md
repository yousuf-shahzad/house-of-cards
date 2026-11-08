# House of Cards v2: AI dependency analysis + share-based portfolio input

> **Status: FINAL** (after the board consultation on 2026-11-07/08 with all eight agents). Lead: Gawyn's Claude. Tracking: #28.
> Research: [`R4-dependency-sources.md`](research/R4-dependency-sources.md) and [`R5-gemini-and-prices.md`](research/R5-gemini-and-prices.md).

## Goal
1. **Share-based ETF adder.**
   - The user enters a number of shares per ETF (fractional shares allowed).
   - The UI shows price × shares = value and the resulting %.
   - Typing a % **pins** that row, and the unpinned rows rescale by value to fill the rest of 100%.
2. **AI dependency analysis.** A "Find dependencies" click on the top 15 company exposures:
   - fetches each company's latest SEC 10-K or 20-F;
   - **Gemini sub-agents** extract suppliers, customers, contract manufacturers and foundries, key inputs, and facilities;
   - **Python verifies every quote**, resolves names, and computes dependency metrics;
   - an **orchestrator Gemini** writes diversification suggestions and critical flaws that cite only verified facts and metrics.

Analysis requests stay in fractions, so `POST /api/analysis` doesn't change.

## Rules every package follows
- **No hallucinated facts.**
  - An edge exists only if its quote is a substring of the filing's normalised text. Verification runs against the whole document via `hoc.filings.text.normalise`, which G-AI imports.
  - Up to one `...` splice is allowed, when both halves are at least 25 characters and appear in order within 300 characters.
  - Rejected edges and claims are counted and shown, never drawn.
- **Python owns every number.**
  - Shares × price, allocations, dependency metrics: all deterministic.
  - The orchestrator writes numbers only as `{{metric:<id>}}` placeholders, which Python fills in.
  - Any other literal number in its text, an unknown metric or edge id, or a company or ticker outside the portfolio or verified edges causes that claim to be dropped (`rejected_claims_count`).
- **The LLM never picks a company key.** Names resolve by exact match against portfolio names, `aliases.json`, SEC `company_tickers` titles and a short manual list (Hon Hai = Foxconn, TSMC). Anything else stays an unresolved `NAME:` node, and fuzzy matching only flags names for review.
- **Honest coverage:**
  - Per-company statuses are enums: `queued, fetching, extracting, cached, done, no_sec_filing, unsupported_form, sec_contact_missing, missing_api_key, error`, plus `extraction_quality=fallback`.
  - Samsung and SK Hynix appear only as counterparties in other filers' quotes ("no primary disclosure").
  - Every edge shows its form and filing date.
- **Secrets:**
  - `GEMINI_API_KEY` (event Argon key) and `HOC_SEC_CONTACT` stay in local env only.
  - The key goes only in the `x-goog-api-key` header, never in a URL, cache entry or log.
  - Without them, the app shows cached results and the matching status, never a 500.
- **Prices:** TickerInside `last_close` / `last_close_date` / `currency` (the exchange close, not NAV), from the same 24 h-cached fund JSON.
  - A price is **stale** if it's more than 4 calendar days older than the analysis date. That covers weekends plus one holiday; there's no exchange calendar.
  - Stale prices warn but don't block.
  - Missing, invalid or non-USD prices block that row until it's pinned to a %. Never price at 0, never guess.
- **No new npm dependencies** (the graph is SVG, the facility chart uses Recharts). **No Gemini SDK:** we call the Interactions REST endpoint through `core/http`.
- **Models:** `HOC_GEMINI_EXTRACTOR_MODEL=gemini-3.8-flash` and `HOC_GEMINI_ORCHESTRATOR_MODEL=gemini-4-argon`, both env-overridable, with Argon falling back to Flash on 429. JSON schemas stay flat.

## API (contract: lead)
- **`POST /api/valuation`.**
  - Request: `{rows:[{ticker, shares|null, allocation_override|null}]}`, overrides as fractions.
  - Response: `{status: usable|blocked, rows:[{ticker, shares, price, price_date, price_age_days, price_stale, currency, value, allocation, pinned, issues[]}], total_value, pinned_total, issues[], attributions[]}`.
  - The maths: pinned sum P; unpinned value Vᵢ; allocationᵢ = (1−P)·Vᵢ/ΣV.
  - Blocked when P > 1, when P < 1 and ΣV = 0, or when all rows are pinned but don't sum to 1.
- **`POST /api/dependencies`** `{holdings, top_n=15}`.
  - Returns 200 with the result if everything is cached, otherwise 202 `{job_id}`.
  - `job_id` is a sha256 of the top-N company keys, filing accessions, prompt versions and allocations hash. It's idempotent, so a double click doesn't double the spend.
- **`GET /api/dependencies/{job_id}`** returns `{status: queued|running|done|error, progress, companies:[status, verified, rejected, filing{form, accession, filed, url}], result}`.
  - `result` is `{edges:[VerifiedEdge], metrics:[MetricFact], insights:{status, model, suggestions[], flaws[], rejected_claims_count}, counts}`.
  - The UI polls every 1–2 s; there's no SSE.
- **Shapes:**
  - `VerifiedEdge`: `edge_id, source_company_key, edge_type, target_name, target_kind, target_key|null, sole_source, qualifier, evidence_quote, section, form, filed, filing_url`.
  - Edge types: `supplier, customer, contract_manufacturer, foundry, key_input, facility, jv_partner`.
  - `MetricFact`: `metric_id, label, value, unit, supporting_edge_ids`.
- Mock fixtures `frontend/api/__fixtures__/synthetic-{valuation,dependencies}.json` are validated by backend tests.

## Packages and owners
| Package | Owner | Paths | Notes |
|---|---|---|---|
| **C0** Contract | Gawyn's Claude | `backend/hoc/contract/`, snapshot, `frontend/api/types.ts`, `registry.tsx` entry `dependencies`, mock fixtures, `docs/hoc/CONTRACT.md`, `.env.example` | **First**; unblocks wiring and the UIs. |
| **P0** Price plumbing | Kendrick's Claude | `sources/tickerinside/` (price fields + `quote(ticker)` reading the cached fund JSON), `normalise/` passthrough | Small, before G-DOC. |
| **G-DOC** Filings | Kendrick's Claude | new `backend/hoc/filings/` | Covers:<ul><li>`normalise()`, shipped first because G-AI imports it</li><li>finding the 10-K/20-F (submissions JSON)</li><li>canonical text + sha256</li><li>section offsets (10-K Items 1/1A/2 plus concentration paragraphs; 20-F Items 3.D/4/5), fallback chunks</li><li>reverse links via EDGAR full-text search (≤10 hits per company)</li><li>exact name → `company_key` resolution</li></ul>Sends sections only, never ASML's full 20-F. |
| **G-AI** Gemini + extractor | Kendrick's Gemini | new `backend/hoc/ai/` | Covers:<ul><li>`GeminiClient` over REST (Interactions, `store:false`) + a deterministic `FakeGeminiClient` that also emits mutated quotes</li><li>one extraction call per company (sections packed, ≤160K chars)</li><li>the verifier; a cap of 3–4 concurrent calls</li><li>per-company result cache keyed by (company_key, accession, model, prompt_version)</li><li>partial failures don't sink the run</li></ul> |
| **G-ORCH** Metrics + orchestrator | Gawyn's Gemini | `backend/hoc/graph/metrics.py`, `backend/hoc/graph/orchestrator.py` | Covers:<ul><li>deterministic metrics, unioned by (dependent company, target) so nothing is double-counted</li><li>supplier dependency %, facility-country concentration, shared single points of failure</li><li>orchestrator with placeholders, numeric allow-list and name lock, cached by (allocations hash, verified edge ids, prompt version)</li><li>metric-only insights when there's no key or no edges</li></ul> |
| **S-API** Valuation | Yousuf's Codex | `backend/hoc/portfolio/valuation.py` + tests | Pure maths per the rules above; full precision, rounded only for display. |
| **S-UI** Shares adder | Yousuf's Claude | `frontend/app/analysis.tsx`, `pages/portfolio/`, `frontend/api/client.ts`, `vite.config.ts` | Covers:<ul><li>`DraftRow += {shares, pinned}` and an "Enter as: Shares \| %" toggle</li><li>`setRows(AllocationInput[])` loads % rows and shows a one-line notice</li><li>valuation called without the debounce, with abort-on-change</li><li>exports `analysedKey`</li><li>client calls + proxy for valuation **and** dependencies</li></ul> |
| **G-UI** Dependencies page | Yousuf's Gemini | `frontend/app/pages/dependencies/`, `frontend/app/dependencies-state.tsx` (`DependenciesProvider`) | Covers:<ul><li>the run state outlives tab switches; stale when `depsKey !== analysedKey`</li><li>bipartite SVG graph, facility-by-country chart (Recharts or SVG)</li><li>coverage/verification audit bar, evidence drawer (quote, form, date, link), insights panel with clickable citations</li><li>missing-key and stale banners</li></ul> |
| **I-API** Integration | Bekarys's Claude | `service.py`, `api/app.py`, `core/` | Covers:<ul><li>routes and job table, with its own 3–4-worker executor</li><li>cost cap per job; Gemini host rules in `core/http` (key in header, no caching of non-2xx, 900 s timeout, spacing, Retry-After backoff)</li><li>startup replay of cached dependency results (cache only, never spends credit)</li><li>a test that the key never reaches disk or logs; an injectable synchronous executor for tests</li></ul> |
| **I-UI** Integration + E2E | Bekarys's Gemini | read-only E2E; fixes go to the owners | Three test tiers: (A) cached replay with no key; (B) `FakeGeminiClient` with mutated quotes and an invented number, so the rejected counts show; (C) mock mode. Plus the shares + pinned checklist and a final UI audit. |

## Order
1. **Now, in parallel:**
   - C0 (lead);
   - P0, then `filings.text.normalise`, then the rest of G-DOC;
   - G-AI, G-ORCH and S-API internals against synthetic data;
   - the I-API `core/http` Gemini rules;
   - S-UI and G-UI on mocks once C0 lands.
2. **After C0 + S-API + P0:** I-API wires valuation, and S-UI switches to the real endpoint.
3. **After G-DOC + G-AI + G-ORCH:** I-API wires the dependency jobs, and G-UI switches to real data. I-UI runs tiers A–C.
4. **Lead:** end-to-end verification with the real key on the example portfolio, then README/DEMO updates.

## Done when
- Shares mode works on real prices, with pinned rescaling and every blocked state shown.
- The top-15 dependency run completes cold and replays from cache with no key.
- Every edge shown carries a verified quote and a filing link, and the rejected counts are visible.
- Insights cite only real metric and edge ids.
- No 500s, offline tests pass, and `npm run build` passes.
