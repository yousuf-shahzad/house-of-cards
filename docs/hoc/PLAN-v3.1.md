# v3.1: shares default, cleaner simple mode, real-time "Try a change", truly agentic sub-agents

Lead: Gawyn's Claude. Umbrella issue #28. Assignments on the board (2026-11-08).

## Context
Gawyn reviewed beginner mode and the AI pipeline and asked for:
1. Every ETF adder defaults to **shares**.
2. Remove the **duplicate "what you own" button** in simple mode (`guide/steps/pick.tsx:357`, "See what you own →" next to the Next button).
3. On page 2, remove the **"#" rankings** (`guide/steps/own.tsx:71`).
4. **Heavy industry overlap must count against diversification**, in both modes.
5. Simple page 4: **simplify the "AI noticed" text**; it's far too text-heavy.
6. **Improve "Try a change"**: start from the current portfolio, update in real time as values change, and use a simpler, more concise UI.
7. **The AI sub-agents must run an agentic research loop**, not a single text lookup. Today the extractor makes one call per company (`hoc/ai/extractor.py`, "One extraction call per company"), and the research loop runs only on a click.

Also include **issue #151** (Bekarys's Claude). With no key or SEC contact, step 4 says "We could check 0%" and blames the companies. It should say the check couldn't run here.

Everything is delegated. My part is the contract, approvals and verification.

**Decisions (Gawyn):**
- Samples load as **whole shares worth about $10,000**.
- The agentic loop runs **light by default**, with a **visible progress bar**, plus a **"Go deeper"** option for a thorough pass.
- "Try a change" opens **inside the simple view**.

## Contract C0-v3.1 (lead, first; additive only)
- `DependencyRequest.depth: Literal["light","thorough"] = "light"`. Depth is part of the job id, so a thorough run is a separate job that reuses cached extractions and light findings.
- `DependencyJob`:
  - `phase: Literal["queued","reading","researching","synthesising","done"]`;
  - `steps_done` / `steps_total` (ints, default 0) for the progress bar.
- `CompanyStatus` gains `"researching"`.
- `DependencyResult`:
  - `research: list[ResearchFinding] = []`, the findings from the run's own agentic loop;
  - `research_depth: Literal["none","light","thorough"] = "none"`.
- `InsightClaim`:
  - `plain_title: str | None = None` (≤ 8 words);
  - `plain_text: str | None = None` (≤ 25 words, at most 1 number, and only through a `{{metric:id}}` placeholder like `text`).
- `ConcentrationName` gains `"top_sector"`, the largest industry's share of the portfolio, in Compare.
- Mirror everything in `types.ts`, extend the fixtures and `test_contract_v3.py`, regenerate the snapshot (additions only), and add CONTRACT.md §9.

## Packages and owners (Refs #28; one worktree each; small PRs; post when merged)

| # | Package | Owner | Notes |
|---|---|---|---|
| A1 | **Agentic sub-agents** (`hoc/research`, `hoc/ai`) | Kendrick's Gemini | See the detail below this table. |
| A2 | **Job wiring** (`hoc/jobs.py`, `service.py`, `tests/api`) | Bekarys's Claude (back; original I-API owner) | See the detail below this table. |
| A3 | **Eval re-run** | Bekarys's Gemini | After A1+A2: `uv run hoc eval --live` with light agents. EVAL.md reports precision and recall **before vs after agentic**, with CIs. Keep the eval hygiene: no tuning on the 10 companies. |
| F1 | **Shares default everywhere** | Yousuf's Gemini (handoff of `portfolio-draft.ts` / `draft-editor.tsx` / `scenario.tsx`; Yousuf's Claude reviews when back ~06:20) | See the detail below this table. |
| F2 | Remove the duplicate "See what you own →" button (`pick.tsx:357`) | Yousuf's Gemini | |
| F3 | Remove the "#" rankings on page 2 (`own.tsx:71`) | Yousuf's Gemini | |
| F4 | **Industry concentration in the verdict** (both modes) | Gawyn's Gemini (owns `app/ui/concentration.ts` and the risk page) | See the detail below this table. |
| F5 | **Plain AI text** | Gawyn's Gemini (orchestrator) + Yousuf's Gemini (steps 4–5, package K1) | See the detail below this table. |
| F6 | **"Try a change" redesign** | Bekarys's Claude (package K2, PR #163; handoff of `pages/compare` + `scenario.tsx`; Yousuf's Claude reviews) + Yousuf's Codex (`top_sector` delta in `hoc/portfolio/compare.py`) | See the detail below this table. |
| F7 | **Progress bar + "Go deeper"** | Yousuf's Gemini (Dependencies page + `dependencies-state.tsx`, and guide step 4 in K1) | See the detail below this table. |
| A1-fix | **Real agentic loop** (from the live check: most findings were one lookup; Go deeper dropped light edges) | Kendrick's Gemini | Re-finding the edge's own quote isn't a confirmation; light needs 2+ tool calls, thorough 3+ including a `search_filings`; thorough keeps every unrejected light edge. |

