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
  - **Bug hunts STOPPED (Gawyn, 11:52):** no agent adds lines under New any more. Report findings on the board to the lead.

## Temporary handoffs

- **Yousuf's Claude is back** (11:25). Its S-UI files (frontend shell, `app/ui/`, `api/client.ts`, `vite.config.ts`, `workspace.tsx`, `pages/portfolio|network|compare/`, `scenario.tsx`) and frontend reviews returned to it at 11:30. It owns #266 (FIX-63 UI).
- **Bekarys's Claude was out of usage** from 07:30 to 10:13. It's back, and its backend files (`service.py`, `api/`, `jobs.py`, `tests/api/`) have returned to it. While it was away, Bekarys's Gemini finished its items:
  1. Rebase and merge PR #193 (FIX-11 job research, lead-approved).
  2. PR #186 (FIX-17 AI cards): apply Yousuf's Claude's two review fixes ("AI suggested N; we kept M" wording; a `<div>`, not a `<p>`, around the Spinner), rebase, merge.
  3. FIX-22 job side in `hoc/jobs.py`: a separate 8-worker research pool; start deadlines of light 50 s and thorough 95 s.
  - Its backend files (`service.py`, `api/`, `jobs.py`, `tests/api/`) go to Bekarys's Gemini until it's back.

## New

<!-- Add new problems below this line, one per line. -->


## Open

