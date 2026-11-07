# R4: Sources for company dependencies (2026-11-07)

Research input for PLAN-v2: what real documents can ground supplier, customer, input and facility edges.

## Key finding: annual reports name suppliers less than you would expect
- **Apple's** latest 10-K (filed 2026-11-03) names **no** supplier: no TSMC, no Foxconn. It lists only the countries where its partners operate (China mainland, India, Japan, South Korea, Taiwan, Vietnam).
- **Microsoft** names none either.
- **Semiconductor companies do name suppliers.** Nvidia's 10-K Item 1 names TSMC and Samsung as foundries, and Hon Hai, Wistron and Fabrinet as contract manufacturers. It says: "We purchase memory from SK Hynix Inc., Micron Technology, Inc., and Samsung."
- **ASML's** 20-F names Carl Zeiss SMT as its *sole* optics supplier.
- **Reverse links are therefore essential.** EDGAR full-text search (`efts.sec.gov/LATEST/search-index?q="…"&forms=10-K`) finds who names a company. TSMC's legal name appears in 18 recent 10-Ks, including Nvidia, AMD, Broadcom, KLA and NXP.
- **Major customers are always anonymous** ("one direct customer 22% of revenue"), so they become `unnamed_customer` nodes with a percentage.
- **Facility sections vary widely.** TSMC's 20-F Item 4 is excellent: a fab table with sites in Arizona, Kumamoto (JASM, with Sony) and Dresden (ESMC, with Bosch, Infineon and NXP). Apple's Item 2 just says "Cupertino".

## Finding and reading the filings (confirmed live)
- **Ticker to CIK:** `https://www.sec.gov/files/company_tickers.json` covers 10,409 tickers, including the TSM and ASML ADRs. Samsung and SK Hynix are absent.
- **Latest filing:** from `https://data.sec.gov/submissions/CIK##########.json`, take the first 10-K/20-F in `filings.recent` and its `accessionNumber` and `primaryDocument`. The document is at `Archives/edgar/data/{cik}/{acc-no-dashes}/{primaryDocument}`, and the filing's file list is at `.../index.json`.
- **Sizes (text, approx tokens):**

  | Filing | Approx tokens |
  |---|---|
  | Apple 10-K | 59K (Items 1 + 1A + 2 ≈ 27K) |
  | Nvidia 10-K | 86K |
  | Microsoft 10-K | 84K |
  | TSMC 20-F | 145K |
  | ASML 20-F | 353K |

  Chunk around 20K tokens at paragraph boundaries.
- **Section headings are only moderately reliable:**
  - Every Item appears in the table of contents and again in the body, so take the last match.
  - Microsoft repeats running headers, and tag-splitting breaks words ("PR OPERTIES").
  - TSMC uses a thin space (U+2009) inside "ITEM 4.".
  - PDF-derived text has hyphenation artefacts.

  So quote checks must run on **normalised** text (Unicode NFKC, collapsed whitespace, unified quotes and dashes).
- **Where 20-F content lives:** risk factors are in Item 3.D and the business in Item 4. Subsidiaries are in Exhibit 21 (10-K) or Exhibit 8.1 (20-F); find the file by name in the filing folder.
- **Fair access:** SEC allows at most 10 requests per second with a User-Agent that includes contact details. Filings are immutable, so cache them by accession number forever.

## Other sources
| Source | Useful for | Notes |
|---|---|---|
| GLEIF (`api.gleif.org/api/v1`, CC0, no key) | Legal and transliterated names, LEI, ownership parents | ISIN lookup works for US/ADR codes only (not KR/TW local). No supplier links. |
| Wikidata SPARQL (CC0) | Cross-check only (P176 manufacturer on products) | Historical and unsourced, so never use it as evidence. |
| OpenCorporates, Open Supply Hub | — | Key or paid; skip. |
| Samsung / SK Hynix English reports (PDF) | Named customers and suppliers (unconfirmed) | Optional. If used, verify the same way. Otherwise say "no primary disclosure". |

## Recommended pipeline (input to G-DOC and G-AI)
1. **Map holdings to filings:** ticker or company_key CIK → latest 10-K/20-F.
2. **Fetch:**
   - 10-K: Items 1, 1A and 2, plus note paragraphs matching "10% or more|concentration", plus Exhibit 21.
   - 20-F: Items 3.D, 4 and 5, plus Exhibit 8.
3. **Canonical text:** strip the iXBRL header and tags, normalise, and hash it. Quote verification runs against exactly this text.
4. **Chunk** at about 20K tokens with about 1K overlap. Items 1 and 2 always go whole; optionally pre-filter 1A by keywords (supplier, foundry, sole, single source, customer, % of revenue, fab, located in).
5. **Extract** flat edges: `subject, predicate, object_name_as_written, object_kind, qualifier, evidence_quote (≤300 chars), section`.
   - Predicates: `supplier_of, customer_of, contract_manufacturer, foundry, facility_in, key_input, jv_partner` plus a `sole_source` flag.
   - `object_kind`: `company | country | region | material | component | facility | unnamed_customer`.
6. **Verify** in Python. Keep an edge only if its normalised quote is a substring of the normalised text **and** the counterparty name appears in the quote.
7. **Resolve names deterministically.** Build an alias table from the SEC title, GLEIF names, the portfolio's company names, `aliases.json` and a short manual list (e.g. Hon Hai = Foxconn). An exact match counts as resolved. A fuzzy match is flagged "needs review" and never merged automatically. The LLM never decides the final match.
8. **Reverse links:** EDGAR full-text search for each top company's name, and the hit documents go through steps 3–7.
9. **Companies without SEC filings** (Samsung, SK Hynix): show them only through other filers' edges, labelled "no primary disclosure fetched".
