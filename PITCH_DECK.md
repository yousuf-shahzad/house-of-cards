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
> **Gradual Expansion:** How we turn your fund shares into a clear list of real companies.

### What Happens on Screen
1. **Enter Dollars, Percentages, or Shares:**
   - You don't have to calculate percentages yourself. Type how many shares you own—say, **120 shares of `IVV`** and **50 shares of `QQQ`**—and lock `EEM` at **20%**.
   - The app checks the latest market closing prices, totals your portfolio at **$121,446.60**, and automatically works out each fund's share of your money.
2. **Combining Split Company Names:**
   - Some companies sell two types of stock under two different codes—for example, Google trades as both `GOOGL` (**1.86%**) and `GOOG` (**1.60%**).
   - Basic portfolio trackers treat those as two smaller, separate companies. House of Cards recognizes they are the same business—**Alphabet (3.46%)**—revealing it is actually your **4th largest holding**.
3. **Showing Missing or Old Data Honestly:**
   - If a fund's holdings list is months old (like `QQQ`, whose public report is **130 days old**), the app puts a clear warning badge next to it instead of pretending the data is fresh.

### Speaker Cue (40s)
*"First, House of Cards does the foundational accounting. You can type in how many shares you hold, and our code values your portfolio from real closing prices—here, $121,446.60. Then it looks inside every fund and merges split stock codes: instead of listing GOOG and GOOGL as two small holdings, it combines them into Alphabet at 3.46%. And if a fund's public report is 130 days old, it tells you right on the screen."*

---

## Slide 3 — Step 2: Going Deeper—The Hidden Supply-Chain Domino Effect (1:15–2:05)
> **Gradual Expansion:** Moving from *which stocks you own* to *who those companies depend on to survive*.

### The Next Question
Even when you own **different** companies—like **Apple**, **Nvidia**, **AMD**, and **Broadcom**—are they truly independent?
- **No:** None of them own the factories that make their most advanced computer chips. They all rely on a single manufacturing partner in Taiwan: **TSMC**.
- If one factory hub halts production, all four stocks fall together.

### How Our AI Agents Uncover This Automatically
The truth about who supplies whom is buried inside **200-page legal annual reports** filed with the US government (SEC reports). No human investor has time to read 15 of them—so our AI agents do it:

```
Your Top 15 Companies ──► Official Annual Reports ──► Gemini AI Readers ──► Supply-Chain Map
                           (22 reports fetched         (Finds suppliers,     • 12.39% of your portfolio
                            automatically from          chip factories,       depends on TSMC (via 4 companies)
                            public SEC records)         and customers)      • 9.42% depends on Samsung
```

- **Smart Two-Way Search:** Samsung doesn't file a US annual report of its own. A normal tool would miss it completely. Our tool searches *other* companies' reports that mention Samsung by name (like Qualcomm and Nvidia), revealing that **9.42% of your portfolio depends on Samsung**.

### Speaker Cue (50s)
*"Now here is the deeper problem. Even when you own different companies—Apple, Nvidia, AMD, Broadcom—they all rely on the exact same chip factories. Those dependencies are hidden inside 200-page annual reports. Click 'Find Dependencies', and our Gemini AI agents read 22 official reports in parallel. They reveal that 12.39% of your entire portfolio depends on a single company—TSMC—and 9.42% depends on Samsung, which we catch even though Samsung doesn't file a US report, because other companies' reports name it as their supplier."*

---

## Slide 4 — How We Keep the AI 100% Honest (2:05–2:45)
> **Gradual Expansion:** Addressing the biggest worry in finance AI—*"What if the AI makes things up?"*

### Three Simple Safety Rules Enforced by Code
In finance, a wrong number is worse than no number. We built **strict code guardrails** so the AI can never invent a fact or a number:

| Safety Rule | How It Works in Plain English | What You See on Screen |
| :--- | :--- | :--- |
| **1. Word-for-Word Quote Check** | Every time the AI claims Company A depends on Company B, it must provide the **exact sentence** from the official annual report. Our code checks the report character-by-character. If the quote isn't there word-for-word, **code deletes it**. | Click any link on the map to read the exact quote, the page section, and open the official government filing. |
| **2. AI Never Touches a Calculator** | The AI is **banned from writing numbers**. Regular Python code calculates every dollar value and percentage, and fills them into blank slots (`12.39%`, `9.42%`). If a summary sentence contains any number not calculated by code, **that sentence is deleted**. | An **Audit Bar** at the top of the page shows how many links were verified (139) and how many AI claims were rejected. |
| **3. Hard Stop on Missing Prices & Advice** | If a fund is missing a valid US dollar price, the app **pauses and asks you to set its percentage** rather than guessing `$0`. And if the AI ever tries to say *"buy"* or *"sell"*, code blocks it immediately. | Clear warning banners and a blocked state until a human approves the input. |

### Speaker Cue (40s)
*"Why would you trust an AI with financial analysis? Because we never let the AI do the math or invent a claim. Every supply-chain link must include a word-for-word quote from the official report—our code checks the text and deletes anything that doesn't match verbatim. And every percentage is calculated by regular Python code, never by the AI. The Audit Bar at the top even shows you how many unverified AI claims our code rejected."*

