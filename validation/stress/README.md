# Independent Stress History Validation (`FIX-63` — 5-Year Worst 21-Trading-Day Falls)

This folder provides an independent, zero-`hoc`-import proof (`validation/stress/run_stress_validation.py`, Python standard library only) for the Compare screen's failure simulator (`FIX-63`, `docs/hoc/CONTRACT.md` §11).

For each sector SPDR ETF (`XLK`, `XLF`, `XLV`, `XLY`, `XLC`, `XLI`, `XLP`, `XLE`, `XLU`, `XLRE`, `XLB`) and country proxy ETF (`EWT`, `MCHI`, `EWJ`, `EWY`, `SPY`, plus 17 additional MSCI country ETFs), it computes the worst 1-month (`21` trading days, `SHOCK_WINDOW_DAYS = 21`) return over the last 5 years (`range=5y&interval=1d`, `1,256` trading days from `2021-11-08` to `2026-11-06`) of daily adjusted closes from Yahoo Finance:

$$\text{return}_{i} = \frac{P_{i + 21}}{P_{i}} - 1, \qquad \text{drop} = -\min_{0 \le i < N - 21} \text{return}_{i}$$

---

## 1. Raw Data Snapshot & Provenance (`validation/stress/data/`)

| Snapshot File | Source | URL | Date Range | Trading Days | Bytes | SHA-256 |
|---|---|---|---|---:|---:|---|
| `yahoo_adj_close_5y.json` | Yahoo Finance v8 Chart API (daily adjusted close) | `https://query1.finance.yahoo.com/v8/finance/chart/{TICKER}?range=5y&interval=1d` | `2021-11-08` to `2026-11-06` | `1,256` | `3,284,856` | `1583b3417a3d1959b02458bbcfca4b7de30306470dc434a3998b4475a889598d` |

---

## 2. Sector SPDR ETFs (`11` GICS Sectors)

| Sector Key (`ShockSpec.key`) | Proxy ETF | Fund Name | Worst 21-Day Drop (`drop`) | Drop (`%`) | Window Start | Window End | Start Adj Close | End Adj Close |
|---|---|---|---:|---:|---|---|---:|---:|
| `information_technology` | `XLK` | Technology Select Sector SPDR Fund | `0.193704` | `19.37%` (`19.4%`) | `2026-10-07` | `2026-11-05` | `201.389999` | `162.380005` |
| `financials` | `XLF` | Financial Select Sector SPDR Fund | `0.157007` | `15.70%` (`15.7%`) | `2023-02-15` | `2023-03-17` | `35.125702` | `29.610718` |
| `health_care` | `XLV` | Health Care Select Sector SPDR Fund | `0.111741` | `11.17%` (`11.2%`) | `2022-04-08` | `2022-05-10` | `133.494690` | `118.577805` |
| `consumer_discretionary` | `XLY` | Consumer Discretionary Select Sector SPDR Fund | `0.224461` | `22.45%` (`22.4%`) | `2022-04-19` | `2022-05-18` | `88.902260` | `68.947189` |
| `communication_services` | `XLC` | Communication Services Select Sector SPDR Fund | `0.157610` | `15.76%` (`15.8%`) | `2022-03-30` | `2022-04-29` | `67.319328` | `56.709106` |
| `industrials` | `XLI` | Industrial Select Sector SPDR Fund | `0.148445` | `14.84%` (`14.8%`) | `2022-08-25` | `2022-09-26` | `93.192490` | `79.358528` |
| `consumer_staples` | `XLP` | Consumer Staples Select Sector SPDR Fund | `0.124364` | `12.44%` (`12.4%`) | `2022-04-20` | `2022-05-19` | `72.143646` | `63.171398` |
| `energy` | `XLE` | Energy Select Sector SPDR Fund | `0.229974` | `23.00%` (`23.0%`) | `2022-06-08` | `2022-07-11` | `39.671642` | `30.548195` |
| `utilities` | `XLU` | Utilities Select Sector SPDR Fund | `0.185472` | `18.55%` (`18.5%`) | `2022-09-13` | `2022-10-12` | `33.541988` | `27.320906` |
| `real_estate` | `XLRE` | Real Estate Select Sector SPDR Fund | `0.199563` | `19.96%` (`20.0%`) | `2022-09-09` | `2022-10-10` | `37.826656` | `30.277861` |
| `materials` | `XLB` | Materials Select Sector SPDR Fund | `0.165622` | `16.56%` (`16.6%`) | `2022-06-07` | `2022-07-08` | `39.776867` | `33.188961` |

---

## 3. Primary Country Proxy ETFs (`EWT`, `MCHI`, `EWJ`, `EWY`, `SPY`)

