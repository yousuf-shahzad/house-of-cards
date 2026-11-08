# Failure Simulator — Demo Scenario Table (FIX-63)

Generated via `python docs/hoc/demo/scan_shocks.py` using only the HTTP API (`GET /api/examples`, `POST /api/analysis`, `POST /api/change-ideas`, `POST /api/valuation`, and `POST /api/stress`). Historical shocks use the proxy ETF's worst 21-trading-day fall over the last 5 years of daily adjusted closes; unmapped groups and suppliers use the simulated **20%** fall (`DEFAULT_SHOCK_DROP = 0.20`).

## 1. Top 5 Scenarios Where the New Mix Loses the Most Less (Against Each Sample's #1 Change Idea)

| Rank | Sample Portfolio | #1 Change Idea | Shock (`kind:key`) | Basis (Proxy / Drop) | Your Portfolio (`Before -> After`) | Your New Mix (`Before -> After`) | Loss Reduction |
|---:|---|---|---|---|---|---|---|
| 1 | US core with a tech tilt (% mode) | Swap 20% QQQ -> VTV | `sector:information_technology` (Information Technology) | Historical `XLK` −19.4% (2026-10-07 to 2026-11-05) | $10,000 → $9,019 (−$981 / `$980.85`) | $10,000 → $9,199 (−$801 / `$800.93`) | **loses $180 less** (`$179.92`) |
| 2 | Global market with a Nasdaq-100 tilt (% mode) | Add 20% IWM (Add smaller companies (IWM)) | `sector:information_technology` (Information Technology) | Historical `XLK` −19.4% (2026-10-07 to 2026-11-05) | $10,000 → $9,341 (−$659 / `$659.33`) | $10,000 → $9,424 (−$576 / `$575.52`) | **loses $83 less** (`$83.81`) |
| 3 | US core with a tech tilt (% mode) | Swap 20% QQQ -> VTV | `supplier:ALIAS:TSMC` (TSMC) | Simulated −20.0% | $10,000 → $9,674 (−$326 / `$325.91`) | $10,000 → $9,748 (−$252 / `$252.44`) | **loses $74 less** (`$73.47`) |
| 4 | Global market with a Nasdaq-100 tilt (% mode) | Add 20% IWM (Add smaller companies (IWM)) | `supplier:ALIAS:TSMC` (TSMC) | Simulated −20.0% | $10,000 → $9,791 (−$209 / `$208.82`) | $10,000 → $9,833 (−$167 / `$167.06`) | **loses $42 less** (`$41.77`) |
| 5 | US core with a tech tilt (% mode) | Swap 20% QQQ -> VTV | `sector:communication_services` (Communication Services) | Historical `XLC` −15.8% (2022-03-30 to 2022-04-29) | $10,000 → $9,880 (−$120 / `$119.55`) | $10,000 → $9,912 (−$88 / `$88.33`) | **loses $32 less** (`$31.22`) |

## 2. Top 5 Scenarios Across All Returned Change Ideas (Both Sample Portfolios)

| Rank | Sample Portfolio | Change Idea | Shock (`kind:key`) | Basis (Proxy / Drop) | Your Portfolio (`Before -> After`) | Your New Mix (`Before -> After`) | Loss Reduction |
|---:|---|---|---|---|---|---|---|
| 1 | US core with a tech tilt (% mode) | Swap 10% XLK -> XLV | `sector:information_technology` (Information Technology) | Historical `XLK` −19.4% (2026-10-07 to 2026-11-05) | $10,000 → $9,019 (−$981 / `$980.85`) | $10,000 → $9,212 (−$788 / `$788.20`) | **loses $193 less** (`$192.65`) |
| 2 | Global market with a Nasdaq-100 tilt (% mode) | Add 20% IEFA (Add international companies (IEFA)) | `country:US` (US) | Historical `SPY` −12.8% (2022-08-25 to 2022-09-26) | $10,000 → $9,120 (−$880 / `$880.26`) | $10,000 → $9,302 (−$698 / `$698.19`) | **loses $182 less** (`$182.07`) |
| 3 | US core with a tech tilt (% mode) | Swap 20% QQQ -> VTV | `sector:information_technology` (Information Technology) | Historical `XLK` −19.4% (2026-10-07 to 2026-11-05) | $10,000 → $9,019 (−$981 / `$980.85`) | $10,000 → $9,199 (−$801 / `$800.93`) | **loses $180 less** (`$179.92`) |
| 4 | US core with a tech tilt (% mode) | Add 20% RSP (Add equal-weight US stocks with RSP) | `sector:information_technology` (Information Technology) | Historical `XLK` −19.4% (2026-10-07 to 2026-11-05) | $10,000 → $9,019 (−$981 / `$980.85`) | $10,000 → $9,161 (−$839 / `$838.79`) | **loses $142 less** (`$142.05`) |
| 5 | Global market with a Nasdaq-100 tilt (% mode) | Add 20% XLU (Add utilities (XLU)) | `sector:information_technology` (Information Technology) | Historical `XLK` −19.4% (2026-10-07 to 2026-11-05) | $10,000 → $9,341 (−$659 / `$659.33`) | $10,000 → $9,473 (−$527 / `$527.46`) | **loses $132 less** (`$131.87`) |

