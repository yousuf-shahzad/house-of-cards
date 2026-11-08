# House of Cards: 3-minute demo script

Numbers below are from live runs on 2026-11-07/08 (holdings disclosed 2026-11-05, QQQ 2026-06-30; prices are
the 2026-11-06 closes). They change with new disclosures, and the AI extraction can vary a little between
runs, so **read the numbers off the screen**, not this page.

## Before the demo

1. **Settings, in your own shell (never committed):** `HOC_SEC_CONTACT="Your Name you@example.com"` (SEC requires a
   contact) and `GEMINI_API_KEY=...` (the event key). Without them the Dependencies page shows cached results only.
2. **Warm the holdings cache** from `backend/`: `uv run python -m hoc.cli warm` and
   `uv run python -m hoc.cli warm --example global-core`.
3. **Start** `uv run uvicorn hoc.api.app:app --port 8000` in `backend/` and `npm run dev` in `frontend/`, then open
   http://localhost:5173.
4. **Run Find dependencies once** on the US core example (Portfolio -> Load "US core with a tech tilt" ->
   Dependencies -> Find dependencies). A cold run takes about 2 minutes; after that it replays from the disk
   cache, and the API's start-up warm-up replays it too. Don't do the cold run live.

## The walkthrough

- **0:00, the problem (Portfolio):** Load **US core with a tech tilt** (IVV 40 / QQQ 25 / XLK 15 / EEM 20). Four
  ETFs look diversified, yet **37.14%** of the money sits in just 10 companies (49.8 effective companies out of
  1,667).
- **0:20, what you really own (Exposures):** Apple **7.37%**, Nvidia **6.89%** and Microsoft **5.60%**, each through
  3 ETFs. Expand **Alphabet (3.46%)**: GOOGL and GOOG merged into one company. Samsung common and preferred merge
  the same way (1.43%).
- **0:40, the hidden overlap (Overlap):** IVV x QQQ share **48.82%** of their weight; QQQ x XLK **50.11%**.
- **0:55, honest data (Risk & data):** **99.93%** of the portfolio is covered, and the sources table flags QQQ's
  holdings as **130 days old** (SEC N-PORT of 2026-06-30). Every number has a source and a date.
- **1:10, enter shares, not percentages (Portfolio):** Switch to **Shares**: IVV **120**, QQQ **50**, and pin EEM
  at **20%**. Valued at the latest exchange closes: **$121,446.60**, IVV **58.39%**, QQQ **21.61%**, EEM **20%**.
  Unpinned rows rescale around the pinned one; the analysis updates on every page.
The Dependencies page reads top to bottom: audit & coverage bar, AI synthesis, key numbers, graph, facilities, and **Investigate gaps**.

- **1:35, go one level deeper (Dependencies, audit & coverage bar):** Load the US core example again and open
  **Dependencies**. Find dependencies read the latest 10-K/20-F of the top 15 companies (14 had one; Samsung has
  no SEC filing) plus other companies' filings that name them: **139 verified links from 22 filings**.
  - **Honest 100% coverage bar (v3):** **40.43%** verified (13 companies), **1.50%** analysed with no named
    dependencies (Meta), **1.43%** no SEC filing (Samsung, reached via reverse links), and **56.64%** outside the
    top-15 cutoff — with per-ETF verified shares (**XLK 63% / QQQ 52% / IVV 37% / EEM 15%**) and plain-English
    coverage gaps.
  - **Interpretation verification (v3):** Every quote is checked word for word against its filing and scanned by
    deterministic rules on ±300 characters of context, with an independent Flash judge reviewing every
    rules-flagged edge plus a 20% sample of unflagged edges: **137 confirmed, 1 rejected, 1 flagged** (`AMD ->
    Sanmina` rejected because *"we sold the ZT Manufacturing Business to Sanmina"* is a divestiture, not supply;
    `Nvidia -> OpenAI` flagged as tentative because the 10-K says *"agreement being finalized... no assurance"*).
- **1:55, the AI synthesis:** read one **critical flaw** and one **diversification idea**. Every number in them is a
  Python metric (`hoc-orch-v3.0`, **0 rejected claims**); a claim with any other number is dropped automatically.
- **2:10, relationship importance & single points of failure (key numbers):** Every edge is scored deterministically
  into **28 critical / 71 high / 37 medium / 3 low** (all foundries and contract manufacturers are `critical`; TSMC
  fabs are `high`; corporate HQs like Nvidia and Alphabet are `low`; customers scale by revenue share, e.g. 22% ->
  `critical`, 13% -> `high`; flagged tentative edges are capped at `medium`). **12.39%** of the portfolio is
  **critically dependent** on **TSMC** (`critical.ALIAS:TSMC = 12.39%`) through 4 companies, and **9.42%** depends
  on Samsung via reverse links. Facility concentration by country places **188 of 189** cached facility edges into
  canonical ISO-2 countries (**US 35.77%**, **China 19.03%**), leaving only region-only `"Asia"` unplaced.