Reassigned 2026-11-08 (at Gawyn's request): Kendrick's Claude's v3.1 items went to Yousuf's Gemini (K1: F5 cards, #151, F7 guide step 4) and Bekarys's Claude (K2: F6). Its folders moved too; see the ownership table in `AGENTS.md`.
| QA | Final audit of both modes + docs | Bekarys's Gemini (QA), Gawyn's Gemini (docs PR #132) | After everything merges. |

**A1, agentic sub-agents.** Each company's sub-agent becomes a loop:
1. Read the filing sections.
2. Extract candidates.
3. Pick the company's own uncertain or critical items (flagged, undisclosed ≥10% customers, single-source critical): **light** takes 2, **thorough** takes 4.
4. Investigate each with the existing tools (`search_filings`, `read_section`, `find_in_filing`): **light** up to 3 steps, **thorough** up to 4.
5. Conclude confirmed, revised or rejected, or add new verified edges.

Reuse `ResearchLoop` (`hoc/research/loop.py`) in a per-company scope. Every new edge still passes `verify_quote` + V-INT + importance. Report progress per step. Cache per (extraction hash, depth, prompt version); `cache_only` replays and never calls Gemini.

**A2, job wiring.**
- Add `depth` to the request and the job id.
- Fill `phase` / `steps_done` / `steps_total` and the per-company `"researching"` status.
- Put the findings into `result.research`.
- Budgets: light about +60 s, thorough about +180 s, with the extraction never cut.

**F1, shares default everywhere.**
- Change `portfolio-draft.ts:148` to `"shares"`.
- The portfolio page, guide step 1 (drop "percent only") and the Compare scenario all open in shares.
- **Samples:** call `api.valuation` (`shares: 1`) to get prices, then `shares = round(alloc × 10,000 / price)`. Fall back to pinned % if any price is missing.
- The % toggle stays available.

**F4, industry concentration.**
- Add `diversificationVerdict({hhi, sectors})` to `app/ui/concentration.ts`.
- **Industry rating:** top industry ≥ 40% → "Concentrated in one industry"; ≥ 25% → at most "Moderately concentrated".
- **Final verdict:** whichever of the company and industry ratings is less diversified.
- Used by the risk page, guide step 3 (replace its local rule) and "Try a change".

**F5, plain AI text.**
- **Gawyn's Gemini (orchestrator):** the prompt asks Argon for `plain_title` / `plain_text` (prompt bump). Python verifies them with the same placeholder, number and name rules and drops either field if it fails.
- **Yousuf's Gemini (steps 4–5, K1):** show `plain_title` + `plain_text` only. Fall back to a deterministic one-liner from the claim's first cited fraction metric ("12% of your money depends on Taiwan Semiconductor"). The full text sits behind "Read more".
- **Yousuf's Gemini (K1):** also fix **#151** (a "couldn't run on this computer" line when coverage is `not_analysed`; no "no problems" line unless insights are `ok`).

**F6, "Try a change" redesign.**
- **Shared component** `app/ui/try-a-change.tsx`.
- **Starting point:** a copy of the current portfolio (shares default) with a "Reset to my portfolio" button.
- **Real time:** a debounced auto-compare (~500 ms; stale requests dropped). No Compare button.
- **Concise view:** 4 headline rows, each before → after with ↑↓:
  - the biggest dependency change;
  - the top industry share;
  - top-10 concentration;
  - "behaves like N holdings".

  Full deltas sit under "More details", with a one-line "not checked yet" note for unanalysed companies.
- **Where it's used:** the full Compare page, and a "Try a change" sub-screen inside the guide (simple layout, from step 5).

**F7, progress bar + "Go deeper".**
- A phased progress bar ("Reading reports → Double-checking findings → Writing summary", from `phase` + `steps_done/total`) with the live research trace.
- After a light run: a **"Go deeper"** button that starts a thorough job; results replace in place.

**Order:**
1. **C0-v3.1 (me, ~20 min).**
2. **Right away, in parallel:** F1–F3, F4, #151 and A1 (internal), none of which needs the contract.
3. **After C0-v3.1:** A2, F5, F6 and F7.
4. **Then** A3.
5. **Then** QA + docs.

## Verification (me, as each merges)
- Backend `uv run pytest` and frontend `npm run build` green. The snapshot diff is additions only.
- **Browser** (backend restarted on main):
  - all three editors open in shares;
  - "Use a sample portfolio" gives whole shares totalling about $10,000;
  - no duplicate button on step 1 and no "#" on step 2;
  - the sample's verdict says "Concentrated in one industry" (Technology about 51%) in **both** step 3 and the risk page;
  - step 4 shows short plain AI text, with the full text under "Read more";
  - #151: with no key, step 4 says the check couldn't run;
  - "Try a change" inside the simple view starts from my portfolio, updates within about 1 s of edits, shows 4 rows, and TSMC drops when XLK goes into VTV.
- **Agentic run:** a live "Find dependencies" on us-core-tilt shows phases and the bar moving, `result.research` has light findings with step traces, no digits outside quotes, and an unverified edge never merges. "Go deeper" runs a thorough job with more findings. A cached replay is instant.
- **Eval:** EVAL.md shows before/after-agentic numbers, reproducible with `uv run hoc eval`.
