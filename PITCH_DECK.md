# House of Cards — Agentverse 2026 Finance Track Pitch Deck

**Track:** Finance ("Trusted Markets", supported by Jane Street) + Google DeepMind ("Best Use of Gemini")  
**Format:** 7-Slide Beginner-Friendly Deck (Gradual Progression) + 4-Minute Live Demo Script

---

## Slide 1 — The Everyday Problem: "Four Baskets, Same Eggs" (0:00–0:35)
> **What the listener needs to know:** Nothing. Starts with an everyday investing mistake.

### On-Screen Headline
**Buying four different funds feels safe—until you look inside and see they own the exact same companies.**

### The Plain-English Story
Most everyday investors don't buy individual stocks anymore. Instead, they buy **ETFs** (Exchange-Traded Funds)—baskets of hundreds of stocks sold under a single ticker—because they are told *"don't put all your eggs in one basket."*

Suppose you split your savings across four popular funds:
- **40%** in a US Top 500 fund (`IVV`)
- **25%** in a Nasdaq Tech fund (`QQQ`)
- **15%** in a Technology Sector fund (`XLK`)
- **20%** in an Emerging Markets fund (`EEM`)

| What Your Broker App Tells You | What Is Actually Happening Inside |
| :--- | :--- |
| **"You own 4 separate funds across 1,667 companies."** | **More than a third of your money (37.14%) is sitting in just 10 giant companies.** |
| **"Your risk is spread across different baskets."** | **Half of two funds (`QQQ` and `XLK`) are the exact same stocks (50.11% overlap).** |

### Speaker Cue (35s)
*"When people invest their savings, they buy three or four different funds thinking they're spreading out their risk—like putting their eggs in four separate baskets. But if you open those four baskets and count what's inside, you get a shock. In this realistic 4-fund portfolio of 1,667 companies, over 37% of your money is quietly piled into the exact same 10 companies. House of Cards opens the baskets so you can see what you really own."*

---

## Slide 2 — Step 1: Counting What You Really Own (0:35–1:15)
> **Gradual Expansion:** How we turn your fund shares into a clear list of real companies—in both **Simple View** (5-step guided flow) and **Full View**.

### What Happens on Screen
1. **Beginner-Friendly Guided Flow or Full Analyst View:**
   - First-time visitors can choose **"I'm new: guide me"** for a 5-step plain-English walkthrough (**Add your funds → What you own → How spread out you are → Hidden risks → What to do next** with interactive **"Try a change"** scenario testing), or switch anytime to **Full View**.
2. **Enter Shares, Dollars, or Percentages:**
   - You don't have to calculate percentages yourself. Type how many shares you own—say, **5 shares of `IVV`**, **4 shares of `QQQ`**, **9 shares of `XLK`**, and **34 shares of `EEM`** (or **120 shares of `IVV`** and **50 shares of `QQQ`** with `EEM` locked at **20%**).
   - The app checks the latest market closing prices, totals your portfolio (`$9,817.68` on the starter sample, or `$121,446.60` on the mixed-mode example), and automatically works out each fund's share of your money.
3. **Combining Split Company Names:**
   - Some companies sell two types of stock under two different codes—for example, Google trades as both `GOOGL` (**1.86%**) and `GOOG` (**1.60%**).
   - Basic portfolio trackers treat those as two smaller, separate companies. House of Cards recognizes they are the same business—**Alphabet (3.46%)**—revealing it is actually your **4th largest holding**.
4. **Showing Missing or Old Data Honestly:**
   - If a fund's holdings list is months old (like `QQQ`, whose public report is **130 days old**), the app puts a clear warning badge next to it instead of pretending the data is fresh.

### Speaker Cue (40s)
*"First, House of Cards meets you at your experience level—either a 5-step plain-English guide or the full analyst workspace. You type in how many shares you hold, and our code values your portfolio from real closing prices. Then it looks inside every fund and merges split stock codes: instead of listing GOOG and GOOGL as two small holdings, it combines them into Alphabet at 3.46%. And if a fund's public report is 130 days old, it tells you right on the screen."*

---

## Slide 3 — Step 2: Going Deeper—The Hidden Supply-Chain Domino Effect (1:15–2:05)
> **Gradual Expansion:** Moving from *which stocks you own* to *who those companies depend on to survive*, powered by per-company **agentic sub-agents**.

### The Next Question
Even when you own **different** companies—like **Nvidia (`6.89%`)**, **Broadcom (`2.28%`)**, **AMD (`2.04%`)**, and **Intel (`1.19%`)**—are they truly independent?
- **No:** They all rely on a single manufacturing partner in Taiwan for advanced computer chips: **TSMC (`12.39%` combined portfolio exposure)**.
- If one factory hub halts production, all four stocks fall together.

### How Our Per-Company Agentic Sub-Agents Uncover This Automatically
The truth about who supplies whom is buried inside **200-page legal annual reports** filed with the US government (SEC 10-K and 20-F reports). No human investor has time to read 15 of them—so our Gemini agents do it in three live phases (**Reading reports → Double-checking findings → Writing summary**):

