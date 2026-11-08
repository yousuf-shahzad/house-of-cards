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

### FIX-3 · high · Simple page 4–5 AI text is too long
- Fix:
  - Show `plain_title` + `plain_text`, with the full text under "Read more".
  - If those are missing, use a one-line fallback ("12% of your money depends on Taiwan Semiconductor").
  - The first-sentence splitter must not cut at "Co., Ltd.", "Inc.", "U.S." or "No.", with a test.
- **Owner:** Yousuf's Gemini (package K1) · **Status:** in progress (branch `28-v3.1-k1-guide-steps45`)

### FIX-4 · high · Page 4 blames the companies when the AI check can't run (issue #151)
With no AI key or SEC contact, page 4 says "We could check 0%".
- Fix: say "The AI check couldn't run on this computer", and show "no problems found" only when the insights are ok.
- **Owner:** Yousuf's Gemini (K1) · **Status:** in progress

### FIX-5 · high · Simple page 4 has no progress bar or "Go deeper"
- Fix: reuse the Dependencies page bar (Reading reports → Double-checking findings → Writing summary), plus one "Go deeper" button after a light run.
- **Owner:** Yousuf's Gemini (K1) · **Status:** in progress

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
- **Owner:** Bekarys's Claude (job) + Yousuf's Gemini (pages) · **Status:** open, after FIX-1 and FIX-5

### FIX-12 · low · 7 links cite the section "document" instead of a 10-K Item
These are 6 Microsoft links and 1 Alphabet link. Their quotes are exact, but the evidence panel can't say which part of the report they're from.
- **Owner:** Yousuf's Codex (filings) · **Status:** open

### FIX-13 · low · PR #25 (AgentVerse kit) has been open since 2026-11-07
- Fix: merge it or close it.
- **Owner:** Bekarys (whichever agent opened it) · **Status:** open

## Done (checked on `main` by the lead)

- Try a change: starts from your portfolio, updates on its own, 4 rows — #156, #163
- Dependencies page progress bar and a single "Go deeper" — #160, #161
- Research agents, first version (follow-ups are FIX-1 and FIX-2) — #162
- Job progress and research depth — #157
- Plain AI summaries from the orchestrator — #159
- Shares by default, sample worth about $10,000, no duplicate button, no "#" ranks — #158
- Heavy industry overlap counts against diversification — #154
- Kendrick's Claude's work reassigned — #164
