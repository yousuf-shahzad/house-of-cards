"""Pydantic schemas and held-out company manifest for the v3 evaluation harness (package E-RUN).

Owner: Bekarys's Gemini (E-RUN).
Rules (docs/hoc/PLAN-v3.md §1 & docs/hoc/eval/ADJUDICATION.md):
- Held-out set of 10 diverse S&P 500 10-K filers outside the development top-15.
- Adjudicated gold answer keys live in `backend/tests/eval/gold/<TICKER>.json` with:
  - `tier`: `'core'` (counts for recall; missing = FN) or `'extended'` (optional; matching = TP, missing != FN).
  - `aliases`: alternative target names matched via `hoc.filings.names.name_key`.
  - `edge_type_alternatives`: additional accepted `EdgeType` values beyond plan compatibility groups.
  - `country`: explicit ISO-2 country code for facility/country relationships.
  - `source` & `annotator_ids`: provenance (`'both'`, `'a'`, `'b'`, `'adjudicated'`, `'pooled'`).
- Quote verification checks every gold quote against `hoc.filings.text.normalise(filing.text)`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from hoc.contract.dependencies import EdgeType, ImportanceTier, TargetKind
from hoc.filings.text import normalise

GoldDirection = Literal["depends_on_target", "target_depends_on_company"]
GoldTier = Literal["core", "extended"]

IMPORTANCE_TIERS_ORDERED: tuple[ImportanceTier, ...] = ("low", "medium", "high", "critical")
IMPORTANCE_TO_SCORE: dict[str, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


@dataclass(frozen=True)
class HeldOutCompany:
    """One of the 10 held-out 10-K evaluation companies from PLAN-v3.md §1."""

    ticker: str
    name: str
    cik: str
    sector_focus: str
    pinned_accession: str

    @property
    def company_key(self) -> str:
        return f"CIK:{self.cik.zfill(10)}"


HELD_OUT_COMPANIES: tuple[HeldOutCompany, ...] = (
    HeldOutCompany(
        ticker="NKE",
        name="NIKE, Inc.",
        cik="0000320187",
        sector_focus="Apparel / contract manufacturing & country concentration (Vietnam, Indonesia, China)",
        pinned_accession="0000320187-26-000088",
    ),
    HeldOutCompany(
        ticker="F",
        name="Ford Motor Company",
        cik="0000037996",
        sector_focus="Automotive / battery JVs, raw materials, semiconductor suppliers, plants",
        pinned_accession="0000037996-26-000015",
    ),
    HeldOutCompany(
        ticker="GM",
        name="General Motors Company",
        cik="0001467858",
        sector_focus="Automotive / Ultium cells JV, LG Energy Solution, North American facilities",
        pinned_accession="0001467858-26-000013",
    ),
    HeldOutCompany(
        ticker="BA",
        name="The Boeing Company",
        cik="0000012927",
        sector_focus="Aerospace / Spirit AeroSystems, CFM/GE engines, titanium & composite inputs",
        pinned_accession="0001628280-26-004357",
    ),
    HeldOutCompany(
        ticker="SWKS",
        name="Skyworks Solutions, Inc.",
        cik="0000004127",
        sector_focus="RF semiconductors / Apple (>60% customer concentration), Mexicali/Osaka/Woburn fabs",
        pinned_accession="0000004127-25-000085",
    ),
    HeldOutCompany(
        ticker="QRVO",
        name="Qorvo, Inc.",
        cik="0001604778",
        sector_focus="RF semiconductors / Apple & Samsung customer concentration, Richardson/Hillsboro/Costa Rica",
        pinned_accession="0001628280-26-032873",
    ),
    HeldOutCompany(
        ticker="GLW",
        name="Corning Incorporated",
        cik="0000024741",
        sector_focus="Specialty glass & optical fiber / Display & Optical customers, noble-metal inputs, Asian plants",
        pinned_accession="0000024741-26-000124",
    ),
    HeldOutCompany(
        ticker="PFE",
        name="Pfizer Inc.",
        cik="0000078003",
        sector_focus="Biopharma / BioNTech collaboration, McKesson/Cencora/Cardinal wholesaler concentration",
        pinned_accession="0000078003-26-000026",
    ),
    HeldOutCompany(
        ticker="DE",
        name="Deere & Company",
        cik="0000315189",
        sector_focus="Agricultural & construction equipment / steel & engine components, US/Germany/Brazil plants",
        pinned_accession="0001104659-25-122321",
    ),
    HeldOutCompany(
        ticker="SBUX",
        name="Starbucks Corporation",
        cik="0000829224",
        sector_focus="Consumer / arabica coffee, dairy, roasting plants, international licensees/JVs",
        pinned_accession="0000829224-25-000114",
    ),
)

HELD_OUT_BY_TICKER: dict[str, HeldOutCompany] = {c.ticker: c for c in HELD_OUT_COMPANIES}
HELD_OUT_BY_CIK: dict[str, HeldOutCompany] = {c.cik.zfill(10): c for c in HELD_OUT_COMPANIES}


class _EvalModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class GoldCompany(_EvalModel):
    name: str
    cik: str
    ticker: str

    @property
    def normalised_cik(self) -> str:
        digits = "".join(ch for ch in self.cik if ch.isdigit())
        return digits.zfill(10) if digits else self.cik.strip()

    @property
    def company_key(self) -> str:
        digits = "".join(ch for ch in self.cik if ch.isdigit())
        return f"CIK:{digits.zfill(10)}" if digits else self.cik.strip()


class GoldFiling(_EvalModel):
    form: str = "10-K"
    accession: str
    url: str = ""
    filed: str | None = None
    sha256: str | None = None


class GoldRelationship(_EvalModel):
    id: str
    edge_type: EdgeType
    target_name: str
    target_kind: TargetKind
    direction: GoldDirection
    quote: str
    importance: ImportanceTier
    tier: GoldTier = "core"
    """'core' counts for recall (missing = FN); 'extended' is optional (matching = TP, missing != FN)."""
    source: str = "gold"
    """Provenance: 'both', 'a', 'b', 'adjudicated', 'pooled', or 'gold'."""
    aliases: list[str] = Field(default_factory=list)
    """Alternative target names also matched via `hoc.filings.names.name_key`."""
    edge_type_alternatives: list[EdgeType] = Field(default_factory=list)
    """Additional accepted `EdgeType` values on top of compatibility groups."""
    country: str | None = None
    """ISO-2 country code for facility/country items (e.g., 'US', 'VN', 'KH')."""
    annotator_ids: list[str] = Field(default_factory=list)
    """Traceability IDs from raw annotator A and B files."""
    sole_source: bool | None = None
    qualifier: str | None = None
    section: str | None = None
    notes: str = ""


class GoldNegative(_EvalModel):
    id: str
    target_name: str
    kind: str
    """Negative category: 'competitor', 'negated', 'hypothetical', 'generic', 'unrelated',
    'direction_mismatch', or 'subject_mismatch'."""
    quote: str
    source: str = ""
    notes: str = ""


class GoldDocument(_EvalModel):
    company: GoldCompany
    filing: GoldFiling
    annotator: str = ""
    annotators: list[str] = Field(default_factory=list)
    adjudicator: str = ""
    relationships: list[GoldRelationship] = Field(default_factory=list)
    negatives: list[GoldNegative] = Field(default_factory=list)


class RecordedCompanyPrediction(_EvalModel):
    """Recorded extractor + V-INT + agentic research output for one held-out company so `--replay` needs no network or keys."""

    ticker: str
    company_key: str
    company_name: str
    filing_accession: str
    filing_form: str = "10-K"
    filing_filed: str = "2026-01-01"
    filing_url: str = ""
    prompt_version: str = ""
    judge_prompt_version: str = ""
    model: str | None = None
    edges: list[dict[str, Any]] = Field(default_factory=list)
    """Verified edges surviving V-INT before the agentic research pass (single-pass baseline)."""
    vint_rejected_edges: list[dict[str, Any]] = Field(default_factory=list)
    """Edges that passed quote verification BEFORE V-INT, but were rejected by V-INT."""
    quote_rejected_count: int = 0
    research_depth: str = "none"
    """v3.1 A3: depth of the per-company agentic research pass ('none', 'light', 'thorough')."""
    agentic_edges: list[dict[str, Any]] | None = None
    """v3.1 A3: final verified edges after the per-company agentic research pass (None = same as `edges`)."""
    agentic_findings: list[dict[str, Any]] = Field(default_factory=list)
    """v3.1 A3: recorded `ResearchFinding` items from the per-company agentic loop."""
    agentic_rejected_edge_ids: list[str] = Field(default_factory=list)
    """v3.1 A3: edge IDs dropped by the per-company agentic loop."""
    agentic_steps_done: int = 0
    agentic_steps_total: int = 0
    agentic_interpretation_rejected: int = 0


class MetricWithCI(_EvalModel):
    value: float
    ci_low: float
    ci_high: float
    numerator: int | None = None
    denominator: int | None = None


class PRFMetrics(_EvalModel):
    precision: MetricWithCI
    recall: MetricWithCI
    f1: MetricWithCI
    tp: int
    tp_core: int = 0
    tp_extended: int = 0
    fp: int
    fn: int
    gold_core_count: int = 0
    gold_extended_count: int = 0
    gold_count: int
    predicted_count: int


class EdgeMatchDetail(_EvalModel):
    gold_id: str
    edge_id: str
    ticker: str
    gold_tier: GoldTier = "core"
    gold_edge_type: EdgeType
    pred_edge_type: EdgeType
    exact_type_match: bool
    gold_target_name: str
    pred_target_name: str
    gold_direction: GoldDirection
    pred_direction: GoldDirection
    direction_correct: bool
    gold_importance: ImportanceTier
    pred_importance: ImportanceTier
    gold_country: str | None = None
    pred_country: str | None = None
    country_correct: bool | None = None
    gold_source: str = "gold"
    annotator_ids: list[str] = Field(default_factory=list)
    is_primary_gold_match: bool = True


class EvalErrorDetail(_EvalModel):
    kind: Literal[
        "false_positive",
        "false_negative",
        "hard_negative_leak",
        "vint_rejected_fp",
        "vint_rejected_tp",
    ]
    ticker: str
    item_id: str
    edge_type: str
    target_name: str
    target_kind: str
    quote: str
    reason: str = ""


class PooledCandidate(_EvalModel):
    ticker: str
    edge_id: str
    edge_type: EdgeType
    target_name: str
    target_kind: TargetKind
    direction: GoldDirection
    quote: str
    section: str = ""
    importance: ImportanceTier = "medium"
    vint_status: str = "confirmed"


class CompanyEvalSummary(_EvalModel):
    ticker: str
    company_name: str
    cik: str
    accession: str
    annotator: str = ""
    gold_total: int
    gold_core_total: int = 0
    gold_extended_total: int = 0
    gold_core_by_source: dict[str, int] = Field(default_factory=dict)
    gold_blind_count: int
    gold_pooled_count: int
    negatives_total: int
    predicted_before_vint: int
    predicted_after_vint: int
    vint_rejected_count: int
    tp_before_vint: int
    tp_core_before_vint: int = 0
    tp_extended_before_vint: int = 0
    fp_before_vint: int
    fn_before_vint: int
    tp_after_vint: int
    tp_core_after_vint: int = 0
    tp_extended_after_vint: int = 0
    fp_after_vint: int
    fn_after_vint: int
    precision_before_vint: float
    recall_before_vint: float
    f1_before_vint: float
    precision_after_vint: float
    recall_after_vint: float
    f1_after_vint: float
    tp_blind_after_vint: int = 0
    fp_blind_after_vint: int = 0
    precision_blind_after_vint: float = 0.0
    f1_blind_after_vint: float = 0.0
    predicted_before_agentic: int = 0
    predicted_after_agentic: int = 0
    tp_before_agentic: int = 0
    tp_core_before_agentic: int = 0
    tp_extended_before_agentic: int = 0
    fp_before_agentic: int = 0
    fn_before_agentic: int = 0
    tp_blind_before_agentic: int = 0
    fp_blind_before_agentic: int = 0
    precision_before_agentic: float = 0.0
    precision_blind_before_agentic: float = 0.0
    recall_before_agentic: float = 0.0
    f1_before_agentic: float = 0.0
    f1_blind_before_agentic: float = 0.0
    tp_after_agentic: int = 0
    tp_core_after_agentic: int = 0
    tp_extended_after_agentic: int = 0
    fp_after_agentic: int = 0
    fn_after_agentic: int = 0
    tp_blind_after_agentic: int = 0
    fp_blind_after_agentic: int = 0
    precision_after_agentic: float = 0.0
    precision_blind_after_agentic: float = 0.0
    recall_after_agentic: float = 0.0
    f1_after_agentic: float = 0.0
    f1_blind_after_agentic: float = 0.0
    agentic_findings_count: int = 0
    agentic_steps_done: int = 0
    agentic_steps_total: int = 0
    agentic_new_edges_count: int = 0
    agentic_rejected_edges_count: int = 0
    direction_correct: int
    direction_total: int
    hard_neg_fp_before_vint: int
    hard_neg_fp_after_vint: int
    facility_country_correct: int
    facility_country_total: int
    matches: list[EdgeMatchDetail] = Field(default_factory=list)
    false_positives: list[EvalErrorDetail] = Field(default_factory=list)
    false_negatives: list[EvalErrorDetail] = Field(default_factory=list)
    hard_negative_leaks: list[EvalErrorDetail] = Field(default_factory=list)
    vint_filtered: list[EvalErrorDetail] = Field(default_factory=list)
    pooled_candidates: list[PooledCandidate] = Field(default_factory=list)


class AgenticAcceptanceReport(_EvalModel):
    """Numeric acceptance check for agentic research sub-agents (FIX-1, FIX-2, FIX-14)."""

    depth: str = "light"
    findings_total: int = 0
    tool_calls_total: int = 0
    avg_tool_calls_per_finding: float = 0.0
    min_tool_calls_per_finding: int = 0
    max_tool_calls_per_finding: int = 0
    single_lookup_findings_count: int = 0
    findings_meeting_min_tool_calls: int = 0
    search_filings_calls_total: int = 0
    findings_with_search_filings: int = 0
    read_section_calls_total: int = 0
    find_in_filing_calls_total: int = 0
    circular_confirmations_count: int = 0
    duplicate_unnamed_customer_edges_count: int = 0
    duplicate_unnamed_customer_edge_ids: list[str] = Field(default_factory=list)
    group_unnamed_customer_edges_count: int = 0
    group_unnamed_customer_edge_ids: list[str] = Field(default_factory=list)
    thorough_evaluated: bool = False
    light_surviving_edges_count: int = 0
    thorough_edges_count: int = 0
    thorough_missing_light_edge_ids: list[str] = Field(default_factory=list)
    thorough_contains_light: bool = True
    fix_1_pass: bool = True
    fix_2_pass: bool = True
    fix_14_pass: bool = True
    all_passed: bool = True


class EvalRunReport(_EvalModel):
    schema_version: str = "hoc-eval-v3.3"
    mode: Literal["replay", "live", "synthetic_baseline"]
    git_commit: str
    extractor_prompt_version: str
    judge_prompt_version: str
    research_depth: str = "light"
    bootstrap_iterations: int = 2000
    bootstrap_seed: int = 20261108
    companies_evaluated: int
    gold_relationships_total: int
    gold_core_total: int = 0
    gold_extended_total: int = 0
    gold_core_by_source: dict[str, int] = Field(default_factory=dict)
    gold_blind_total: int
    gold_pooled_total: int
    gold_negatives_total: int
    overall_after_vint: PRFMetrics
    overall_before_vint: PRFMetrics
    macro_after_vint: PRFMetrics
    macro_before_vint: PRFMetrics
    blind_overall_after_vint: PRFMetrics | None = None
    blind_macro_after_vint: PRFMetrics | None = None
    overall_before_agentic: PRFMetrics | None = None
    blind_overall_before_agentic: PRFMetrics | None = None
    macro_before_agentic: PRFMetrics | None = None
    blind_macro_before_agentic: PRFMetrics | None = None
    overall_after_agentic: PRFMetrics | None = None
    blind_overall_after_agentic: PRFMetrics | None = None
    macro_after_agentic: PRFMetrics | None = None
    blind_macro_after_agentic: PRFMetrics | None = None
    agentic_findings_total: int = 0
    agentic_steps_done_total: int = 0
    agentic_steps_total: int = 0
    agentic_new_edges_total: int = 0
    agentic_rejected_edges_total: int = 0
    agentic_acceptance: AgenticAcceptanceReport | None = None
    per_edge_type: dict[str, PRFMetrics]
    direction_accuracy: MetricWithCI
    hard_negative_fp_rate_before_vint: MetricWithCI
    hard_negative_fp_rate_after_vint: MetricWithCI
    hard_negative_by_kind: dict[str, dict[str, Any]]
    facility_country_accuracy: MetricWithCI
    importance_weighted_kappa: MetricWithCI
    importance_linear_kappa: MetricWithCI
    importance_exact_agreement: MetricWithCI
    companies: list[CompanyEvalSummary]
    false_positives: list[EvalErrorDetail]
    false_negatives: list[EvalErrorDetail]
    hard_negative_leaks: list[EvalErrorDetail]
    vint_filtered: list[EvalErrorDetail]
    pooled_candidates: list[PooledCandidate]


def load_gold_document(path: Path) -> GoldDocument:
    """Load and validate a single `<TICKER>.json` gold answer key."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return GoldDocument.model_validate(raw)