## 3. Full Sector & Country Scan — US core with a tech tilt (default shares: 5 IVV, 4 QQQ, 9 XLK, 34 EEM) ($9,817.68 valuation (shares mode))

- **Top Change Idea**: Add 20% XLU (Add utilities (XLU))

| Shock (`kind:key`) | Basis | Drop | Exposed (`Before -> After`) | Your Portfolio (`Before -> After`) | Your New Mix (`Before -> After`) | Delta |
|---|---|---:|---|---|---|---|
| `sector:information_technology` (Information Technology) | Historical (`XLK`) | −19.4% | 51.1% → 40.9% | $9,818 → $8,846 (−$972) | $9,818 → $9,040 (−$778) | loses $194 less (`+$194.41`) |
| `supplier:ALIAS:TSMC` (TSMC) | Simulated | −20.0% | 16.3% → 13.0% | $9,818 → $9,498 (−$320) | $9,818 → $9,562 (−$256) | loses $64 less (`+$63.90`) |
| `sector:consumer_discretionary` (Consumer Discretionary) | Historical (`XLY`) | −22.4% | 7.6% → 6.1% | $9,818 → $9,650 (−$168) | $9,818 → $9,683 (−$134) | loses $34 less (`+$33.55`) |
| `country:TW` (TW) | Historical (`EWT`) | −26.1% | 5.5% → 4.4% | $9,818 → $9,677 (−$141) | $9,818 → $9,705 (−$113) | loses $28 less (`+$28.20`) |
| `sector:communication_services` (Communication Services) | Historical (`XLC`) | −15.8% | 7.6% → 6.1% | $9,818 → $9,700 (−$118) | $9,818 → $9,723 (−$94) | loses $24 less (`+$23.58`) |
| `country:KR` (KR) | Historical (`EWY`) | −28.3% | 3.8% → 3.0% | $9,818 → $9,713 (−$104) | $9,818 → $9,734 (−$84) | loses $20 less (`+$20.89`) |
| `sector:financials` (Financials) | Historical (`XLF`) | −15.7% | 6.4% → 5.1% | $9,818 → $9,719 (−$98) | $9,818 → $9,739 (−$79) | loses $19 less (`+$19.69`) |
| `sector:industrials` (Industrials) | Historical (`XLI`) | −14.8% | 4.3% → 3.4% | $9,818 → $9,755 (−$62) | $9,818 → $9,768 (−$50) | loses $12 less (`+$12.46`) |
| `sector:health_care` (Health Care) | Historical (`XLV`) | −11.2% | 5.2% → 4.2% | $9,818 → $9,761 (−$57) | $9,818 → $9,772 (−$46) | loses $11 less (`+$11.42`) |
| `country:HK` (HK) | Historical (`EWH`) | −15.3% | 3.5% → 2.8% | $9,818 → $9,765 (−$53) | $9,818 → $9,776 (−$42) | loses $11 less (`+$10.52`) |
| `sector:consumer_staples` (Consumer Staples) | Historical (`XLP`) | −12.4% | 3.8% → 3.0% | $9,818 → $9,772 (−$46) | $9,818 → $9,781 (−$37) | loses $9 less (`+$9.20`) |
| `sector:energy` (Energy) | Historical (`XLE`) | −23.0% | 1.6% → 1.3% | $9,818 → $9,781 (−$36) | $9,818 → $9,789 (−$29) | loses $7 less (`+$7.24`) |
| `country:IN` (IN) | Historical (`INDA`) | −13.1% | 2.6% → 2.1% | $9,818 → $9,784 (−$33) | $9,818 → $9,791 (−$27) | loses $6 less (`+$6.67`) |
| `sector:materials` (Materials) | Historical (`XLB`) | −16.6% | 1.9% → 1.5% | $9,818 → $9,787 (−$31) | $9,818 → $9,793 (−$25) | loses $6 less (`+$6.14`) |
| `country:CN` (CN) | Historical (`MCHI`) | −28.2% | 0.8% → 0.7% | $9,818 → $9,795 (−$23) | $9,818 → $9,799 (−$18) | loses $5 less (`+$4.55`) |
| `sector:real_estate` (Real Estate) | Historical (`XLRE`) | −20.0% | 0.9% → 0.7% | $9,818 → $9,800 (−$18) | $9,818 → $9,803 (−$14) | loses $4 less (`+$3.61`) |
| `country:BR` (BR) | Historical (`EWZ`) | −26.2% | 0.7% → 0.6% | $9,818 → $9,800 (−$18) | $9,818 → $9,803 (−$14) | loses $4 less (`+$3.55`) |
| `country:ZA` (ZA) | Historical (`EZA`) | −21.3% | 0.7% → 0.5% | $9,818 → $9,803 (−$14) | $9,818 → $9,806 (−$11) | loses $3 less (`+$2.86`) |
| `country:SA` (SA) | Historical (`KSA`) | −14.2% | 0.5% → 0.4% | $9,818 → $9,811 (−$7) | $9,818 → $9,812 (−$6) | loses $1 less (`+$1.42`) |
| `country:PL` (PL) | Historical (`EPOL`) | −27.5% | 0.3% → 0.2% | $9,818 → $9,811 (−$7) | $9,818 → $9,812 (−$6) | loses $1 less (`+$1.41`) |
| `country:MX` (MX) | Historical (`EWW`) | −18.6% | 0.4% → 0.3% | $9,818 → $9,811 (−$7) | $9,818 → $9,812 (−$6) | loses $1 less (`+$1.38`) |
| `country:AE` (AE) | Historical (`UAE`) | −19.6% | 0.3% → 0.2% | $9,818 → $9,812 (−$5) | $9,818 → $9,813 (−$4) | loses $1 less (`+$1.07`) |
| `country:GR` (GR) | Historical (`GREK`) | −18.5% | 0.1% → 0.1% | $9,818 → $9,815 (−$2) | $9,818 → $9,816 (−$2) | same (`$+0.48`) |
| `country:MY` (MY) | Historical (`EWM`) | −10.7% | 0.2% → 0.2% | $9,818 → $9,816 (−$2) | $9,818 → $9,816 (−$2) | same (`$+0.42`) |
| `country:KW` (KW) | Historical (`KWT`) | −10.7% | 0.1% → 0.1% | $9,818 → $9,816 (−$1) | $9,818 → $9,817 (−$1) | same (`$+0.25`) |
| `country:US` (US) | Historical (`SPY`) | −12.8% | 78.9% → 83.1% | $9,818 → $8,826 (−$992) | $9,818 → $8,773 (−$1,044) | loses $52 more (`-$52.46`) |
| `sector:utilities` (Utilities) | Historical (`XLU`) | −18.6% | 1.2% → 20.9% | $9,818 → $9,796 (−$21) | $9,818 → $9,437 (−$381) | loses $360 more (`-$359.20`) |

