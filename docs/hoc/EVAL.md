# House of Cards v3 — Unseen-Data Dependency Extraction Evaluation (`E-RUN`)

## 1. Run Metadata & Methodology

| Parameter | Value |
|---|---|
| **Evaluation Mode** | `replay` |
| **Git Commit** | `4fea05a` |
| **Extractor Prompt Version** | `hoc-v2-extract-1` |
| **V-INT Judge Prompt Version** | `hoc-v3-judge-1` |
| **Held-Out Companies Evaluated** | `10` |
| **Gold Relationships Total** | `212` (`115` core + `97` extended; `212` initial blind, `0` pooled) |
| **Core Gold by Source** | `a`: 26, `b`: 8, `both`: 81 |
| **Gold Hard Negatives** | `79` |
| **Bootstrap Confidence Intervals** | 95% percentile CI across companies (`B = 2000`, seed `20261108`) |

### Matching & Scoring Rules (`docs/hoc/PLAN-v3.md` §1 & `docs/hoc/eval/ADJUDICATION.md`)
- **Target Resolution**: A predicted `VerifiedEdge` matches a gold relationship on the same company when `hoc.filings.names.name_key(target)` matches `target_name` or any entry in `aliases[]`, when both resolve to the same ISO-2 country via `hoc.graph.metrics.canonical_country_info` (or explicit `gold.country`) for facility/country targets, or when both describe the same `unnamed_customer` revenue-share disclosure.
- **Compatible Edge Types**: Exact match on all 7 `EdgeType` values, any type listed in `edge_type_alternatives[]`, plus compatible equivalence groups `supplier` ↔ `key_input` (and sole-source supplier) and `foundry` ↔ `contract_manufacturer`.
- **Core vs. Extended Tiers**: Core relationships (`tier = "core"`) count toward recall (a missing core relationship is a false negative). Extended relationships (`tier = "extended"`) are optional list/distribution items: a prediction matching an extended item counts as a true positive for precision, while an unextracted extended item is not a false negative.
- **Hard Negatives & Pooling**: A prediction matching a hard negative is always a false positive. Remaining unmatched verified predictions are exported as `pooled_candidates` for blind adjudication; approved pooled additions carry `"source": "pooled"`. Of the `212` gold relationships in this run, `212` came from initial blind annotation and `0` came from pooling.

---

## 2. Headline Metrics (After V-INT, with 95% Bootstrap CIs)

