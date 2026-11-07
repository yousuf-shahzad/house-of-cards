# House of Cards contract (frozen)

The single source of truth for everything that crosses a package boundary. Code:
`backend/hoc/contract/` (Pydantic), `backend/hoc/sources/base.py` (adapter protocols),
`frontend/api/types.ts` (TypeScript mirror), `backend/tests/snapshots/openapi.json` (HTTP shape).
**Changes go through the lead (Gawyn's Claude) in one PR that updates all four.** Post the request on the board.

## 1. Units and numbers

- **Every weight is a fraction of 1** (`0.05` = 5%), a `float`. Adapters convert percent at the boundary;
  only `frontend/api/client.ts` converts the user's percent input. Nothing else ever sees percent.
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