## 3. Full Sector & Country Scan — US core with a tech tilt (% mode) ($10,000 notional (% mode))

- **Top Change Idea**: Swap 20% QQQ -> VTV

| Shock (`kind:key`) | Basis | Drop | Exposed (`Before -> After`) | Your Portfolio (`Before -> After`) | Your New Mix (`Before -> After`) | Delta |
|---|---|---:|---|---|---|---|
| `sector:information_technology` (Information Technology) | Historical (`XLK`) | −19.4% | 50.6% → 41.3% | $10,000 → $9,019 (−$981) | $10,000 → $9,199 (−$801) | loses $180 less (`+$179.92`) |
| `supplier:ALIAS:TSMC` (TSMC) | Simulated | −20.0% | 16.3% → 12.6% | $10,000 → $9,674 (−$326) | $10,000 → $9,748 (−$252) | loses $74 less (`+$73.47`) |
| `sector:communication_services` (Communication Services) | Historical (`XLC`) | −15.8% | 7.6% → 5.6% | $10,000 → $9,880 (−$120) | $10,000 → $9,912 (−$88) | loses $32 less (`+$31.22`) |
| `sector:consumer_discretionary` (Consumer Discretionary) | Historical (`XLY`) | −22.4% | 7.6% → 6.3% | $10,000 → $9,829 (−$171) | $10,000 → $9,859 (−$141) | loses $30 less (`+$30.17`) |
| `country:AE` (AE) | Historical (`UAE`) | −19.6% | 0.3% → 0.3% | $10,000 → $9,995 (−$5) | $10,000 → $9,995 (−$5) | same (`$+0.00`) |
| `country:BR` (BR) | Historical (`EWZ`) | −26.2% | 0.7% → 0.7% | $10,000 → $9,982 (−$18) | $10,000 → $9,982 (−$18) | same (`$+0.00`) |
| `country:CN` (CN) | Historical (`MCHI`) | −28.2% | 0.8% → 0.8% | $10,000 → $9,977 (−$23) | $10,000 → $9,977 (−$23) | same (`$+0.00`) |
| `country:GR` (GR) | Historical (`GREK`) | −18.5% | 0.1% → 0.1% | $10,000 → $9,998 (−$2) | $10,000 → $9,998 (−$2) | same (`$+0.00`) |
| `country:HK` (HK) | Historical (`EWH`) | −15.3% | 3.4% → 3.4% | $10,000 → $9,948 (−$52) | $10,000 → $9,948 (−$52) | same (`$+0.00`) |
| `country:IN` (IN) | Historical (`INDA`) | −13.1% | 2.5% → 2.5% | $10,000 → $9,967 (−$33) | $10,000 → $9,967 (−$33) | same (`$+0.00`) |
| `country:KR` (KR) | Historical (`EWY`) | −28.3% | 3.7% → 3.7% | $10,000 → $9,896 (−$104) | $10,000 → $9,896 (−$104) | same (`$+0.00`) |
| `country:KW` (KW) | Historical (`KWT`) | −10.7% | 0.1% → 0.1% | $10,000 → $9,999 (−$1) | $10,000 → $9,999 (−$1) | same (`$+0.00`) |
| `country:MX` (MX) | Historical (`EWW`) | −18.6% | 0.4% → 0.4% | $10,000 → $9,993 (−$7) | $10,000 → $9,993 (−$7) | same (`$+0.00`) |
| `country:MY` (MY) | Historical (`EWM`) | −10.7% | 0.2% → 0.2% | $10,000 → $9,998 (−$2) | $10,000 → $9,998 (−$2) | same (`$+0.00`) |
| `country:PL` (PL) | Historical (`EPOL`) | −27.5% | 0.3% → 0.3% | $10,000 → $9,993 (−$7) | $10,000 → $9,993 (−$7) | same (`$+0.00`) |
| `country:SA` (SA) | Historical (`KSA`) | −14.2% | 0.5% → 0.5% | $10,000 → $9,993 (−$7) | $10,000 → $9,993 (−$7) | same (`$+0.00`) |
| `country:TW` (TW) | Historical (`EWT`) | −26.1% | 5.4% → 5.4% | $10,000 → $9,860 (−$140) | $10,000 → $9,860 (−$140) | same (`$+0.00`) |
| `country:ZA` (ZA) | Historical (`EZA`) | −21.3% | 0.7% → 0.7% | $10,000 → $9,986 (−$14) | $10,000 → $9,986 (−$14) | same (`$+0.00`) |
| `country:US` (US) | Historical (`SPY`) | −12.8% | 79.5% → 79.8% | $10,000 → $8,982 (−$1,018) | $10,000 → $8,979 (−$1,021) | loses $3 more (`-$3.25`) |
| `sector:consumer_staples` (Consumer Staples) | Historical (`XLP`) | −12.4% | 3.8% → 4.3% | $10,000 → $9,953 (−$47) | $10,000 → $9,947 (−$53) | loses $6 more (`-$6.06`) |
| `sector:materials` (Materials) | Historical (`XLB`) | −16.6% | 1.9% → 2.3% | $10,000 → $9,969 (−$31) | $10,000 → $9,962 (−$38) | loses $7 more (`-$6.87`) |
| `sector:real_estate` (Real Estate) | Historical (`XLRE`) | −20.0% | 1.0% → 1.5% | $10,000 → $9,981 (−$19) | $10,000 → $9,971 (−$29) | loses $10 more (`-$10.06`) |
| `sector:utilities` (Utilities) | Historical (`XLU`) | −18.6% | 1.2% → 1.9% | $10,000 → $9,978 (−$22) | $10,000 → $9,964 (−$36) | loses $14 more (`-$13.59`) |
| `sector:health_care` (Health Care) | Historical (`XLV`) | −11.2% | 5.4% → 7.7% | $10,000 → $9,940 (−$60) | $10,000 → $9,914 (−$86) | loses $26 more (`-$25.86`) |
| `sector:energy` (Energy) | Historical (`XLE`) | −23.0% | 1.7% → 3.0% | $10,000 → $9,961 (−$39) | $10,000 → $9,932 (−$68) | loses $29 more (`-$29.39`) |
| `sector:industrials` (Industrials) | Historical (`XLI`) | −14.8% | 4.4% → 6.7% | $10,000 → $9,935 (−$65) | $10,000 → $9,901 (−$99) | loses $34 more (`-$34.15`) |
| `sector:financials` (Financials) | Historical (`XLF`) | −15.7% | 6.6% → 11.1% | $10,000 → $9,896 (−$104) | $10,000 → $9,825 (−$175) | loses $71 more (`-$70.50`) |