- **2:25, prove it & investigate gaps (graph + research loop):** click a TSMC edge to open the evidence drawer
  (verbatim quote, section, form, filing date, importance tier/reasons, interpretation badge, and SEC link). Click
  **Investigate gaps** (`A-RES`) to run the bounded agentic research loop over SEC filings for flagged edges,
  undisclosed customers ($\ge 10\%$ revenue), and zero-disclosure holdings — on `us-core-tilt` (`~65 s` live, instant
  from replay cache), `Nvidia -> OpenAI` stays `unresolved` (agreement not final), four unnamed big customers are
  confirmed with verbatim passages (Nvidia 22%, Apple 13%, Broadcom 32%, Micron 17%), and anonymised table rows like
  TSMC's `Customer A` are normalised to `Unnamed customer (Customer A)` (`unnamed_customer`), while keeping the Argon
  AI synthesis intact.
- **2:40, act on it (Compare):** open **Compare** (`#/compare`). The Scenario is seeded from your current portfolio
  (`IVV 40 / QQQ 25 / XLK 15 / EEM 20`). Cut `QQQ` to **10%**, remove `XLK`, and add **VTV 30%** (`IVV 40 / QQQ 10 /
  VTV 30 / EEM 20`), then click **Compare**. Instantly (cache-only, zero Gemini or SEC calls):
  - **TSMC dependency drops from 12.39% to 4.69% (-7.71 pts)**.
  - **Top-10 concentration drops from 37.14% to 24.98%**, and **effective companies more than double from 49.8 to 107.0**.
  - Unanalysed scenario holdings are listed explicitly, with a one-click button to make the scenario your active portfolio.

## Beginner Mode (Guided View, `#/guide`)

On every page load, a welcome modal asks **"Have you analysed an ETF portfolio before?"** with two choices:
- **"I'm new: guide me"** opens the 5-step guided view (`#/guide`) with no sidebar, a slim top bar (`Step N of 5` + **Simple view / Full view** switch), and plain-English cards (zero jargon: no `HHI`, `GICS`, `look-through`, `10-K`/`20-F`, `CIK`, metric IDs, `"edges"`, tier names, or `"orchestrator"`):
  1. **Step 1 — Pick your ETFs:** Opens in **shares** by default (with a `%` toggle). Load a sample portfolio in one click (valued as whole shares worth ~$10,000 at latest exchange closes) or enter your own ETFs.
  2. **Step 2 — What you really own:** Top 5 companies as plain sentences (*"7.37% of your money ends up in Apple, through 3 of your ETFs"*) plus one sentence for the most-overlapping ETF pair (*"IVV and QQQ overlap by 48.82%"*). Entering Step 2 automatically starts the agentic supply-chain check (`light` depth by default) in the background.
  3. **Step 3 — How spread out is it?:** Combined company + industry concentration verdict chip (**Concentrated in one industry** when the top industry is $\ge 40\%$, matching the full Risk page and noting that **50.64%** sits in **Technology**), *"Your 10 biggest companies are 37.14% of your money"*, *"It behaves like about 50 equal holdings"*, and the top 3 industries.
  4. **Step 4 — Hidden risks:** Shows a phased progress bar (*"Reading reports -> Double-checking findings -> Writing summary"*) and live/cached results from the background supply-chain check — 3 plain findings (biggest supplier dependency **12.39% on TSMC**, biggest non-US factory country **China 19.03%**, and checked portfolio share **40.43%**), concise `plain_title` + `plain_text` AI cards (with **Read more** for full detail), and a **Go deeper** option (`thorough` depth).
  5. **Step 5 — What could you do?:** The AI's top 2 diversification suggestions (`plain_title` + `plain_text`) plus three actions: **Try a change** (opens the real-time before/after comparison right inside the simple view, showing 4 headline rows including `top_sector`), **See everything** (switches to Full view on `#/dependencies`), and **Start over**.
- **"I'm experienced: show everything"** opens the full 7-page dashboard above. Toggling the top-bar **Simple view / Full view** switch mid-flow keeps the active portfolio and returns to the same step when switching back.

## Running the v3 Gold Evaluation Benchmark

From `backend/`:

```bash
uv run hoc eval          # offline replay (default): reproduces all numbers in docs/hoc/eval/results.json with zero API calls
uv run hoc eval --live   # full extraction + judge evaluation over the 10 held-out 10-Ks (115 core + 107 extended + 79 hard negatives)
```

Headline benchmark numbers ([`docs/hoc/EVAL.md`](EVAL.md)): **88.4% [83.2%, 92.5%]** blind precision (**96.1% [89.6%, 100.0%]** pooled precision, 124/129; blind F1 **69.6% [51.9%, 82.7%]**, pooled F1 **71.9% [53.3%, 85.1%]**), **57.4% [35.3%, 76.0%]** core recall (66/115; inter-annotator F1 = **0.49**), **1.3% [0.0%, 3.9%]** hard-negative false-positive rate (**1/79**), **100.0%** direction accuracy (124/124), **100.0%** facility-country accuracy (**39/39**), and importance-tier quadratic weighted Cohen's $\kappa = \mathbf{0.475\ [0.382,\ 0.631]}$ (54/79). (On the 10 held-out filings V-INT filtered **0** edges beyond quote verification; its live contribution is on `us-core-tilt`, where it rejected the `AMD -> Sanmina` divestiture and flagged the tentative `Nvidia -> OpenAI` disclosure.)

## If something goes wrong

- **"sec_contact_missing" / "missing_api_key" on Dependencies:** the setting isn't in the shell that started the
  API. Cached results still show; restart the API from a shell with the variables set.
- **A row says "No price, enter a %":** that fund has no usable close (or isn't in USD). Pin it to a %.
- **No network:** start the API with `HOC_OFFLINE=1`; everything warmed above still works.
