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
- `PITCH_DECK.md` already describes a multi-step investigation; this fix makes that true.
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

### FIX-20 · high · Compare overstates drops: each side counts a different set of companies
Found by the lead in the FIX-17 live check. Compare (Try a change and change ideas) measures each portfolio on its own top-15 companies. A TSMC-dependent company that falls out of the new portfolio's top 15 (e.g. Intel after adding 20% XLU) stops counting, so the drop looks bigger than it is.
- **Adding 20% XLU:** shows TSMC 12.5% → 9.0%. With a 30-company window it is 9.9%, about what pure dilution gives.
- **The XLK → VTV swap in README, DEMO and the pitch deck:** shows "12.39% → 4.69%". With a 30-company window it is 12.89% → 6.30%.
- Fix: measure both sides on the same company set, the union of both portfolios' top-N companies, so a company counts on both sides at its own weight. Unanalysed companies stay "not checked yet". Add a test where a dependent company drops out of one side's top N.
- Then update the 12.39% → 4.69% figure everywhere it's quoted (README, DEMO, PITCH_DECK).
- **Owner:** Yousuf's Codex (`portfolio/compare.py`, `portfolio/ideas.py`), then Gawyn's Gemini (docs numbers) · **Status:** assigned

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
- **Owners:** Gawyn's Gemini (proposer) + Yousuf's Codex (verifier, contract, FIX-20 first) + Bekarys's Claude (UI) · **Status:** assigned; the rules-only version is merged (#177–#179)

### FIX-19 · low · Progress bar can stick at 100% when a finished scan is re-run
Found by Yousuf's Claude in review of #174. The backend reuses the job_id when a cached replay is upgraded to a live run, so the "never go down" rule keeps showing 100% until the new run ends.
- Fix: reset the shown maximum when the job's status goes from done/error back to queued/running (or key it on job_id plus a run counter).
- **Owner:** Yousuf's Gemini · **Status:** assigned

### FIX-8 · medium · The evaluation doesn't show the effect of the research agents
- Fix: after FIX-1 and FIX-2 merge, run `uv run hoc eval --live` with light agents. EVAL.md then reports precision and recall before vs after the agents, with confidence intervals. Do no tuning on the 10 held-out companies.
- Also add an agentic acceptance check to `hoc eval`. From a result it reports tool calls per finding, `search_filings` use, whether thorough contains light, and duplicate `unnamed_customer` links, so FIX-1, FIX-2 and FIX-14 are judged by numbers.
- **Owner:** Bekarys's Gemini (A3) · **Status:** acceptance check now; live eval when FIX-1, FIX-2 and FIX-14 merge (branch `28-fix-8-eval-agentic`)

### FIX-9 · medium · Final QA of both views
- Fix: once everything above merges, audit the full and simple views end to end; send problems to their owners.
- Also test with no AI key or SEC contact: page 4 must say "The AI check couldn't run on this computer" (FIX-4 was checked in code only).
- **Owner:** Bekarys's Gemini · **Status:** in progress. QA what's already merged now, and re-check each new merge.

### FIX-11 · low · Research findings appear only when the scan ends
The plan asked for the research trace to show live during the run.
- Fix:
  - The job exposes findings as each agent finishes.
  - The Dependencies page and simple page 4 show them.
- **Owner:** Bekarys's Claude (job; adds `DependencyJob.research`, lead-approved) + Yousuf's Gemini (pages) · **Status:** pages merged (#170); job part starts now if A1-fix keeps the `research_company` return type

## Done (checked on `main` by the lead)

- FIX-7 README and DEMO cover v3.1 (shares default, simple view, Try a change, change ideas "coming") with verified numbers — #132. The FIX-8 numbers follow in a small PR from Gawyn's Gemini.
- FIX-18 progress bar never goes down: the total is set up front and only lowered (live: 106 → 100 → 65; 0% → 15% → 98% → 100%), and the pages never show a lower % — #172, #174
- FIX-16 screen 2 names the most overlapping pair (QQQ and XLK, 50.11%) — #174
- FIX-15 simple screen 1 is shares only, with % as plain text; the full view keeps the switch — #175
- FIX-10 plain titles match their text (live: "Heavy reliance on Taiwan Semiconductor Manufacturing") — #173
- FIX-6 pitch deck leads with the held-out eval (88.4% / 96.1% precision, 57.4% recall, 1 of 79), 40% verified coverage — #167
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
