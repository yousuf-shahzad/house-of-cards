# House of Cards v3: prove it, prioritise it, act on it

Lead: Gawyn's Claude. Umbrella issue: #28. Builds on v2 (`docs/hoc/PLAN-v2.md`), whose rules all still hold:
- verified quotes only;
- Python owns every number;
- deterministic name resolution;
- enum statuses;
- the key stays local.

## Goals

The judges give 25% to testing. v2 proves the code is correct; v3 must also:

1. prove that Gemini finds **real** dependencies, on data we never tuned on;
2. let users **act**, by testing an allocation change;
3. rank what **matters**;
4. check that each quote is **interpreted** correctly;
5. let the AI **investigate** what it is unsure about;
6. say plainly what we **don't** know.

## Features, owners and order

| # | Feature | Package | Owner | Wave |
|---|---|---|---|---|
| 1 | Unseen-data evaluation | E-GOLD: answer key, two blind annotators | Yousuf's Codex (A), Bekarys's Claude (B); I adjudicate | 1 |
| | | E-RUN: harness, scoring, report, `hoc eval` | Bekarys's Gemini | 1–2 |
| 2 | Before/after comparison | X-API: `POST /api/compare` (cache-only, deterministic) | Yousuf's Codex | 2 |
| | | X-UI: Compare page (scenario editor + deltas) | Yousuf's Claude | 1–2 |
| 4 | Relationship importance | R-IMP: deterministic score/tier per edge + `critical.*` metrics | Gawyn's Gemini | 1 |
| 5 | Interpretation verification | V-INT: rules layer + independent model judge | Kendrick's Gemini | 1 |
| 6 | Agentic research loop | A-RES: bounded investigate loop over SEC tools | Kendrick's Claude | 1–2 |
| 7 | Coverage reporting | C-COV: CoverageReport in Python | Gawyn's Gemini | 1 |
| all | Pipeline/API wiring | I-API: jobs, routes, research job, compare route | Bekarys's Claude (after E-GOLD) | 2 |
| all | Dependencies page | G-UI: coverage bar, importance, interpretation badges, investigations | Yousuf's Gemini | 2 |
| all | Contract C0-v3, plan, gold adjudication, verification | lead | Gawyn's Claude | 0, then throughout |

