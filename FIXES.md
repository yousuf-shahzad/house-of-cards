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
  - Exception: the bug hunter (FIX-37), QA (FIX-9) and the new-user review (FIX-39) may add one line per finding under **New**, straight to `main` (pull first, touch only New). The lead triages it into Open.

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
BUG: Entering 0 shares for an ETF alongside a positive-share ETF passes validation (validShares allows >= 0 while validPercent requires > 0), sending allocation: 0 to /api/analysis and polluting Exposures, Overlap, and Guide Step 2 with hundreds of 0.00% holdings, false "Multi-ETF holdings (held in 2+ ETFs)" counts, and false pairwise ETF overlap — repro: On Portfolio in Shares mode, set IVV to 0 shares and QQQ to 10 shares, then open Exposures, Overlap, or Guide Step 2 — where: frontend/app/portfolio-draft.ts, backend/hoc/portfolio/exposure.py, frontend/app/pages/exposures/index.tsx (Kendrick's Gemini)
BUG: Huge share counts (e.g. 1e20 to 1e305) are accepted by DraftEditor and /api/valuation without an upper bound, rendering 30+ digit unbreakable currency strings in whitespace-nowrap cells that overflow the Portfolio card and mobile viewport while silently underflowing other ETFs to 0.00% — repro: On Portfolio in Shares mode, enter 1e25 shares for IVV and 10 shares for QQQ — where: frontend/app/ui/draft-editor.tsx, frontend/app/portfolio-draft.ts, backend/hoc/portfolio/valuation.py (Kendrick's Gemini)
BUG: Navigating from the 5-step guide (#/guide) to any sidebar page (Portfolio, Exposures, Overlap, Dependencies, Compare, Risk) or pressing the browser Back button forcibly switches the user from Simple view into Full view because experience.tsx treats every hashchange leaving #/guide as opening an expert page — repro: Choose Simple view in the welcome dialog, click "5-step guide" in the top bar, then click any page in the left sidebar — where: frontend/app/experience.tsx (Kendrick's Gemini)
BUG: Returning to a previously analysed portfolio (e.g. Portfolio A -> Portfolio B -> Portfolio A) leaves Simple Dependencies and Guide Step 4 stuck on an infinite progress bar and Step 5 stuck on "waiting", because useAutoDependencies tracks started portfolio keys in a module Set and refuses to re-run A even though depsKey is now B (stale=true) — repro: In Simple view or the 5-step guide, load sample preset 1, visit Step 2/Dependencies, switch to sample preset 2, visit Step 2/Dependencies, then switch back to sample preset 1 and open Step 4/Dependencies — where: frontend/app/pages/guide/use-auto-dependencies.ts, frontend/app/pages/guide/step-4-risks.tsx (Kendrick's Gemini)
BUG: When a user already has an analysed portfolio and edits Portfolio (or Step 1) to an incomplete state or an unknown ticker (e.g. ZZZZ), Simple Exposures, Overlap, and Risk (and Guide Steps 2–3) ignore stale/error state and silently display the previous portfolio's companies and metrics with no warning; if no prior analysis exists, Simple pages show "Pick your ETFs on the Portfolio page first" instead of the analysis error — repro: Load the sample portfolio, add unknown ticker ZZZZ (pinned 10% or in % mode) on Portfolio, then click Exposures, Overlap, or Risk in Simple view — where: frontend/app/pages/simple/index.tsx, frontend/app/pages/guide/steps/own.tsx, frontend/app/pages/guide/steps/spread.tsx (Kendrick's Gemini)
BUG: In Simple view, clicking "What's here & why" on Exposures, Overlap, Dependencies, or Risk displays PAGE_INFO_COPY written for Full view, instructing the user to click table rows, heatmap cells, graph lines, citation chips, and coverage bars that do not exist on Simple pages — repro: Switch to Simple view, open Exposures, Overlap, Dependencies, or Risk, and click "What's here & why" — where: frontend/app/workspace.tsx, frontend/app/pages/guide/copy.ts (Kendrick's Gemini)
BUG: Clicking "Try this" on a Change Idea when the portfolio is in % mode calls scenario.setRows(), which forces the Scenario editor into Shares mode and rounds to whole shares of $10,000 so the Compare deltas immediately differ from the Idea card; in Shares mode with small holdings (e.g. 1 share of QQQ), rounding left-over shares keeps 1 share of the swapped-out ETF, turning a Swap idea into an Add — repro: Switch Portfolio to % mode (or enter 1 share each of IVV and QQQ), go to Compare, and click "Try this" on an idea — where: frontend/app/ui/try-a-change.tsx, frontend/app/portfolio-draft.ts (Kendrick's Gemini)
BUG: Clicking "Make this my portfolio and find its dependencies" under "More details" in Try a change only copies the scenario and sets window.location.hash = "#/dependencies" without calling runDependencies(), leaving Full-view users on a stale Dependencies page that does not run; from Guide Step 5 it also exits the guide into Full view — repro: On Compare (or Guide Step 5 -> Try a change), add an ETF with unanalysed holdings, open "More details", and click "Make this my portfolio and find its dependencies" — where: frontend/app/ui/try-a-change.tsx (Kendrick's Gemini)
BUG: On the Full Dependencies page, selectEdge() does not clear selectedNodeId, so after clicking any graph node, clicking a graph edge or citation chip opens the drawer for the edge while the graph highlight and inline "Verified Evidence for Selected Node" inspector stay locked on the old node; additionally, hovering nodes in the SVG recomputes activeNodeId and swaps the 6 inline evidence cards on every mouse move, shifting the page layout beneath the cursor — repro: On Full Dependencies, click any node in the graph, then click an edge line or citation chip (or move the mouse across nodes in the SVG) — where: frontend/app/dependencies-state.tsx, frontend/app/pages/dependencies/index.tsx (Kendrick's Gemini)
BUG: Clicking "Go deeper" or "Run again" on Dependencies sets status="starting" without clearing the previous job's status="done" and phase="done" while POST /api/dependencies is in flight, causing the progress bar to start at 100% with all three phase chips green before jumping backward when polling begins — repro: After a light dependency scan completes, click "Go deeper" or "Run again" and observe the progress bar and phase chips during job startup — where: frontend/app/dependencies-state.tsx, frontend/app/pages/guide/step-4-risks.tsx, frontend/app/pages/dependencies/index.tsx (Kendrick's Gemini)


## Open

### FIX-45 · low · BUG: on mobile, tapping the page you're already on leaves the navigation drawer open
Found by Codex during the #223 review (existing behaviour). The hash doesn't change, so no `hashchange` fires and the drawer stays open; Close works.
- Fix: close the drawer on any sidebar item click, not only on hash change.
- **Owner:** Yousuf's Codex (`workspace.tsx`) · **Status:** assigned (after FIX-41)

### FIX-40 · high · BUG: guide steps 1–3 "Learn more in the full …" links land on the Simple page
Found by Bekarys's Gemini (QA). Since #221, these links only change the hash, so they open the Simple version instead of Full view. Repro: `#/guide`, Step 1, "Learn more in the full Portfolio builder".
- Fix: use `openExpertPage(...)` in `guide/copy.ts:95`, `steps/pick.tsx:195`, `steps/own.tsx:127` and `steps/spread.tsx:151`.
- **Owner:** Yousuf's Gemini (guide) · **Status:** assigned

### FIX-41 · medium · UX: Simple-mode controls (from FIX-39)
- The top-bar switch says "Simple view / Full view" without showing which is active. Label the state clearly, e.g. "Full view" on or off, or highlight the active mode.
- Each Simple page has both "Show full detail on this page" and "Open the five-step guide" at the bottom. Keep one clear footer action per page; the guide link can live once in the walkthrough tips.
- Simple Dependencies embeds Guide Step 4, so it shows duplicate "Learn more" and "See every link and its evidence" buttons. Hide Step 4's "Learn more" when embedded (add a small prop to `step-4-risks.tsx`; lead-approved).
- **Owner:** Yousuf's Codex (`workspace.tsx`, `pages/simple/`, plus the one prop in `step-4-risks.tsx`) · **Status:** assigned

### FIX-42 · medium · UX: plain words in the info text and on the Dependencies page (from FIX-39)
- **Info banners (`guide/copy.ts`):** SEC N-PORT → "official fund reports"; 10-K/20-F → "company annual reports"; look-through → "the companies inside your ETFs"; ISIN/CIK merging → "merges share classes like GOOG and GOOGL"; HHI/1-HHI → "concentration score"; GICS → "industry breakdown".
- **Dependencies (Full view):**
  - "edges" → "links"; "counterparties" → "suppliers & partners"; "SEC 10-K / 20-F" → "annual reports".
  - Remove internal codes from the visible UI: V-INT, R-IMP, model and version chips. They can stay in a details tooltip.
  - Show "Item 1A", not "1A".
  - "Why this tier:" → "Why this matters:".
  - Drop the two-letter country chips next to country names.
- **Mobile 390px:** collapse the three rows of graph filter pills into one compact selector.
- **Owner:** Yousuf's Gemini (`guide/copy.ts`, `pages/dependencies/`) · **Status:** after FIX-40

### FIX-43 · medium · UX: plain words on Exposures, Overlap, the editor and Compare (from FIX-39)
- **Exposures:** "Look-through coverage" → "Holdings traced to companies"; "issuers" → "companies". No raw CIK/ISIN/ALIAS keys in table cells or expanded cards. Simplify or remove the "Identity" filter; the detail can sit behind a tooltip.
- **Overlap:** "Covered NAV" → "Holdings covered"; "Company level / Security level" → "Companies / Exact share classes"; "Issuers held…" → "Companies held…". No raw keys in shared-holdings rows.
- **Editor (Shares mode):** "Type a % to pin" → "Or type a % to fix this row"; make the total dollar value clear.
- **Compare / Try a change:**
  - Use the same wording for "Effective number of companies" and "Behaves like N holdings".
  - Put "Use this as my portfolio" next to "Reset to my portfolio", not only inside More details.
- Copy and presentation only; no logic or data changes.
- **Owner:** Yousuf's Codex. Lead-approved handoffs: `pages/exposures/` from Yousuf's Gemini, `pages/overlap/` from Bekarys's Gemini (busy with QA), `app/ui/draft-editor.tsx` and `app/ui/try-a-change.tsx` (Yousuf's Claude's, held by Yousuf's Gemini) · **Status:** after FIX-41

### FIX-44 · low · UX: plain words on Risk & data (from FIX-39)
- Remove the raw "HHI 0.0201 (201 pts)" from the card face (keep it in a tooltip).
- "GICS sector exposures" → "Industry breakdown"; "Line-level (>=95%)" → "From company holdings".
- Remove "layer: l1_sec_nport" and raw warning-code prefixes such as `STALE_HOLDINGS:`.
- Spell out "Excluded" and "Portfolio coverage".
- **Owner:** Gawyn's Gemini (`pages/risk/`), after FIX-36 · **Status:** queued

### FIX-38 · high · Remove the Network page; Exposures covers it (Gawyn, 09:27)
- Remove the `network` entry from `frontend/app/registry.tsx` (lead-approved edit), so it leaves the sidebar in both views. Old `#/network` links redirect to `#/exposures`.
- Delete `frontend/app/pages/network/index.tsx`, but **keep the graph helper**: `pages/simple/index.tsx` imports `buildGraph` from `../network/graph`. Move it to `frontend/app/ui/money-flow-graph.ts`, or leave `graph.ts` in place and update the import.
- Simple mode: drop the `pageKey === "network"` branch in `pages/simple/index.tsx`. If the money-flow diagram is shown only there, show it on Simple Exposures instead, so nothing useful is lost.
- Remove `PAGE_INFO_COPY.network` in `guide/copy.ts`, and any "Network" mentions in the README, DEMO and pitch deck.
- Check: `npm run build` / tsc clean; no sidebar entry; `#/network` lands on Exposures; Simple Exposures still works.
- **Owner:** Yousuf's Gemini; Codex reviews · **Status:** PR #223 passed Codex's review and the lead's browser check (no Network in either sidebar; `#/network` → Exposures on cold load and in-app; money flow on Simple Exposures). Author merges.

### FIX-36 · high · Independent proof outside the app: QQQ vs XLK overlap, and dependencies vs price history (Gawyn, 09:22)
Prove one example without the app's own code or validation.

**Part 1, overlap.**
- Download QQQ's and XLK's holdings straight from the issuers (Invesco for QQQ, State Street for XLK). Record the URL, as-of date and file hash.
- Compute the company-level weighted overlap O = Σ_c min(w_QQQ,c, w_XLK,c), as defined in `docs/hoc/CONTRACT.md` (share classes such as GOOG/GOOGL merged by issuer), plus the shared-company count and the top shared names.
- Compare with the app's 50.11% / 35 shared, and explain any gap (the app's QQQ is the N-PORT file as of 2026-06-30). Use the issuer file closest to that date if one exists.

**Part 2, dependencies vs history.**
- Hypotheses: the app's predicted links between companies in these ETFs. Use pairs where both sides have US-listed price history, ADRs included, e.g. Nvidia/AMD/Broadcom/Intel → TSMC (TSM) and Intel → ASML. Export them from an app result JSON; that's the thing being tested, not the evidence.
- Data: about 3 years of daily adjusted prices from a public source the app doesn't use (e.g. Yahoo Finance or Stooq). Record the source and dates.
- Method:
  - Take residual returns after the market (SPY) and the sector (e.g. SOXX/XLK).
  - Compare residual correlation for predicted-link pairs against matched same-sector pairs with no predicted link, using a permutation or bootstrap CI.
  - Add an event study: on the target's |z| > 2 days, check whether linked companies move the same way more often than controls.
- Report the effect sizes with CIs, honestly: correlation isn't dependency, and samples are small.

**Deliverables:**
- A new top-level `validation/` folder with a README (sources, method, results) and standalone Python that does **not** import `hoc`.
- Small raw-data snapshots, with sources and dates.
- A `results.json`.

- **Owner:** Gawyn's Gemini (new folder `validation/`) · **Status:** assigned

### FIX-37 · high · Bug hunt across the whole app; report bugs in FIXES.md (Gawyn, 09:23)
Find real bugs on current `main`, in both views and on every page:
- Portfolio inputs: empty, one ETF, an unknown ticker, shares vs %, huge numbers.
- Overlap, Network, Dependencies (Go deeper during a run, collapsing sections, the evidence drawer), Compare / Try a change / change ideas, Risk, and the Simple-mode walkthrough and guide.
- The API: validation, error codes, and cache-only paths with no key.
- Mobile width and dark mode.

For each **confirmed** bug, add one line under **New** in FIXES.md: `BUG: <what happens> — repro: <steps> — where: <page/file> (Kendrick's Gemini)`. Skip anything already in Open. Don't fix bugs; the lead assigns them. Post a short board summary every ~10 bugs or 30 minutes.

- **Owner:** Kendrick's Gemini · **Status:** assigned

### FIX-9 · medium · Final QA of both views
- Fix: once everything above merges, audit the full and simple views end to end; send problems to their owners.
- Also test with no AI key or SEC contact: page 4 must say "The AI check couldn't run on this computer" (FIX-4 was checked in code only).
- **Owner:** Bekarys's Gemini · **Status:** START NOW (FIX-34 has landed). Final pass of both views, including the new Simple walkthrough (#221) and change ideas. Add bugs under New.

## Done (checked on `main` by the lead)

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
