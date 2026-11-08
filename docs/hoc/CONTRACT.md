# House of Cards contract (frozen)

The single source of truth for everything that crosses a package boundary. Code:
`backend/hoc/contract/` (Pydantic), `backend/hoc/sources/base.py` (adapter protocols),
`frontend/api/types.ts` (TypeScript mirror), `backend/tests/snapshots/openapi.json` (HTTP shape).
**Changes go through the lead (Gawyn's Claude) in one PR that updates all four.** Post the request on the board.

## 1. Units and numbers

- **Every weight is a fraction of 1** (`0.05` = 5%), a `float`. Adapters convert percent at the boundary;
  only `frontend/api/client.ts` converts the user's percent input. Nothing else ever sees percent.
- Weights must be **finite**: the `Weight` type rejects NaN and infinity at construction. An adapter that hits
  malformed upstream data should raise `SourceParseError`; as a safety net, the registry records any
  validation/parse exception from an adapter as a `parse_error` attempt, so bad data never becomes a 500.
- Add weights with `hoc.contract.wsum` (`math.fsum`: exactly rounded, order independent).
- Every sort has an explicit tie-break (usually the key ascending), so output is deterministic.
- JSON weights are rounded to 10 decimal places on serialisation.
- Money is never needed: we work in weights. `market_value_usd` is carried for display only.

## 2. Pipeline and data models

```
SourceAdapter.fetch(ticker)          -> RawEtfHoldings      (one source's file, as reported)   packages a, b, c
SourceRegistry.fetch_with_fallback   -> FetchResult          (first success wins, all attempts kept)  lead
normalise_etf(raw, reference, aliases) -> EtfHoldings        (identity resolved, cash excluded)  package d
analyse(request, loaded, failures, today=, generated_at=) -> AnalysisResponse   (pure maths)   package e
EtfService / FastAPI routes          -> HTTP                                                    package f
```

Fallback order (env `HOC_SOURCE_ORDER`): `tickerinside, ishares, sec_nport`. A source that is not yet
implemented declines in `supports()`, so the registry falls through.

**Lines excluded from look-through**: asset classes `cash`, `derivative`, `fx`. They count in
`excluded_weight`, never in exposure. Everything else (equity, preferred, fund, fixed income, other) is kept.

## 3. Identity

**`security_key`** (listing level; drives "shared securities"), first match wins:

1. `SYM:{symbol}` in the TickerInside convention: US symbols with a class dot (`BRK.B`), elsewhere
   `{local}.{ISO2 of the listing country}` (`2330.TW`, `005930.KR`, `700.HK`). iShares rows combine
   ticker + exchange; N-PORT rows get a symbol from OpenFIGI (ISIN -> ticker + exchange) when possible.
2. `ISIN:{isin}` 3. `CUSIP:{cusip}` 4. `NAME:{upper-cased normalised name}`

Display `security_id`: ISIN, else FIGI, else CUSIP, else symbol, else name.

**`company_key`** (drives exposures), first match wins:

| Key | Basis | `identity_status` | Merges |
|---|---|---|---|
| `ALIAS:{id}` | curated `identity/aliases.json` (<= 50 entries, each with a source note) | resolved | ADR <-> local line (TSM / 2330.TW), Samsung common / preferred |
| `CIK:{10 digits}` | line or TickerInside `identifiers.json` | resolved | GOOG/GOOGL, BRK.A/B, FOX/FOXA |
| `LEI:{lei}` | N-PORT lines | resolved | share classes in N-PORT |
| `ISSUER:{isin[:8]}` | US/CA ISINs only (CUSIP issuer prefix) | resolved | US/CA share classes |
| `SYM:{symbol}` | no company identifier found | partial | nothing |
| `NAME:{name}` | name only | unmatched | nothing |

FIGI is never a company key (it is per security). **Unmatched lines are never dropped**: each is its own
company, counts towards coverage and `unmatched_weight`, and raises a gap if significant. Share classes stay
separate `NormalisedHolding`s and are merged only when computing company exposure.

## 4. Definitions (package e implements exactly these)

Notation: `A_e` = allocation of ETF e (fraction of portfolio); `w_{e,s}` = weight of security s in ETF e
(fraction of the ETF's NAV); `w_{e,c} = Σ_{s∈c} w_{e,s}`.

- **Validation**: total of allocations must be `1 ± 1e-4` (`ALLOCATION_SUM_INVALID`, details `{total, tolerance}`);
  no duplicate tickers, case-insensitive (`DUPLICATE_TICKER`); at most 10 ETFs (`TOO_MANY_ETFS`).
  A 0% allocation is allowed and produces a notice.
- **Exposure**: `contribution_{e,c} = A_e · w_{e,c}`; `E_c = Σ_e contribution_{e,c}`. **Never renormalised**:
  exposures are fractions of the investor's whole portfolio, so data gaps stay visible.
  `Σ_c E_c (+ other_exposure) = coverage.covered_weight`.
- **Coverage** (per ETF and total):
  `covered = Σ A_e · holdings_weight_e`; `excluded = Σ A_e · excluded_weight_e`;
  `missing = Σ A_e` over ETFs that failed to load; `unexplained = total − covered − excluded − missing`.
  The four always add up to `total_allocation`.
- **Weighted overlap** (pair i, j): `O_ij = Σ_c min(max(w_ic, 0), max(w_jc, 0))` at company level
  (`weighted_overlap`), and the same at security level (`weighted_overlap_securities`). Not renormalised after
  removing cash. Matrix diagonal = `holdings_weight_i`. Computed for every loaded ETF (even at 0% allocation).
  `shared_securities` / `shared_companies` count keys with positive weight in both. `top_shared`: up to 10 by
  `min_weight` desc, then key.
- **Concentration**: `topN = Σ` of the N largest `E_c` (fraction of the whole portfolio).
  `hhi = Σ p_c²` with `p_c = E_c⁺ / Σ E⁺`; `effective_companies = 1 / hhi` (0 if no exposure).
  `distinct_securities` / `distinct_companies` count keys with exposure > 0 (securities >= companies).
- **Sectors**: per ETF, basis `holdings` if lines with a known sector are >= 95% of `holdings_weight`;
  else `fund_reported` (the fund's own breakdown, scaled down to `holdings_weight` if larger, remainder to
  `unknown`); else `none` (everything `unknown`). Portfolio `S_k = Σ_e A_e · s_{e,k}`; `Σ_k S_k = covered`.
- **Missing ETF**: in `missing_allocation`, status `unavailable`, a `critical` `missing_etf` gap. Nothing is
  renormalised. If any requested ticker is not found by any source, the API returns `UNKNOWN_TICKER`.
- **Gaps**: `unmatched_identity` / `nested_fund` listed one by one when >= 0.05% of the portfolio, smaller ones
  aggregated per ETF; `stale_disclosure` info > 35 days, warning > 100 days; `low_coverage` warning when covered
  < 95% of total; `excluded_lines` info per ETF; `no_sector_data` when an ETF's sector basis is `none`.
- **ETF status**: `unavailable` if it failed to load; `warning` if it has a warning/critical gap; else `ok`.

## 5. HTTP API

| Method and path | Body / query | Response |
|---|---|---|
| `GET /api/health` | | `HealthResponse` |
| `GET /api/etfs/{ticker}` | `?holdings=true` to include lines, `?source=` to force one source | `EtfSummary`, 404 `ETF_NOT_FOUND`, 503 |
| `POST /api/analysis` | `PortfolioRequest` `{"holdings":[{"ticker":"IVV","allocation":0.4}, ...]}` | `AnalysisResponse` |
| `GET /api/examples` | | `ExamplesResponse` (each example `verified` only if all its ETFs loaded) |

Errors always have one shape: `{"error": {"code", "message", "details"}}`.

| Code | HTTP | When |
|---|---|---|
| `VALIDATION_ERROR` | 422 | body or path does not match the schema (`details.errors`) |
| `ALLOCATION_SUM_INVALID` | 422 | total != 100% within tolerance |
| `DUPLICATE_TICKER` | 422 | a ticker appears twice |
| `TOO_MANY_ETFS` | 422 | more than 10 ETFs |
| `UNKNOWN_TICKER` | 422 | a requested ETF was not found by any source (`details.tickers`, `attempts`) |
| `ETF_NOT_FOUND` | 404 | `GET /api/etfs/{ticker}` for an unknown ETF |
| `SOURCES_UNAVAILABLE` | 503 | nothing could be loaded (network down, offline with empty cache) |

Some ETFs failing for availability reasons is **not** an error: 200 with those ETFs `unavailable` and their
allocation in `coverage.missing_allocation`.

Dev: the Vite dev server proxies `/api` to `http://127.0.0.1:8000`; CORS allows `HOC_CORS_ORIGINS`.

## 6. Data rules

- No financial data is hardcoded or committed. `examples.py` holds tickers and allocations only.
- Real files are fetched at runtime and cached in `backend/.cache/` (gitignored). TTLs: TickerInside fund and
  reference files 24 h (they ask for at most one fetch per nightly build); iShares CSV 24 h; SEC submissions 24 h;
  N-PORT filings never expire (immutable). `HOC_OFFLINE=1` serves only from the cache.
- Synthetic data only in `backend/tests/fixtures/synthetic/` and `frontend/api/__fixtures__/`, labelled, with
  `ZZ` tickers and `999` CIKs. The UI shows a SYNTHETIC banner whenever it displays `source: "fake"` data.
- Attribution: TickerInside is CC BY 4.0, so its `cite_as` text is carried in `attribution` and shown in the UI.
  SEC data is public domain (send a User-Agent with contact details). Issuer files (iShares) must not be
  republished.

## 7. v2 additions (PLAN-v2, C0)

Models: `backend/hoc/contract/valuation.py`, `backend/hoc/contract/dependencies.py`, `PriceQuote` in `raw.py`;
TypeScript mirror at the end of `frontend/api/types.ts`; mocks `frontend/api/__fixtures__/synthetic-{valuation,dependencies}.json`.
Routes are wired by I-API (Bekarys's Claude); the OpenAPI snapshot updates with them.

- **Prices.** `PriceQuote {price > 0 finite, currency (ISO 4217), as_of (trading date), kind close|nav, source, attribution}`,
  optional on `RawEtfHoldings`, `EtfHoldings` (passed through) and `EtfSummary`. TickerInside `last_close` is an exchange
  close, not NAV. Bad price data → `price: null` plus a warning, never an invalid ETF.
- **`POST /api/valuation`** `ValuationRequest {rows: [{ticker, shares?, allocation_override?}]}` → `ValuationResponse`.
  Pinned rows have `allocation_override` (fraction). With pinned total P and unpinned values Vᵢ = sharesᵢ × priceᵢ:
  allocationᵢ = (1 − P)·Vᵢ / ΣV. Blocking issues: `pinned_over_100`, `nothing_to_rescale` (P < 1 and ΣV = 0),
  `allocation_sum_invalid` (all pinned, not 1), `no_price` / `invalid_price` / `non_usd_price` / `price_unavailable` /
  `missing_shares` on an unpinned row (pin it to a %), `duplicate_ticker`, `too_many_etfs`. Warning: `stale_price`
  (price date more than `PRICE_STALE_DAYS` = 4 calendar days before `as_of_date`). `status: usable` ⇒ allocations total 1
  and go to `/api/analysis` unchanged.
- **`POST /api/dependencies`** `DependencyRequest {holdings, top_n=15 (1..30)}` → `DependencyJob` (HTTP 200 if done from
  cache, 202 otherwise). **`GET /api/dependencies/{job_id}`** → `DependencyJob`; unknown id → 404 `JOB_NOT_FOUND`.
  `job_id` = sha256(top-N company keys + allocations + prompt_version + top_n) → idempotent (filing accessions are only known
  once the job runs; per-company extraction caches key on accession, so a new filing still re-extracts).
- **Pipeline seams** (called by `hoc/jobs.py`, I-API): `filing(company) -> FilingRef` (G-DOC), `extract(company, filing, *,
  cache_only) -> Extraction` (G-AI), `insights(analysis, edges, *, cache_only) -> (metrics, Insights)` (G-ORCH), plus each
  module's `prompt_version`. A company that can't be analysed raises `hoc.contract.CompanyUnavailable(status, message)`
  (status: `no_sec_filing | unsupported_form | sec_contact_missing | missing_api_key | error`); insights never raises
  for those, it returns the matching `Insights.status`.
- **Statuses are enums.** Company: `queued fetching extracting cached done no_sec_filing unsupported_form
  sec_contact_missing missing_api_key error` (+ `extraction_quality sections|fallback`). Insights:
  `ok metrics_only missing_api_key no_verified_edges error`. Missing key/contact is a status, never a 500.
- **Edges** (`VerifiedEdge`) exist only if `normalise(evidence_quote)` (one `...` splice allowed, halves ≥ 25 chars,
  in order within 300 chars) is found in `normalise(html_to_text(filing))` (`hoc.filings.text`). `target_key` comes
  only from deterministic name resolution, else null. Types: `supplier customer contract_manufacturer foundry key_input
  facility jv_partner`; target kinds: `company country region material component facility unnamed_customer`.
- **Metrics** (`MetricFact`) are Python's (unit `fraction|count|ratio|days`); supplier dependency is unioned per
  (dependent company, target) so a company is never counted twice. **Insights** cite `metric_id`s/`edge_id`s; any number
  in `text` must come from a cited metric, and names must be in the portfolio or verified edges, else the claim is dropped
  (`rejected_claims_count`).
- **Settings** (env): `GEMINI_API_KEY` (secret; never in URLs, cache or logs; `repr=False`),
  `HOC_GEMINI_EXTRACTOR_MODEL` (default `gemini-3.8-flash`), `HOC_GEMINI_ORCHESTRATOR_MODEL` (default `gemini-4-argon`),
  `HOC_DEPS_TOP_N` (default 15). Fetching filings needs `HOC_SEC_CONTACT`.

## 8. v3 additions (PLAN-v3, C0-v3)

Models: `hoc/contract/dependencies.py` (edge, coverage and research models) and `hoc/contract/compare.py`. Mirrored in `frontend/api/types.ts`. Fixtures:
- `synthetic-dependencies.json` (now with importance, interpretation, coverage and `critical.*`);
- `synthetic-research.json`;
- `synthetic-compare.json`.

`tests/test_contract_v3.py` checks the invariants below.

- **`VerifiedEdge.importance`** (`EdgeImportance{score 0..1, tier, reasons}`, R-IMP):
  - computed in Python only;
  - tier is critical when score ≥ 0.8, high ≥ 0.6, medium ≥ 0.4, otherwise low;
  - a `flagged` interpretation caps the tier at medium;
  - `reasons` quote any cue words from the verified evidence.
- **`VerifiedEdge.interpretation`** (`EdgeInterpretation{status, method, flags, reason, model}`, V-INT):
  - `rejected` edges never appear in `DependencyResult.edges`; they are counted in `DependencyCounts.interpretation_rejected`;
  - `flagged` edges stay, with their flags.
  - The judge sees only the quote, its context and the claimed relationship, never the extractor's output.
- **`critical.<key>`** (with a `.companies` twin): exposure that depends on `<key>` through critical- or high-tier edges. It always has a `dep.<key>` twin.
- **`DependencyResult.coverage`** (`CoverageReport`, C-COV):
  - the `buckets` (verified, no_disclosures, no_sec_filing, not_analysed, outside_top_n) are portfolio-weight fractions that sum to 1 within ±1e-6;
  - `by_etf` gives each ETF's verified share;
  - `largest_unanalysed` lists at most 10 companies;
  - `gaps` are plain-English messages whose numbers are rendered by Python.
- **Research** (A-RES):
  - `POST /api/dependencies/{job_id}/research` (`ResearchRequest{max_items 1..10 = 6}`) → `ResearchJob`, with HTTP 202, or 200 if cached;
  - poll `GET /api/research/{research_id}`; an unknown id gives 404 `RESEARCH_NOT_FOUND` (`ResearchNotFoundError`).
  - Each `ResearchFinding` has `steps` numbered 1..n and ending in `conclude`.
  - Every edge in `new_edges` passed `verify_quote` and V-INT, and appears in `ResearchJob.result.edges`. No `rejected_edge_ids` remain in the result.
  - `explanation` contains digits only inside quotes of verified evidence.
- **Compare** (X-API):
  - `POST /api/compare` (`CompareRequest{baseline, candidate, top_n}`) → `CompareResponse`.
  - It is synchronous and cache-only: no Gemini calls and no filing fetches.
  - `delta = candidate − baseline` when both exist, otherwise null.
  - `dependency_deltas` list fraction metrics first, then count metrics. Within each unit they are sorted by absolute delta, largest first; a metric on only one side sorts by its value, and ties go by `metric_id`.
  - `status` is `partial` exactly when `candidate_unanalysed` is non-empty.

## 9. v3.1 additions (PLAN-v3.1, C0-v3.1)

All additive with defaults, so v3 payloads stay valid.

- **`DependencyRequest.depth`** (`"light"` default, or `"thorough"`): how far each company's agent investigates its own uncertain findings. It is part of the job id, so a thorough run is a separate job that reuses cached extractions and light findings.
- **`DependencyJob` progress fields:**
  - `phase`: queued → reading (fetch + extract) → researching (the agentic loop) → synthesising (metrics + insights) → done;
  - `steps_done` / `steps_total`: progress across all phases, with `0 <= steps_done <= steps_total`.
  - `CompanyStatus` gains `"researching"`.
  - `research` (FIX-11): the findings of each company's agent, added as soon as that agent finishes, so a page can show them while the job runs. Once the job is done, `result.research` is the merged list to use.
- **`DependencyResult` research fields:**
  - `research: list[ResearchFinding]` holds the findings from the run's own agentic loop. Every finding obeys the §8 research rules: steps numbered 1..n ending in `conclude`, `new_edges` verified and present in `edges`, and no `rejected_edge_ids` left in the result.
  - `research_depth` is `"none"`, `"light"` or `"thorough"`.
- **`InsightClaim` beginner fields:**
  - `plain_title` (≤ 8 words);
  - `plain_text` (≤ 25 words, at most 1 number, and only via a cited `{{metric:id}}` placeholder, rendered like `text`).

  The orchestrator verifies both with the same rules as `text`. A field that fails is set to null, and the claim itself is kept.
- **`ConcentrationName`** gains `"top_sector"`: the largest industry's share of the portfolio.

## 10. Concrete ETF change ideas (FIX-17)

`POST /api/change-ideas` takes `ChangeIdeasRequest{holdings, top_n=15}` and returns
`ChangeIdeasResponse{status, ideas, notes, ai_status, model, prompt_version, rejected_proposals}`.
Models live in `hoc/contract/ideas.py`, mirrored in
`frontend/api/types.ts`; `synthetic-change-ideas.json` is a labelled, invented fixture.

- The fixed shortlist is RSP, IWD, IEFA, IWM, XLV, XLP and XLU. Already-held ETFs are skipped.
  Each available fund is tested at `add_fraction` 0.1 and 0.2. Existing allocations are scaled
  proportionally to the remainder; `holdings` is the complete scenario. Whole-share rounding in
  the UI can change the result and must be compared again.
- ETF holdings load through existing sources. Dependency measurement uses one shared verified extraction
  cache snapshot and the union of both top-N company sets, with no filing fetches or dependency jobs.
  Absent metrics remain null. AI proposes changes separately; Python verifies every shown number.
- Rank improvements to the largest known industry when its portfolio share is at least 40%, matching
  `diversificationVerdict`; otherwise the largest cached `dep.*` fraction;
  otherwise top-ten concentration, with effective company count as tie-break/fallback.
  Industry ranking requires usable sector data on both sides. Unknown dependencies never imply improvement.
- Return at most three distinct ETFs, taking the best tested fraction for each. Non-improving,
  unavailable and funds with less than 95% company holdings are omitted. Skipped source candidates
  are named in notes. No new ETF is suggested at the ten-ETF limit or with missing current ETF holdings.
- Each `ChangeIdea` contains `idea_id`, `ticker`, `etf_name`, `add_fraction`, `addresses`
  (`top_sector|dependency|top10|effective_n`), `metric_id` (`dep.<key>` for dependency, else null),
  `title` (one to eight words, no digits), `reason` (one Python-rendered sentence with before/after
  values), full `holdings`, `concentration_deltas`, and `biggest_dependency_delta` (largest absolute
  comparable `dep.*` fraction change, else null). It also preserves compare's `status`,
  `candidate_unanalysed` and `notes`; dependency results can be partial even when concentration improves.
- Response status is partial when a candidate is unavailable, current holdings are missing,
  or a returned idea has unknown dependencies. Results share in-flight work and are memoised per
  holdings/top-N key for one minute. The HTTP call waits at most nine seconds; if loading takes
  longer it returns partial, empty ideas and skipped-candidate notes, and a retry reuses that work.
  Errors for invalid portfolios/unknown current tickers/unavailable current sources match analysis (422/503).

  When `addresses` is `dependency`, `biggest_dependency_delta` is the addressed baseline dependency
  (`metric_id`), so the card's label and numbers agree; for other issues it is the largest comparable change.

### AI proposals and rules fallback (lead-approved additive extension)

- `proposed_by` defaults to `rules`; `action` defaults to `add`; `swap_from` and `rationale` default
  to null. Existing clients and rules payloads remain valid. `add_fraction` allows 0.1, 0.2 or 0.3.
  For `add`, scale existing allocations by `1 - add_fraction`. For `swap`, move `add_fraction` of
  the whole portfolio from a held `swap_from` into `ticker`; insufficient source allocation is rejected.
  `holdings` always contains the complete candidate. A swap requires a different, nonempty source;
  an add cannot name one. The UI rounds shares then compares the actual candidate again.
- Argon proposes up to five adds/swaps from the pinned ETF universe against Python issue ids.
  Python rejects invalid tickers/fractions/sources, unsupported rationale text, no measurable gain,
  or a materially worse largest industry/top dependency. Only verified survivors can be labelled `ai`;
  `rationale` is checked text whose metric placeholders Python has rendered.
- `ai_status` defaults to `not_used`; other values are `pending`, `ok`, `missing_api_key`, `failed`,
  and `timeout`. While `pending`, return rules ideas immediately within the existing HTTP deadline;
  clients can poll about every three seconds for up to ninety seconds. Once the background proposal
  finishes, return its verified ideas, or the rules fallback if none survives. An unavailable AI key,
  failed call or timeout also returns rules ideas. `status` continues to describe data coverage.
- `model` and `prompt_version` identify the proposal attempt (nullable). `rejected_proposals` defaults
  to an empty list; each entry has `ticker`, `action`, and a machine-readable `reason`.
  Proposal caching includes holdings, Python issues, model and prompt version, with disk reuse across
  restarts. Pending work is shared rather than starting a model call on each poll.
