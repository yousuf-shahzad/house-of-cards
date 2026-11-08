# Answer-key adjudication (E-GOLD, v3)

Adjudicator: Gawyn's Claude (lead). The plan is in `docs/hoc/PLAN-v3.md` §1.

## Inputs

There are two independent, blind answer keys over the same 10 held-out 10-Ks. Both annotators used the same pinned accessions, posted on the board by Yousuf's Codex. Neither ran the app's extractor, saw any Gemini output, or saw the other's labels.

| Annotator | Files | Relationships | Hard negatives |
|---|---|---|---|
| A: Yousuf's Codex | `backend/tests/eval/gold/<TICKER>.a.json` | 204 | 39 |
| B: Bekarys's Claude | `backend/tests/eval/gold/<TICKER>.b.json` | 100 | 49 |

Every quote in both files appears verbatim in its pinned filing after `hoc.filings.text.normalise`. That is 243 quotes for A and 149 for B, and the adjudicator re-checked B independently.

## Inter-annotator agreement (before adjudication)

**Units.** Both answer keys are reduced to `(company, family, target)` units:
- **family:** supply (supplier, key_input, contract_manufacturer, foundry), customer, jv, or facility;
- **facility targets:** the ISO2 country;
- **other targets:** `hoc.filings.names.name_key`.

| Company | A units | B units | Both | Agreement F1 |
|---|---|---|---|---|
| BA | 15 | 11 | 9 | 0.69 |
| DE | 17 | 11 | 11 | 0.79 |
| F | 24 | 15 | 9 | 0.46 |
| GLW | 18 | 7 | 5 | 0.40 |
| GM | 23 | 9 | 8 | 0.50 |
| NKE | 21 | 11 | 4 | 0.25 |
| PFE | 19 | 13 | 13 | 0.81 |
| QRVO | 11 | 8 | 6 | 0.63 |
| SBUX | 11 | 7 | 3 | 0.33 |
| SWKS | 42 | 6 | 5 | 0.21 |
| **All** | **201** | **98** | **73** | **0.49** |

By family (A / B / both):
- facility: 61 / 55 / 49;
- jv: 16 / 12 / 8;
- customer: 42 / 10 / 7;
- supply: 82 / 21 / 9.

There were no conflicts: no unit was a relationship for one annotator and a negative for the other.

**Importance tier** on the 73 shared units: 36 exact matches (49%) and 65 within one tier (89%).

**Why agreement is low, and where.** The disagreement is about granularity, not substance:
- A labelled every item of generic lists, such as Ford's "wide variety of raw materials" (steel, aluminum, cobalt…), Nike's "principal materials" (yarns, threads, trims…) and Skyworks' 35-name "key customers include" list.
- B labelled only the named, significant relationships.
- Facilities, where the filing gives countries, agree at 89% of B's units.

## Adjudication rules

