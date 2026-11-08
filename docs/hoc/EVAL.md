# House of Cards v3 — Unseen-Data Dependency Extraction Evaluation (`E-RUN`)

## 1. Run Metadata & Methodology

| Parameter | Value |
|---|---|
| **Evaluation Mode** | `replay` |
| **Git Commit** | `ee1c795` |
| **Extractor Prompt Version** | `hoc-v2-extract-1` |
| **V-INT Judge Prompt Version** | `hoc-v3-judge-1` |
| **Held-Out Companies Evaluated** | `10` |
| **Gold Relationships Total** | `222` (`115` core + `107` extended; `212` initial blind, `10` pooled) |
| **Core Gold by Source** | `a`: 26, `b`: 8, `both`: 81 |
| **Gold Hard Negatives** | `79` |
| **Bootstrap Confidence Intervals** | 95% percentile CI across companies (`B = 2000`, seed `20261108`) |

### Matching & Scoring Rules (`docs/hoc/PLAN-v3.md` §1 & `docs/hoc/eval/ADJUDICATION.md`)
- **Target Resolution**: A predicted `VerifiedEdge` matches a gold relationship on the same company when `hoc.filings.names.name_key(target)` matches `target_name` or any entry in `aliases[]`, when both resolve to the same ISO-2 country via `hoc.graph.metrics.canonical_country_info` (or explicit `gold.country`) for facility/country targets, or when both describe the same `unnamed_customer` revenue-share disclosure.
- **Compatible Edge Types**: Exact match on all 7 `EdgeType` values, any type listed in `edge_type_alternatives[]`, plus compatible equivalence groups `supplier` ↔ `key_input` (and sole-source supplier) and `foundry` ↔ `contract_manufacturer`.
- **Core vs. Extended Tiers**: Core relationships (`tier = "core"`) count toward recall (a missing core relationship is a false negative). Extended relationships (`tier = "extended"`) are optional list/distribution items: a prediction matching an extended item counts as a true positive for precision, while an unextracted extended item is not a false negative.
- **Hard Negatives & Pooling**: A prediction matching a hard negative is always a false positive. In the first live run, 14 unmatched non-negative predictions were exported for blind adjudication by the lead (`docs/hoc/eval/ADJUDICATION.md`): **10 were accepted** with `"source": "pooled"` and `"tier": "extended"` (adding precision credit while keeping the `115` core recall denominator strictly blind), and **4 were rejected** (remaining false positives). Of the `222` gold relationships in this run, `212` came from initial blind annotation and `10` came from pooling.

---

## 2. Headline Metrics (After V-INT, with 95% Bootstrap CIs)

