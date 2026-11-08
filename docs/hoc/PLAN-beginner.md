# Beginner mode (guided view)

Lead: Gawyn's Claude. Umbrella issue #28. Assignments are on the board (roll call, 2026-11-08).

## Context
The app is built for experienced users:
- 8 pages, about 13,000 px of Dependencies detail;
- jargon such as HHI, GICS, 10-K, look-through and CIK;
- shares, pinning and evidence drawers.

Gawyn wants a beginner-friendly version.
- **At launch** the site asks whether you're experienced.
- **"No"** gives a streamlined guided experience without the clutter.
- **"Yes"** gives the full app as today.

The work goes to other agents, after a roll call to see who's available. My part is design, approvals and verification.

**Decisions (Gawyn):**
- **Guided steps** (a walkthrough with Next and Back), not one page.
- **The AI supply-chain check always runs** in the beginner flow, with no button.
- **Ask every time the site opens.** The answer isn't remembered across reloads. A "Simple view / Full view" switch stays available.

## UX design
1. **Launch dialog (every load).** A Modal that can't be dismissed without a choice, keyboard accessible.
   - Title: "Welcome to House of Cards".
   - Question: "Have you analysed an ETF portfolio before?"
   - Two large buttons: **"I'm new: guide me"** (→ beginner) and **"I'm experienced: show everything"** (→ full app).
   - A one-line description under each.
2. **Mode switch.** The top bar has a `Switch`, "Simple view / Full view", in both modes. Switching keeps the portfolio, because `AnalysisProvider` already holds it.
3. **Beginner layout** (`#/guide`):
   - no sidebar or 8-page nav;
   - a slim top bar with the logo, "Step N of 5" and the switch;
   - one centred column (max width ~720px);
   - big Next and Back buttons;
   - a `ProgressBar` (`components/base/progress/progress.tsx`).
4. **Steps.** One idea per screen and no more than 2 short sentences per card. Every number is formatted with `formatPct` / `<Pct>` (`app/ui/pct.tsx`).
   1. **Pick your ETFs.** "Use a sample portfolio" (one click) or "Enter my own": ticker + % rows in percent mode only, with "Split evenly"; shares mode is hidden. Includes a one-line explainer: "An ETF is a basket of companies".
   2. **What you really own.** The top 5 companies as sentences ("7.4% of your money ends up in Apple, through 3 of your ETFs"), plus one overlap sentence for the most-overlapping ETF pair.
   3. **How spread out is it?** One verdict chip (Diversified / Moderately concentrated / Highly concentrated), "Your 10 biggest companies are 37% of your money", "It behaves like about 50 equal holdings", and the top 3 sectors.
   4. **Hidden risks.** The AI check is already running from step 2 (see Data). Shows a friendly progress line ("Reading 15 company annual reports…"), then:
      - 3 plain findings: the biggest dependency ("12% of your money relies on TSMC"), the biggest factory country, and how much we could check ("We could check 40% of your portfolio");
      - the AI's top 2 flaws as plain cards (title + text, no citation chips).
   5. **What could you do?** The AI's top 2 suggestions, plus three buttons: "Try a change" (→ Full view `#/compare`), "See everything" (→ Full view `#/dependencies`) and "Start over".
5. **Words we never show beginners:** HHI, GICS, look-through, 10-K/20-F, CIK, metric ids, "edges", tier names, "orchestrator". Every step has a small "Learn more" link that switches to Full view on the matching page.

## Data and architecture (frontend only; no backend or contract change)
- **Reuse:**
  - `useAnalysis()` (`app/analysis.tsx`): `rows`, `setRows`, `status`, `analysis.exposures`, `.overlap`, `.concentration`, `.sectors`, `.coverage`. Analysis already runs 400 ms after valid edits.
  - `api.examples()`, plus the example-loading pattern in `app/pages/portfolio/index.tsx:101-108`.
  - `DraftEditor` (`app/ui/draft-editor.tsx`), in percent mode.
  - `useDependencies()` / `runDependencies(topN)` (`app/dependencies-state.tsx`), a module store that works without its provider.
  - `buildMetricCards` / `metricCitationLabel` (`app/pages/dependencies/metrics.ts`) and `result.coverage` for the risk findings.
  - `Modal`, `Switch`, `Button`, `Chip`, `ProgressBar` from `components/base/`.
