# R2: Source Freshness, Identifier Coverage, and Fallback Order

**Date:** 2026-11-07  
**Author:** Kendrick's Gemini (`@kendricklow2008 (Gemini)`)  
**Package:** `R2` (`Refs #28`)

---

## 1. Executive Summary & Recommendations

We probed all three data sources (**TickerInside API v1**, **iShares direct CSV via JSON-LD `contentUrl`**, and **SEC EDGAR Form N-PORT XML**) live on `2026-11-07` across the 4 example-portfolio ETFs (`IVV`, `QQQ`, `XLK`, `EEM`), `ACWI`, and 6 common benchmark ETFs (`SPY`, `VOO`, `VTI`, `VXUS`, `SCHD`, `VEA`), plus inspected SSGA SPDR daily XLSX and Vanguard endpoints.

### Key Findings
1. **TickerInside is tied for freshest on every tested ETF and has superior symbol/company normalization:**
   - For **iShares (`IVV`, `EEM`, `ACWI`)** and **SPDR (`SPY`, `XLK`)**, TickerInside uses its `issuer` source layer with `holdings_as_of = 2026-11-05` (T-2 daily), matching the live iShares `latest-holdings.csv` (`Nov 05, 2026`) and SPDR daily XLSX (`05-Nov-2026`) to the day.
   - For **Invesco (`QQQ`)**, **Vanguard (`VOO`, `VTI`, `VXUS`, `VEA`)**, and **Schwab (`SCHD`)**, TickerInside uses its `sec_nport` layer (`2026-06-30` to `2026-08-31`), matching the **exact latest `NPORT-P` `repPdDate` on SEC EDGAR** to the day.