| Country Key (`ISO-2`) | Proxy ETF | Fund Name | Worst 21-Day Drop (`drop`) | Drop (`%`) | Window Start | Window End | Start Adj Close | End Adj Close |
|---|---|---|---:|---:|---|---|---:|---:|
| `TW` | `EWT` | iShares MSCI Taiwan ETF | `0.261184` | `26.12%` (`26.1%`) | `2026-10-07` | `2026-11-05` | `116.239998` | `85.879997` |
| `CN` | `MCHI` | iShares MSCI China ETF | `0.282362` | `28.24%` (`28.2%`) | `2022-02-10` | `2022-03-14` | `56.609673` | `40.625275` |
| `JP` | `EWJ` | iShares MSCI Japan ETF | `0.126122` | `12.61%` (`12.6%`) | `2025-03-07` | `2025-04-07` | `68.384514` | `59.759743` |
| `KR` | `EWY` | iShares MSCI South Korea ETF | `0.283303` | `28.33%` (`28.3%`) | `2026-10-07` | `2026-11-05` | `183.690002` | `131.649994` |
| `US` | `SPY` | SPDR S&P 500 ETF Trust | `0.128015` | `12.80%` (`12.8%`) | `2022-08-25` | `2022-09-26` | `397.902222` | `346.964752` |

---

## 4. Additional MSCI Country Proxy ETFs (`17` Countries)

| Country Key (`ISO-2`) | Proxy ETF | Fund Name | Worst 21-Day Drop (`drop`) | Drop (`%`) | Window Start | Window End |
|---|---|---|---:|---:|---|---|
| `NL` | `EWN` | iShares MSCI Netherlands ETF | `0.188959` | `18.90%` (`18.9%`) | `2022-02-03` | `2022-03-07` |
| `DE` | `EWG` | iShares MSCI Germany ETF | `0.225132` | `22.51%` (`22.5%`) | `2022-02-03` | `2022-03-07` |
| `GB` | `EWU` | iShares MSCI United Kingdom ETF | `0.153088` | `15.31%` (`15.3%`) | `2022-08-25` | `2022-09-26` |
| `FR` | `EWQ` | iShares MSCI France ETF | `0.191763` | `19.18%` (`19.2%`) | `2022-02-03` | `2022-03-07` |
| `CH` | `EWL` | iShares MSCI Switzerland ETF | `0.135417` | `13.54%` (`13.5%`) | `2022-04-11` | `2022-05-11` |
| `CA` | `EWC` | iShares MSCI Canada ETF | `0.142099` | `14.21%` (`14.2%`) | `2022-08-25` | `2022-09-26` |
| `AU` | `EWA` | iShares MSCI Australia ETF | `0.152623` | `15.26%` (`15.3%`) | `2022-06-02` | `2022-07-05` |
| `IN` | `INDA` | iShares MSCI India ETF | `0.131050` | `13.11%` (`13.1%`) | `2026-02-27` | `2026-03-30` |
| `IE` | `EIRL` | iShares MSCI Ireland ETF | `0.224314` | `22.43%` (`22.4%`) | `2022-02-03` | `2022-03-07` |
| `IL` | `EIS` | iShares MSCI Israel ETF | `0.175212` | `17.52%` (`17.5%`) | `2023-09-28` | `2023-10-27` |
| `HK` | `EWH` | iShares MSCI Hong Kong ETF | `0.153203` | `15.32%` (`15.3%`) | `2025-03-10` | `2025-04-08` |
| `SG` | `EWS` | iShares MSCI Singapore ETF | `0.150943` | `15.09%` (`15.1%`) | `2022-02-10` | `2022-03-14` |
| `SE` | `EWD` | iShares MSCI Sweden ETF | `0.219472` | `21.95%` (`21.9%`) | `2022-02-03` | `2022-03-07` |
| `IT` | `EWI` | iShares MSCI Italy ETF | `0.218447` | `21.84%` (`21.8%`) | `2022-02-03` | `2022-03-07` |
| `ES` | `EWP` | iShares MSCI Spain ETF | `0.164434` | `16.44%` (`16.4%`) | `2022-02-03` | `2022-03-07` |
| `BR` | `EWZ` | iShares MSCI Brazil ETF | `0.261750` | `26.17%` (`26.2%`) | `2026-10-05` | `2026-11-03` |
| `MX` | `EWW` | iShares MSCI Mexico ETF | `0.186051` | `18.61%` (`18.6%`) | `2024-05-16` | `2024-06-17` |

---

## 5. Reproducing `results.json` Offline

Run from the repository root using standard Python 3 (no virtual environment, network access, or `hoc` package needed):

```bash
python3 validation/stress/run_stress_validation.py
```
