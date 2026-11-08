# House of Cards — Version History & Detailed Architecture (v1–v3.1)

This document preserves the complete version history, mechanism details, and evaluation benchmark notes moved from the top-level `README.md` (`FIX-70`).

---

## 1. Version Evolution (v1 → v3.1)

- **Version 1 (Look-through & Overlap):** Enter ETF tickers and portfolio allocations. House of Cards fetches each fund's real, published holdings (`TickerInside`, `iShares` CSV, `SEC N-PORT`), normalises weights as fractions of `1` (without rescaling), merges share classes and cross-listings via `CIK`/`LEI`/`ISIN` and curated aliases, and computes effective company exposure, pairwise weighted ETF overlap, concentration (`top5`, `top10`, `top20`, `HHI`, `effective_n`), sector breakdowns, and coverage gaps.
- **Version 2 (Shares Valuation & SEC Filing Dependencies):**
  - **Shares input (`S-API` / `S-UI`):** Enter share counts (fractions allowed); each ETF is valued at its latest exchange close (`TickerInside`, not NAV) to compute allocations. Typing a `%` on a row pins it and rescales the remaining rows by value.
  - **Find dependencies (`G-DOC` / `G-AI` / `G-ORCH`):** Fetches the latest SEC `10-K` or `20-F` for the top `N` (default `15`) companies, extracts supplier/foundry/customer/facility relationships with Gemini Flash sub-agents, verifies every quote word for word in Python (`verify_quote`), resolves counterparty identities deterministically, computes graph metrics, and generates a placeholder-only Gemini Argon synthesis (`{{metric:id}}`).
- **Version 3 (Verification, Research Loop, Scenario Comparison & Gold Benchmark):**
  - **Compare / Try a change (`X-API` / `X-UI`):** Synchronous, cache-only before/after portfolio comparison (`POST /api/compare`) plus automatic rules and Argon AI **Change ideas** (`POST /api/change-ideas`, verified in Python).
  - **Failure simulator (`FIX-63`, `POST /api/stress`):** Simulates a single industry, country, or supplier failure before and after a portfolio change using 5-year worst 21-trading-day historical ETF drops (`XLK`, `XLF`, `XLV`, `EWT`, `SPY`, etc. from Yahoo Finance daily adjusted closes) or a simulated `20%` fall (`DEFAULT_SHOCK_DROP = 0.20`).
  - **Relationship importance (`R-IMP`):** Deterministic scoring in `[0, 1]` and tiering (`critical >= 0.8`, `high >= 0.6`, `medium >= 0.4`, `low < 0.4`) from edge type, customer revenue share (`>= 20%` critical, `10–20%` high), facility role (production vs. HQ/office/R&D), and target-local concentration cues (`sole`, `substantially all`, `one of several`).
  - **Interpretation verification (`V-INT`):** Deterministic context rules on `±300` characters of surrounding filing text (`competitor_mention`, `negated`, `hypothetical`, `direction_mismatch`, `generic_reference`, `subject_mismatch`) plus an independent `gemini-3.8-flash` judge (`hoc-v3-judge-1`) on rules-flagged edges and a deterministic `20%` sample of unflagged edges. Contradicted or competitor edges are rejected (`interpretation_rejected`); uncertain edges remain `flagged` and are capped at `medium` importance.
  - **Honest coverage reporting (`C-COV`):** Partitions `100%` of portfolio weight into five mutually exclusive buckets (`verified`, `no_disclosures`, `no_sec_filing`, `not_analysed`, `outside_top_n`), reports per-ETF verified shares (`by_etf`), lists the top 10 unanalysed holdings outside the cutoff, and emits plain-English `CoverageGap`s (`outside_top_n`, `unnamed_customers`, `non_sec_counterparties`, `old_filings`, `region_only_facilities`).
  - **Agentic research loop (`A-RES`):** Bounded multi-step tool loop (`search_filings`, `read_section`, `find_in_filing`, `conclude`) running both per-company during the dependency job (`light` depth, up to 2 items / 2 tool calls per company) and on demand via **Go deeper** (`thorough` depth, up to 6 items / 4 steps per item). Every candidate edge passes through `verify_quote`, `V-INT`, and `R-IMP`.
  - **Simple vs. Full views (`v3.1`):** Plain-English Simple view walkthrough (`#/portfolio`, `#/exposures`, `#/overlap`, `#/risk`, `#/dependencies`, `#/compare`) and 5-step guided flow (`#/guide`), switchable anytime with the top-bar **Simple | Full** toggle.

---

## 2. Detailed Pipeline Mechanics

### Look-Through & Portfolio Maths

```text
 ETF ticker ──> source adapters ──> normalisation ──> identity resolution ──> portfolio maths ──> API ──> UI
               TickerInside        weights as         same company across     exposure, overlap,   FastAPI  React
               iShares CSV         fractions, cash    ETFs (CIK, LEI,         concentration,
               SEC N-PORT          and derivatives    ISIN, curated           sectors, coverage,
               (first that works)  excluded           aliases)                data gaps
```