1. A unit labelled by **both** annotators is **core**.
2. A **single-annotator** unit is **core** when it is any of the following:
   - a named company, JV or alliance partner;
   - a named customer with stated significance;
   - a facility country stated as a production, assembly, R&D or HQ location;
   - an input the filing singles out (e.g. Skyworks' gallium and germanium, under export controls).
3. A single-annotator item that only appears inside a generic list, or a distribution-only site, is **extended**. That means it is optional: a prediction matching it is a true positive, but missing it is not a false negative.
4. **Merges.** Units that are the same relationship under different names or framings are merged, with `aliases` and `edge_type_alternatives`:
   - Ford Otosan / Ford Otomotiv Sanayi;
   - BlueOval SK / SK On / SK Battery America;
   - Nestlé (Global Coffee Alliance) as jv_partner or contract_manufacturer;
   - Pepsi-Cola / PepsiCo;
   - composites (carbon and boron);
   - lithium niobate and lithium tantalate;
   - dairy / fluid milk.
5. **Rejections, under the labelling policy posted on the board:**
   - customer groups become generic negatives: NKE "three largest United States customers" and GLW "three combined Display end customers";
   - NKE Sojitz America is dropped, because it holds preferred stock and is not a supplier;
   - BA Spirit AeroSystems moves to extended, because Boeing acquired it in December 2025.
6. **Importance.** When the annotators disagree, the gold tier is the lower of the two.
7. **Negatives** are the union of both annotators' negatives, deduplicated by target and kind.

## Result: `backend/tests/eval/gold/<TICKER>.json`

| Company | Core | Extended | Negatives |
|---|---|---|---|
| BA | 12 | 2 | 7 |
| DE | 12 | 5 | 6 |
| F | 17 | 11 | 9 |
| GLW | 13 | 6 | 9 |
| GM | 9 | 15 | 8 |
| NKE | 9 | 16 | 10 |
| PFE | 19 | 0 | 8 |
| QRVO | 10 | 1 | 7 |
| SBUX | 7 | 5 | 8 |
| SWKS | 7 | 36 | 7 |
| **All** | **115** | **97** | **79** |

Where the core items came from: 81 were labelled by both annotators, 26 by A only, and 8 by B only.

**Fields added for scoring:**
- `tier`: core or extended;
- `source`: both, a, b, adjudicated or pooled;
- `aliases`;
- `edge_type_alternatives`;
- `country`: ISO2, for facilities;
- `annotator_ids`: traceability to the raw files.

**Recall** counts core items only. **Precision** treats a prediction as correct when it matches a core or extended item. A prediction that matches nothing goes to the adjudicator for pooled review: approved ones are added with `source: "pooled"`, and the count is reported. A prediction that matches a negative is always a false positive.

**Known issue found while adjudicating.** `hoc.graph.metrics` does not recognise "Cambodia" as a country. This was reported to G-ORCH; the answer key maps it to KH explicitly.

## Pooled review (after the first live run, PR #131)

The 14 predictions that matched no gold item were reviewed by the adjudicator against the labelling policy.
Accepted ones were added as `source: "pooled"`, `tier: "extended"`. They therefore add precision credit but never enlarge recall's core denominator, so core recall stays measured against the two blind annotators only. Rejected ones remain false positives.

| Prediction | Company | Target | Decision | Reason |
|---|---|---|---|---|
| `edge_d3ccd3a1052a` | NKE | Unnamed Customer | reject | Customer group ('three largest customers outside the US'), not one counterparty (policy 3). |
| `edge_db8132253be5` | NKE | Air Manufacturing Innovation | reject | Air Manufacturing Innovation is a wholly-owned Nike subsidiary, not an external supplier. |
| `edge_55810b619d12` | NKE | Sojitz Corporation of America | reject | Sojitz America provides import-export financing and holds preferred stock; not a supply dependency (already rejected in adjudication). |
| `edge_83e00ad1aec8` | F | Takata | reject | Takata appears only in an industry-wide NHTSA study; the filing does not state Takata supplies Ford. |
| `edge_cf85a07ce5ef` | F | ARC Automotive | accept | Ford has 2.5 million vehicles with ARC inflators: a supplier relationship evidenced in the filing. |
| `edge_a7c38c5f5085` | F | Delphi Automotive | accept | Ford has 2.5 million vehicles with Delphi inflators: a supplier relationship evidenced in the filing. |
| `edge_d3d268649da2` | GM | SAIC General Motors Sales Co., Ltd. | accept | SGMS is one of GM's named Automotive China joint ventures. |
| `edge_85f1bd72c86f` | GM | SAIC GM Wuling Automobile Co., Ltd. | accept | SGMW is one of GM's named Automotive China joint ventures. |
| `edge_8058aeca27ad` | BA | United States Department of War | accept | A substantial portion of Boeing revenue comes from the US government, primarily the Department of War. |
| `edge_dea2976ebbd3` | BA | NASA | accept | NASA is named among Boeing's government customers. |
| `edge_bc723b6898e2` | SWKS | Unnamed Customer | accept | One unnamed customer above 10% of net revenue (policy 2). |
| `edge_e60d52406d66` | DE | The Home Depot | accept | The Home Depot is named as a mass-retail channel for Deere turf products. |
| `edge_a31a7be471da` | DE | Lowe's | accept | Lowe's is named as a mass-retail channel for Deere turf products. |
| `edge_448da3c0e5ef` | DE | rare earth minerals | accept | Rare earth minerals singled out as an input, a significant majority sourced from China. |

Result: 10 accepted, 4 rejected (Nike non-US customer group, Air Manufacturing Innovation, Sojitz America, Takata).