def load_gold_directory(
    gold_dir: Path,
    *,
    tickers: tuple[str, ...] | list[str] | None = None,
    include_raw_annotators: bool = False,
) -> list[GoldDocument]:
    """Load all adjudicated `<TICKER>.json` files from `gold_dir` (skipping `*.a.json` and `*.b.json`
    raw annotator files unless `include_raw_annotators=True`)."""
    if not gold_dir.exists():
        return []
    wanted = {t.upper() for t in tickers} if tickers else None
    docs: list[GoldDocument] = []
    for path in sorted(gold_dir.glob("*.json")):
        lower_name = path.name.lower()
        if lower_name.endswith((".a.json", ".b.json")) and not include_raw_annotators:
            continue
        doc = load_gold_document(path)
        if wanted is not None and doc.company.ticker.upper() not in wanted:
            continue
        docs.append(doc)
    order = {c.ticker: idx for idx, c in enumerate(HELD_OUT_COMPANIES)}
    docs.sort(key=lambda d: (order.get(d.company.ticker.upper(), 999), d.company.ticker.upper()))
    return docs


def verify_gold_quotes(gold_doc: GoldDocument, filing_text: str) -> list[str]:
    """Verify that every relationship and negative quote in `gold_doc` is a verbatim substring of
    `normalise(filing_text)` (supporting `...` two-half ellipsis bridges when both halves >= 25 chars).

    Returns a list of human-readable error strings (empty list when all quotes pass).
    """
    norm_doc = normalise(filing_text)
    errors: list[str] = []

    def _quote_in_doc(raw_quote: str) -> bool:
        nq = normalise(raw_quote)
        if not nq:
            return False
        if nq in norm_doc or nq.casefold() in norm_doc.casefold():
            return True
        if "..." in nq:
            parts = [p.strip() for p in nq.split("...") if p.strip()]
            if len(parts) == 2 and len(parts[0]) >= 25 and len(parts[1]) >= 25:
                lower_doc = norm_doc.casefold()
                idx1 = lower_doc.find(parts[0].casefold())
                if idx1 >= 0:
                    idx2 = lower_doc.find(parts[1].casefold(), idx1 + len(parts[0]))
                    if idx2 >= 0 and (idx2 - idx1) <= 1200:
                        return True
        return False

    for rel in gold_doc.relationships:
        if not _quote_in_doc(rel.quote):
            errors.append(
                f"{gold_doc.company.ticker} relationship {rel.id} ({rel.target_name!r}): "
                f"quote not found in normalised filing text"
            )
    for neg in gold_doc.negatives:
        if not _quote_in_doc(neg.quote):
            errors.append(
                f"{gold_doc.company.ticker} negative {neg.id} ({neg.target_name!r}): "
                f"quote not found in normalised filing text"
            )
    return errors