---

## Slide 5 — Proving It Works: 3 Quantitative Tests (Real & Synthetic Data) (2:45–3:25)
> **Rubric & Organiser Proof:** Showing quantitative proof that the tool works across both real-world data and synthetic "trap" data.

| Test Scenario | What Data We Used | What We Compared Against | Quantitative Result |
| :--- | :--- | :--- | :--- |
| **Test 1: Real Portfolio Math Check** (`IVV`, `QQQ`, `XLK`, `EEM` — 1,667 companies) | **Real published fund holdings** and closing prices | An independent commercial portfolio calculator ([TickerInside](https://tickerinside.com/)) | • Matched every single-stock percentage to within **0.0003 percentage points** (`AAPL` `7.3659%` vs. `7.3656%`).<br>• Caught the **Alphabet (`3.46%`)** split-stock blind spot that ticker-only calculators miss.<br>• Handled the full 4-fund portfolio where the commercial API failed with a *"portfolio too large"* error. |
| **Test 2: Real Unseen Annual Reports** (Top 15 companies + reverse search) | **22 real SEC annual reports** (50,000 to 350,000 words each) | Standard portfolio trackers (which show **0%** TSMC outside `EEM` and **0** filings for Samsung) | • Extracted **139 verified supply-chain links**.<br>• Uncovered **12.39% TSMC** exposure across 4 holdings and **9.42% Samsung** exposure.<br>• **100% of displayed quotes** matched the official filing text word-for-word. |
| **Test 3: Synthetic "Trap" Data Suite** (Controlled stress test) | **Synthetic test portfolios** + **deliberately faked AI outputs** (made-up quotes, fake `99.99%` numbers, outside stocks, and "sell" orders) | An unchecked AI chatbot | • **100% of fake or altered quotes** were caught and blocked by code.<br>• **100% of invented numbers and trading instructions** were blocked before reaching the screen.<br>• Completes within a strict **100-second** time budget. |

### Speaker Cue (40s)
*"We proved this works quantitatively across three scenarios. First, on real holdings across 1,667 companies, our math matches an independent commercial benchmark to within three ten-thousandths of a percent—and works on large portfolios where their API crashes. Second, on 22 real SEC annual reports, it uncovered 139 verified links with 100% quote accuracy. Third, we built a synthetic trap suite that feeds the system fake AI quotes and made-up numbers—and our code caught and blocked 100% of them."*

---

## Slide 6 — Repeatability: Same Portfolio, Same Answer Every Time (3:25–3:45)
> **Organiser Repeatability Requirement:** Why any user or judge gets consistent, repeatable results across runs.

1. **Zero Drift in the Math:**
   - Because standard Python code—not an AI—computes every weight, overlap score, and dependency percentage, running the same portfolio 100 times gives the **exact same numbers 100 times (0% variation)**.
2. **Smart Local Saving (Instant Replay):**
   - Official annual reports never change once published. Once a report is checked, the verified quotes are saved on disk.
   - Clicking a portfolio a second time—or running in **Offline Mode** without an internet connection or API key—replays the full analysis in **under 1.5 seconds** at **$0 cost**.
3. **Automatic Backup Model:**
   - If the primary AI model (`Gemini 4 Argon`) hits a busy rate limit during live synthesis, the system automatically switches to `Gemini 3.8 Flash` so a run never crashes.

```bash
# Anyone can re-run our exact verification tests and portfolio analysis in one command:
cd backend && uv run pytest
HOC_OFFLINE=1 uv run python -m hoc.cli analyse --example us-core-tilt
```

---

## Slide 7 — Honest Limits & Summary (3:45–4:00)
> **Closing with Trust:** A tool you can trust tells you what it *cannot* see.

### What House of Cards Does Not Claim to Do (Shown Live on Screen)
- **Only Sees Public Disclosures (~45% of Portfolio Weight):** Companies only reveal so much in public filings. For instance, Apple and Microsoft do not name their suppliers in their annual reports, and big customers are often listed anonymously (*"one customer was 22% of revenue"*). Our app shows that **~45%** of the portfolio is covered by verified disclosures and never guesses the rest.
- **Reports Are Snapshots in Time:** Annual reports come out once a year, and some fund disclosures come out quarterly. Every link and fund row displays its **exact publication date** so you never mistake old data for live news.
- **Visibility, Not Trading Advice:** House of Cards is an X-ray for your portfolio—it never trades your money and never gives buy or sell advice.

### 10-Second Judge Recap
| Question | Our Answer |
| :--- | :--- |
| **Who is it for?** | Anyone holding ETFs who wants to see their true company concentration and supply-chain risk. |
| **Why is it trustworthy?** | Python does 100% of the math; AI is only used to read 10-K reports, and every quote is checked word-for-word. |
| **How is it proven?** | Cross-checked within `0.0003%` on 1,667 real stocks, verified on 22 real SEC reports (`139` quotes), and stress-tested against synthetic AI traps (`100%` blocked). |