| Metric | Score & 95% CI (Count) |
|---|---|
| **Micro Precision (After V-INT)** | 88.4% [83.0%, 92.9%] (114/129) |
| **Micro Recall on Core (After V-INT)** | 57.4% [35.3%, 76.0%] (66/115) |
| **Micro F1 (After V-INT)** | 69.6% [52.1%, 82.1%] |
| **Macro Precision (After V-INT)** | 89.3% [82.7%, 94.9%] |
| **Macro Recall on Core (After V-INT)** | 60.9% [42.6%, 76.1%] |
| **Macro F1 (After V-INT)** | 68.2% [51.6%, 81.9%] |
| **Direction Accuracy** (`depends_on_target` vs. `target_depends_on_company`) | 100.0% [100.0%, 100.0%] (114/114) |
| **Hard-Negative False-Positive Rate (After V-INT)** | 1.3% [0.0%, 3.9%] (1/79) |
| **Facility-Country Accuracy** (ISO-2 country resolution) | 100.0% [100.0%, 100.0%] (39/39) |
| **Importance-Tier Agreement (Quadratic Weighted Cohen's $\kappa$)** | 0.475 [0.382, 0.631] (54/79) |
| **Importance-Tier Agreement (Linear Weighted Cohen's $\kappa$)** | 0.466 [0.299, 0.637] (54/79) |
| **Importance-Tier Exact Agreement** | 68.3% [50.0%, 84.0%] (54/79) |

---

## 3. Before vs. After V-INT (Quote Verification Only vs. Quote + Semantic Interpretation Verification)

| Metric | Before V-INT (Quote Check Only) | After V-INT (Quote + V-INT) | Delta (After − Before) |
|---|---|---|---|
| **Micro Precision** | 88.4% [82.6%, 92.7%] (114/129) | 88.4% [83.0%, 92.9%] (114/129) | `+0.0 pp` |
| **Micro Recall (Core)** | 57.4% [36.2%, 75.9%] (66/115) | 57.4% [35.3%, 76.0%] (66/115) | `+0.0 pp` |
| **Micro F1** | 69.6% [52.0%, 82.5%] | 69.6% [52.1%, 82.1%] | `+0.0 pp` |
| **Macro Precision** | 89.3% [82.4%, 94.8%] | 89.3% [82.7%, 94.9%] | `+0.0 pp` |
| **Macro Recall (Core)** | 60.9% [44.1%, 76.8%] | 60.9% [42.6%, 76.1%] | `+0.0 pp` |
| **Macro F1** | 68.2% [51.9%, 81.9%] | 68.2% [51.6%, 81.9%] | `+0.0 pp` |
| **Hard-Negative FP Rate** | 1.3% [0.0%, 3.8%] (1/79) | 1.3% [0.0%, 3.9%] (1/79) | `+0.0 pp` |
| **Predicted Edges (TP [Core+Ext] / FP / Core FN)** | `129` (`114` [`66`+`13`] / `15` / `49`) | `129` (`114` [`66`+`13`] / `15` / `49`) | `+0` edges |

---

## 4. Per-`edge_type` Breakdown (After V-INT)

| `edge_type` | Gold (Core+Ext) | Predicted | TP (Core+Ext) | FP | Core FN | Precision (95% CI) | Core Recall (95% CI) | F1 (95% CI) |
|---|---:|---:|---:|---:|---:|---|---|---|
| `supplier` | 4 (3+1) | 6 | 1 (0+0) | 5 | 3 | 16.7% [0.0%, 25.0%] (1/6) | 0.0% [0.0%, 0.0%] (0/3) | 0.0% [0.0%, 0.0%] |
| `customer` | 43 (8+35) | 18 | 11 (5+6) | 7 | 3 | 61.1% [16.7%, 83.3%] (11/18) | 62.5% [18.2%, 100.0%] (5/8) | 61.8% [20.0%, 87.0%] |
| `contract_manufacturer` | 9 (8+1) | 5 | 5 (6+0) | 0 | 2 | 100.0% [0.0%, 100.0%] (5/5) | 75.0% [33.3%, 100.0%] (6/8) | 85.7% [0.0%, 100.0%] |
| `foundry` | 1 (0+1) | 0 | 0 (0+0) | 0 | 0 | 100.0% [100.0%, 100.0%] (0/0) | 100.0% [100.0%, 100.0%] (0/0) | 100.0% [100.0%, 100.0%] |
| `key_input` | 76 (20+56) | 18 | 17 (9+7) | 1 | 11 | 94.4% [72.7%, 100.0%] (17/18) | 45.0% [15.4%, 80.0%] (9/20) | 61.0% [26.7%, 88.9%] |
| `facility` | 61 (58+3) | 68 | 68 (35+0) | 0 | 23 | 100.0% [100.0%, 100.0%] (68/68) | 60.3% [29.8%, 89.1%] (35/58) | 75.3% [46.0%, 94.2%] |
| `jv_partner` | 18 (18+0) | 14 | 12 (11+0) | 2 | 7 | 85.7% [46.7%, 100.0%] (12/14) | 61.1% [23.1%, 96.2%] (11/18) | 71.4% [35.3%, 100.0%] |

---

## 5. Per-Company Breakdown

| Ticker | Company | Accession | Gold (Core+Ext) | Negs | Pred (Pre→Post V-INT) | TP (Core+Ext) | FP | Core FN | P (Pre→Post) | Core R | F1 | Dir Acc | Hard-Neg FP (Pre→Post) | Fac Country |
|---|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---|---|---|
| `NKE` | NIKE, Inc. | `0000320187-26-000088` | 25 (9+16) | 10 | 9→9 | 6 (5+0) | 3 | 4 | 66.7%→66.7% | 55.6% | 60.6% | 6/6 | 0→0/10 | 5/5 |
| `F` | Ford Motor Company | `0000037996-26-000015` | 28 (17+11) | 9 | 18→18 | 15 (14+0) | 3 | 3 | 83.3%→83.3% | 82.3% | 82.8% | 15/15 | 0→0/9 | 6/6 |
| `GM` | General Motors Company | `0001467858-26-000013` | 24 (9+15) | 8 | 14→14 | 12 (3+7) | 2 | 6 | 85.7%→85.7% | 33.3% | 48.0% | 12/12 | 0→0/8 | 2/2 |
| `BA` | The Boeing Company | `0001628280-26-004357` | 14 (12+2) | 7 | 10→10 | 8 (5+0) | 2 | 7 | 80.0%→80.0% | 41.7% | 54.8% | 8/8 | 0→0/7 | 1/1 |
| `SWKS` | Skyworks Solutions, Inc. | `0000004127-25-000085` | 43 (7+36) | 7 | 15→15 | 14 (7+6) | 1 | 0 | 93.3%→93.3% | 100.0% | 96.5% | 14/14 | 0→0/7 | 4/4 |
| `QRVO` | Qorvo, Inc. | `0001628280-26-032873` | 11 (10+1) | 7 | 8→8 | 8 (6+0) | 0 | 4 | 100.0%→100.0% | 60.0% | 75.0% | 8/8 | 0→0/7 | 2/2 |
| `GLW` | Corning Incorporated | `0000024741-26-000124` | 19 (13+6) | 9 | 16→16 | 15 (11+0) | 1 | 2 | 93.8%→93.8% | 84.6% | 88.9% | 15/15 | 1→1/9 | 10/10 |
| `PFE` | Pfizer Inc. | `0000078003-26-000026` | 19 (19+0) | 8 | 1→1 | 1 (1+0) | 0 | 18 | 100.0%→100.0% | 5.3% | 10.0% | 1/1 | 0→0/8 | — |
| `DE` | Deere & Company | `0001104659-25-122321` | 17 (12+5) | 6 | 32→32 | 29 (9+0) | 3 | 3 | 90.6%→90.6% | 75.0% | 82.1% | 29/29 | 0→0/6 | 8/8 |
| `SBUX` | Starbucks Corporation | `0000829224-25-000114` | 12 (7+5) | 8 | 6→6 | 6 (5+0) | 0 | 2 | 100.0%→100.0% | 71.4% | 83.3% | 6/6 | 0→0/8 | 1/1 |

---

## 6. Hard-Negative False-Positive Rate by Category

| Negative Kind | Gold Negatives | Falsely Extracted (Before V-INT) | Falsely Extracted (After V-INT) | Rate Before V-INT | Rate After V-INT |
|---|---:|---:|---:|---:|---:|
| `competitor` | 27 | 0 | 0 | 0.0% | 0.0% |
| `generic` | 25 | 1 | 1 | 4.0% | 4.0% |
| `hypothetical` | 9 | 0 | 0 | 0.0% | 0.0% |
| `negated` | 11 | 0 | 0 | 0.0% | 0.0% |
| `unrelated` | 7 | 0 | 0 | 0.0% | 0.0% |

---

## 7. All False Positives After V-INT (15)

| Ticker | Edge ID | `edge_type` | Target (`target_kind`) | Reason | Verbatim Quote |
|---|---|---|---|---|---|
| `NKE` | `edge_d3ccd3a1052a` | `customer` | Unnamed Customer (`unnamed_customer`) | Unmatched verified prediction (pooled candidate / unannot... | "During fiscal 2026, NIKE's three largest customers outside of the United States accounted for approximately 16% of total non-U.S. sales." |
| `NKE` | `edge_db8132253be5` | `supplier` | Air Manufacturing Innovation (`company`) | Unmatched verified prediction (pooled candidate / unannot... | "During fiscal 2026, Air Manufacturing Innovation, a wholly-owned subsidiary, with facilities near Beaverton, Oregon, in Dong Nai City, Vi..." |
| `NKE` | `edge_55810b619d12` | `supplier` | Sojitz Corporation of America (`company`) | Unmatched verified prediction (pooled candidate / unannot... | "Since 1972, Sojitz Corporation of America ("Sojitz America"), a large Japanese trading company and the sole owner of our redeemable prefe..." |
| `F` | `edge_83e00ad1aec8` | `supplier` | Takata (`company`) | Unmatched verified prediction (pooled candidate / unannot... | "For example, NHTSA and the automotive industry are currently engaged in a study of the safety of approximately 56 million Takata desiccat..." |
| `F` | `edge_cf85a07ce5ef` | `supplier` | ARC Automotive (`company`) | Unmatched verified prediction (pooled candidate / unannot... | "In addition, NHTSA is considering action related to 52 million vehicles containing inflators from ARC Automotive and Delphi Automotive in..." |
| `F` | `edge_a7c38c5f5085` | `supplier` | Delphi Automotive (`company`) | Unmatched verified prediction (pooled candidate / unannot... | "In addition, NHTSA is considering action related to 52 million vehicles containing inflators from ARC Automotive and Delphi Automotive in..." |
| `GM` | `edge_d3d268649da2` | `jv_partner` | SAIC General Motors Sales Co., Ltd. (`company`) | Unmatched verified prediction (pooled candidate / unannot... | "Includes sales by the Automotive China Joint Ventures (Automotive China JVs): SAIC General Motors Sales Co., Ltd. (SGMS) and SAIC GM Wuli..." |
| `GM` | `edge_85f1bd72c86f` | `jv_partner` | SAIC GM Wuling Automobile Co., Ltd. (`company`) | Unmatched verified prediction (pooled candidate / unannot... | "Includes sales by the Automotive China Joint Ventures (Automotive China JVs): SAIC General Motors Sales Co., Ltd. (SGMS) and SAIC GM Wuli..." |
| `BA` | `edge_8058aeca27ad` | `customer` | United States Department of War (`company`) | Unmatched verified prediction (pooled candidate / unannot... | "We derive a substantial portion of our revenue from the U.S. government, primarily from defense related programs with the United States D..." |
| `BA` | `edge_dea2976ebbd3` | `customer` | NASA (`company`) | Unmatched verified prediction (pooled candidate / unannot... | "We derive a substantial portion of our revenue from the U.S. government, primarily from defense related programs with the United States D..." |
| `SWKS` | `edge_bc723b6898e2` | `customer` | Unnamed Customer (`unnamed_customer`) | Unmatched verified prediction (pooled candidate / unannot... | "In each of fiscal 2025, fiscal 2024, and fiscal 2023, one customer accounted for greater than ten percent of our net revenue." |
| `GLW` | `edge_4a8f0bde58a7` | `customer` | Unnamed Customer (`unnamed_customer`) | Hard negative leak (generic: GLW-NADJ1) | "The following table details the number of combined customers of our reportable segments that accounted for a large percentage of segment ..." |
| `DE` | `edge_e60d52406d66` | `customer` | The Home Depot (`company`) | Unmatched verified prediction (pooled candidate / unannot... | "although the segment also builds turf products for sale by mass retailers, including The Home Depot and Lowe's." |
| `DE` | `edge_a31a7be471da` | `customer` | Lowe's (`company`) | Unmatched verified prediction (pooled candidate / unannot... | "although the segment also builds turf products for sale by mass retailers, including The Home Depot and Lowe's." |
| `DE` | `edge_448da3c0e5ef` | `key_input` | rare earth minerals (`material`) | Unmatched verified prediction (pooled candidate / unannot... | "certain of our products, including motors, batteries, and other components, rely on rare earth minerals for their manufacturing, of which..." |

---

## 8. All Core False Negatives After V-INT (49)

| Ticker | Gold ID | `edge_type` | Target (`target_kind`) | Reason | Gold Quote |
|---|---|---|---|---|---|
| `NKE` | `NKE-7` | `facility` | Netherlands (`country`) | Core gold relationship (importance=low, source=a) not ext... | "We lease a similar, but smaller, administrative facility in Hilversum, the Netherlands, which serves as the headquarters for our EMEA geo..." |
| `NKE` | `NKE-10` | `key_input` | cotton (`material`) | Core gold relationship (importance=high, source=a) not ex... | "Continued volatility in the availability and prices for commodities and raw materials we use in our products and in our supply chain (suc..." |
| `NKE` | `NKE-16` | `key_input` | NIKE Air-Sole cushioning components (`component`) | Core gold relationship (importance=medium, source=b) not ... | "contract manufacturers in China and Vietnam, were our suppliers of NIKE Air-Sole and other cushioning components used in footwear" |
| `NKE` | `NKE-18` | `key_input` | petroleum derivatives (`material`) | Core gold relationship (importance=high, source=a) not ex... | "Continued volatility in the availability and prices for commodities and raw materials we use in our products and in our supply chain (suc..." |
| `F` | `F-18` | `contract_manufacturer` | Jiangling Motors Corporation, Ltd. (`company`) | Core gold relationship (importance=medium, source=b) not ... | "units produced by our unconsolidated Chinese joint venture Jiangling Motors Corporation, Ltd." |
| `F` | `F-19` | `contract_manufacturer` | Lio Ho Group (`company`) | Core gold relationship (importance=low, source=b) not ext... | "Ford badged vehicles produced in Taiwan by Lio Ho Group" |
| `F` | `F-25` | `supplier` | Novelis Inc. (`company`) | Core gold relationship (importance=high, source=b) not ex... | "Novelis is a major aluminum supplier to Ford, and since the initial fire occurred, we have been working closely with Novelis to address t..." |
| `GM` | `GM-1` | `facility` | Brazil (`country`) | Core gold relationship (importance=medium, source=both) n... | "The major facilities outside the U.S., which are principally vehicle manufacturing and assembly operations, are located in Canada and Mex..." |
| `GM` | `GM-2` | `facility` | Canada (`country`) | Core gold relationship (importance=high, source=both) not... | "The major facilities outside the U.S., which are principally vehicle manufacturing and assembly operations, are located in Canada and Mex..." |
| `GM` | `GM-3` | `facility` | China (`country`) | Core gold relationship (importance=medium, source=both) n... | "The major facilities outside the U.S., which are principally vehicle manufacturing and assembly operations, are located in Canada and Mex..." |
| `GM` | `GM-4` | `facility` | South Korea (`country`) | Core gold relationship (importance=high, source=both) not... | "The major facilities outside the U.S., which are principally vehicle manufacturing and assembly operations, are located in Canada and Mex..." |
| `GM` | `GM-8` | `jv_partner` | Shanghai Automotive Industry Corporat... (`company`) | Core gold relationship (importance=high, source=b) not ex... | "SGM is a joint venture we established with Shanghai Automotive Industry Corporation (SAIC) (50%)." |
| `GM` | `GM-24` | `supplier` | Ultium Cells Holdings LLC (`company`) | Core gold relationship (importance=medium, source=both) n... | "Our EV portfolio takes advantage of integrated supply chain development, including battery cell production from Ultium Cells Holdings LLC..." |
| `BA` | `BA-2` | `facility` | Australia (`country`) | Core gold relationship (importance=low, source=both) not ... | "Commercial Airplanes - Greater Seattle, WA; Wichita, KS; China; Greater Charleston, SC; Greater Los Angeles, CA; Tulsa, OK; Greater Portl..." |
| `BA` | `BA-3` | `facility` | Canada (`country`) | Core gold relationship (importance=low, source=both) not ... | "Commercial Airplanes - Greater Seattle, WA; Wichita, KS; China; Greater Charleston, SC; Greater Los Angeles, CA; Tulsa, OK; Greater Portl..." |
| `BA` | `BA-4` | `facility` | China (`country`) | Core gold relationship (importance=low, source=both) not ... | "Commercial Airplanes - Greater Seattle, WA; Wichita, KS; China; Greater Charleston, SC; Greater Los Angeles, CA; Tulsa, OK; Greater Portl..." |
| `BA` | `BA-5` | `facility` | Great Britain (`country`) | Core gold relationship (importance=low, source=a) not ext... | "Other - Great Britain; India; Greater Los Angeles, CA; and Greater Washington, DC" |
| `BA` | `BA-6` | `facility` | India (`country`) | Core gold relationship (importance=low, source=a) not ext... | "Other - Great Britain; India; Greater Los Angeles, CA; and Greater Washington, DC" |
| `BA` | `BA-7` | `facility` | Mexico (`country`) | Core gold relationship (importance=low, source=both) not ... | "Commercial Airplanes - Greater Seattle, WA; Wichita, KS; China; Greater Charleston, SC; Greater Los Angeles, CA; Tulsa, OK; Greater Portl..." |
| `BA` | `BA-8` | `facility` | Malaysia (`country`) | Core gold relationship (importance=low, source=both) not ... | "Commercial Airplanes - Greater Seattle, WA; Wichita, KS; China; Greater Charleston, SC; Greater Los Angeles, CA; Tulsa, OK; Greater Portl..." |
| `QRVO` | `QRVO-6` | `key_input` | GaAs wafers (`material`) | Core gold relationship (importance=medium, source=both) n... | "In our GaN and GaAs manufacturing operations, we use several raw materials, including GaN on silicon carbide ("SiC") wafers and GaAs wafers." |
| `QRVO` | `QRVO-9` | `key_input` | passive components (`component`) | Core gold relationship (importance=high, source=a) not ex... | "We purchase numerous raw materials and parts, such as silicon, passive components and substrates for our manufacturing processes." |
| `QRVO` | `QRVO-10` | `key_input` | silicon (`material`) | Core gold relationship (importance=high, source=a) not ex... | "We purchase numerous raw materials and parts, such as silicon, passive components and substrates for our manufacturing processes." |
| `QRVO` | `QRVO-11` | `key_input` | substrates (`material`) | Core gold relationship (importance=high, source=a) not ex... | "We purchase numerous raw materials and parts, such as silicon, passive components and substrates for our manufacturing processes." |
| `GLW` | `GLW-13` | `key_input` | industrial water (`material`) | Core gold relationship (importance=high, source=a) not ex... | "Our manufacturing processes and products require access to uninterrupted power sources, significant quantities of industrial water, certa..." |
| `GLW` | `GLW-18` | `key_input` | precious metals (`material`) | Core gold relationship (importance=medium, source=both) n... | "We have adequate programs to ensure a reliable supply of raw and batch materials, as well as precious metals which are used in our produc..." |
| `PFE` | `PFE-1` | `customer` | Cardinal Health, Inc. (`company`) | Core gold relationship (importance=high, source=both) not... | "The following summarizes revenue, as a percentage of Total revenues, from our three largest U.S. wholesaler customers, which was concentr..." |
| `PFE` | `PFE-2` | `customer` | Cencora, Inc. (`company`) | Core gold relationship (importance=high, source=both) not... | "The following summarizes revenue, as a percentage of Total revenues, from our three largest U.S. wholesaler customers, which was concentr..." |
| `PFE` | `PFE-3` | `customer` | McKesson, Inc. (`company`) | Core gold relationship (importance=critical, source=both)... | "The following summarizes revenue, as a percentage of Total revenues, from our three largest U.S. wholesaler customers, which was concentr..." |
| `PFE` | `PFE-4` | `facility` | Belgium (`country`) | Core gold relationship (importance=high, source=both) not... | "As of December 31, 2025, Pfizer Global Supply (PGS) had responsibility for 36 manufacturing plants around the world, which manufacture pr..." |
| `PFE` | `PFE-5` | `facility` | Germany (`country`) | Core gold relationship (importance=medium, source=both) n... | "As of December 31, 2025, Pfizer Global Supply (PGS) had responsibility for 36 manufacturing plants around the world, which manufacture pr..." |
| `PFE` | `PFE-6` | `facility` | United Kingdom (`country`) | Core gold relationship (importance=low, source=a) not ext... | "Outside of the U.S., we lease R&D labs in the U.K., India and Belgium." |
| `PFE` | `PFE-7` | `facility` | Ireland (`country`) | Core gold relationship (importance=high, source=both) not... | "As of December 31, 2025, Pfizer Global Supply (PGS) had responsibility for 36 manufacturing plants around the world, which manufacture pr..." |
| `PFE` | `PFE-8` | `facility` | India (`country`) | Core gold relationship (importance=medium, source=both) n... | "As of December 31, 2025, Pfizer Global Supply (PGS) had responsibility for 36 manufacturing plants around the world, which manufacture pr..." |
| `PFE` | `PFE-9` | `facility` | Italy (`country`) | Core gold relationship (importance=medium, source=both) n... | "As of December 31, 2025, Pfizer Global Supply (PGS) had responsibility for 36 manufacturing plants around the world, which manufacture pr..." |
| `PFE` | `PFE-10` | `facility` | Japan (`country`) | Core gold relationship (importance=medium, source=both) n... | "As of December 31, 2025, Pfizer Global Supply (PGS) had responsibility for 36 manufacturing plants around the world, which manufacture pr..." |
| `PFE` | `PFE-11` | `facility` | Singapore (`country`) | Core gold relationship (importance=medium, source=both) n... | "As of December 31, 2025, Pfizer Global Supply (PGS) had responsibility for 36 manufacturing plants around the world, which manufacture pr..." |
| `PFE` | `PFE-12` | `facility` | United States (`country`) | Core gold relationship (importance=high, source=both) not... | "As of December 31, 2025, Pfizer Global Supply (PGS) had responsibility for 36 manufacturing plants around the world, which manufacture pr..." |
| `PFE` | `PFE-13` | `jv_partner` | Astellas (`company`) | Core gold relationship (importance=medium, source=both) n... | "Xtandi (enzalutamide) is an androgen receptor inhibitor that blocks multiple steps in the androgen receptor signaling pathway within tumo..." |
| `PFE` | `PFE-15` | `jv_partner` | BMS (`company`) | Core gold relationship (importance=medium, source=a) not ... | "Eliquis (apixaban) is part of the novel oral anticoagulant market and was jointly developed and is commercialized with BMS as an alternat..." |
| `PFE` | `PFE-16` | `jv_partner` | Genmab (`company`) | Core gold relationship (importance=medium, source=a) not ... | "Tivdak (tisotumab vedotin-tftv) is commercialized in collaboration with Genmab. Pfizer has co-promotion rights in the U.S. Outside the U...." |
| `PFE` | `PFE-17` | `jv_partner` | SMPS (`company`) | Core gold relationship (importance=medium, source=a) not ... | "Orgovyx (relugolix) is an oral gonadotropin-releasing hormone (GnRH) receptor antagonist for the treatment of adult patients with advance..." |
| `PFE` | `PFE-18` | `jv_partner` | Takeda (`company`) | Core gold relationship (importance=medium, source=a) not ... | "Adcetris (brentuximab vedotin) is being developed and commercialized in collaboration with Takeda. Pfizer has commercialization rights fo..." |
| `PFE` | `PFE-19` | `supplier` | BMS (`company`) | Core gold relationship (importance=medium, source=a) not ... | "In certain smaller markets we have full commercialization rights and BMS supplies the product to us at cost plus a percentage of the net ..." |
| `DE` | `DE-2` | `facility` | Canada (`country`) | Core gold relationship (importance=high, source=a) not ex... | "In the U.S. and Canada, the equipment operations own and operate 23 factory locations and lease and operate four locations for manufactur..." |
| `DE` | `DE-11` | `key_input` | electronics (`component`) | Core gold relationship (importance=medium, source=both) n... | "We source raw materials, manufactured components, and replacement parts for our equipment, engines, and other products from leading suppl..." |
| `DE` | `DE-17` | `key_input` | steel products (`material`) | Core gold relationship (importance=medium, source=both) n... | "We source raw materials, manufactured components, and replacement parts for our equipment, engines, and other products from leading suppl..." |
| `SBUX` | `SBUX-2` | `facility` | United States (`country`) | Core gold relationship (importance=high, source=both) not... | "York, PA 1,957,000 Roasting, warehousing and distribution" |
| `SBUX` | `SBUX-3` | `jv_partner` | Boyu Capital (`company`) | Core gold relationship (importance=medium, source=b) not ... | "our new strategic joint venture partner, Boyu Capital, to accelerate long-term growth in China" |

---

## 9. Edges Filtered Out by V-INT (0)

No edges were filtered by V-INT in this run.

---

## 10. Pooled Unmatched Candidates for Adjudication (14)

| Ticker | Edge ID | `edge_type` | Target (`target_kind`) | Direction | Importance | V-INT | Quote |
|---|---|---|---|---|---|---|---|
| `NKE` | `edge_d3ccd3a1052a` | `customer` | Unnamed Customer (`unnamed_customer`) | `target_depends_on_company` | `high` | `confirmed` | "During fiscal 2026, NIKE's three largest customers outside of the United States accounted for approximately 16% of to..." |
| `NKE` | `edge_db8132253be5` | `supplier` | Air Manufacturing Innovation (`company`) | `depends_on_target` | `critical` | `confirmed` | "During fiscal 2026, Air Manufacturing Innovation, a wholly-owned subsidiary, with facilities near Beaverton, Oregon, ..." |
| `NKE` | `edge_55810b619d12` | `supplier` | Sojitz Corporation of America (`company`) | `depends_on_target` | `critical` | `confirmed` | "Since 1972, Sojitz Corporation of America ("Sojitz America"), a large Japanese trading company and the sole owner of ..." |
| `F` | `edge_83e00ad1aec8` | `supplier` | Takata (`company`) | `depends_on_target` | `medium` | `confirmed` | "For example, NHTSA and the automotive industry are currently engaged in a study of the safety of approximately 56 mil..." |
| `F` | `edge_cf85a07ce5ef` | `supplier` | ARC Automotive (`company`) | `depends_on_target` | `medium` | `confirmed` | "In addition, NHTSA is considering action related to 52 million vehicles containing inflators from ARC Automotive and ..." |
| `F` | `edge_a7c38c5f5085` | `supplier` | Delphi Automotive (`company`) | `depends_on_target` | `medium` | `confirmed` | "In addition, NHTSA is considering action related to 52 million vehicles containing inflators from ARC Automotive and ..." |
| `GM` | `edge_d3d268649da2` | `jv_partner` | SAIC General Motors Sales Co., Ltd. (`company`) | `depends_on_target` | `medium` | `confirmed` | "Includes sales by the Automotive China Joint Ventures (Automotive China JVs): SAIC General Motors Sales Co., Ltd. (SG..." |
| `GM` | `edge_85f1bd72c86f` | `jv_partner` | SAIC GM Wuling Automobile Co., Ltd. (`company`) | `depends_on_target` | `medium` | `confirmed` | "Includes sales by the Automotive China Joint Ventures (Automotive China JVs): SAIC General Motors Sales Co., Ltd. (SG..." |
| `BA` | `edge_8058aeca27ad` | `customer` | United States Department of War (`company`) | `target_depends_on_company` | `medium` | `confirmed` | "We derive a substantial portion of our revenue from the U.S. government, primarily from defense related programs with..." |
| `BA` | `edge_dea2976ebbd3` | `customer` | NASA (`company`) | `target_depends_on_company` | `medium` | `confirmed` | "We derive a substantial portion of our revenue from the U.S. government, primarily from defense related programs with..." |
| `SWKS` | `edge_bc723b6898e2` | `customer` | Unnamed Customer (`unnamed_customer`) | `target_depends_on_company` | `medium` | `confirmed` | "In each of fiscal 2025, fiscal 2024, and fiscal 2023, one customer accounted for greater than ten percent of our net ..." |
| `DE` | `edge_e60d52406d66` | `customer` | The Home Depot (`company`) | `target_depends_on_company` | `medium` | `confirmed` | "although the segment also builds turf products for sale by mass retailers, including The Home Depot and Lowe's." |
| `DE` | `edge_a31a7be471da` | `customer` | Lowe's (`company`) | `target_depends_on_company` | `medium` | `confirmed` | "although the segment also builds turf products for sale by mass retailers, including The Home Depot and Lowe's." |
| `DE` | `edge_448da3c0e5ef` | `key_input` | rare earth minerals (`material`) | `depends_on_target` | `high` | `confirmed` | "certain of our products, including motors, batteries, and other components, rely on rare earth minerals for their man..." |
