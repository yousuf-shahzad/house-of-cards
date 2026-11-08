# Independent External Validation (`QQQ` vs `XLK` Overlap & Dependency Links vs 3-Year Price History)

This folder provides an independent, zero-`hoc`-import proof (`validation/run_validation.py`, Python standard library only) testing two parts of the application on the `QQQ + XLK` portfolio:

1. **Part 1 — ETF Holdings Overlap (`QQQ` vs `XLK`)**: Recomputes company-level weighted overlap $O = \sum_c \min(w_{\text{QQQ},c}, w_{\text{XLK},c})$ and shared-company count directly from official issuer and SEC EDGAR files, merging dual-class shares by 6-character issuer CUSIP (`GOOG` + `GOOGL` $\to$ `02079K`), and explains the exact gap against the app's `50.11%` / `35` shared companies.
2. **Part 2 — Predicted Dependency Links vs 3-Year Price History**: Tests the app's exported company-to-company dependency links (`validation/data/app_qqq_xlk_export.json`) against 3 years of daily adjusted close prices (`2023-11-07` to `2026-11-06`, $N = 752$ daily return observations) from Yahoo Finance, using multi-factor OLS residual correlations and a target shock-day ($|z_{\text{target}}| > 2$) event study against matched same-sector unlinked control pairs.

---

## 1. Raw Data Snapshots & Provenance (`validation/data/`)

| Snapshot File | Source / Issuer | URL | As-of Date | Bytes | SHA-256 |
|---|---|---|---|---:|---|
| `xlk_ssga_2026-11-05.xlsx` | State Street Global Advisors (SPDR) | `https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xlk.xlsx` | `2026-11-05` (`As of 05-Nov-2026`) | `23,179` | `75506f73ac483d82faaba9b38066079bd9b8db1fafa8526e99b7fcc9c2fbc153` |
| `qqq_invesco_2026-11-05.json` | Invesco (Direct ETF Holdings API) | `https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/46090E103/holdings/fund?idType=cusip&productType=ETF` | `2026-11-05` | `37,671` | `0025c73d7d24c226880f0a7ec9483c9af6be77b3bd2944fe947ee2e3b51bd243` |
| `qqq_sec_nport_2026-06-30.xml` | SEC EDGAR (Invesco QQQ Trust Form N-PORT, filed `2026-08-28`) | `https://www.sec.gov/Archives/edgar/data/1067839/000106783926000030/primary_doc.xml` | `2026-06-30` | `116,905` | `86f2d61f048c29209592872c5807e6e220d02e0dd7ea9164af446f36561c8d22` |
| `app_qqq_xlk_export.json` | App output under test (`/api/analysis` & `/api/dependencies`) | `http://127.0.0.1:8000/api/dependencies` | `2026-11-05` | `41,976` | `a06df785f20e5d8ea5b663f94c27b16a2fe18d2da044dea17581f6491cb3a4eb` |
| `yahoo_adj_close_3y.json` | Yahoo Finance v8 Chart API (daily adjusted close) | `https://query1.finance.yahoo.com/v8/finance/chart/{TICKER}?range=3y&interval=1d` | `2023-11-07` to `2026-11-06` (`753` trading days) | `221,145` | `c112e71b944feb27a327086d62d27ae8e2683b95b2e156ebd1ad0b8cfaa29b92` |

---

## 2. Part 1 — `QQQ` vs `XLK` Company-Level Overlap