```
Your Top 15 Companies ──► Official Annual Reports ──► Per-Company Gemini Sub-Agents ──► Supply-Chain Map
                           (22 reports fetched         (Initial extraction + multi-step  • 12.39% of your portfolio
                            automatically from          tool investigation across         depends on TSMC (Nvidia 6.89%
                            public SEC records)         filings; Light or "Go deeper")    + Broadcom 2.28% + AMD 2.04% + Intel 1.19%)
                                                                                         • 9.42% depends on Samsung
```

- **Multi-Step Agentic Investigation (`Light` + `"Go deeper"`):** After initial extraction, a dedicated **per-company Gemini 3.8 Flash sub-agent** investigates each company's open risk items (missing customer concentration, unnamed `>=10%` customers, and rule-flagged claims) using `find_in_filing`, `read_section`, and cross-company `search_filings`—and users can click **"Go deeper"** for a thorough multi-step pass.
- **Smart Two-Way Search:** Samsung doesn't file a US annual report of its own. A normal tool would miss it completely. Our tool searches *other* companies' reports that mention Samsung by name (like Qualcomm and Nvidia), revealing that **9.42% of your portfolio depends on Samsung**.

### Speaker Cue (50s)
*"Now here is the deeper problem. Even when you own different companies—Nvidia, Broadcom, AMD, and Intel—they all rely on the exact same chip factories. Click 'Find Dependencies', and our Gemini pipeline reads 22 official SEC reports and launches per-company agentic sub-agents that search across filings to double-check flagged claims and uncover missing customer disclosures. They reveal that 12.39% of your entire portfolio depends on TSMC across Nvidia, Broadcom, AMD, and Intel—and 9.42% depends on Samsung, which we catch even though Samsung doesn't file a US report, because other companies' reports name it as their supplier."*

---

## Slide 4 — How We Keep the AI 100% Honest (2:05–2:45)
> **Gradual Expansion:** Addressing the biggest worry in finance AI—*"What if the AI makes things up?"*

### Three Simple Safety Rules Enforced by Code
In finance, a wrong number is worse than no number. We built **strict code guardrails** so the AI can never invent a fact or a number:

| Safety Rule | How It Works in Plain English | What You See on Screen |
| :--- | :--- | :--- |
| **1. Word-for-Word Quote + Semantic Check** | Every time the AI claims Company A depends on Company B, it must provide the **exact sentence** from the official annual report. Our code checks the report character-by-character, and our **V-INT** verifier checks that the quote isn't a competitor mention, negation, or divestiture. If it fails, **code deletes it**. | Click any link on the map to read the exact quote, the page section, the agentic step trace, and open the official government filing. |
| **2. AI Never Touches a Calculator** | The AI is **banned from writing numbers**. Regular Python code calculates every dollar value and percentage, and fills them into blank slots (`12.39%`, `9.42%`). Both the full summary and the beginner plain-English cards are verified so any unquoted digit is **automatically rejected**. | An **Audit Bar** and **Coverage Panel** show how many links were verified (`139` on the development portfolio) and how many AI claims were rejected. |
| **3. Hard Stop on Missing Prices & Advice** | If a fund is missing a valid US dollar price, the app **pauses and asks you to set its percentage** rather than guessing `$0`. And if the AI ever tries to say *"buy"* or *"sell"*, code blocks it immediately. | Clear warning banners and a blocked state until a human approves the input. |

### Speaker Cue (40s)
*"Why would you trust an AI with financial analysis? Because we never let the AI do the math or invent a claim. Every supply-chain link must include a word-for-word quote from the official report—our code checks the text verbatim and runs a semantic check to filter out competitor or divestiture mentions. And every percentage is calculated by regular Python code, never by the AI."*

---

## Slide 5 — Proving It Works: Quantitative Evaluation on Unseen Filings, Real Portfolios & Synthetic Traps (2:45–3:25)
> **Rubric & Organiser Proof:** Rigorous quantitative evaluation on **10 held-out unseen 10-Ks** (blindly annotated by two independent annotators), plus real-world portfolio benchmarks and synthetic trap suites.