## 3. Full Sector & Country Scan — Global market with a Nasdaq-100 tilt (% mode) ($10,000 notional (% mode))

- **Top Change Idea**: Add 20% IWM (Add smaller companies (IWM))

| Shock (`kind:key`) | Basis | Drop | Exposed (`Before -> After`) | Your Portfolio (`Before -> After`) | Your New Mix (`Before -> After`) | Delta |
|---|---|---:|---|---|---|---|
| `sector:information_technology` (Information Technology) | Historical (`XLK`) | −19.4% | 34.0% → 29.7% | $10,000 → $9,341 (−$659) | $10,000 → $9,424 (−$576) | loses $83 less (`+$83.81`) |
| `supplier:ALIAS:TSMC` (TSMC) | Simulated | −20.0% | 10.4% → 8.4% | $10,000 → $9,791 (−$209) | $10,000 → $9,833 (−$167) | loses $42 less (`+$41.77`) |
| `sector:communication_services` (Communication Services) | Historical (`XLC`) | −15.8% | 8.1% → 6.9% | $10,000 → $9,873 (−$127) | $10,000 → $9,891 (−$109) | loses $18 less (`+$18.09`) |
| `country:TW` (TW) | Historical (`EWT`) | −26.1% | 2.1% → 1.5% | $10,000 → $9,946 (−$54) | $10,000 → $9,960 (−$40) | loses $14 less (`+$14.63`) |
| `country:JP` (JP) | Historical (`EWJ`) | −12.6% | 3.6% → 2.5% | $10,000 → $9,954 (−$46) | $10,000 → $9,968 (−$32) | loses $14 less (`+$13.84`) |
| `country:KR` (KR) | Historical (`EWY`) | −28.3% | 1.5% → 1.1% | $10,000 → $9,958 (−$42) | $10,000 → $9,969 (−$31) | loses $11 less (`+$11.32`) |
| `country:GB` (GB) | Historical (`EWU`) | −15.3% | 2.2% → 1.6% | $10,000 → $9,967 (−$33) | $10,000 → $9,976 (−$24) | loses $9 less (`+$9.07`) |
| `country:HK` (HK) | Historical (`EWH`) | −15.3% | 1.5% → 1.0% | $10,000 → $9,978 (−$22) | $10,000 → $9,985 (−$15) | loses $7 less (`+$7.49`) |
| `country:DE` (DE) | Historical (`EWG`) | −22.5% | 1.3% → 1.0% | $10,000 → $9,970 (−$30) | $10,000 → $9,978 (−$22) | loses $8 less (`+$7.36`) |
| `country:FR` (FR) | Historical (`EWQ`) | −19.2% | 1.4% → 1.1% | $10,000 → $9,973 (−$27) | $10,000 → $9,980 (−$20) | loses $7 less (`+$7.03`) |
| `sector:consumer_staples` (Consumer Staples) | Historical (`XLP`) | −12.4% | 4.5% → 4.0% | $10,000 → $9,944 (−$56) | $10,000 → $9,950 (−$50) | loses $6 less (`+$5.82`) |
| `country:AU` (AU) | Historical (`EWA`) | −15.3% | 1.1% → 0.8% | $10,000 → $9,983 (−$17) | $10,000 → $9,988 (−$12) | loses $5 less (`+$5.20`) |
| `country:IN` (IN) | Historical (`INDA`) | −13.1% | 0.8% → 0.4% | $10,000 → $9,989 (−$11) | $10,000 → $9,995 (−$5) | loses $6 less (`+$5.06`) |
| `country:CH` (CH) | Historical (`EWL`) | −13.5% | 1.4% → 1.1% | $10,000 → $9,981 (−$19) | $10,000 → $9,985 (−$15) | loses $4 less (`+$4.67`) |
| `country:NL` (NL) | Historical (`EWN`) | −18.9% | 0.9% → 0.7% | $10,000 → $9,982 (−$18) | $10,000 → $9,986 (−$14) | loses $4 less (`+$4.26`) |
| `country:SE` (SE) | Historical (`EWD`) | −21.9% | 0.5% → 0.3% | $10,000 → $9,989 (−$11) | $10,000 → $9,993 (−$7) | loses $4 less (`+$4.00`) |
| `country:IT` (IT) | Historical (`EWI`) | −21.8% | 0.5% → 0.4% | $10,000 → $9,988 (−$12) | $10,000 → $9,992 (−$8) | loses $4 less (`+$3.18`) |
| `country:ES` (ES) | Historical (`EWP`) | −16.4% | 0.7% → 0.5% | $10,000 → $9,989 (−$11) | $10,000 → $9,992 (−$8) | loses $3 less (`+$2.60`) |
| `sector:materials` (Materials) | Historical (`XLB`) | −16.6% | 3.0% → 3.2% | $10,000 → $9,950 (−$50) | $10,000 → $9,947 (−$53) | loses $3 more (`-$3.49`) |
| `sector:utilities` (Utilities) | Historical (`XLU`) | −18.6% | 1.9% → 2.1% | $10,000 → $9,964 (−$36) | $10,000 → $9,960 (−$40) | loses $4 more (`-$4.11`) |
| `sector:consumer_discretionary` (Consumer Discretionary) | Historical (`XLY`) | −22.4% | 8.6% → 8.8% | $10,000 → $9,807 (−$193) | $10,000 → $9,802 (−$198) | loses $5 more (`-$5.33`) |
| `sector:energy` (Energy) | Historical (`XLE`) | −23.0% | 2.6% → 3.2% | $10,000 → $9,939 (−$61) | $10,000 → $9,927 (−$73) | loses $12 more (`-$12.11`) |
| `sector:industrials` (Industrials) | Historical (`XLI`) | −14.8% | 9.0% → 10.0% | $10,000 → $9,866 (−$134) | $10,000 → $9,851 (−$149) | loses $15 more (`-$14.37`) |
| `sector:real_estate` (Real Estate) | Historical (`XLRE`) | −20.0% | 1.8% → 2.7% | $10,000 → $9,964 (−$36) | $10,000 → $9,947 (−$53) | loses $17 more (`-$16.81`) |
| `sector:financials` (Financials) | Historical (`XLF`) | −15.7% | 11.3% → 13.0% | $10,000 → $9,822 (−$178) | $10,000 → $9,795 (−$205) | loses $27 more (`-$26.76`) |
| `sector:health_care` (Health Care) | Historical (`XLV`) | −11.2% | 7.1% → 9.8% | $10,000 → $9,921 (−$79) | $10,000 → $9,890 (−$110) | loses $31 more (`-$30.71`) |
| `country:US` (US) | Historical (`SPY`) | −12.8% | 68.8% → 71.4% | $10,000 → $9,120 (−$880) | $10,000 → $9,086 (−$914) | loses $34 more (`-$34.01`) |
