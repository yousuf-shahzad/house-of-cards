# R3: Sector Label Mapping Across Sources (2026-11-07)

> Owner: Gawyn's Gemini (`@whitehawk9571 (Gemini)`). Feeds package `d` (`hoc.normalise`) and package `a` (`hoc.sources.tickerinside`). Refs #28.

## 1. Summary of Findings

We audited live payloads from **TickerInside** (`fund/{ticker}.json`, `securities.json`, `identifiers.json`, and `sec/{symbol}.json` across `IVV`, `QQQ`, `XLK`, `EEM`, `SPY`, `VOO`, `VTI`, `VXUS`, `ACWI`) and **iShares** (`latest-holdings.csv` for `IVV`), plus **SEC N-PORT** XML schema:

1. **Two critical label mismatches require explicit aliases in `hoc.normalise`:**
   - **TickerInside `breakdown.sectors_pct`** uses `"technology"` (not `"information_technology"`). The other 10 GICS sectors match our `Sector` enum strings verbatim.
   - **iShares `latest-holdings.csv` (`Sector` column)** uses `"Communication"` (not `"Communication Services"`). It also uses `"Cash and/or Derivatives"` on cash/margin/futures lines.
2. **TickerInside bulk reference files (`securities.json`, `identifiers.json`) do not contain sector labels:**
   - `securities.json` rows are `[ticker, holder_count, max_weight, company_name, has_written_page, has_stock_file]`.
   - `identifiers.json` rows are `[ticker, name, asset_type, exchange, composite_figi, share_class_figi, cik, series_id, class_id]`.
   - Individual `sec/{symbol}.json` files carry `"sector"` (human-readable GICS name, e.g. `"Information Technology"`), but only for US-listed stocks with `has_stock_file == 1` (foreign listings like `2330.TW` and unindexed symbols like `EA` or `BRK.A` return `"coverage": "holders_only"` with `"sector": null`).
   - **Implication for package `a` & `d`:** Fetching hundreds of per-stock `sec/{symbol}.json` files per ETF is prohibitive and violates TickerInside's cache-friendly usage pattern. Instead, `TickerInsideAdapter` populates `RawEtfHoldings.reported_sector_weights` from `breakdown.sectors_pct` (converting percentages to fractions of 1). Under `CONTRACT.md` §4 (`SECTOR_COVERAGE_THRESHOLD = 0.95`), TickerInside ETFs cleanly resolve to `sector_basis = "fund_reported"`, while iShares CSVs (which carry line-level `Sector` on ~99.7% of equity weight) resolve to `sector_basis = "holdings"`.

---

## 2. Exact Mapping Table to `hoc.contract.Sector`

Normalisation should normalise any incoming sector key or label by stripping whitespace, lowercasing, replacing `&`/`/`/`-`/spaces with `_`, and collapsing repeated underscores before lookup:

```python
def normalise_sector_token(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")
```

| `hoc.contract.Sector` enum value | TickerInside `breakdown.sectors_pct` key | TickerInside `sec/{t}.json` `sector` | iShares CSV `Sector` column | Normalised token(s) to accept |
|---|---|---|---|---|
| `information_technology` | `"technology"` | `"Information Technology"` | `"Information Technology"` | `information_technology`, `technology`, `tech`, `it` |
| `financials` | `"financials"` | `"Financials"` | `"Financials"` | `financials`, `financial`, `financial_services` |
| `health_care` | `"health_care"` | `"Health Care"` | `"Health Care"` | `health_care`, `healthcare` |
| `consumer_discretionary` | `"consumer_discretionary"` | `"Consumer Discretionary"` | `"Consumer Discretionary"` | `consumer_discretionary`, `consumer_cyclical` |
| `communication_services` | `"communication_services"` | `"Communication Services"` | `"Communication"` | `communication_services`, `communication`, `communications`, `telecommunication_services`, `telecom` |
| `industrials` | `"industrials"` | `"Industrials"` | `"Industrials"` | `industrials`, `industrial` |
| `consumer_staples` | `"consumer_staples"` | `"Consumer Staples"` | `"Consumer Staples"` | `consumer_staples`, `consumer_defensive` |
| `energy` | `"energy"` | `"Energy"` | `"Energy"` | `energy` |
| `utilities` | `"utilities"` | `"Utilities"` | `"Utilities"` | `utilities`, `utility` |
| `real_estate` | `"real_estate"` | `"Real Estate"` | `"Real Estate"` | `real_estate` |
| `materials` | `"materials"` | `"Materials"` | `"Materials"` | `materials`, `basic_materials` |
| `unknown` | *(unmapped / remainder)* | `null` | `"-"`, `""`, `"Cash and/or Derivatives"` | *(fallback for any unrecognised or empty label)* |