| Test Scenario | What Data We Used | What We Compared Against | Quantitative Result |
| :--- | :--- | :--- | :--- |
| **Test 1 (Headline): Unseen 10-K Benchmark (`docs/hoc/EVAL.md`)** | **10 held-out SEC 10-K filings** across 5 non-tech industries (`NKE`, `F`, `GM`, `BA`, `SWKS`, `QRVO`, `GLW`, `PFE`, `DE`, `SBUX`), frozen before prompt tuning | **222 gold relationships** (`115` core + `107` extended) & **79 hard negatives** from **two blind human annotators** (inter-annotator agreement F1 `0.49`) | • **88.4% [83.2%, 92.5%]** micro precision against initial blind gold (`114/129`).<br>• **96.1% [89.6%, 100.0%]** pooled precision (`124/129`).<br>• **57.4% [35.3%, 76.0%]** core recall (`66/115`), **100.0%** direction accuracy (`124/124`), **100.0%** facility-country accuracy (`39/39`).<br>• **1.3% (1/79)** hard-negative false-positive rate. |
| **Test 2: Real Portfolio Math Check** (`IVV`, `QQQ`, `XLK`, `EEM` — 1,667 companies) | **Real published fund holdings** and closing prices + our **development portfolio** (Top 15 companies, 22 SEC filings) | Independent commercial calculator ([TickerInside](https://tickerinside.com/)) & standard portfolio trackers | • Matched every single-stock percentage to within **0.0003 percentage points** (`AAPL` `7.3659%` vs. `7.3656%`) and caught the **Alphabet (`3.46%`)** split-class blind spot.<br>• On the development portfolio (`us-core-tilt`), extracted **139 verified links**, uncovering **12.39% TSMC** and **9.42% Samsung** exposure with **100% verbatim quotes**. |
| **Test 3: Synthetic "Trap" Data Suite** (Controlled stress test) | **Synthetic test portfolios** + **deliberately faked AI outputs** (made-up quotes, fake `99.99%` numbers, outside stocks, and "sell" orders) | An unchecked AI chatbot | • **100% of fake or altered quotes** were caught and blocked by code.<br>• **100% of invented numbers and trading instructions** were blocked before reaching the screen. |

### Speaker Cue (40s)
*"We proved this works quantitatively across three scenarios. First, our headline test on 10 unseen annual reports outside our development portfolio—blindly annotated by two independent annotators with 79 hard-negative traps: we achieved 88.4% blind precision, 96.1% pooled precision, 57.4% core recall, 100% direction accuracy, and only 1 false positive across 79 hard negatives. Second, on real ETF holdings across 1,667 companies, our math matches an independent commercial benchmark to within three ten-thousandths of a percent—and on our 4-ETF development portfolio, it uncovers 12.39% TSMC and 9.42% Samsung exposure across 139 verified quotes. Third, our synthetic trap suite feeds the verifier fake quotes and invented numbers, blocking 100% of them."*

---

## Slide 6 — Repeatability: Same Portfolio, Same Answer Every Time (3:25–3:45)
> **Organiser Repeatability Requirement:** Why any user or judge gets consistent, repeatable results across runs.

1. **Zero Drift in the Math:**
   - Because standard Python code—not an AI—computes every weight, overlap score, diversification verdict (combining company HHI and top industry share), and dependency percentage, running the same portfolio 100 times gives the **exact same numbers 100 times (0% variation)**.
2. **Smart Local Saving (Instant Replay):**
   - Official annual reports never change once published. Once a report and its agentic sub-agent investigation are checked, the verified quotes and step traces are saved on disk.
   - Clicking a portfolio a second time—or running in **Offline Mode** without an internet connection or API key—replays the full analysis in **under 1.5 seconds** at **$0 cost**.
3. **Automatic Backup Model:**
   - If the primary AI model (`Gemini 4 Argon`) hits a busy rate limit during live synthesis, the system automatically switches to `Gemini 3.8 Flash` so a run never crashes.

```bash
# Anyone can re-run our unseen-10-K evaluation, verification tests, and portfolio analysis:
cd backend && uv run pytest
uv run hoc eval
HOC_OFFLINE=1 uv run python -m hoc.cli analyse --example us-core-tilt
```

---

## Slide 7 — Honest Limits & Summary (3:45–4:00)
> **Closing with Trust:** A tool you can trust tells you what it *cannot* see.

### What House of Cards Does Not Claim to Do (Shown Live on Screen)
- **Only Sees Public Disclosures (40% Verified Portfolio Weight):** Companies only reveal so much in public filings. For instance, Apple and Microsoft do not name their individual component suppliers in their annual reports (`16.7%` filed with no named suppliers/customers), and big customers are often listed anonymously (*"Customer A — 22% of revenue"*). Our Coverage Panel shows that **40.0%** of the portfolio has verified supplier/customer disclosures (`56.7%` analysed total) and never guesses the rest.
- **Reports Are Snapshots in Time:** Annual reports come out once a year, and some fund disclosures come out quarterly. Every link and fund row displays its **exact publication date** so you never mistake old data for live news.
- **Visibility, Not Trading Advice:** House of Cards is an X-ray for your portfolio—including an interactive **"Try a change"** side-by-side comparison and verified **Change ideas** (e.g., swapping `XLK` and part of `QQQ` into `30% VTV` cuts TSMC dependency from **12.39% → 6.30%, −6.10 pts**, and adding `+20% XLU` dilutes it from **12.39% → 9.92%, −2.48 pts**)—it never trades your money and never gives buy or sell advice.

### 10-Second Judge Recap
| Question | Our Answer |
| :--- | :--- |
| **Who is it for?** | Both everyday ETF investors (**5-step Simple View + Try a change**) and analysts (**Full View**) who want to see true company concentration and supply-chain risk. |
| **Why is it trustworthy?** | Python does 100% of the math; Gemini extraction + per-company agentic sub-agents read SEC reports, and every quote and number is verified by code. |
| **How is it proven?** | Evaluated on **10 unseen 10-Ks** (`88.4%` blind / `96.1%` pooled precision, `57.4%` core recall, `100%` direction, `1/79` hard-neg FP), cross-checked within `0.0003%` on 1,667 stocks, and `100%` trap-tested. |
