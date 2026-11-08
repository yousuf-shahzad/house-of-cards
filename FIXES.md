# Fixes list

Every known problem, who is fixing it, and where it stands. This is the team's single to-do list.

## How this file works

- **Adding a problem (Gawyn or any human):** add one line under **New**. A sentence is enough, with no owner or ID needed. Commit it straight to `main` with no PR: run `git pull --rebase` first, then commit only this file.
- **Lead (Gawyn's Claude):** watches this file. It gives each new line an ID and an owner, moves it to **Open**, and tells the owner on the board. An item moves to **Done** only after the lead has checked it on `main`.
- **Every agent:**
  - Read this file at the start of every task and after every `git pull`.
  - Work on items with your name, top to bottom (`high` before `low`).
  - Put the ID in your branch and PR title, e.g. `28-fix-3-plain-cards` and "FIX-3: …".
  - Post on the board when you start and when you merge, as usual.
  - Don't edit this file: tell the lead on the board, and the lead updates it.

## Temporary handoffs

- **Yousuf's Claude is out of usage** (Yousuf, 08:41). Until it's back:
  - Its files go to Yousuf's Gemini: `frontend/` shell, `frontend/app/ui/`, `frontend/api/client.ts`, `vite.config.ts`, `frontend/app/workspace.tsx`, `pages/portfolio/`, `pages/network/`, `pages/compare/`, `frontend/app/scenario.tsx`.
  - Its frontend PR reviews go to Yousuf's Gemini. The lead's browser check stands in for the review on #186 and #193.
  - It has no open items: its FIX-28 part is done (#212).
- **Bekarys's Claude is out of usage** (since 07:30; Bekarys's Gemini, 08:43). Bekarys's Gemini takes its open items, in this order:
  1. Rebase and merge PR #193 (FIX-11 job research, lead-approved).
  2. PR #186 (FIX-17 AI cards): apply Yousuf's Claude's two review fixes ("AI suggested N; we kept M" wording; a `<div>`, not a `<p>`, around the Spinner), rebase, merge.
  3. FIX-22 job side in `hoc/jobs.py`: a separate 8-worker research pool; start deadlines of light 50 s and thorough 95 s.
  - Its backend files (`service.py`, `api/`, `jobs.py`, `tests/api/`) go to Bekarys's Gemini until it's back.

## New

<!-- Add new problems below this line, one per line. -->

## Open

### FIX-31 · medium · Link importance is shown as a percentage, and graph line width means something else
From Codex's FIX-30 audit:
- `importance.score` is a heuristic ranking score, but the UI shows it like a measured share ("Critical 90%").
- Graph line width follows the company's portfolio exposure, not link importance, and nothing says so.
- Fix: show only the tier (Critical/High/Medium/Low) with a tooltip such as "how much this link matters to the company, judged from the filing". Add a legend line: "Line thickness = how much of your money is in that company". No backend change.
- **Owner:** Yousuf's Gemini (Dependencies and Network pages) · **Status:** assigned

### FIX-30 · high · Yousuf's requests: audit dependency links; a simple dashboard instead of the step-by-step guide (Yousuf, 08:43)
- **Audit** (read-only, can start now): how dependencies are detected, how links are weighted and displayed. Report findings as new FIX items.
- **Simple mode as a walkthrough of the real app** (Yousuf clarified at 08:45: "Make the walkthrough of the bigger UI with its more simplified views"):
  - Simple mode keeps the same sidebar and pages as Full mode, with simplified versions of each page (new `pages/simple/` renderers).
  - Walkthrough tips are optional and can be dismissed. No 5-step funnel; you can go anywhere.
  - Needs `workspace.tsx`, `experience.tsx` and `onboarding/welcome-dialog.tsx`.
  - **On hold until Gawyn decides,** because it replaces the 5-step guide Gawyn chose.
- **Owner:** Yousuf's Codex · **Status:** audit in progress; dashboard waiting for Gawyn

### FIX-22 · medium · Research time budgets are too tight
In the FIX-1 live check, 4 of 23 light findings stopped after one tool call ("step budget expired"), and 15 of 45 thorough findings were skipped ("time budget reached").
- Fix:
  - Raise the per-company budgets, especially thorough's, since the user asked to go deeper, or run a company's items in parallel. Keep the job inside A2's limits (light about +90 s, thorough about +180 s).
  - Label budget stops "not finished in time", not plain "unresolved".
  - Make each explanation match its outcome (Nvidia→OpenAI: outcome "unresolved", but the text says "is rejected").
- After it merges, Bekarys's Gemini re-runs the held-out eval at thorough depth to see whether deeper research changes links.
- **Owner:** Kendrick's Gemini (+ Bekarys's Claude for job limits) · **Status:** plan approved (an 8-worker research pool; light 40 s and thorough 85 s per company)

### FIX-17 · high · Change ideas: AI proposes, Python verifies (Gawyn, 07:08)
Gawyn wants concrete ideas ("add this ETF to help fix this diversification issue") on screen 5 and in Try a change, in both views. **The AI proposes the changes and Python verifies them**, the same pattern as the AI summaries.

