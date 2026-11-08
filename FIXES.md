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

## New

<!-- Add new problems below this line, one per line. -->

## Open

### FIX-1 · high · Research agents still do mostly one lookup
In the live check, 22 of 25 light findings and 41 of 45 thorough ones made one tool call and stopped. `search_filings` was never used, and most "confirmed" results just re-found the edge's own quote. Gawyn asked for a real research loop, not a text lookup.
- Fix: re-finding the edge's own quote is not a confirmation. Light needs 2 or more tool calls; thorough needs 3 or more, including a `search_filings` across other companies' filings. Keep light within about +90 s.
- **Owner:** Kendrick's Gemini · **Status:** in progress (branch `28-v3.1-a1-fix`)

### FIX-2 · high · "Go deeper" loses findings
The thorough run dropped 3 verified links that the light run had found: Nvidia's 22% and 14% direct customers, and Cisco's 11% channel partner.
- Fix: thorough starts from the light results and goes further. Add a test that thorough keeps every light edge that wasn't rejected.
- **Owner:** Kendrick's Gemini · **Status:** in progress (same branch as FIX-1)

### FIX-14 · high · Research agents add duplicate "unnamed customer" links
Seen by Bekarys's Gemini on NKE: the agent added a new link "Three largest customers outside of the United States" on the same quote as the existing "Unnamed Customer" link. It got a different ID, so it was counted twice. A group of customers is also not one customer.
- Fix: when merging an agent's new links, skip an `unnamed_customer` link whose source, link type and normalised quote already match an existing link. Treat groups like "three largest customers" as not a link.
- **Owner:** Kendrick's Gemini (fold into A1-fix) · **Status:** assigned

### FIX-15 · high · Simple screen 1: shares only, no percent editing
Gawyn: remove the option to switch to percent on simple screen 1, and make the percent column read-only in shares mode there.
- Fix:
  - Add a `DraftEditor` option that hides the Shares | % switch and shows % as plain text (not an input). Use it in `guide/steps/pick.tsx` only; the full view keeps both.
  - If a sample's prices can't be fetched, load it as shares anyway (or show a short "prices unavailable, try again" message), not as pinned % rows the user can't edit.
- **Owner:** Yousuf's Claude (owns `app/ui/draft-editor.tsx`; lead-approved one-line change in `pick.tsx`) · **Status:** in progress (branch `28-fix-15-shares-only`)

### FIX-16 · high · Simple screen 2 shows the first ETF pair, not the most overlapping one
"Do your ETFs own the same companies?" uses `analysis.overlap.pairs[0]`, but the API returns pairs in input order. For the sample it shows IVV/QQQ (48.82%) when QQQ/XLK overlap most (50.11%).
- Fix: pick the pair with the highest `weighted_overlap`; add a test.
- **Owner:** Yousuf's Gemini (`guide/steps/own.tsx`) · **Status:** assigned

### FIX-17 · high · Suggest specific changes on screen 5 and in Try a change (both views)
Gawyn wants concrete ideas such as "add this ETF to help fix this diversification issue", which the user can pick to load into Try a change, in the simple view and the full view.
- **Backend (Python owns every number):** a new `POST /api/change-ideas`.
  - **Input:** the current holdings.
  - **Candidates:** a pinned list of diversifying ETFs that our sources can load (e.g. equal-weight S&P 500, value, international, under-weighted sectors).
  - **Testing:** try each at 10% and 20%, using compare in cache-only mode with no AI calls.
  - **Ranking:** order the ideas by how much they fix the portfolio's worst issue (the largest industry when that's the problem, else the biggest dependency, else top 10 / effective N).
  - **Output:** the top 3. Each has the ETF, its share, which issue it addresses, a plain title and reason, the full candidate holdings, and the before → after deltas.
  - **Contract:** new models, lead-approved and additive only: `hoc/contract`, the `types.ts` mirror, a fixture, the snapshot, and `CONTRACT.md` §10.
- **Frontend:**
  - **Screen 5:** idea cards ("Add RSP: largest industry 51% → 41%") with a "Try this" button that opens Try a change with the idea loaded. The ETF is added as whole shares worth its share of your portfolio.
  - **Try a change** (guide and Compare page): an "Ideas" list at the top that loads an idea in one click.
