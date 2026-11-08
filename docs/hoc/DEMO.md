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
- **1:35, go one level deeper (Dependencies):** Load the US core example again and open **Dependencies**. Find
  dependencies read the latest 10-K/20-F of the top 15 companies (14 had one; Samsung has no SEC filing) plus
  other companies' filings that name them: **139 verified links from 22 filings**.
- **1:55, the single point of failure:** **12.39%** of the portfolio depends on **TSMC**, through 4 companies, and
  **9.42%** on Samsung, which has no SEC filing of its own and shows up only because other companies' filings
  name it (Qualcomm's 10-K calls it a foundry, a supplier and a customer). "TSMC" and "Taiwan Semiconductor
  Manufacturing Company Limited" are one node because names are matched exactly, never by the AI.
- **2:15, prove it:** click a TSMC edge. The evidence drawer shows the **verbatim quote**, the section, the form, the
  filing date and the SEC link. Every quote is checked word for word against the filing; the audit bar counts what
  was rejected.
- **2:35, the AI synthesis:** read one **critical flaw** and one **diversification idea**. Every number in them is a
  Python metric; a claim with any other number was dropped (the audit bar shows how many).
- **2:50, close with the limits:** filings cover about **45%** of the portfolio, big customers are usually unnamed,
  and annual reports can be a year old. House of Cards says so on screen instead of guessing.

## If something goes wrong

- **"sec_contact_missing" / "missing_api_key" on Dependencies:** the setting isn't in the shell that started the
  API. Cached results still show; restart the API from a shell with the variables set.
- **A row says "No price, enter a %":** that fund has no usable close (or isn't in USD). Pin it to a %.
- **No network:** start the API with `HOC_OFFLINE=1`; everything warmed above still works.