**1. AI proposer** (Gawyn's Gemini; new `backend/hoc/graph/idea_proposer.py`, next to the orchestrator; uses the existing Gemini client without changing `hoc/ai`):
- **Input from Python:** the portfolio's issues. That means the largest industry (same ≥40% rule as the verdict on screen 3 and the Risk page), the biggest dependencies, top 10, and effective N, all as metric ids. It also gets the current holdings, and a pinned universe of loadable ETFs (about 15–20: broad, equal-weight, value, international, sector funds). Each ETF comes with its name, category and largest industry, computed by Python.
- **Asks the model (Argon, `gemini-4-argon`, the orchestrator's model; Gawyn's call, for accuracy)** for up to 5 proposals. Each one is:
  - `add`: put fraction f of the portfolio into ETF Z, scaling the rest; or
  - `swap`: move f from held ETF Y into ETF Z;
  - with f in {0.1, 0.2, 0.3}, the issue id it addresses, and a short `rationale`. Numbers in the rationale appear only as `{{metric:id}}` placeholders.
- **Behaviour:** versioned prompt, JSON schema, cached per (holdings, issues, prompt version, model).
- **On a missing key, error or timeout:** return no proposals with an `ai_status`.
- **Argon is slow (about 45 s), so it runs in the background:**
  - the first request returns the rules ideas at once with `ai_status: "pending"`;
  - the AI ideas replace them when they're verified;
  - results are cached on disk, so restarts and repeat clicks are free;
  - the startup warm-up also prepares AI ideas for the example portfolios, so the demo is instant.

**2. Python verifier and ranker** (Yousuf's Codex; `portfolio/ideas.py`, after FIX-20). It rejects any proposal that:
- uses a ticker outside the universe;
- has a bad fraction, or a swap source that isn't held;
- has a rationale that fails the orchestrator's placeholder, number and name rules;
- doesn't measurably improve the issue it names;
- makes the largest industry or the top dependency worse beyond a small tolerance.

Survivors are measured with cache-only compare on one company set (FIX-20). Python renders every number, ranks by verified improvement, and returns the top 3 distinct ETFs. If the AI is unavailable or nothing survives, the current rules shortlist is the fallback.

**3. Contract** (lead-approved, Codex adds it; additive):
- **`ChangeIdea`:**
  - `proposed_by: "ai" | "rules"`;
  - `action: "add" | "swap"`;
  - `swap_from: str | None`;
  - `rationale: str | None`, the verified and rendered text;
  - `add_fraction` widens to 0.1 / 0.2 / 0.3.
- **`ChangeIdeasResponse`:**
  - `ai_status: "ok" | "pending" | "missing_api_key" | "failed" | "timeout" | "not_used"`;
  - `model` and `prompt_version`;
  - `rejected_proposals: [{ticker, action, reason}]`, so the UI can say "the AI suggested 5, we kept 3".

**4. UI** (Bekarys's Claude):
- **Cards:** idea cards show the rationale and an "AI idea, checked with your numbers" note. Rules ideas are labelled as such.
- **Swaps:** they move shares from the source ETF.
- **Polling:** while `ai_status` is `pending`, show the rules ideas with "AI is checking more ideas…". Re-request about every 3 s, for up to about 90 s, and swap in the AI ideas when they arrive.
- **Live check (lead):** sample portfolio. Every shown idea improves its named issue by the shown amount; the AI and fallback paths both work, including with no key.
- **Owners:** Gawyn's Gemini (proposer) + Yousuf's Codex (verifier, contract) + Bekarys's Claude (UI)
- **Status:**
  - Merged: rules version (#177–#181), AI contract (#185), proposer (#194, plus name and sector checks; "Consider" fixed in #197).
  - Engine merged (#192); FIX-24 fix merged (#199).
  - **Live AI path PASS (lead, main 6e3c825):** rules ideas show first ("pending"), then after about 36 s 2 Argon ideas replace them. Add SCHD: GPU dependency 8.1% → 6.5%. Add RSP: top 10 37.2% → 30.1%. Both match an independent compare. 3 proposals were rejected, with reasons.
  - **No-key path PASS:** `missing_api_key`, rules ideas.
  - **Left:** UI PR #186 (final wording fix), then merge.
  - UI PR #186 is in review.

### FIX-9 · medium · Final QA of both views
- Fix: once everything above merges, audit the full and simple views end to end; send problems to their owners.
- Also test with no AI key or SEC contact: page 4 must say "The AI check couldn't run on this computer" (FIX-4 was checked in code only).
- **Owner:** Bekarys's Gemini · **Status:** interim QA passed on everything merged through #183, including a live no-key/no-contact test of page 4; final pass after FIX-1 and FIX-17.

### FIX-11 · low · Research findings appear only when the scan ends
The plan asked for the research trace to show live during the run.
- Fix:
  - The job exposes findings as each agent finishes.
  - The Dependencies page and simple page 4 show them.
- **Owner:** Bekarys's Claude (job; adds `DependencyJob.research`, lead-approved) + Yousuf's Gemini (pages) · **Status:** pages merged (#170); job PR #193 approved; then remove the type casts

## Done (checked on `main` by the lead)

- FIX-29 beginner-friendly text: AI cards on the Dependencies page show one plain sentence with a Full detail toggle (lead: 514 → 1,335 chars when opened); section intros are one sentence; guide step 4 shows one line per finding ("Checked: Apple Inc. single-source reliance on Japan — confirmed") with Details. Kendrick's Gemini may polish wording such as "Nvidia -> OpenAI" — #214
- FIX-28 "What's here & why" on every page; copy has no stale numbers; Risk thresholds 35/100 days; Light vs Go deeper described correctly — #207, #212, #213, #214
- Thorough held-out eval after FIX-22's research side: 35/35 findings with 3 tool calls and `search_filings`, 0 budget stops; thorough keeps every light edge; 0 links changed, so precision and recall are unchanged (88.4% / 96.1% / 57.4%). Reproduced offline by the lead — #211
- FIX-26 AI idea text: no rewriting. Unclear AI sentences are dropped and the card shows Python's reason. Live: VTV and SCHD ideas kept with rationale None and correct reasons; XLV keeps its clean sentence — #207, #210
- FIX-27 clicking a graph edge opens the section and its evidence drawer; Show less then folds it and it stays folded with the edge still selected (lead, browser) — #205
- FIX-23 the four Dependencies sections fold to a 280 px faded preview with Show all / Show less, and Countries is stacked. Lead check: each section 280 px when folded, 1.6k–12k px open; the page is 19,196 → 4,690 px at 1280×800 (PR) — #203
- FIX-25 AI swaps into XLV and VTV accepted under a worst-case industry check (live: XLK→XLV Technology 51.1% → 41.2%; QQQ→VTV → 41.8%; all 3 AI ideas match compare) — #201
- FIX-24 the idea proposer reaches Argon (the invalid timeout argument is gone; timeouts classified by type) — #199
- FIX-21 docs: swap 12.39% → 6.30% (−6.10 pts), XLU 9.92%, slide 3 companies Nvidia/Broadcom/AMD/Intel, and the honest held-out agent result (+0.0 pp, no accuracy claims) — #195, #198
- FIX-8 before/after eval on the 10 held-out 10-Ks (light agents): precision 88.4% blind / 96.1% pooled and core recall 57.4%, all unchanged (+0.0 pp); 18 findings, 0 links added or removed; agentic check PASS (18/18 make 2+ tool calls, 0 circular). Reproduced offline by the lead — #196
- FIX-1, FIX-2, FIX-14 real research loop. Light: 17/23 findings make 2+ tool calls (was 3/25). Thorough: 27/45 use `search_filings` (was 0). Thorough keeps every light edge. 0 duplicate or group customer links — #189
- FIX-19 the bar resets only when a reused job starts again; a running bar at 100% stays at 100% — #187, #191
- FIX-20 compare measures both sides on the same companies (+20% XLU: 9.92%, exact dilution; swap: 12.39% → 6.30%) — #183
- FIX-7 README and DEMO cover v3.1 (shares default, simple view, Try a change, change ideas "coming") with verified numbers — #132. The FIX-8 numbers follow in a small PR from Gawyn's Gemini.
- FIX-18 progress bar never goes down: the total is set up front and only lowered (live: 106 → 100 → 65; 0% → 15% → 98% → 100%), and the pages never show a lower % — #172, #174
- FIX-16 screen 2 names the most overlapping pair (QQQ and XLK, 50.11%) — #174
- FIX-15 simple screen 1 is shares only, with % as plain text; the full view keeps the switch — #175
- FIX-10 plain titles match their text (live: "Heavy reliance on Taiwan Semiconductor Manufacturing") — #173
- FIX-6 pitch deck leads with the held-out eval (88.4% / 96.1% precision, 57.4% recall, 1 of 79), 40% verified coverage — #167
- FIX-12 all links cite a real 10-K Item (Microsoft, Alphabet sections fixed; 132/132 quotes exact) — #169
- FIX-13 PR #25 closed by Bekarys (branch kept)
- FIX-3 short AI cards on simple pages 4–5, "Read more", a splitter that keeps "Co., Ltd." whole; FIX-4 "couldn't run on this computer" (#151; live-tested by QA with no key and no contact); FIX-5 page 4 progress bar and "Go deeper" that updates in place — #166
- Try a change: starts from your portfolio, updates on its own, 4 rows — #156, #163
- Dependencies page progress bar and a single "Go deeper" — #160, #161
- Research agents, first version (follow-ups are FIX-1 and FIX-2) — #162
- Job progress and research depth — #157
- Plain AI summaries from the orchestrator — #159
- Shares by default, sample worth about $10,000, no duplicate button, no "#" ranks — #158
- Heavy industry overlap counts against diversification — #154
- Kendrick's Claude's work reassigned — #164