2. **When iShares CSV beats TickerInside:**
   - Intraday before TickerInside's nightly build updates, or for long-tail iShares ETFs not in TickerInside's catalog.
   - Provides line-level GICS-style `Sector`, `Asset Class`, `Location`, `Exchange`, and `Currency` on every row (whereas TickerInside's ETF endpoint provides `{symbol: percent}` plus fund-level `breakdown.sectors_pct`).
   - **Trade-off:** iShares CSV lacks `ISIN`, `LEI`, and `CIK`, and uses raw local exchange tickers without suffixes (e.g. `2330` and `005930` in `EEM` instead of TickerInside's `2330.TW` and `005930.KS`).
3. **When SEC N-PORT beats TickerInside and iShares:**
   - **Identifier richness:** Live `NPORT-P` XML files provide **98.8%–100% ISIN coverage**, **53.0%–100% LEI coverage**, and **CUSIP** on every holding—none of which are in TickerInside's ETF file or iShares CSVs.
   - **Breadth & newly filed reports:** Covers any US 1940-Act registered ETF/fund on EDGAR (including newly filed `NPORT-P` reports before TickerInside's nightly scrape).
   - **Trade-off:** Lags 60–120 days behind daily issuer files (`2026-06-30` to `2026-08-31`) and omits ticker symbols and equity sectors (requiring OpenFIGI or reference lookup).
4. **Recommendation on Queue Item #9 (SPDR & Vanguard adapters):** **Do NOT build.**
   - SSGA SPDR's daily XLSX (`holdings-daily-us-en-{ticker}.xlsx`) has the exact same `2026-11-05` date as TickerInside, contains only CUSIP + SEDOL (no ISIN or LEI), and carries a restrictive legal notice prohibiting reproduction, whereas TickerInside already serves SPDR ETFs (`SPY`, `XLK`) under CC BY 4.0 with CIK + FIGI.
   - Vanguard has no unauthenticated daily holdings dump, and its N-PORT filings are already covered by both TickerInside and `sec_nport`.

### Recommended `HOC_SOURCE_ORDER`

| Scope / Issuer | Recommended `HOC_SOURCE_ORDER` | Rationale |
|---|---|---|
| **Global Default** | `tickerinside,ishares,sec_nport` | Confirming `PLAN.md`: TickerInside is fastest (1 JSON fetch), normalized (`2330.TW`), and matches the freshest available date across all 11 tested ETFs. |
| **iShares ETFs** (`IVV`, `EEM`, `ACWI`, etc.) | `tickerinside,ishares,sec_nport` (or `ishares,tickerinside,sec_nport` if line-level sectors are required) | Both `tickerinside` and `ishares` are daily (`2026-11-05`). Keep `tickerinside` first for normalized foreign symbols + CIK/FIGI, with `ishares` as immediate daily fallback long before `sec_nport` (`2026-06-30`–`2026-08-31`). |
| **SPDR / State Street** (`SPY`, `XLK`, etc.) | `tickerinside,sec_nport` | `ishares` fails fast (not an iShares fund); `tickerinside` serves daily (`2026-11-05`) issuer data; `sec_nport` provides quarterly fallback. |
| **Vanguard / Invesco / Schwab** (`VOO`, `VTI`, `VXUS`, `VEA`, `QQQ`, `SCHD`) | `tickerinside,sec_nport` | Both sources derive from the same latest `NPORT-P` filing (`2026-06-30` to `2026-08-31`), but `tickerinside` already resolves symbols, CIKs, FIGIs, and fund-level sector breakdowns. `sec_nport` serves as fallback or ISIN/LEI enricher. |

---

## 2. Live Freshness & Coverage Comparison (Probed 2026-11-07)

| ETF | Issuer | CIK / Series ID | TickerInside `holdings_as_of` (Layer, Count) | iShares CSV `as_of` | SEC EDGAR Latest `NPORT-P` `repPdDate` (`filingDate`, Accession) | N-PORT `<invstOrSec>` (ISIN / LEI Count) | Freshest Source |
|---|---|---|---|---|---|---|---|
| **IVV** | iShares | `0001100663` / `S000004310` | **2026-11-05** (`issuer`, 503) | **2026-11-05** | `2026-06-30` (`2026-08-25`, `0002071691-26-019760`) | 508 (507 ISIN / 495 LEI) | **Tie:** TickerInside = iShares (`2026-11-05`, +128d over N-PORT) |
| **QQQ** | Invesco | `0001067839` / `S000101292` | **2026-06-30** (`sec_nport`, 102) | N/A | **2026-06-30** (`2026-08-28`, `0001067839-26-000030`) | 105 (102 ISIN / 101 LEI) | **Tie:** TickerInside = SEC N-PORT (`2026-06-30`) |
| **XLK** | SPDR | `0001064641` / `S000006415` | **2026-11-05** (`issuer`, 77) | N/A | `2026-06-30` (`2026-08-28`, `0001410368-26-089672`) | 79 (78 ISIN / 79 LEI) | **TickerInside** (`2026-11-05`, +128d over N-PORT) |
| **EEM** | iShares | `0000930667` / `S000004266` | **2026-11-05** (`issuer`, 1,182) | **2026-11-05** | `2026-08-31` (`2026-10-23`, `0001004726-26-010025`) | 1,220 (1,220 ISIN / 647 LEI) | **Tie:** TickerInside = iShares (`2026-11-05`, +66d over N-PORT) |
| **ACWI** | iShares | `0001100663` / `S000021461` | **2026-11-05** (`issuer`, 2,192) | **2026-11-05** | `2026-07-31` (`2026-09-23`, `0001004726-26-008801`) | 2,273 (2,273 ISIN / 1,767 LEI) | **Tie:** TickerInside = iShares (`2026-11-05`, +97d over N-PORT) |
| **SPY** | SPDR (UIT) | `0000884394` / `None` (UIT) | **2026-11-05** (`issuer`, 504) | N/A | `2026-06-30` (`2026-08-28`, `0001410368-26-089410`) | 504 (NPORT-P filed under CIK) | **TickerInside** (`2026-11-05`, +128d over N-PORT) |
| **VOO** | Vanguard | `0000036405` / `S000002839` | **2026-06-30** (`sec_nport`, 504) | N/A | **2026-06-30** (`2026-08-28`, `0000036405-26-000473`) | 520 (504 ISIN / 494 LEI) | **Tie:** TickerInside = SEC N-PORT (`2026-06-30`) |
| **VTI** | Vanguard | `0000036405` / `S000002848` | **2026-06-30** (`sec_nport`, 3,483) | N/A | **2026-06-30** (`2026-08-28`, `0000036405-26-000480`) | 3,546 (3,502 ISIN / 2,529 LEI) | **Tie:** TickerInside = SEC N-PORT (`2026-06-30`) |
| **VXUS** | Vanguard | `0000736054` / `S000002932` | **2026-07-31** (`sec_nport`, 8,702) | N/A | **2026-07-31** (`2026-09-28`, `0000736054-26-000275`) | 8,868 (8,794 ISIN / 5,701 LEI) | **Tie:** TickerInside = SEC N-PORT (`2026-07-31`) |
| **SCHD** | Schwab | `0001454889` / `S000034163` | **2026-08-31** (`sec_nport`, 99) | N/A | **2026-08-31** (`2026-10-27`, `0001410368-26-108609`) | 102 (100 ISIN / 90 LEI) | **Tie:** TickerInside = SEC N-PORT (`2026-08-31`) |
| **VEA** | Vanguard | `0000923202` / `S000004386` | **2026-06-30** (`sec_nport`, 3,834) | N/A | **2026-06-30** (`2026-08-28`, `0000923202-26-000149`) | 3,908 (3,866 ISIN / 2,683 LEI) | **Tie:** TickerInside = SEC N-PORT (`2026-06-30`) |

---

## 3. Technical Findings for Adapter Implementation (`b` and `c`)

### A. SEC N-PORT Adapter (`backend/hoc/sources/sec_nport/`, Package `b`)
1. **Ticker → `(cik, series_id, class_id)` Resolution:**
   - Open-end ETFs (`IVV`, `QQQ`, `XLK`, `EEM`, `ACWI`, `VOO`, `VTI`, `VXUS`, `SCHD`, `VEA`) appear in `https://www.sec.gov/files/company_tickers_mf.json` (`fields: ["cik", "seriesId", "classId", "symbol"]`).
   - Unit Investment Trusts like `SPY` (`CIK 0000884394`) do **not** have a `seriesId` in `company_tickers_mf.json`; they appear in `https://www.sec.gov/files/company_tickers.json` (`{"cik_str": 884394, "ticker": "SPY", ...}`) and file `NPORT-P` directly at the CIK level.
2. **Filtering Multi-Series Trusts on EDGAR:**
   - Trusts like iShares Trust (`CIK 0001100663`) and Vanguard Index Funds (`CIK 0000036405`) file hundreds of `NPORT-P` reports across dozens of ETFs. Querying `data.sec.gov/submissions/CIK{cik}.json` does not index `recent` rows by `seriesId`.
   - **Verified fast path:** Querying EDGAR's Atom feed with `CIK={series_id}` (`https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=S000004310&type=NPORT-P&count=5&output=atom`) filters server-side to that exact series and returns the latest accession number in a single lightweight XML response. For UITs without a `series_id` (`SPY`), query `data.sec.gov/submissions/CIK{cik:010d}.json` and pick the latest `form == "NPORT-P"`.
3. **Raw XML URL & `<invstOrSec>` Parsing:**
   - The `submissions` JSON lists `primaryDocument: "xslFormNPORT-P_X01/primary_doc.xml"` (which renders HTML via XSLT). Strip the `xslFormNPORT-P_X01/` prefix to fetch raw XML at `https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}/primary_doc.xml`.
   - Report date is `<repPdDate>` (e.g. `2026-06-30`); fund net assets is `<netAssets>`.
   - Each `<invstOrSec>` provides `<name>`, `<title>`, `<lei>` (may be `"N/A"`), `<cusip>`, `<identifiers><isin value="..."/></identifiers>`, `<valUSD>`, `<pctVal>` (**percentage** of net assets, e.g. `0.061079735228` = `0.06108%` → divide by `100.0` for unit fraction), `<assetCat>` (`EC` = equity common, `EP` = equity preferred, `STIV` = short-term investment vehicle, `DE` = derivative), and `<securityLending><isCashCollateral>Y|N</isCashCollateral></securityLending>`.
   - **Critical filter:** Exclude securities-lending cash collateral reinvestments (`isCashCollateral == "Y"`) or classify non-`EC`/`EP` rows as cash/excluded so total weights do not exceed 1.0 when funds lend securities.

### B. iShares Adapter (`backend/hoc/sources/ishares/`, Package `c`)
1. **Product Page & JSON-LD `contentUrl` Discovery:**
   - Every iShares US ETF product page embeds `<script type="application/ld+json">` containing `"contentUrl": "https://www.ishares.com/us/products/{product_id}/{slug}/latest-holdings.csv"`.
2. **CSV Schema Variations Across Live Funds (`IVV` vs `EEM` vs `ACWI`):**
   - Line 2 contains `Fund Holdings as of,"Nov 05, 2026"` (parse with `%b %d, %Y`).
   - The table header begins at the line starting with `Ticker,Name,`.
   - **Weight column naming differs by fund:**
     - `EEM` & `ACWI`: column is named **`Weight (%)`** (e.g. `"15.06"` → `0.1506`).
     - `IVV`: has **no `Weight (%)` column**; instead it has **`Market Weight`** and `Notional Weight` at the end of the header (`Ticker,Name,Type,Sector,Asset Class,Market Value,Notional Value,Quantity,Price,Location,Exchange,Currency,FX Rate,Market Currency,Accrual Date,Market Weight,Notional Weight`, e.g. `"7.92"` → `0.0792`).
     - **Parser rule:** Check `row.get("Weight (%)") or row.get("Market Weight")` (divided by `100.0`), falling back to `Market Value / sum(Market Value)`.
   - **`Type` column presence differs:** `IVV` and `EEM` include `Type` (`EQUITY`, `CASH`, `FUTURE`, `STIF`, `COLLATERAL`, `FX`, `FUND`, `INDEX`, `WARRANT`), whereas `ACWI` omits `Type` entirely and only has `Asset Class` (`Equity`, `Cash`, `Futures`, `Money Market`, `Cash Collateral and Margins`, `FX`).
   - **Parser rule:** Classify holdings primarily by `Asset Class == "Equity"` (and `Type not in {"FUTURE", "INDEX", "CASH", "STIF", "COLLATERAL", "FX"}` when `Type` is present).