- **Effective exposure** to company $c$ = $\sum_{\text{ETF}} (\text{allocation} \times \text{weight}_{c,\text{ETF}})$. It is never rescaled, so data the sources cannot cover remains visible as a gap.
- **Coverage** splits the portfolio into `covered`, `excluded` (cash and derivatives), `missing` (ETFs that failed to load), and `unexplained`. The four always add up to `100%`.
- **Weighted overlap** between two ETFs = $\sum_{c \in A \cap B} \min(w_{c,A}, w_{c,B})$.
- **Concentration**: the sum of the top 5, 10, and 20 exposures, and the Herfindahl-Hirschman Index (`HHI`) with its effective number of equal-sized companies ($1 / \text{HHI}$).

### Dependencies & Verification Pipeline

```text
 company --> SEC 10-K / 20-F --> Gemini Flash --> Python checks --> V-INT + R-IMP --> Python metrics --> Gemini Argon --> Python checks
             newest from EDGAR,   one sub-agent    verbatim quote   context rules +   dependency %,      synthesis of     {{metric:id}}
             sections 1/1A/2 or   per company +    check & exact    Flash judge +     critical.*,        flaws & ideas    placeholders
             3/4/5 + reverse      light research   name resolution  importance tier   coverage buckets                    verified
```

- **No hallucinated facts:** An edge survives only if its quote appears word for word in the filing text (after normalising whitespace, quotes, and dashes). Rejected edges are counted on the page, never drawn.
- **Deterministic entity resolution:** Counterparty names resolve by exact word-boundary match against the portfolio, the 48 curated aliases, and SEC company titles (`TSMC` and `Taiwan Semiconductor Manufacturing Company Limited` resolve to `ISIN:TW0002330008`). Anything else stays an unresolved `NAME:<slug>`.
- **Target-local qualifier grounding (`FIX-34`):** `sole_source` and concentration qualifiers are grounded in the clause mentioning the specific target (or within `±80` characters for single-clause quotes) so multi-entity sentences never transfer another clause's *"sole"* wording.
- **Python owns every number:** The synthesis may only write `{{metric:id}}` placeholders, which Python renders. Any claim with an unverified number, unknown metric ID, or unverified company name is dropped.

---

## 3. Gold Extraction & Verification Benchmark (`E-GOLD` / `E-RUN`)

House of Cards includes an adjudicated benchmark of **10 held-out SEC 10-K filings** outside the default demo top-15 (`NKE`, `F`, `GM`, `BA`, `SWKS`, `QRVO`, `GLW`, `PFE`, `DE`, `SBUX`) in [`backend/tests/eval/gold/`](../../backend/tests/eval/gold/) (documented in [`docs/hoc/eval/ADJUDICATION.md`](eval/ADJUDICATION.md)):
- **115 core** relationships (`81` agreed by both independent annotators, `26` Annotator A, `8` Annotator B; **inter-annotator F1 = 0.49**)
- **107 extended** relationships (`97` blind + `10` pooled; **222 total**)
- **79 hard negatives** (competitor lists, negated claims, hypotheticals, generic groups)

### Commands

```bash
# Offline replay (default: deterministic verifier + V-INT + R-IMP against recorded predictions; zero API calls)
cd backend && uv run hoc eval

# Live (runs Gemini extractor + V-INT Flash judge + per-company light research agents on the 10 held-out 10-Ks)
cd backend && uv run hoc eval --live
cd backend && uv run hoc eval --check-agentic recorded
```

### Results Summary ([`docs/hoc/EVAL.md`](EVAL.md))

- **Micro precision:** **88.4% [83.2%, 92.5%]** blind (`114/129`; **Micro F1 = 69.6% [51.9%, 82.7%]**) and **96.1% [89.6%, 100.0%]** after blind pooled adjudication (`124/129`; **Micro F1 = 71.9% [53.3%, 85.1%]**, with 10 of 15 unmatched predictions confirmed verbatim in the filings as extended relationships).
- **Core recall (`tier='core'`, blind denominator):** **57.4% [35.3%, 76.0%]** (`66/115` core relationships; misses are mainly multi-site facility countries, `23/49`, and Pfizer co-development alliances, `18/49`).
- **Hard-negative false-positive rate:** **1.3% [0.0%, 3.9%]** (**`1/79`** across 27 competitor, 11 negated, 9 hypothetical, 7 unrelated, and 25 generic passages).
- **Direction accuracy:** **100.0% [100.0%, 100.0%]** (`124/124`).
- **Facility-country accuracy:** **100.0% [100.0%, 100.0%]** (`39/39`).
- **Importance-tier agreement:** quadratic weighted Cohen's $\kappa = \mathbf{0.475\ [0.382,\ 0.631]}$ (`54/79`).
- **Honest V-INT & light-agent note (`FIX-8`):** On the 10 held-out filings, the extractor + verbatim quote check already rejected `78/79` hard negatives so **V-INT filtered 0 edges on the held-out set** (`129 -> 129`), and the per-company `light` research agents double-checked **18/18** open findings with **2+ tool calls** (`avg = 2.00`, `0` circular confirmations, `0` duplicate/group unnamed-customer links) while adding `+0` and rejecting `-0` edges on the held-out set — leaving held-out precision (**88.4%** blind / **96.1%** pooled) and core recall (**57.4%**) unchanged (`+0.0 pp`). On the live `us-core-tilt` portfolio run, V-INT rejected **1** misread divestiture (`AMD -> Sanmina`, *"we sold the ZT Manufacturing Business to Sanmina"*) and flagged **1** tentative overclaim (`Nvidia -> OpenAI`).