- **Owner:** Yousuf's Codex (backend + contract; shape approved) + Yousuf's Claude (vite proxy + `api.changeIdeas`) + Bekarys's Claude (frontend; can start on the fixture) · **Status:** in progress (branch `28-fix-17-change-ideas`)

### FIX-18 · high · The progress bar can go down
`steps_total` grows when the research phase starts (16 → about 50), so the bar drops from about 100% to about 30%. It also changes as agents finish.
- **Fix:**
  - **Backend:** set `steps_total` to its full estimate from the start, and only ever lower it.
  - **Frontend:** never show a lower % than already shown for the same job, on simple screen 4 and the Dependencies page.
- **Owner:** Bekarys's Claude (`hoc/jobs.py`) + Yousuf's Gemini (both pages) · **Status:** assigned

### FIX-6 · high · Pitch deck numbers are wrong
`PITCH_DECK.md` has these errors:
- Its "unseen annual reports" test is our development portfolio, and it leaves out the real held-out evaluation.
- It says about 45% coverage; the verified figure is 40%.

Fix:
- Lead with the held-out results from `docs/hoc/EVAL.md`: blind precision 88.4% [83.2, 92.5], pooled 96.1%, core recall 57.4%, direction 100%, and 1 of 79 hard negatives wrongly flagged.
- Add the research agents and beginner mode once FIX-1 lands.
- **Owner:** Gawyn's Gemini (alongside docs PR #132) · **Status:** assigned

### FIX-7 · medium · README and demo docs are out of date
- Fix: PR #132 needs the current numbers and the v3.1 features (shares default, simple view, "Try a change", research agents).
- **Owner:** Gawyn's Gemini · **Status:** in progress (PR #132)

### FIX-8 · medium · The evaluation doesn't show the effect of the research agents
- Fix: after FIX-1 and FIX-2 merge, run `uv run hoc eval --live` with light agents. EVAL.md then reports precision and recall before vs after the agents, with confidence intervals. Do no tuning on the 10 held-out companies.
- **Owner:** Bekarys's Gemini (A3) · **Status:** waiting for FIX-1 and FIX-2

### FIX-9 · medium · Final QA of both views
- Fix: once everything above merges, audit the full and simple views end to end; send problems to their owners.
- Also test with no AI key or SEC contact: page 4 must say "The AI check couldn't run on this computer" (FIX-4 was checked in code only).
- **Owner:** Bekarys's Gemini · **Status:** waiting

### FIX-10 · low · One AI summary title doesn't match its text
The title says "Heavy reliance on two chip makers", but its text names only TSMC.
- Fix: the plain title must name only what its text supports.
- **Owner:** Gawyn's Gemini (orchestrator) · **Status:** open

### FIX-11 · low · Research findings appear only when the scan ends
The plan asked for the research trace to show live during the run.
- Fix:
  - The job exposes findings as each agent finishes.
  - The Dependencies page and simple page 4 show them.
- **Owner:** Bekarys's Claude (job; adds `DependencyJob.research`, lead-approved) + Yousuf's Gemini (pages) · **Status:** pages merged (#170); job part starts after FIX-1

## Done (checked on `main` by the lead)

- FIX-12 all links cite a real 10-K Item (Microsoft, Alphabet sections fixed; 132/132 quotes exact) — #169
- FIX-13 PR #25 closed by Bekarys (branch kept)
- FIX-3 short AI cards on simple pages 4–5, "Read more", a splitter that keeps "Co., Ltd." whole; FIX-4 "couldn't run on this computer" (#151, checked in code); FIX-5 page 4 progress bar and "Go deeper" that updates in place — #166
- Try a change: starts from your portfolio, updates on its own, 4 rows — #156, #163
- Dependencies page progress bar and a single "Go deeper" — #160, #161
- Research agents, first version (follow-ups are FIX-1 and FIX-2) — #162
- Job progress and research depth — #157
- Plain AI summaries from the orchestrator — #159
- Shares by default, sample worth about $10,000, no duplicate button, no "#" ranks — #158
- Heavy industry overlap counts against diversification — #154
- Kendrick's Claude's work reassigned — #164