---

## 3. Source-Specific Sector Coverage & Gaps

### 3.1 TickerInside (`fund/{ticker}.json`)

Verified across 9 funds on 2026-11-07 (`as_of: 2026-11-06`):

| ETF | `source_layer` | `holdings_as_of` | Sum of `breakdown.sectors_pct` (%) | `breakdown.no_sector_pct` (%) | Notes / Gaps |
|---|---|---|---:|---:|---|
| `IVV` | `issuer` | `2026-11-05` | `99.9429` | `0.0` | All 11 GICS sectors present; `0.0571%` cash/excluded gap becomes `unknown` remainder when scaled to `holdings_weight`. |
| `SPY` | `issuer` | `2026-11-05` | `99.9143` | `0.0` | All 11 GICS sectors present. |
| `QQQ` | `sec_nport` | `2026-06-30` | `99.9270` | `0.0` | 10 sectors present (`real_estate` absent = 0%). |
| `XLK` | `issuer` | `2026-11-05` | `100.0105` | `-0.0105` | `{"technology": 100.0105}` because of short futures line `IXTZ6` (`-0.0105%`). Per `CONTRACT.md` §4, `fund_reported` weights summing above `holdings_weight` are scaled down proportionally to `holdings_weight`. |
| `VOO` | `sec_nport` | `2026-06-30` | `99.8396` | `0.0` | All 11 GICS sectors present. |
| `VTI` | `sec_nport` | `2026-06-30` | `99.9251` | `0.0749` | `0.0749%` unmapped small-cap weight falls into `Sector.unknown`. |
| `ACWI` | `issuer` | `2026-11-05` | `94.5884` | `5.4116` | Non-US constituents without TickerInside stock pages (`5.41%`) are reflected in `no_sector_pct` and become `Sector.unknown` under `fund_reported`. |
| `VXUS` | `sec_nport` | `2026-07-31` | `75.1676` | `24.8324` | `24.83%` of international holdings lack TickerInside sector tags -> `Sector.unknown`. |
| `EEM` | `issuer` | `2026-11-05` | `59.6678` | `40.3322` | `40.33%` of emerging-market holdings lack TickerInside sector tags (e.g. `.KR`, `.TW`, `.IN` local lines have `coverage: "holders_only"` in TickerInside). Calling `iSharesAdapter` directly for `EEM` or `ACWI` fills 99%+ of line-level sectors because iShares CSV includes GICS `Sector` on non-US equities. |

### 3.2 iShares (`latest-holdings.csv`)

Verified against live `IVV` `latest-holdings.csv`:
- Every equity row carries a populated `Sector` string from the 11-sector set above (with `"Communication"` for `communication_services`).
- Non-equity rows (`Asset Class` in `{"Cash", "Cash Collateral and Margins", "Futures", "Money Market"}`) carry `Sector = "Cash and/or Derivatives"`. Because `normalise_etf` moves `cash`, `derivative`, and `fx` asset classes to `excluded` first, those lines are excluded from `holdings_weight` and never pollute `sector_weights`.

### 3.3 SEC Form N-PORT (`sec_nport`)

- Form N-PORT XML provides `assetCat` (e.g. `EC` for equity common) and `issuerCat` (e.g. `CORP`), but **no GICS sector**.
- Unless a `ReferenceProvider` supplies `sector_label` for >= 95% of `holdings_weight`, N-PORT ETFs fall back to `sector_basis = "none"`, assigning 100% of `holdings_weight` to `Sector.unknown` and emitting a `no_sector_data` gap (`CONTRACT.md` §4).