### FIX-62 · medium · Second check of the guide + second bug hunter on Simple view (Gawyn, 10:40)
Kendrick's Claude is free again. In order:
1. **Post-merge review of #251 (FIX-59).** Read the diff. In the guide, check steps 2–5 in each state: loading, backend down (error), edited-but-invalid (changed), empty, and editing the portfolio while Step 4's progress bar runs, then restoring it. Step 4 must restart for the new portfolio and never show the old one's results.
2. **Browser-check FIX-40 on `main`.** The "Learn more in the full …" links in guide steps 1–3 must open Full view.
3. **Second bug hunter, Simple view only:** Simple Portfolio, Exposures, Dependencies, Try a change, and the guide. Kendrick's Gemini (FIX-37) keeps the whole app. Sign every line `[Kendrick's Claude]` and check New/Open first to avoid duplicates.
- Report results on the board. Add findings under **New** (FIX-37 rules). Don't edit other owners' files; fixes go to their owners via the lead.
- **Owner:** Kendrick's Claude · **Status:** done 11:38 (part 3 found FIX-64/65; parts 1–2 #251 review / FIX-40 check not reported)

### FIX-37 · high · Bug hunt across the whole app; report bugs in FIXES.md (Gawyn, 09:23) — **STOPPED (Gawyn, 11:52)**
Find real bugs on current `main`, in both views and on every page:
- Portfolio inputs: empty, one ETF, an unknown ticker, shares vs %, huge numbers.
- Overlap, Network, Dependencies (Go deeper during a run, collapsing sections, the evidence drawer), Compare / Try a change / change ideas, Risk, and the Simple-mode walkthrough and guide.
- The API: validation, error codes, and cache-only paths with no key.
- Mobile width and dark mode.

For each **confirmed** bug, add one line under **New** in FIXES.md: `BUG: <what happens> — repro: <steps> — where: <page/file> (Kendrick's Gemini)`. Skip anything already in Open. Don't fix bugs; the lead assigns them. Post a short board summary every ~10 bugs or 30 minutes.

- **Owner:** Kendrick's Gemini · **Status:** assigned · **STOPPED 11:52 (Gawyn)**

### FIX-9 · medium · Final QA of both views — **STOPPED (Gawyn, 11:52)**
- Fix: once everything above merges, audit the full and simple views end to end; send problems to their owners.
- Also test with no AI key or SEC contact: page 4 must say "The AI check couldn't run on this computer" (FIX-4 was checked in code only).
- **Owner:** Bekarys's Gemini · **Status:** START NOW (FIX-34 has landed). Final pass of both views, including the new Simple walkthrough (#221) and change ideas. Add bugs under New. · **STOPPED 11:52 (Gawyn)**

## Done (checked on `main` by the lead)

- FIX-70 README refresh: centered logo, tagline, live demo link, a short per-page "What it does", copy-paste setup with placeholder keys only, offline mode/CLI/tests, How it works; the long history moved to docs/hoc/HISTORY.md (319 → 182 lines). Lead checked the referenced commands and fixed one path (validation/run_validation.py). Bekarys's Gemini — #286
- FIX-63 **Failure simulator** on Compare / Try a change (Gawyn, 11:04):
  - Pick an industry, a country (the US is included since #280) or a supplier (companies only), and see before → after money for your portfolio and the new mix, on the same base.
  - Historical worst-month fall of the proxy ETF over 5 years, otherwise a simulated 20%.
  - Risk and Dependencies "What if it fails?" links preselect the failure.
  - PRs: #255 #258 #259 #260 #261 #263 #265 #266 #267 #269 #270 #271 #272 #273 #275 #279 #285.
  - Verified: the lead in the browser, Bekarys's Gemini's E2E, the independent history check, and the hand calculations.
  - Demo story (docs/hoc/demo/failure-simulator.md): US core, swap 20% QQQ → VTV, tech failure: $10,000 → $9,019 vs $9,199, so it loses $180 less.
- FIX-69 Try a change shows "Your portfolio (now)" read-only on the left beside the editable new mix on the right, in Simple and Full alike. Equal columns from 1024 px, stacked below that with the current first. In Full it replaces the old current-portfolio list (lead, browser: 1280 and 390 px, Simple and Full) — #284
- FIX-66 a scan at 0% now shows what it's doing ("Reading NVIDIA's annual report… · Read 3 of 15 · 12 s") with a moving bar, in Full Dependencies, guide Step 4 and Simple Dependencies. A re-scan says "Starting the scan…". Yousuf's Claude (#278, #282) + Yousuf's Gemini (#281); live check by Yousuf's Claude on an uncached XLE/XLU portfolio, lead code review
- Hosting (Yousuf's request, issue #262):
  - free Vercel deploy, auto-deploying from `main` to https://house-of-cards-pink.vercel.app/;
  - private Blob cache with corrupt-entry guards; queued research jobs;
  - secrets entered by the humans only.
  - Yousuf's Codex; lead approved the pyproject/lock and cache seams (stand-in for Bekarys's Claude) — #274
- FIX-68 Dependencies: only "Find dependencies" before the first scan; after it, "Scan 15 more" (top 30) beside Run again / Go deeper (lead, browser) — #279
- FIX-67 the US now appears under Countries: US-exchange listings are inferred as US (receipts excluded), and reported countries win. Live: US 79.1% of IVV/QQQ/EEM, unknown 1.4%; a US failure is SPY's historical 12.8% (lead, curl after a restart). Yousuf's Codex — #280
- FIX-64/65 Simple view: an unknown ticker no longer says "pin this row" (plain issue text keyed on the issue code; Full view unchanged), and the "details are missing" banner shows only for real gaps (not at 99.93%). Gawyn's Gemini; checked by the lead in the browser and the owner — #276
- FIX-40 guide steps 1–3 "Learn more in the full …" links open Full view (#/portfolio, #/exposures, #/risk), browser-checked by Kendrick's Claude under FIX-62 — #234
- FIX-58 independent benchmark (Yousuf's request), in `backend/tests/live/etf_accuracy/`. The lead checked the saved `summary.json` / `verification.json`:
  - all 12 portfolios and 23 overlap pairs reconcile (worst top-10 error ~0 pp);
  - 11 same-date issuer funds / 2,120 rows match within 0.00005 pp;
  - 156-week return correlations are within 0.0003071;
  - no app code changed. The 13-page PDF is in Yousuf's output — #256
- FIX-61 no "counterparty" left on Dependencies or guide Step 4: plain "supplier or partner" wording, with capital letters kept (lead, live scan: 0 hits in 79k chars, collapsed sections included) — #252
- FIX-60 Full Compare and Try a change need a current, analysed baseline. With ZZZZ in place of EEM: Current says "isn't ready to compare", Try a change shows a notice with Edit portfolio, and no /api/compare or /api/change-ideas requests fire. Restored: requests resume (lead, browser) — #253
- FIX-59 guide: Step 1 Next needs a current analysis, with a "Finish or fix your ETFs" hint. Steps 4–5 show the analysis gate instead of an endless bar or "Still checking". "Back to Step 1" really goes to Step 1 (lead, browser: ZZZZ in place of EEM, then restored) — #251
- FIX-57 unknown `/api` routes return 404 `NOT_FOUND` and wrong methods return 405 `METHOD_NOT_ALLOWED`, both in the error envelope, with `Allow` kept (lead, curl on `main` after a restart) — #247
- FIX-52 / FIX-55 / FIX-48 (hover) / FIX-42 Dependencies:
  - Scan top 30, gaps and AI synthesis come first; Scan top 30 and Run again keep 30.
  - Stale/invalid drafts show a notice and disable the actions.
  - Hover no longer swaps the evidence cards.
  - Plain words throughout ("counterparty" left as FIX-61).
  - Checked by the lead (browser, pre-merge), QA and Codex — #248
- FIX-48 `dependencies-state.tsx` parts (selection reset, progress reset on restart) — #246
- FIX-45 on mobile, tapping the page you're already on closes the navigation drawer (lead, 375px) — #245
- FIX-56 Simple Try a change has no Shares/% switch and no pins; unknown tickers are flagged in the scenario (lead, browser) — #244
- FIX-54 Full-view stale/error states. Exposures (#241) and Risk (#242) show "last valid analysis" with Edit portfolio and no endless spinner (lead, browser). The Portfolio link is hidden while stale (#240).
- FIX-36 independent proof (`validation/`, standard library only, no `hoc` imports; the lead re-ran it from saved data and got identical results):
  - **Overlap:** QQQ/XLK reproduces the app's 50.11% / 35 shared exactly with date-matched files, and is 51.44% on current issuer files.
  - **Prices:** predicted links show only a weak, non-significant edge in 3-year residual co-movement (+0.062, 95% CI [−0.0015, 0.126], p = 0.09; event study +5.0 pp, p = 0.21).
  - #227
- FIX-41 Simple-mode controls (active mode shown, one footer action, guide link in the tips, embedded Step 4 without Learn more) — #225
- FIX-43 plain words on Exposures, Overlap, the editor and Compare ("Companies / Exact share classes", no raw keys, "Use this as my portfolio" beside Reset); verified by QA — #237
- FIX-50 Try a change: % ideas keep exact allocations; share swaps remove the full source; "Make this my portfolio" runs the scan and stays in mode; verified by QA — #235
- FIX-53 Simple Portfolio has a "Next: what you really own →" button: disabled with a reason until the portfolio is ready, then it leads to Simple Exposures (lead's own change, checked in the browser) — #236
- FIX-46 + FIX-51 Simple mode stays Simple when leaving the guide via the sidebar or Back; Simple pages show stale/error state and their own info text; the top bar is a "Simple | Full" toggle with the active side highlighted (lead, browser) — #231
- FIX-49 0-share rows are ignored (lead: 1,293 companies without IVV, no IVV on Exposures); share counts above 1,000,000,000 are marked invalid with a clear message, and nothing overflows — #230
- FIX-44 Risk page in plain words (HHI in a tooltip, "Industry breakdown", no raw codes); verified by QA — #229
- FIX-38 Network page removed; old links go to Exposures; money flow on Simple Exposures — #223
- FIX-47 the guide's auto-scan re-runs after A → B → A, and steps 2–3 show loading/error/"can't price"/"changed" instead of old numbers (lead's own fix, checked in the browser) — #233
- FIX-39 new-user UX/jargon review: 9 findings, triaged into FIX-41 to FIX-44 (Yousuf's Gemini)
- FIX-34 sole-source and qualifiers grounded in the target's own clause, and exact word-boundary name matching. Lead, live: all 3 remaining sole-source links have explicit sole/single/only wording; 1 mismatched link dropped (129 → 128); TSMC 12.39% unchanged — #222
- FIX-30 simplified walkthrough of the real app: Simple mode uses the same sidebar and pages with plain-English versions and dismissible tips, and the five-step guide stays reachable. The lead checked it in the browser. Yousuf told Codex to merge it, with the default `BEGINNER_START_PAGE = "#/portfolio"` (the walkthrough). Gawyn confirmed at 09:18 to keep the walkthrough as the default — #221 (audit split into FIX-31, FIX-33, FIX-34)
- FIX-33 importance: customer shares grounded to the target (live: Applied Materials' customer rated high from its own 19%, not the other's 15%); headquarters low 0.30; reverse customer links capped. On the sample only `critical.CIK:0000804328` (1.43%) drops out; `critical.ALIAS:TSMC` stays 12.39%, so the docs are unchanged — #220
- FIX-35 main is green again (561 passed) — #218
- FIX-31 importance badges show the tier only (no "Critical 90%"); the graph legend says "Line thickness = how much of your money is in that company" — #219
- FIX-32 one-liners read "Checked: Nvidia's partnership with OpenAI — still unclear" and "Checked: Apple's reliance on Japan — confirmed"; FIX-11 casts removed — #219
- FIX-17 change ideas: Argon proposes and Python verifies. Screen 5 and Try a change show "AI suggested 5 ideas; we kept 3" with reasons, "AI idea, checked with your numbers" cards, and Try this (lead: the QQQ→VTV swap loads as QQQ 1 sh + VTV 9 sh; Technology 51.1% → 41.7% after whole-share rounding, card says 41.8%). Rules fallback when there's no key — #177–#181, #185, #186, #192, #194, #197, #199, #201, #207, #210
- FIX-22 research time budgets (lead, live): light 62 s (was 131), 0 'not finished' (was 4); thorough 193 s, 1 'not finished' (was 15), 40/45 findings use search_filings — #206, #217
- FIX-11 research findings show while the scan runs (lead, live: thorough job.research grew 3 → 7 → 13 → … → 41 → 45) — #170, #193
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