**Order of work:**
- **Wave 0 (lead):** this plan, then contract C0-v3 (`hoc/contract`, `types.ts`, fixtures, snapshot, CONTRACT.md §8).
- **Wave 1:** everything that needs no other package.
- **Wave 2:** wiring and UI on top.
- **Last:** a live run with eval numbers in the README, then the I-UI audit (Bekarys's Gemini).

Until C0-v3 merges, code against the field names below; they will not change.

## 1. Unseen-data evaluation (E-GOLD, E-RUN)

**Held-out set.** Ten 10-K filers that the pipeline has never processed. None is in either example's top 30, in the extraction cache, or among the reverse-link filers:

| Ticker | Company | CIK |
|---|---|---|
| NKE | Nike | 0000320187 |
| F | Ford Motor | 0000037996 |
| GM | General Motors | 0001467858 |
| BA | Boeing | 0000012927 |
| SWKS | Skyworks Solutions | 0000004127 |
| QRVO | Qorvo | 0001604778 |
| GLW | Corning | 0000024741 |
| PFE | Pfizer | 0000078003 |
| DE | Deere & Company | 0000315189 |
| SBUX | Starbucks | 0000829224 |

The extractor prompt, rules and thresholds must not be tuned on these filings. E-RUN reports the git commit and prompt versions it ran with.

**Annotation (blind).**
- Each annotator reads the latest 10-K of each company, Items 1, 1A and 2 plus the concentration notes. They use sec.gov or `FilingFetcher`.
- Annotators never run the app's extractor on these companies and never look at Gemini output for them.
- Annotator A labels all ten companies and Annotator B labels all ten, independently.
- I adjudicate disagreements and record the decisions.
- The answer key is one JSON file per company at `backend/tests/eval/gold/<TICKER>.json`:

```json
{
  "company": {"name": "Nike, Inc.", "cik": "0000320187", "ticker": "NKE"},
  "filing": {"form": "10-K", "accession": "0000320187-26-000123", "url": "https://www.sec.gov/Archives/..."},
  "annotator": "Yousuf's Codex",
  "relationships": [
    {"id": "NKE-1", "edge_type": "contract_manufacturer", "target_name": "contract manufacturers in Vietnam",
     "target_kind": "country", "direction": "depends_on_target",
     "quote": "<verbatim, copied from the filing>", "importance": "critical", "notes": ""}
  ],
  "negatives": [
    {"id": "NKE-N1", "target_name": "adidas", "kind": "competitor", "quote": "<verbatim>"}
  ]
}
```

**Field rules:**
- `edge_type` and `target_kind` use the contract enums (supplier, customer, contract_manufacturer, foundry, key_input, facility, jv_partner; company, country, region, material, component, facility, unnamed_customer).
- `direction` is `depends_on_target` (the target supplies, makes for, or hosts the company) or `target_depends_on_company` (the target is a customer).
- `importance` follows the R-IMP tiers (critical, high, medium, low).
- `negatives` are hard cases that a correct extractor must **not** return: competitor mentions, negated statements, hypotheticals, and generic references. Aim for at least 3 per company.
- Quotes must pass `hoc.filings.text.normalise` substring matching against the filing; E-RUN checks this.

**Scoring (E-RUN, `backend/hoc/eval/`, CLI `uv run hoc eval [--live|--replay]`):**
- **Matching.** A predicted edge matches a gold relationship when it has the same company, the same `name_key(target)` (or the same ISO2 country for facilities), and a compatible edge type. Compatible pairs are supplier/key_input/sole-source supplier, and foundry/contract_manufacturer.
- **Pooling.** Unmatched predictions go to the lead for a yes/no call. Approved ones join the answer key with `"source": "pooled"`; this is standard pooled evaluation, and the report says how many were added.
- **Report.** Precision, recall and F1 overall and per edge type. Also:
  - direction accuracy;
  - hard-negative false-positive rate;
  - facility-country accuracy;
  - importance-tier agreement (weighted kappa);
  - precision before and after V-INT.
- **Intervals.** Every figure gets a 95% bootstrap interval over companies.
- **Outputs:**
  - `docs/hoc/EVAL.md`: method, numbers, every error listed;
  - `docs/hoc/eval/results.json`;
  - an offline replay test that reruns scoring from recorded responses.

## 2. Before/after comparison (X-API, X-UI)

`POST /api/compare {baseline, candidate, top_n}` → `CompareResponse`.
- **Behaviour.** It is synchronous and cache-only, and never calls Gemini. It runs both analyses, takes verified edges from the extraction cache for each portfolio's top-N companies, resolves names per portfolio, and computes metrics with `hoc.graph.compute_dependency_metrics`.
- **Returns:**
  - per-metric deltas (`dep.*`, `critical.*`, `facility.*`), sorted by absolute change;
  - concentration deltas: top 5, top 10, top 20, effective N, largest company;
  - the candidate's top-N companies that have no cached extraction (`candidate_unanalysed`), so the UI can offer "Find dependencies for this scenario".
- **X-UI.** A Compare page with:
  - "Current" (the analysed portfolio) next to "Scenario" (an editable copy, in % or shares);
  - a Compare button;
  - the largest decreases and increases in plain English, e.g. "Depends on TSMC: 12.39% → 8.10% (−4.29 pts)";
  - concentration before and after;
  - a coverage note.

## 4. Relationship importance (R-IMP)

`VerifiedEdge.importance = EdgeImportance{score 0..1, tier, reasons}`, computed in Python only (`backend/hoc/graph/importance.py`) from verified fields. No prompt change.
- **Base by type:**
  - foundry 0.9, contract_manufacturer 0.85, key_input 0.6, supplier 0.5, jv_partner 0.4;
  - customer 0.9 at ≥20% of revenue, 0.7 at ≥10%, else 0.5;
  - facility 0.7 for production (fab, factory, plant, assembly, manufacturing), 0.3 for headquarters, office or R&D.
- **Cues in the verified quote** (whole words, case-insensitive):
  - up: sole, single source, only source, limited number of, substantially all, critical, depend(s/ent) on, rely/relies on;
  - down: one of several, multiple sources, alternative sources, readily available.
- **Overrides:** `sole_source` → at least 0.95.
- **Tiers:** critical ≥0.8, high ≥0.6, medium ≥0.4, otherwise low.
- **`reasons`:** short strings that quote the cue words, e.g. "Named as the sole source ('sole source')".
- **New metrics:** `critical.<key>` is the portfolio exposure that depends on the subject through critical- or high-tier edges, with a `.companies` twin.
- **Orchestrator.** It receives importance and bumps its prompt version (one Argon call).
- **Eval.** Tier agreement against the answer key.

## 5. Interpretation verification (V-INT)

`VerifiedEdge.interpretation = EdgeInterpretation{status, method, flags, reason, model}`, set in `backend/hoc/ai/` after `verify_quote`.
- **Rules first.** They run on the quote plus about 300 characters of context on each side, from the quote's span in `Filing.text`. Flags:
  - `competitor_mention` (compete, competitor(s), rival);
  - `negated` (not, no, never, without, nor, or "do not rely" in the clause that names the target);
  - `hypothetical` (if, could, may, might, would, with no factual verb);
  - `direction_mismatch` (supplier or customer patterns pointing the wrong way, e.g. "we sell to X" labelled supplier);
  - `generic_reference` (a target that is a class, not an entity);
  - `subject_mismatch` (reverse links: the filer is not the subject).
- **Then an independent judge.** It handles every edge that the rules flag, plus a random 20% of unflagged edges, logged for eval.
  - One Flash call per company, with a separate prompt (`hoc-v3-judge-1`) that never sees the extractor's output, only the quote, its context and the claimed relationship.
  - The label is one of supports, contradicts, competitor, unrelated or unclear.
- **Decision (Python):**
  - supports → `confirmed`;
  - contradicts, competitor or unrelated → `rejected`: removed from `edges` and counted in `DependencyCounts.interpretation_rejected`;
  - unclear, or any flag the judge did not clear → `flagged`: kept, with a badge, and importance capped at medium.
- **Caching:** per edge, keyed on the judge prompt version and model.

## 6. Agentic research loop (A-RES)

A user-triggered phase after a dependency run: "Investigate uncertain findings".
- **Endpoints:**
  - `POST /api/dependencies/{job_id}/research {max_items}` → `ResearchJob`;
  - poll with `GET /api/research/{research_id}`.
- **Item selection (Python, deterministic).** Ranked by importance × exposure and capped at `max_items` (default 6). Kinds:
  - V-INT flagged edges (`flagged_edge`);
  - undisclosed customers at ≥10% of revenue (`undisclosed_customer`);
  - critical or high edges supported by only one filing (`single_source`);
  - analysed companies with zero edges (`no_disclosures`);
  - unresolved counterparties at high tier (`unresolved_counterparty`).
- **Loop (`backend/hoc/research/`).** Gemini picks one action per step as structured output, and Python executes it. At most 4 steps per item, with a wall-clock budget. Actions:
  - `search_filings(phrase)`: EDGAR full-text search over the last 15 months of primary 10-K/20-F documents;
  - `read_section(cik, section)`;
  - `find_in_filing(cik, phrase)`: verified spans with context;
  - `conclude(outcome, evidence)`.
- **Evidence.** Every new edge must pass `verify_quote` and V-INT.
- **Outcome:** confirmed, revised, rejected, new_evidence or unresolved.
- **Explanations** carry no numbers except inside verified quotes.
- **Merge.** Findings merge into a new `DependencyResult`: confirmed or new edges are added, rejected ones are removed and counted. Metrics are recomputed and the orchestrator reruns.
- **Display.** Each finding shows its step trace ("searched X: 3 filings; read Qualcomm 10-K Item 1A; found ...").

## 7. Coverage reporting (C-COV)

`DependencyResult.coverage = CoverageReport`, computed in Python (`backend/hoc/graph/coverage.py`).
- **Buckets.** These are portfolio weight fractions that sum to 1 within ±1e-6:
  - `verified`: in the top N, with at least one verified edge;
  - `no_disclosures`: filing read, no edges;
  - `no_sec_filing`;
  - `not_analysed`: error, skipped or over budget;
  - `outside_top_n`.
- **`by_etf`:** the verified share of each ETF's look-through weight.
- **`largest_unanalysed`:** the 10 largest exposures outside the top N.
- **`gaps`:**
  - unnamed customers (count and weight);
  - counterparties that aren't SEC filers;
  - filings more than 12 months old;
  - region-only facilities;
  - and "N% of your portfolio is outside the companies we analysed; raise the top N to 30".
- **G-UI.** A stacked bar at the top of the Dependencies page titled "What we know about your portfolio", with the gaps listed in plain English.

## Contract C0-v3 (lead; field names fixed now)

- **`VerifiedEdge`:**
  - `importance: EdgeImportance | None` (`score`, `tier`, `reasons`);
  - `interpretation: EdgeInterpretation | None` (`status` confirmed|flagged|rejected, `method` rules|rules+model, `flags` list, `reason`, `model`).
- **`DependencyCounts`:** `interpretation_rejected: int = 0`.
- **`DependencyResult`:** `coverage: CoverageReport | None`.
- **Coverage models:** `CoverageReport{buckets[CoverageBucket{kind, weight, companies, label}], by_etf[EtfCoverage{ticker, verified_weight}], largest_unanalysed[UnanalysedCompany{company_key, company_name, exposure}], gaps[CoverageGap{kind, message, weight?}]}`.
- **Research models:**
  - `ResearchRequest{max_items 1..10 = 6}`;
  - `ResearchJob{research_id, dependency_job_id, status, progress_done, progress_total, findings, result?, error?}`;
  - `ResearchFinding{finding_id, kind, subject, question, outcome, explanation, steps[ResearchStep{index, action, query?, summary, filing?}], confirmed_edge_ids, rejected_edge_ids, new_edges}`.
- **Compare models (`hoc/contract/compare.py`):**
  - `CompareRequest{baseline, candidate, top_n}`;
  - `CompareResponse{status ok|partial, baseline_top_n_weight, candidate_top_n_weight, dependency_deltas[MetricDelta{metric_id, label, unit, baseline?, candidate?, delta?}], concentration_deltas[ConcentrationDelta{name, baseline, candidate, delta}], candidate_unanalysed[UnanalysedCompany], notes}`.
- **Errors:** `ErrorCode` gains `RESEARCH_NOT_FOUND`.

## Done when

1. `docs/hoc/EVAL.md` reports precision, recall and F1 on the 10 unseen companies, with intervals, every error listed, and the before/after effect of V-INT. README quotes the headline numbers.
2. On the live us-core-tilt run:
   - every edge carries importance and interpretation;
   - rejected interpretations are counted;
   - coverage buckets sum to 100%;
   - the research loop resolves at least 3 items with verified evidence and a visible trace.
3. Compare: lowering XLK and QQQ in favour of an ex-tech ETF visibly lowers `dep.ALIAS:TSMC` in the UI, with no Gemini call.
4. All backend tests pass, the frontend builds, and the I-UI audit passes on every page.
