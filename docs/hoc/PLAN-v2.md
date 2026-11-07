# House of Cards v2: AI dependency analysis + share-based portfolio input

> **Status: DRAFT for team consultation (RFC on the board).** Lead: Gawyn's Claude. Tracking issue: #28. Reply on the board; the final plan replaces this draft.

## Context
The House of Cards PoC is complete: real ETF holdings, look-through exposure, overlap and concentration (M3, main `92a51b0`). Gawyn wants two additions:

1. **AI dependency analysis.** In-app Gemini API sub-agents read real company documents and extract dependencies between companies: suppliers, customers, physical goods and inputs, and facilities with their locations. An orchestrator Gemini then makes final suggestions to improve diversity and points out critical flaws. This is the "recursive dependency intelligence" goal, plugging in at `backend/hoc/graph/`.
2. **Share-based ETF adder.** The user enters the number of shares per ETF instead of a percentage. The percentage is still displayed, and it can be overridden by hand.

**Team for this round:**
- **Planners and builders:** Gawyn's Gemini; Kendrick's Claude and Gemini; Yousuf's Claude, Gemini and Codex.
- **Integrators:** Bekarys's Claude and Gemini help integrate but don't take part in planning.
- **Lead:** I (Gawyn's Claude) own the contract and the final integration.

Gawyn asked that the plan be fleshed out together with the six planning agents, so **Step 0 is a board consultation**. This draft is what they react to.

**Facts from the code exploration (main `92a51b0`):**
- **ETF prices already exist.** TickerInside's fund JSON already carries each ETF's price: `last_close` (e.g. IVV 738.68) with `last_close_date` and `currency`. It's fetched with the holdings at no extra cost, but no adapter or contract model reads it yet.
- **Portfolio rows aren't persisted.** They live only in React state (`frontend/app/analysis.tsx:77`, `DraftRow = {id, ticker, allocationPct}`). Pages call `setRows(AllocationInput[])` inline: exposures, risk and overlap. That signature must keep working.
- **Percent conversion:** percent becomes a fraction only in `frontend/api/client.ts:29-36`. The analysis wire format stays fractions, so `POST /api/analysis` doesn't change.
- **Company keys:** 17 of the us-core-tilt top-20 companies are `CIK:`-keyed. TSMC and Samsung are `ALIAS:`, and SK Hynix is `SYM:`. That's enough to fetch SEC 10-K/20-F filings for most of the top 15.
- **HTTP layer:** `core/http.py` is usable for Gemini and EDGAR, with four fixes:
  - send the API key in the `x-goog-api-key` header, never in the URL (URLs are written to cache metadata);
  - don't cache 4xx responses for Gemini;
  - allow a longer timeout than 30 s;
  - add per-host spacing for `generativelanguage.googleapis.com`.

  The N-PORT adapter's EDGAR URL, header and TTL pattern is the model for a new filing fetcher.
- **Shared files:** new routes touch `api/app.py`, the snapshot, `types.ts` and the Vite proxy allow-list (`frontend/vite.config.ts:9`). The new page needs a `registry.tsx` entry.

**Decisions (Gawyn):**
- Use the event's Gemini 4 Argon key, kept in a local env var only and never committed.
- A manual % override pins that row, and the other rows rescale by their share values to fill the rest of 100%.
- The AI analysis runs on click ("Find dependencies") for the top 15 company exposures, with results cached per company and filing.

## Step 0: board consultation (in progress)
1. Post this draft as an RFC to the six planning agents (`@login (Agent)` each; not Bekarys's agents, who integrate). Each gets the 1–2 questions below, plus "what's missing or risky in your area?"
2. Collect their replies, give it one round at most, and fold the answers into this plan and `docs/hoc/PLAN-v2.md` (committed).
3. Only then post the final assignments.

| Agent | Proposed package (draft) | Questions for them |
|---|---|---|
| Yousuf's Claude | **S-UI**: share-based adder in `frontend/app/pages/portfolio/` + `frontend/app/analysis.tsx` (rows hold shares, a computed % and a pinned-override flag; keep `setRows(AllocationInput[])` working for the other pages) | How should the rows model shares vs override with the least churn? How should the 100% validation behave with pinned rows? |
| Yousuf's Codex | **S-API**: read TickerInside `last_close`, `last_close_date` and `currency` through the adapter (a contract field, added by me). Deterministic valuation as `POST /api/valuation`: shares × price → value → %, then rescale the unpinned rows around the pinned ones. With tests. | Fractional shares? What happens when a price is missing or stale (e.g. a fund only on the iShares/N-PORT fallback, which has no `last_close`)? |
| Kendrick's Claude | **G-DOC**: EDGAR 10-K/20-F retrieval and section extraction (Items 1, 1A, 2), plus resolving extracted counterparty names to portfolio `company_key`s | Section-extraction reliability? What do we say for non-SEC companies (Samsung, SK Hynix)? |
| Kendrick's Gemini | **G-AI**: the Gemini client wrapper (`hoc/ai/`: key, model ids, concurrency cap, disk cache, fake client for tests) + the per-company extractor sub-agent (structured output, evidence quotes) | Model choice (Argon vs a faster sibling) for the extraction calls, structured-output schema, chunking? |
| Gawyn's Gemini | **G-ORCH**: the orchestrator Gemini (diversity suggestions + critical flaws) that cites only verified edges and backend metrics | How do we stop the orchestrator inventing numbers? (Proposal: it cites metric ids; Python checks every number.) |
| Yousuf's Gemini | **G-UI**: new Dependencies page (supplier/customer graph, facility concentration by country, evidence drawer with quote + filing link) and an Insights panel for the orchestrator's output | Graph layout without new dependencies? How to show "unverified/omitted" honestly? |
| Gawyn's Claude (me) | Contract (new frozen models + OpenAPI snapshot + `types.ts`), deterministic graph metrics (or assign), integration, end-to-end verification | — |

**Integrators.** Bekarys's agents are not consulted, but get integration packages once the plan is final:
- **Bekarys's Claude (I-API):** owns `service.py`, `api/app.py` and `core/`, where every new feature meets. It wires `POST /api/valuation` and the dependency endpoints into the service and routes. It adds the Gemini host rules to `core/http.py`: the key in a header, no caching of 4xx, a longer timeout, per-host spacing. It also extends the startup warm-up to replay cached dependency results.
- **Bekarys's Gemini (I-UI):** end-to-end integration testing across the new pages against the real backend. It wires the Dependencies and Insights views into the shared state hook with the page owners, and runs a UI audit after the merges, as last round.

## Draft architecture (to be refined by Step 0)
- **Zero hallucinated facts:**
  - The extractor gets fetched filing text and returns structured edges, each with a verbatim evidence quote, the section and the filing URL.
  - Python keeps an edge only if its normalised quote appears in that text. Rejected edges are counted and shown as "unverified" and are never used.
- **Edge types:** `supplier`, `customer`, `contract_manufacturer`, `sole_source`, `key_input` (material/component), `facility` (country/region).
- **Deterministic graph metrics (Python, not the LLM):**
  - portfolio exposure that depends on each supplier (e.g. "X% of your portfolio depends on TSMC");
  - facility concentration by country;
  - single points of failure shared across holdings.
- **Orchestrator:** its input is the analysis, the verified graph and the metrics. It outputs suggestions and flaws, each citing edge ids and metric ids. Any number it states must match a metric value, or the claim is dropped. Its output is advisory only: no trading.
- **Operation:**
  - Results are cached on disk by (company_key, filing accession, prompt version), so demos replay offline.
  - Without a key the feature shows a clear "needs GEMINI_API_KEY" state and any cached results.
- **API (draft):** `POST /api/valuation`, `POST /api/dependencies` (top-N, streamed progress or a job id), `GET /api/dependencies/{job}`.

(The detailed design, sources, verification and waves are filled in after research and Step 0.)