| Metric | Score & 95% CI (Count) |
|---|---|
| **Micro Precision — Blind (Initial Blind Gold Only)** | 88.4% [83.2%, 92.5%] (114/129) |
| **Micro Precision — Pooled (After Blind Pooling Review)** | 96.1% [89.6%, 100.0%] (124/129) |
| **Micro Recall on Core (`tier = 'core'`, Blind Denominator)** | 57.4% [35.3%, 76.0%] (66/115) |
| **Micro F1 — Blind** | 69.6% [51.9%, 82.7%] |
| **Micro F1 — Pooled** | 71.9% [53.3%, 85.1%] |
| **Macro Precision — Blind / Pooled** | 89.3% [82.6%, 95.1%] / 95.5% [88.8%, 100.0%] |
| **Macro Recall on Core (After V-INT)** | 60.9% [42.6%, 76.1%] |
| **Macro F1 — Blind / Pooled** | 68.2% [51.1%, 82.1%] / 70.0% [53.4%, 84.1%] |
| **Direction Accuracy** (`depends_on_target` vs. `target_depends_on_company`) | 100.0% [100.0%, 100.0%] (124/124) |
| **Hard-Negative False-Positive Rate (After V-INT)** | 1.3% [0.0%, 3.9%] (1/79) |
| **Facility-Country Accuracy** (ISO-2 country resolution) | 100.0% [100.0%, 100.0%] (39/39) |
| **Importance-Tier Agreement (Quadratic Weighted Cohen's $\kappa$)** | 0.475 [0.382, 0.631] (54/79) |
| **Importance-Tier Agreement (Linear Weighted Cohen's $\kappa$)** | 0.466 [0.299, 0.637] (54/79) |
| **Importance-Tier Exact Agreement** | 68.3% [50.0%, 84.0%] (54/79) |

### 2.1 Key Findings & Error Analysis
1. **V-INT on the held-out set vs. live portfolio run**: V-INT filtered `0` edges on the 10 held-out companies (`129 → 129`), so it had no measurable precision/recall delta on this corpus — the extractor prompt (`hoc-v2-extract-1`) and deterministic quote/generic-noun verifier already avoided all `27` competitor, `11` negated, `9` hypothetical, and `7` unrelated hard negatives, and the `hoc-v3-judge-1` Flash judge cleared 2 false-alarm `competitor_mention` rule flags on Skyworks' `Samsung` and `Tesla` customer edges. V-INT's practical value shows up on the live `us-core-tilt` portfolio run: with the tightened rules (PR #130), it correctly **rejects 1 edge** (`AMD` → `Sanmina` `contract_manufacturer` from *"we sold the ZT Manufacturing Business to Sanmina"*, a divestiture rather than supply) and **flags 1 tentative overclaim** (`Nvidia` → `OpenAI`).
2. **Recall misses are concentrated in facility countries (`23/49`) and Pfizer alliances**: Of the `49` missed core relationships, `23` (`23/49`) are facility countries where a 10-K lists multiple countries in a single prose sentence (e.g., Boeing's 8 international locations in Item 2, GM's 4 non-US assembly countries, Pfizer's 8-country plant summary), and `18/49` come from Pfizer (`PFE`), whose three wholesaler customers (`McKesson`, `Cencora`, `Cardinal Health`) sit in a Note 17B table and whose drug co-development/commercialization alliances (`Astellas`, `BMS`, `Genmab`, `SMPS`, `Takeda`) are spread across product paragraphs in Item 1 (`1/19` core recall on `PFE`, vs. `65/96` = `67.7%` across the other 9 filers).
3. **`supplier` precision is the weak edge type**: On `supplier` predictions (`n = 6`), blind precision is `16.7%` (`1/6`, where `Ford Otosan` matched a core `jv_partner`/`supplier` relationship) and pooled precision is `50.0%` (`3/6`, after `ARC Automotive` and `Delphi Automotive` were accepted in pooling). The 3 remaining `supplier` false positives are a wholly-owned subsidiary (`NKE` `Air Manufacturing Innovation`), a trade-finance/preferred-stock holder (`NKE` `Sojitz Corporation of America`), and an industry-wide NHTSA recall mention (`F` `Takata`). By contrast, `facility` (`68/68`), `key_input` (`18/18`), `jv_partner` (`14/14`), and `contract_manufacturer` (`5/5`) achieve `100.0%` pooled precision, and `customer` reaches `88.9%` (`16/18`).

---

## 3. Before vs. After V-INT (Quote Verification Only vs. Quote + Semantic Interpretation Verification)

| Metric | Before V-INT (Quote Check Only) | After V-INT (Quote + V-INT) | Delta (After − Before) |
|---|---|---|---|
| **Micro Precision** | 96.1% [89.5%, 100.0%] (124/129) | 96.1% [89.6%, 100.0%] (124/129) | `+0.0 pp` |
| **Micro Recall (Core)** | 57.4% [36.2%, 75.9%] (66/115) | 57.4% [35.3%, 76.0%] (66/115) | `+0.0 pp` |
| **Micro F1** | 71.9% [53.2%, 85.1%] | 71.9% [53.3%, 85.1%] | `+0.0 pp` |
| **Macro Precision** | 95.5% [88.8%, 100.0%] | 95.5% [88.8%, 100.0%] | `+0.0 pp` |
| **Macro Recall (Core)** | 60.9% [44.1%, 76.8%] | 60.9% [42.6%, 76.1%] | `+0.0 pp` |
| **Macro F1** | 70.0% [53.0%, 84.1%] | 70.0% [53.4%, 84.1%] | `+0.0 pp` |
| **Hard-Negative FP Rate** | 1.3% [0.0%, 3.8%] (1/79) | 1.3% [0.0%, 3.9%] (1/79) | `+0.0 pp` |
| **Predicted Edges (TP [Core+Ext] / FP / Core FN)** | `129` (`124` [`66`+`23`] / `5` / `49`) | `129` (`124` [`66`+`23`] / `5` / `49`) | `+0` edges |

---

## 4. Per-`edge_type` Breakdown (After V-INT)

| `edge_type` | Gold (Core+Ext) | Predicted | TP (Core+Ext) | FP | Core FN | Precision (95% CI) | Core Recall (95% CI) | F1 (95% CI) |
|---|---:|---:|---:|---:|---:|---|---|---|
| `supplier` | 6 (3+3) | 6 | 3 (0+2) | 3 | 3 | 50.0% [0.0%, 75.0%] (3/6) | 0.0% [0.0%, 0.0%] (0/3) | 0.0% [0.0%, 0.0%] |
| `customer` | 48 (8+40) | 18 | 16 (5+11) | 2 | 3 | 88.9% [57.1%, 100.0%] (16/18) | 62.5% [18.2%, 100.0%] (5/8) | 73.4% [30.3%, 98.6%] |
| `contract_manufacturer` | 9 (8+1) | 5 | 5 (6+0) | 0 | 2 | 100.0% [0.0%, 100.0%] (5/5) | 75.0% [33.3%, 100.0%] (6/8) | 85.7% [0.0%, 100.0%] |
| `foundry` | 1 (0+1) | 0 | 0 (0+0) | 0 | 0 | 100.0% [100.0%, 100.0%] (0/0) | 100.0% [100.0%, 100.0%] (0/0) | 100.0% [100.0%, 100.0%] |
| `key_input` | 77 (20+57) | 18 | 18 (9+8) | 0 | 11 | 100.0% [100.0%, 100.0%] (18/18) | 45.0% [15.4%, 80.0%] (9/20) | 62.1% [27.6%, 89.5%] |
| `facility` | 61 (58+3) | 68 | 68 (35+0) | 0 | 23 | 100.0% [100.0%, 100.0%] (68/68) | 60.3% [29.8%, 89.1%] (35/58) | 75.3% [46.0%, 94.2%] |
| `jv_partner` | 20 (18+2) | 14 | 14 (11+2) | 0 | 7 | 100.0% [100.0%, 100.0%] (14/14) | 61.1% [23.1%, 96.2%] (11/18) | 75.9% [40.0%, 100.0%] |

---

## 5. Per-Company Breakdown

| Ticker | Company | Accession | Gold (Core+Ext) | Negs | Pred (Pre→Post V-INT) | TP (Core+Ext) | FP | Core FN | P (Blind→Pooled) | Core R | F1 (Blind→Pooled) | Dir Acc | Hard-Neg FP | Fac Country |
|---|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---|---|---|
| `NKE` | NIKE, Inc. | `0000320187-26-000088` | 25 (9+16) | 10 | 9→9 | 6 (5+0) | 3 | 4 | 66.7%→66.7% | 55.6% | 60.6%→60.6% | 6/6 | 0→0/10 | 5/5 |
| `F` | Ford Motor Company | `0000037996-26-000015` | 30 (17+13) | 9 | 18→18 | 17 (14+2) | 1 | 3 | 83.3%→94.4% | 82.3% | 82.8%→88.0% | 17/17 | 0→0/9 | 6/6 |
| `GM` | General Motors Company | `0001467858-26-000013` | 26 (9+17) | 8 | 14→14 | 14 (3+9) | 0 | 6 | 85.7%→100.0% | 33.3% | 48.0%→50.0% | 14/14 | 0→0/8 | 2/2 |
| `BA` | The Boeing Company | `0001628280-26-004357` | 16 (12+4) | 7 | 10→10 | 10 (5+2) | 0 | 7 | 80.0%→100.0% | 41.7% | 54.8%→58.8% | 10/10 | 0→0/7 | 1/1 |
| `SWKS` | Skyworks Solutions, Inc. | `0000004127-25-000085` | 44 (7+37) | 7 | 15→15 | 15 (7+7) | 0 | 0 | 93.3%→100.0% | 100.0% | 96.5%→100.0% | 15/15 | 0→0/7 | 4/4 |
| `QRVO` | Qorvo, Inc. | `0001628280-26-032873` | 11 (10+1) | 7 | 8→8 | 8 (6+0) | 0 | 4 | 100.0%→100.0% | 60.0% | 75.0%→75.0% | 8/8 | 0→0/7 | 2/2 |
| `GLW` | Corning Incorporated | `0000024741-26-000124` | 19 (13+6) | 9 | 16→16 | 15 (11+0) | 1 | 2 | 93.8%→93.8% | 84.6% | 88.9%→88.9% | 15/15 | 1→1/9 | 10/10 |
| `PFE` | Pfizer Inc. | `0000078003-26-000026` | 19 (19+0) | 8 | 1→1 | 1 (1+0) | 0 | 18 | 100.0%→100.0% | 5.3% | 10.0%→10.0% | 1/1 | 0→0/8 | — |
| `DE` | Deere & Company | `0001104659-25-122321` | 20 (12+8) | 6 | 32→32 | 32 (9+3) | 0 | 3 | 90.6%→100.0% | 75.0% | 82.1%→85.7% | 32/32 | 0→0/6 | 8/8 |
| `SBUX` | Starbucks Corporation | `0000829224-25-000114` | 12 (7+5) | 8 | 6→6 | 6 (5+0) | 0 | 2 | 100.0%→100.0% | 71.4% | 83.3%→83.3% | 6/6 | 0→0/8 | 1/1 |

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

## 7. All False Positives After V-INT (5)

| Ticker | Edge ID | `edge_type` | Target (`target_kind`) | Reason | Verbatim Quote |
|---|---|---|---|---|---|
| `NKE` | `edge_d3ccd3a1052a` | `customer` | Unnamed Customer (`unnamed_customer`) | Pooled review: reject — customer group ('three largest cu... | "During fiscal 2026, NIKE's three largest customers outside of the United States accounted for approximately 16% of total non-U.S. sales." |
| `NKE` | `edge_db8132253be5` | `supplier` | Air Manufacturing Innovation (`company`) | Pooled review: reject — Air Manufacturing Innovation is a... | "During fiscal 2026, Air Manufacturing Innovation, a wholly-owned subsidiary, with facilities near Beaverton, Oregon, in Dong Nai City, Vi..." |
| `NKE` | `edge_55810b619d12` | `supplier` | Sojitz Corporation of America (`company`) | Pooled review: reject — Sojitz America provides import-ex... | "Since 1972, Sojitz Corporation of America ("Sojitz America"), a large Japanese trading company and the sole owner of our redeemable prefe..." |
| `F` | `edge_83e00ad1aec8` | `supplier` | Takata (`company`) | Pooled review: reject — Takata appears only in an industr... | "For example, NHTSA and the automotive industry are currently engaged in a study of the safety of approximately 56 million Takata desiccat..." |
| `GLW` | `edge_4a8f0bde58a7` | `customer` | Unnamed Customer (`unnamed_customer`) | Hard negative leak (generic: GLW-NADJ1) | "The following table details the number of combined customers of our reportable segments that accounted for a large percentage of segment ..." |

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

## 10. Pooled Unmatched Candidates for Adjudication (0)

No unmatched pooled candidates awaiting review.
