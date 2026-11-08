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