- **Always-run AI:** when step 2 first renders with `status === "ready"`, the guide calls `runDependencies(DEFAULT_TOP_N)` once per analysed portfolio key, in the background. Step 4 shows progress or the result. If the AI isn't configured or errors, step 4 says so in plain words and lets the user continue; it never blocks.
- **The verdict helper** `hhiRating()` moves from `pages/risk/index.tsx:155` to `app/ui/concentration.ts`, so the risk page and the guide share it.
- **New files:**
  - `app/experience.tsx`: `ExperienceProvider` / `useExperience()`. `mode` is `"beginner" | "expert" | null`, in memory only (asked every load). `null` shows the dialog.
  - `app/onboarding/welcome-dialog.tsx`
  - `app/pages/guide/index.tsx`: the stepper, with `GuideStepProps { onNext(); onBack() }` and a `steps` array.
  - `app/pages/guide/steps/{pick,own,spread,risks,next}.tsx`
  - `app/pages/guide/copy.ts`: all beginner strings in one place.
- **Edited files:**
  - `app/main.tsx`: wrap `<Workspace/>` in `ExperienceProvider` and render `WelcomeDialog`.
  - `app/workspace.tsx`: the beginner layout and the top-bar switch; the default route is `#/guide` in beginner mode.
  - `app/registry.tsx`: add a `guide` entry, filtered out of the expert nav.

## Packages and owners (Refs #28; one worktree each; small PRs)

| Package | Scope | Default owner | Fallback |
|---|---|---|---|
| B-SHELL | `experience.tsx`, `welcome-dialog.tsx`, `main.tsx` + `workspace.tsx` mode layout and switch, registry `guide` entry, `app/ui/concentration.ts` (move `hhiRating`) | Gawyn's Gemini (built G-UI v3; owns the risk page) | Yousuf's Gemini |
| B-GUIDE | `pages/guide/index.tsx` stepper + `copy.ts` + steps 1–3 (`pick`, `own`, `spread`); stub files for steps 4–5, merged early so B-RISKS doesn't conflict | Yousuf's Gemini (exposures and dependencies UI) | Kendrick's Claude |
| B-RISKS | Steps 4–5 (`risks.tsx`, `next.tsx`) + the always-run trigger in step 2 (a hook in `pages/guide/use-auto-dependencies.ts`) | Kendrick's Claude if the roll call confirms, else Gawyn's Gemini after B-SHELL | Gawyn's Gemini |
| B-QA | End-to-end on both modes against the live backend; the final audit | Bekarys's Gemini | Yousuf's Codex |
| B-DOCS | A beginner-mode section in README + DEMO (added to held PR #132) | Gawyn's Gemini | — |

Handoffs (lead-approved, posted with the assignments):
- `main.tsx` and `workspace.tsx` belong to Yousuf's Claude (out until 06:20).
- `registry.tsx` entries are mine.

**Order:**
1. B-SHELL and B-GUIDE start in parallel. B-GUIDE merges its scaffold and stubs within about 15 minutes.
2. Then B-RISKS.
3. Then B-QA and B-DOCS.

**Parallel track (unchanged):**
1. PR #143 (the A-RES research loop) gets its Codex and Bekarys's Gemini re-review of `fe95ef7`.
2. Then my live 3-item check, then merge.
3. Then the final v3 audit, which B-QA folds in.

## Verification (me, after each merge)
- `cd frontend && npm run build`, so `tsc -b` and `vite build` pass. Backend tests are unaffected.
- **In the browser** (in-app preview; backend restarted on main):
  - Reload → the dialog appears every time.
  - "I'm new" → `#/guide` with no sidebar.
  - Sample portfolio → steps 1–5 in order.
  - Step 4 shows AI findings, which come from cache and are fast for the example.
  - No jargon words appear (scripted text scan for the forbidden list).
  - The switch to Full view mid-flow keeps the portfolio. The switch back returns to the same step.
  - "I'm experienced" → today's full app, unchanged apart from the switch.
- **Own ETFs path:** enter 2 tickers, "Split evenly", and the steps work. The AI step shows progress, then results or a friendly fallback.
- **Mobile:** a 360px viewport with no horizontal scroll, keyboard-only through the dialog and steps, and no console errors.
- **No key:** temporarily unset `GEMINI_API_KEY` on a side backend (port 8001) → step 4 shows the friendly message and Next still works.