### Method
- **Equity filtering**: Cash, currency collateral, pending dividends, and index futures (`CURR`, `CURRCOL`, `IFUT`, `SYN` in Invesco's JSON; non-`EC` rows in Form N-PORT) are excluded so only equity holdings (`COM`, `ADR`, `DRNY`) are included.
- **Issuer-level share-class aggregation**: Holdings are grouped by the 6-character CUSIP issuer prefix (`CUSIP[:6]`), as specified in `docs/hoc/CONTRACT.md`. In `QQQ`, Alphabet Class A (`GOOGL`, `02079K305`, `2.8702%`) and Class C (`GOOG`, `02079K107`, `2.6955%`) merge into a single issuer (`CUSIP6:02079K`, `5.5657%` on `2026-11-05`; `5.3679%` on `2026-06-30`). Because S&P GICS classifies Alphabet under Communication Services (`XLC`) rather than Information Technology (`XLK`), Alphabet's weight in `XLK` is `0%`.
- **Weighted overlap**:
  $$O(\text{QQQ}, \text{XLK}) = \sum_{c} \min\left(w_{\text{QQQ},c},\; w_{\text{XLK},c}\right)$$

### Summary Comparison

| Comparison Basis | `QQQ` Source & As-of Date | `XLK` Source & As-of Date | Shared Companies | Weighted Overlap ($O$) | Difference vs App |
|---|---|---|---:|---:|---:|
| **App Reported** | SEC Form N-PORT (`2026-06-30`) | Issuer file (`2026-11-05`) | **`35`** | **`50.11%` (`0.501063`)** | — |
| **Independent Date-Matched Proof** | SEC EDGAR Form N-PORT XML (`2026-06-30`) | State Street SPDR XLSX (`2026-11-05`) | **`35`** | **`50.11%` (`0.501063`)** | **`0.000000` (`0.00 pp`)** |
| **Independent Current Issuer Proof** | Invesco Direct ETF JSON (`2026-11-05`) | State Street SPDR XLSX (`2026-11-05`) | **`35`** | **`51.44%` (`0.514370`)** | **`+0.013307` (`+1.33 pp`)** |

### Explaining the `+1.33 pp` (`51.44%` vs `50.11%`) Gap
1. **Exact mathematical verification on the app's filing dates (`0.000000` gap)**: When computed directly from QQQ's SEC Form N-PORT XML (`2026-06-30`) and State Street's XLK daily holdings XLSX (`2026-11-05`), our standalone script yields **`0.501063` (`50.11%`) across `35` shared companies** — matching the app's output to all 6 decimal places.
2. **Market-cap drift between `2026-06-30` and `2026-11-05` (`+1.33 pp`)**: Both `2026-06-30` and `2026-11-05` QQQ files share the exact same **`35` companies** with XLK. Because `QQQ` has smaller weights than `XLK` in mega-cap tech (`AAPL`, `MSFT`, `NVDA`, `AVGO`), $\min(w_{\text{QQQ},c}, w_{\text{XLK},c})$ is bound by $w_{\text{QQQ},c}$ for those names. Between `2026-06-30` and `2026-11-05`, `MSFT` rose in `QQQ` from `4.35%` to `6.89%` (`+2.54 pp` overlap contribution) and `AAPL` rose from `6.67%` to `8.70%` (`+2.03 pp`), partially offset by decreases in `AMD` (`-0.86 pp`), `SNDK` (`-0.55 pp`), `INTC` (`-0.46 pp`), `AMAT` (`-0.51 pp`), `LRCX` (`-0.47 pp`), and `AVGO` (`-0.41 pp`), producing a net shift of **`+1.33 percentage points` (`+0.013307`)**.

### Top 10 Shared Companies (`2026-11-05` Direct Issuer vs `2026-06-30` N-PORT)

| Ticker | Company | `QQQ` (`2026-06-30` N-PORT) | `QQQ` (`2026-11-05` Invesco) | `XLK` (`2026-11-05` SSGA) | $\min$ (`2026-06-30`) | $\min$ (`2026-11-05`) | $\Delta \min$ |
|---|---|---:|---:|---:|---:|---:|---:|
| `AAPL` | Apple Inc. | `6.67%` | `8.70%` | `16.87%` | `6.67%` | `8.70%` | `+2.03%` |
| `NVDA` | NVIDIA Corp. | `7.60%` | `7.58%` | `14.76%` | `7.60%` | `7.58%` | `-0.02%` |
| `MSFT` | Microsoft Corp. | `4.35%` | `6.89%` | `13.37%` | `4.35%` | `6.89%` | `+2.54%` |
| `MU` | Micron Technology Inc. | `5.64%` | `3.54%` | `3.30%` | `3.30%` | `3.30%` | `0.00%` |
| `AMD` | Advanced Micro Devices Inc. | `4.10%` | `3.15%` | `4.01%` | `4.01%` | `3.15%` | `-0.86%` |
| `AVGO` | Broadcom Inc. | `2.81%` | `2.40%` | `4.66%` | `2.81%` | `2.40%` | `-0.41%` |
| `CSCO` | Cisco Systems Inc. | `2.01%` | `1.80%` | `2.57%` | `2.01%` | `1.80%` | `-0.21%` |
| `PLTR` | Palantir Technologies Inc. | `1.07%` | `1.70%` | `2.42%` | `1.07%` | `1.70%` | `+0.63%` |
| `INTC` | Intel Corp. | `3.04%` | `1.31%` | `1.77%` | `1.77%` | `1.31%` | `-0.46%` |
| `PANW` | Palo Alto Networks Inc. | `1.21%` | `1.23%` | `1.74%` | `1.21%` | `1.23%` | `+0.01%` |

---

## 3. Part 2 — Predicted Dependency Links vs 3-Year Daily Price History

### Hypotheses & Sample Construction
- **Hypotheses under test**: Exported directly from `/api/dependencies` (`top_n=15`) for `QQQ + XLK` (`validation/data/app_qqq_xlk_export.json`). Filtering to company-to-company edges where both `source` and `target` have liquid US-listed common shares or ADRs yields **`16` unique directed pairs** across `17` tickers (`AAPL`, `AMD`, `ASML`, `AVGO`, `FLEX`, `FN`, `GFS`, `GOOGL`, `INTC`, `LRCX`, `MSFT`, `MU`, `NVDA`, `PANW`, `SONY`, `TSM`, `UMC`). Non-US-listed or private targets (`OpenAI`, `Groq`, `SK Hynix`, `Samsung`, `Hon Hai`, `Wistron`, `CATL`, `Panasonic`, etc.) are excluded because they lack continuous US-listed daily price series.
- **Control group (`n = 150` pairs)**: All unordered pairs `(A, B)` among the 32 US-listed technology and semiconductor constituents (`17` linked-universe tickers + `15` additional top `QQQ`/`XLK` holdings: `AMAT`, `CSCO`, `PLTR`, `TXN`, `CRWD`, `ADI`, `KLAC`, `QCOM`, `MRVL`, `ADBE`, `INTU`, `SNPS`, `CDNS`, `NXPI`, `MPWR`) where at least one side is in the app's analysed portfolio companies, both belong to the same sub-sector (`semiconductor–semiconductor` or `technology–technology`), and **no dependency link** is predicted by the app.
- **Price data**: `753` common trading days (`752` daily simple return days) from `2023-11-07` to `2026-11-06` via Yahoo Finance (`yahoo_adj_close_3y.json`).
- **Residual return models**:
  1. **3-Factor (`SPY + XLK + SOXX`)**: Regresses each stock's daily return $r_{i,t}$ on the market (`SPY`), broad technology sector (`XLK`), and semiconductor benchmark (`SOXX`) via OLS:
     $$r_{i,t} = \alpha_i + \beta_{i,\text{SPY}} r_{\text{SPY},t} + \beta_{i,\text{XLK}} r_{\text{XLK},t} + \beta_{i,\text{SOXX}} r_{\text{SOXX},t} + \varepsilon_{i,t}$$
  2. **2-Factor (`SPY + XLK`)**: Regresses $r_{i,t}$ on `SPY` and `XLK` only.
- **Event study on target shock days ($|z_{\text{target},t}| > 2$)**: For each pair `(source, target)`, identifies trading days where the target's standardized residual return satisfies $|z_{\text{target},t}| > 2$ (typically `30–41` days per target over 3 years) and measures:
  - **Same-sign co-movement rate**: fraction of target shock days where $\text{sign}(\varepsilon_{\text{source},t}) = \text{sign}(\varepsilon_{\text{target},t})$.
  - **Signed source response**: mean of $\text{sign}(z_{\text{target},t}) \cdot z_{\text{source},t}$ on target shock days.

### Aggregate Results (`n = 16` Linked Pairs vs `n = 150` Same-Sector Controls)

| Model & Metric | Linked Pairs ($n = 16$) | Matched Controls ($n = 150$) | Difference (Linked $-$ Control) | Bootstrap 95% CI ($10{,}000$ resamples) | Two-Sided Permutation $p$-value |
|---|---:|---:|---:|---:|---:|
| **3-Factor (`SPY + XLK + SOXX`) Residual Correlation ($\bar{r}_{\text{res}}$)** | **`+0.0287`** | **`-0.0338`** | **`+0.0624`** | **`[-0.0015, +0.1259]`** | **`0.0925`** |
| **3-Factor (`SPY + XLK + SOXX`) Event Same-Sign Rate ($|z_{\text{target}}| > 2$)** | **`49.93%`** | **`44.93%`** | **`+5.00 pp` (`+0.0500`)** | **`[-0.0239, +0.1196]`** | **`0.2106`** |
| **3-Factor (`SPY + XLK + SOXX`) Event Signed Source $z$-Score** | **`+0.0568`** | **`-0.0897`** | **`+0.1465`** | **`[-0.0439, +0.3413]`** | **`0.1597`** |
| **2-Factor (`SPY + XLK`) Residual Correlation ($\bar{r}_{\text{res}}$)** | **`+0.0896`** | **`+0.0929`** | **`-0.0033`** | **`[-0.0839, +0.0796]`** | **`0.9459`** |
| **2-Factor (`SPY + XLK`) Event Same-Sign Rate ($|z_{\text{target}}| > 2$)** | **`55.16%`** | **`56.31%`** | **`-1.16 pp` (`-0.0116`)** | **`[-0.0996, +0.0810]`** | **`0.7963`** |

### Pair-by-Pair Results (`16` Predicted US-Listed Links)

| Source | Target | Predicted Relationship (`Tier`) | 3-Factor $r_{\text{res}}$ (`SPY+XLK+SOXX`) | 2-Factor $r_{\text{res}}$ (`SPY+XLK`) | Target $\|z\|>2$ Days (3F) | 3-Factor Event Same-Sign Rate |
|---|---|---|---:|---:|---:|---:|
| `NVDA` | `TSM` | `foundry` (`critical`) | **`+0.2545`** | `+0.2087` | `37` | `59.46%` |
| `LRCX` | `MU` | `customer` (`medium`) | **`+0.2063`** | `+0.4618` | `35` | `68.57%` |
| `AVGO` | `TSM` | `foundry` (`critical`) | **`+0.1804`** | `+0.2265` | `37` | `70.27%` |
| `AMD` | `MSFT` | `customer` (`medium`) | **`+0.1093`** | `-0.1500` | `37` | `56.76%` |
| `INTC` | `UMC` | `jv_partner` (`medium`) | **`+0.0786`** | `+0.1751` | `40` | `55.00%` |
| `NVDA` | `FN` | `contract_manufacturer` (`critical`) | **`+0.0683`** | `+0.0415` | `30` | `56.67%` |
| `AMD` | `SONY` | `customer` (`medium`) | **`+0.0500`** | `+0.0236` | `31` | `54.84%` |
| `LRCX` | `TSM` | `customer` (`medium`) | **`+0.0433`** | `+0.2658` | `37` | `48.65%` |
| `AMD` | `UMC` | `foundry` (`critical`) | **`+0.0152`** | `+0.1298` | `40` | `50.00%` |
| `PANW` | `FLEX` | `contract_manufacturer` (`critical`) | **`+0.0115`** | `-0.1145` | `35` | `42.86%` |
| `AAPL` | `GOOGL` | `jv_partner` (`medium`) | `-0.0199` | `-0.0065` | `38` | `39.47%` |
| `AMD` | `TSM` | `foundry` (`critical`) | `-0.0355` | `+0.1189` | `37` | `51.35%` |
| `NVDA` | `MU` | `supplier` (`medium`) | `-0.0803` | `-0.1101` | `35` | `42.86%` |
| `AMD` | `GFS` | `foundry` (`critical`) | `-0.0874` | `+0.0968` | `38` | `36.84%` |
| `INTC` | `ASML` | `supplier` (`critical`) | `-0.1031` | `+0.1329` | `39` | `35.90%` |
| `INTC` | `TSM` | `foundry` (`critical`) | `-0.2325` | `-0.0666` | `37` | `29.73%` |

### Honest Interpretation & Limitations
1. **Why factor specification matters (`SPY+XLK` vs `SPY+XLK+SOXX`)**: Under the 2-factor (`SPY + XLK`) model, both linked pairs (`+0.0896`) and unlinked control pairs (`+0.0929`) show positive residual correlation (`diff = -0.0033`, $p = 0.9459$) because `XLK` alone does not remove the strong industry-wide semiconductor factor (`SOXX`). Once `SOXX` is included (`SPY + XLK + SOXX`), the average residual correlation among unlinked same-sector pairs drops to `-0.0338` (as expected when regressing out a sector index from its constituents), while the app's predicted-link pairs remain positive (`+0.0287`), yielding a **`+0.0624` (`+6.24 pp`)** positive difference (`95% CI [-0.0015, +0.1259]`, permutation $p = 0.0925$) and a **`+5.00 pp`** higher same-sign co-movement rate on target $|z| > 2$ shock days (`49.93%` vs `44.93%`, `95% CI [-0.0239, +0.1196]`, $p = 0.2106$).
2. **Heterogeneity across relationship types (substitution vs. complement effects)**: Core fabless-to-foundry and equipment links (`NVDA -> TSM` $r_{\text{res}} = +0.2545$, `LRCX -> MU` $+0.2063$, `AVGO -> TSM` $+0.1804$) exhibit strong positive idiosyncratic co-movement. Conversely, `INTC -> TSM` ($r_{\text{res}} = -0.2325$) is both a foundry customer link and a direct competitive rivalry (Intel Foundry vs. TSMC), so positive news for TSMC frequently coincides with negative idiosyncratic returns for Intel.
3. **Statistical power & causal caveat**: Return correlation is not proof of operational supply-chain dependency, and with only $n = 16$ US-listed predicted links from a 2-ETF sample portfolio, confidence intervals cross zero (`p = 0.0925` for 3-factor correlation; `p = 0.2106` for the shock-day sign test).

---

## 4. Reproducing `results.json`

Run from the repository root using standard Python 3 (no virtual environment or `hoc` package needed):

```bash
python3 validation/run_validation.py
```
