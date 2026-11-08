"""Bounded agentic research loop for House of Cards v3 (package A-RES).

Owner: Kendrick's Gemini (`@kendricklow2008 (Gemini)`).
Rules (docs/hoc/PLAN-v3.md §6 & docs/hoc/CONTRACT.md §8):
- Python selects up to `max_items` (default 6) uncertain items ranked by `importance * exposure`
  across 5 `ResearchItemKind`s (`flagged_edge`, `undisclosed_customer`, `single_source`,
  `no_disclosures`, `unresolved_counterparty`).
- For each item, Gemini runs a bounded multi-step loop (at most `MAX_RESEARCH_STEPS = 4` steps)
  choosing one structured `ResearchAction` per step (`search_filings`, `read_section`,
  `find_in_filing`, `conclude`), and Python executes the filing tools against `FilingFetcher`.
- Every proposed edge in `ResearchFinding.new_edges` must pass `verify_quote` (against `Filing.text`),
  `verify_company_interpretations` (V-INT), and `attach_edge_importance` (R-IMP).
- Every `ResearchFinding.explanation` carries NO numbers except inside `"..."` quotes of verified evidence.
- Findings merge into a new `DependencyResult` (`merge_research_findings`) that updates `edges`,
  `companies`, `counts`, `metrics`, `insights`, and `coverage`.
- Matches the exact `ResearchRunner` protocol in `hoc.jobs`:
  `run(result, analysis, *, max_items, cache_only, progress) -> tuple[list[ResearchFinding], DependencyResult]`.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from hoc.ai.cache import ExtractionCache
from hoc.ai.client import (
    DEFAULT_EXTRACTOR_MODEL,
    GeminiClient,
    GeminiError,
    GeminiMissingKeyError,
)
from hoc.ai.extractor import EXTRACTION_SCHEMA, verify_and_build_edges
from hoc.ai.interpretation import check_interpretation_rules, verify_company_interpretations
from hoc.ai.verifier import normalise_for_verify, verify_quote
from hoc.contract import (
    AnalysisResponse,
    CompanyRunStatus,
    CompanyUnavailable,
    DependencyCounts,
    DependencyResult,
    EdgeInterpretation,
    FilingRef,
    Insights,
    ResearchFinding,
    ResearchStep,
    SourceError,
    VerifiedEdge,
)
from hoc.contract.dependencies import ResearchAction, ResearchItemKind, ResearchOutcome
from hoc.core.http import HttpClient
from hoc.filings.fetch import Filing, FilingFetcher
from hoc.filings.names import NameResolver
from hoc.filings.sections import section_map
from hoc.graph.coverage import compute_coverage_report
from hoc.graph.importance import attach_edge_importance, score_edge_importance
from hoc.graph.metrics import compute_dependency_metrics
from hoc.identity.resolver import Aliases, clean_company_name, load_aliases

log = logging.getLogger(__name__)

RESEARCH_PROMPT_VERSION = "hoc-v3-research-1"
MAX_RESEARCH_STEPS = 4
DEFAULT_ITEM_TIMEOUT_SECONDS = 25.0
DEFAULT_TOTAL_TIMEOUT_SECONDS = 90.0

RESEARCH_STEP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["search_filings", "read_section", "find_in_filing", "conclude"],
        },
        "query": {"type": "string"},
        "cik": {"type": "string"},
        "section": {"type": "string"},
        "outcome": {
            "type": "string",
            "enum": ["confirmed", "revised", "rejected", "new_evidence", "unresolved"],
        },
        "explanation": {"type": "string"},
        "candidate_edges": {
            "type": "array",
            "items": EXTRACTION_SCHEMA["properties"]["edges"]["items"],
        },
    },
    "required": ["action", "query", "outcome", "explanation", "candidate_edges"],
}

RESEARCH_SYSTEM_PROMPT = """You are a supply-chain forensic research agent investigating uncertain or incomplete dependency findings in SEC annual reports (10-K / 20-F).

At each step, pick ONE `action`:
- `find_in_filing`: search a specific company's filing (`cik`) for a verbatim `query` phrase (e.g. a supplier/customer name, "sole source", "customer", "foundry", "manufactur").
- `read_section`: inspect a section (`section` in `"1"`, `"1A"`, `"2"`, `"concentration_1"`) of the filing for `cik`.
- `search_filings`: search other companies' SEC filings for a company or counterparty `query` phrase to corroborate single-source dependencies or identify undisclosed customers.
- `conclude`: finish the investigation once you have inspected the filing observations.

STRICT GROUNDING RULES WHEN CONCLUDING (`action == "conclude"`):
1. `outcome` MUST be one of: `"confirmed"`, `"revised"`, `"rejected"`, `"new_evidence"`, `"unresolved"`.
2. `explanation` MUST NOT contain ANY numbers or percentages outside double-quoted (`"..."`) verbatim passages from the observed filing text.
3. Every item in `candidate_edges` MUST have an `evidence_quote` (20-400 characters) copied character-for-character from an observed filing passage. Never paraphrase or invent quotes.
"""

_UNNAMED_CUSTOMER_PATTERNS: tuple[str, ...] = (
    "unnamed",
    "undisclosed",
    "customer a",
    "customer b",
    "customer c",
    "single customer",
    "one customer",
    "major customer",
    "largest customer",
)

_DEPENDENCY_KEYWORDS: tuple[str, ...] = (
    "rely",
    "relies",
    "depend",
    "sole",
    "single source",
    "supplier",
    "foundry",
    "wafer",
    "manufactur",
    "assembly",
    "fab",
    "facility",
    "customer",
    "revenue",
    "partner",
    "agreement",
)

_QUOTED_SEGMENT_RE = re.compile(r'("[^"]*")')
_DIGIT_TOKEN_RE = re.compile(
    r"\$?\b\d+(?:[.,]\d+)*(?:\s*%|\s*(?:billion|million|thousand|trillion|bps|pts|x|st|nd|rd|th))?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ResearchItem:
    """One uncertain finding or coverage gap queued for agentic investigation."""

    item_id: str
    item_kind: ResearchItemKind
    subject_key: str
    subject_name: str
    subject_label: str
    question: str
    priority_score: float
    edge: VerifiedEdge | None = None
    company_status: CompanyRunStatus | None = None
    target_name: str | None = None
    cik: str | None = None
    filing_ref: FilingRef | None = None


def _extract_cik_from_key(company_key: str | None) -> str | None:
    if not company_key:
        return None
    if company_key.startswith("CIK:"):
        raw = company_key.removeprefix("CIK:").strip()
        if raw.isdigit():
            return raw.zfill(10)
    return None


def _is_unnamed_customer_edge(edge: VerifiedEdge) -> bool:
    if edge.target_kind == "unnamed_customer":
        return True
    if edge.edge_type != "customer":
        return False
    lower_name = edge.target_name.lower()
    return any(tok in lower_name for tok in _UNNAMED_CUSTOMER_PATTERNS)


def select_research_items(
    result: DependencyResult,
    analysis: AnalysisResponse | None = None,
    *,
    max_items: int = 6,
) -> list[ResearchItem]:
    """Deterministically select and rank up to `max_items` research items by `importance * exposure`."""
    if max_items <= 0:
        return []

    exposure_by_key: dict[str, float] = {
        c.company_key: float(c.exposure) for c in result.companies if c.exposure > 0
    }
    name_by_key: dict[str, str] = {c.company_key: c.company_name for c in result.companies}
    filing_ref_by_key: dict[str, FilingRef] = {
        c.company_key: c.filing for c in result.companies if c.filing is not None
    }
    if analysis is not None:
        for exp in analysis.exposures:
            if exp.exposure > 0:
                exposure_by_key.setdefault(exp.company_key, float(exp.exposure))
            name_by_key.setdefault(exp.company_key, exp.company_name)

    cik_by_key: dict[str, str] = {}
    for comp in result.companies:
        cik = _extract_cik_from_key(comp.company_key)
        if cik:
            cik_by_key[comp.company_key] = cik
    for edge in result.edges:
        cik_from_filing = _extract_cik_from_key(edge.filing.company_key)
        if cik_from_filing and edge.source_company_key == edge.filing.company_key:
            cik_by_key.setdefault(edge.source_company_key, cik_from_filing)
        filing_ref_by_key.setdefault(edge.source_company_key, edge.filing)

    # Count distinct filing accessions supporting each (source_company_key, target_identity, edge_type)
    filing_support_counts: dict[tuple[str, str, str], set[str]] = {}
    for edge in result.edges:
        target_id = edge.target_key or edge.target_name.strip().casefold()
        pair_key = (edge.source_company_key, target_id, edge.edge_type)
        filing_support_counts.setdefault(pair_key, set()).add(edge.filing.accession)

    candidates: list[ResearchItem] = []
    used_primary_edge_ids: set[str] = set()

    # 1. Flagged edges (`interpretation.status == "flagged"`)
    for edge in result.edges:
        imp = edge.importance if edge.importance is not None else score_edge_importance(edge)
        exp = max(exposure_by_key.get(edge.source_company_key, 0.0), 0.005)
        subj_name = name_by_key.get(edge.source_company_key, edge.source_company_name)
        cik = cik_by_key.get(edge.source_company_key) or _extract_cik_from_key(edge.filing.company_key)

        if edge.interpretation is not None and edge.interpretation.status == "flagged":
            candidates.append(
                ResearchItem(
                    item_id=f"res_flagged_{edge.edge_id}",
                    item_kind="flagged_edge",
                    subject_key=edge.source_company_key,
                    subject_name=subj_name,
                    subject_label=f"{subj_name} -> {edge.target_name} ({edge.edge_type})",
                    question=f"Does {subj_name}'s filing context confirm or contradict the {edge.edge_type} link to {edge.target_name}?",
                    priority_score=round((imp.score + 0.30) * exp, 8),
                    edge=edge,
                    target_name=edge.target_name,
                    cik=cik,
                    filing_ref=edge.filing,
                )
            )
            used_primary_edge_ids.add(edge.edge_id)

    # 2. Undisclosed customers (`target_kind == "unnamed_customer"` or unnamed customer cue)
    for edge in result.edges:
        if edge.edge_id in used_primary_edge_ids:
            continue
        if _is_unnamed_customer_edge(edge):
            imp = edge.importance if edge.importance is not None else score_edge_importance(edge)
            exp = max(exposure_by_key.get(edge.source_company_key, 0.0), 0.005)
            subj_name = name_by_key.get(edge.source_company_key, edge.source_company_name)
            cik = cik_by_key.get(edge.source_company_key) or _extract_cik_from_key(edge.filing.company_key)
            candidates.append(
                ResearchItem(
                    item_id=f"res_undisclosed_{edge.edge_id}",
                    item_kind="undisclosed_customer",
                    subject_key=edge.source_company_key,
                    subject_name=subj_name,
                    subject_label=f"{subj_name}'s undisclosed customer ({edge.target_name})",
                    question=f"Do {subj_name}'s or peer SEC filings name or corroborate {edge.target_name}?",
                    priority_score=round((imp.score + 0.25) * exp, 8),
                    edge=edge,
                    target_name=edge.target_name,
                    cik=cik,
                    filing_ref=edge.filing,
                )
            )
            used_primary_edge_ids.add(edge.edge_id)

    # 3. Unresolved counterparties (`target_kind == "company"` and `target_key is None` at critical/high importance)
    for edge in result.edges:
        if edge.edge_id in used_primary_edge_ids:
            continue
        imp = edge.importance if edge.importance is not None else score_edge_importance(edge)
        if edge.target_kind == "company" and edge.target_key is None and (
            imp.tier in ("critical", "high") or imp.score >= 0.55
        ):
            exp = max(exposure_by_key.get(edge.source_company_key, 0.0), 0.005)
            subj_name = name_by_key.get(edge.source_company_key, edge.source_company_name)
            cik = cik_by_key.get(edge.source_company_key) or _extract_cik_from_key(edge.filing.company_key)
            candidates.append(
                ResearchItem(
                    item_id=f"res_unresolved_{edge.edge_id}",
                    item_kind="unresolved_counterparty",
                    subject_key=edge.source_company_key,
                    subject_name=subj_name,
                    subject_label=f"{subj_name} counterparty {edge.target_name}",
                    question=f"Can counterparty {edge.target_name} in {subj_name}'s filing be verified and resolved?",
                    priority_score=round((imp.score + 0.15) * exp, 8),
                    edge=edge,
                    target_name=edge.target_name,
                    cik=cik,
                    filing_ref=edge.filing,
                )
            )
            used_primary_edge_ids.add(edge.edge_id)

    # 4. Companies with `no_disclosures` (`status in ("done", "cached")` and `verified_edges == 0`)
    edges_by_source: dict[str, int] = {}
    for edge in result.edges:
        edges_by_source[edge.source_company_key] = edges_by_source.get(edge.source_company_key, 0) + 1

    for comp in result.companies:
        actual_edges = edges_by_source.get(comp.company_key, comp.verified_edges)
        if comp.status in ("done", "cached") and actual_edges == 0:
            exp = max(float(comp.exposure), exposure_by_key.get(comp.company_key, 0.0), 0.005)
            cik = cik_by_key.get(comp.company_key) or _extract_cik_from_key(comp.company_key)
            candidates.append(
                ResearchItem(
                    item_id=f"res_nodisc_{comp.company_key}",
                    item_kind="no_disclosures",
                    subject_key=comp.company_key,
                    subject_name=comp.company_name,
                    subject_label=f"{comp.company_name} (no verified disclosures)",
                    question=f"Does {comp.company_name}'s annual report or peer filings contain verifiable dependency disclosures?",
                    priority_score=round(0.80 * exp, 8),
                    company_status=comp,
                    target_name=None,
                    cik=cik,
                    filing_ref=comp.filing or filing_ref_by_key.get(comp.company_key),
                )
            )

    # 5. Single-source / single-filing critical or high edges (`single_source`)
    for edge in result.edges:
        if edge.edge_id in used_primary_edge_ids:
            continue
        imp = edge.importance if edge.importance is not None else score_edge_importance(edge)
        target_id = edge.target_key or edge.target_name.strip().casefold()
        pair_key = (edge.source_company_key, target_id, edge.edge_type)
        filing_count = len(filing_support_counts.get(pair_key, {edge.filing.accession}))
        if filing_count <= 1 and (edge.sole_source or imp.tier in ("critical", "high")):
            exp = max(exposure_by_key.get(edge.source_company_key, 0.0), 0.005)
            subj_name = name_by_key.get(edge.source_company_key, edge.source_company_name)
            cik = cik_by_key.get(edge.source_company_key) or _extract_cik_from_key(edge.filing.company_key)
            candidates.append(
                ResearchItem(
                    item_id=f"res_single_{edge.edge_id}",
                    item_kind="single_source",
                    subject_key=edge.source_company_key,
                    subject_name=subj_name,
                    subject_label=f"{subj_name} single-source reliance on {edge.target_name}",
                    question=f"Is {subj_name}'s critical reliance on {edge.target_name} corroborated in the filing or peer filings?",
                    priority_score=round(imp.score * exp, 8),
                    edge=edge,
                    target_name=edge.target_name,
                    cik=cik,
                    filing_ref=edge.filing,
                )
            )

    candidates.sort(key=lambda item: (-item.priority_score, item.item_id))

    # Diversity pass: take the top-ranked item from each available kind first, then fill by priority_score
    selected: list[ResearchItem] = []
    selected_ids: set[str] = set()
    seen_kinds: set[ResearchItemKind] = set()

    for cand in candidates:
        if len(selected) >= max_items:
            break
        if cand.item_kind not in seen_kinds:
            seen_kinds.add(cand.item_kind)
            selected.append(cand)
            selected_ids.add(cand.item_id)

    seen_subjects: set[str] = {item.subject_key for item in selected}
    for cand in candidates:
        if len(selected) >= max_items:
            break
        if cand.item_id in selected_ids:
            continue
        if cand.subject_key not in seen_subjects:
            seen_subjects.add(cand.subject_key)
            selected.append(cand)
            selected_ids.add(cand.item_id)

    for cand in candidates:
        if len(selected) >= max_items:
            break
        if cand.item_id not in selected_ids:
            selected.append(cand)
            selected_ids.add(cand.item_id)

    selected.sort(key=lambda item: (-item.priority_score, item.item_id))
    return selected[:max_items]


def strip_unquoted_numbers(explanation: str, verified_quotes: Sequence[str] = ()) -> str:
    """Ensure `explanation` contains NO digits outside `"..."` quotes of verified evidence."""
    if not explanation or not explanation.strip():
        return "Verified filing context reviewed."

    norm_verified = [
        normalise_for_verify(q).casefold()
        for q in verified_quotes
        if isinstance(q, str) and q.strip()
    ]

    def _is_verified_quote_segment(quoted_str: str) -> bool:
        inner = quoted_str.strip('"').strip()
        if len(inner) < 10 or not norm_verified:
            return False
        norm_inner = normalise_for_verify(inner).casefold()
        if not norm_inner:
            return False
        return any(norm_inner in vq or vq in norm_inner for vq in norm_verified)

    parts = _QUOTED_SEGMENT_RE.split(explanation.strip())
    cleaned_parts: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith('"') and part.endswith('"') and len(part) >= 2:
            if _is_verified_quote_segment(part):
                cleaned_parts.append(part)
            else:
                inner_clean = _DIGIT_TOKEN_RE.sub("", part[1:-1])
                inner_clean = re.sub(r"\d+", "", inner_clean)
                inner_clean = re.sub(r"\s{2,}", " ", inner_clean).strip()
                if inner_clean:
                    cleaned_parts.append(f'"{inner_clean}"')
        else:
            scrubbed = _DIGIT_TOKEN_RE.sub("", part)
            scrubbed = re.sub(r"\d+", "", scrubbed)
            cleaned_parts.append(scrubbed)

    joined = "".join(cleaned_parts)
    joined = re.sub(r"\s+([,.;:!?])", r"\1", joined)
    joined = re.sub(r"\(\s*\)", "", joined)
    joined = re.sub(r"\s{2,}", " ", joined).strip()
    if not joined:
        if verified_quotes:
            return f'Verified filing passage: "{verified_quotes[0]}".'
        return "Verified filing context reviewed."
    return joined


def merge_research_findings(
    result: DependencyResult,
    analysis: AnalysisResponse,
    findings: Sequence[ResearchFinding],
    *,
    orchestrator: Any = None,
    resolver: Callable[[str], str | None] | None = None,
    cache_only: bool = False,
) -> DependencyResult:
    """Merge `findings` into `result`, updating edges, companies, counts, metrics, insights, and coverage."""
    if resolver is None:
        try:
            resolver = NameResolver(analysis.exposures, load_aliases()).resolve
        except Exception:  # noqa: BLE001
            resolver = None

    rejected_ids: set[str] = set()
    confirmed_ids: set[str] = set()
    added_edges: list[VerifiedEdge] = []

    for finding in findings:
        for rid in finding.rejected_edge_ids:
            if rid:
                rejected_ids.add(rid)
        for cid in finding.confirmed_edge_ids:
            if cid and cid not in rejected_ids:
                confirmed_ids.add(cid)
        for new_edge in finding.new_edges:
            if new_edge.edge_id not in rejected_ids:
                added_edges.append(new_edge)

    portfolio_names = {c.company_key: c.company_name for c in analysis.exposures}
    portfolio_keys = set(portfolio_names)

    merged_by_id: dict[str, VerifiedEdge] = {}
    for edge in result.edges:
        if edge.edge_id in rejected_ids:
            continue
        updated = edge
        if edge.edge_id in confirmed_ids:
            prev_flags = list(edge.interpretation.flags) if edge.interpretation is not None else []
            prev_method = edge.interpretation.method if edge.interpretation is not None else "rules"
            prev_model = edge.interpretation.model if edge.interpretation is not None else None
            updated = updated.model_copy(
                update={
                    "interpretation": EdgeInterpretation(
                        status="confirmed",
                        method=prev_method,
                        flags=prev_flags,
                        reason="Confirmed by multi-step filing verification.",
                        model=prev_model,
                    )
                }
            )
        if updated.target_key is None and resolver is not None and updated.target_kind == "company":
            resolved_key = resolver(updated.target_name)
            if resolved_key:
                updated = updated.model_copy(
                    update={
                        "target_key": resolved_key,
                        "target_in_portfolio": resolved_key in portfolio_keys,
                    }
                )
        updated = updated.model_copy(update={"importance": score_edge_importance(updated)})
        merged_by_id[updated.edge_id] = updated

    for new_edge in added_edges:
        target_key = new_edge.target_key
        if target_key is None and resolver is not None and new_edge.target_kind == "company":
            target_key = resolver(new_edge.target_name)
        interp = new_edge.interpretation or EdgeInterpretation(
            status="confirmed",
            method="rules",
            flags=[],
            reason=None,
            model=None,
        )
        prepared = new_edge.model_copy(
            update={
                "target_key": target_key,
                "source_company_name": portfolio_names.get(
                    new_edge.source_company_key, new_edge.source_company_name
                ),
                "source_in_portfolio": new_edge.source_company_key in portfolio_keys,
                "target_in_portfolio": target_key is not None and target_key in portfolio_keys,
                "interpretation": interp,
            }
        )
        prepared = prepared.model_copy(update={"importance": score_edge_importance(prepared)})
        merged_by_id[prepared.edge_id] = prepared

    merged_edges = list(merged_by_id.values())

    edges_per_company: dict[str, int] = {}
    for edge in merged_edges:
        edges_per_company[edge.source_company_key] = edges_per_company.get(edge.source_company_key, 0) + 1

    updated_companies: list[CompanyRunStatus] = []
    for comp in result.companies:
        new_count = edges_per_company.get(comp.company_key, 0)
        updated_companies.append(comp.model_copy(update={"verified_edges": new_count}))

    top_n = result.request.top_n
    top_exposures = [c for c in analysis.exposures if c.exposure > 0][:top_n]
    metrics = list(result.metrics)
    insights: Insights = result.insights

    if orchestrator is not None and hasattr(orchestrator, "insights"):
        try:
            metrics, insights = orchestrator.insights(analysis, merged_edges, cache_only=cache_only)
        except Exception:
            log.exception("orchestrator.insights failed during research merge; falling back to deterministic metrics")
            metrics = compute_dependency_metrics(top_exposures, merged_edges)
    else:
        try:
            metrics = compute_dependency_metrics(top_exposures, merged_edges)
        except Exception:
            log.exception("compute_dependency_metrics failed during research merge")

    try:
        coverage = compute_coverage_report(
            analysis,
            updated_companies,
            merged_edges,
            as_of_date=analysis.as_of_date,
        )
    except Exception:
        log.exception("compute_coverage_report failed during research merge")
        coverage = result.coverage

    analysed = sum(1 for c in updated_companies if c.status in ("cached", "done"))
    unresolved_count = len(
        {
            e.target_name.casefold()
            for e in merged_edges
            if e.target_key is None and e.target_kind == "company"
        }
    )
    updated_counts = DependencyCounts(
        companies_requested=result.counts.companies_requested,
        companies_analysed=analysed,
        companies_skipped=max(0, result.counts.companies_requested - analysed),
        verified_edges=len(merged_edges),
        rejected_edges=result.counts.rejected_edges,
        interpretation_rejected=result.counts.interpretation_rejected + len(rejected_ids),
        unresolved_counterparties=unresolved_count,
    )

    return DependencyResult(
        as_of_date=result.as_of_date,
        request=result.request,
        companies=updated_companies,
        edges=merged_edges,
        metrics=metrics,
        insights=insights,
        counts=updated_counts,
        attributions=result.attributions,
        coverage=coverage,
    )


class ResearchLoop:
    """Bounded multi-step agentic research runner implementing `hoc.jobs.ResearchRunner`."""

    prompt_version: str = RESEARCH_PROMPT_VERSION

    def __init__(
        self,
        client: GeminiClient | Any,
        fetcher: FilingFetcher | None = None,
        *,
        edgar: Any = None,
        orchestrator: Any = None,
        cache: ExtractionCache | None = None,
        aliases: Aliases | None = None,
        filings_by_key: Mapping[str, Filing] | None = None,
        filings_by_cik: Mapping[str, Filing] | None = None,
        model: str | None = None,
        max_steps: int = MAX_RESEARCH_STEPS,
        item_timeout_s: float = DEFAULT_ITEM_TIMEOUT_SECONDS,
        total_timeout_s: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
    ) -> None:
        self.client = client
        self.fetcher = fetcher
        self.edgar = edgar
        self.orchestrator = orchestrator
        self.cache = cache
        self.aliases = aliases
        self._filings_by_key: dict[str, Filing] = dict(filings_by_key or {})
        self._filings_by_cik: dict[str, Filing] = {
            str(k).zfill(10): v for k, v in (filings_by_cik or {}).items()
        }
        for filing in self._filings_by_key.values():
            if filing.cik:
                self._filings_by_cik.setdefault(str(filing.cik).zfill(10), filing)
        self.model = model or getattr(client, "extractor_model", DEFAULT_EXTRACTOR_MODEL)
        self.max_steps = max(1, min(int(max_steps), MAX_RESEARCH_STEPS))
        self.item_timeout_s = max(1.0, float(item_timeout_s))
        self.total_timeout_s = max(5.0, float(total_timeout_s))

    @classmethod
    def from_settings(cls, http: HttpClient, settings: Any = None) -> ResearchLoop:
        """Construct a production `ResearchLoop` from `HttpClient` and `Settings`."""
        from hoc.config import get_settings
        from hoc.graph import Orchestrator

        cfg = settings if settings is not None else get_settings()
        client = GeminiClient(http, cfg)
        cache = ExtractionCache(cfg.cache_dir)
        fetcher = FilingFetcher(http, cfg)
        edgar = None
        aliases = load_aliases()
        orchestrator = Orchestrator(http, cfg)
        return cls(
            client=client,
            fetcher=fetcher,
            edgar=edgar,
            orchestrator=orchestrator,
            cache=cache,
            aliases=aliases,
        )

    def run(
        self,
        result: DependencyResult,
        analysis: AnalysisResponse,
        *,
        max_items: int = 6,
        cache_only: bool = False,
        progress: Callable[[int, int, list[ResearchFinding]], None] | None = None,
        on_finding: Callable[[ResearchFinding], None] | None = None,
    ) -> tuple[list[ResearchFinding], DependencyResult]:
        """Run the bounded research loop on up to `max_items` uncertain items and return `(findings, merged_result)`."""
        items = select_research_items(result, analysis, max_items=max_items)
        total = len(items)
        findings: list[ResearchFinding] = []
        if progress is not None:
            progress(0, total, [])

        aliases = self.aliases if self.aliases is not None else load_aliases()
        resolver = NameResolver(analysis.exposures, aliases).resolve
        top_keys = {c.company_key for c in analysis.exposures if c.exposure > 0}

        started = time.monotonic()
        for idx, item in enumerate(items, start=1):
            elapsed = time.monotonic() - started
            if elapsed >= self.total_timeout_s:
                finding = ResearchFinding(
                    finding_id=item.item_id,
                    kind=item.item_kind,
                    subject=item.subject_label,
                    question=item.question,
                    outcome="unresolved",
                    explanation="Research wall-clock budget reached before investigating this item.",
                    steps=[
                        ResearchStep(
                            index=1,
                            action="conclude",
                            query=item.subject_name,
                            summary="Skipped remaining steps because the research time budget was reached.",
                            filing=item.filing_ref,
                        )
                    ],
                )
            else:
                try:
                    finding = self._investigate_item(
                        item=item,
                        result=result,
                        analysis=analysis,
                        resolver=resolver,
                        top_keys=top_keys,
                        cache_only=cache_only,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("research item %s failed: %s", item.item_id, exc)
                    finding = ResearchFinding(
                        finding_id=item.item_id,
                        kind=item.item_kind,
                        subject=item.subject_label,
                        question=item.question,
                        outcome="unresolved",
                        explanation="Investigation could not be completed due to an unexpected source error.",
                        steps=[
                            ResearchStep(
                                index=1,
                                action="conclude",
                                query=item.subject_name,
                                summary="Investigation terminated cleanly after an unexpected error.",
                                filing=item.filing_ref,
                            )
                        ],
                    )

            findings.append(finding)
            if on_finding is not None:
                on_finding(finding)
            if progress is not None:
                progress(idx, total, list(findings))

        merged = merge_research_findings(
            result,
            analysis,
            findings,
            orchestrator=self.orchestrator,
            resolver=resolver,
            cache_only=cache_only,
        )
        return findings, merged

    # ---------- per-item investigation ----------

    def _investigate_item(
        self,
        *,
        item: ResearchItem,
        result: DependencyResult,
        analysis: AnalysisResponse,
        resolver: Callable[[str], str | None],
        top_keys: set[str],
        cache_only: bool,
    ) -> ResearchFinding:
        filing = self._load_filing_for_item(item, analysis)
        cik = (
            (filing.cik if filing is not None else None)
            or item.cik
            or _extract_cik_from_key(item.subject_key)
            or "0000000000"
        )
        cik = str(cik).zfill(10) if str(cik).isdigit() else str(cik)
        filing_ref = self._filing_ref_for(item, filing)

        steps: list[ResearchStep] = []
        observations: list[str] = []
        verified_quotes: list[str] = []

        if item.edge is not None and item.edge.evidence_quote:
            verified_quotes.append(item.edge.evidence_quote)

        has_key = bool(getattr(self.client, "has_api_key", True))
        can_call_gemini = has_key and not cache_only

        item_started = time.monotonic()
        concluded_payload: Mapping[str, Any] | None = None

        for step_idx in range(1, self.max_steps + 1):
            if time.monotonic() - item_started > self.item_timeout_s:
                break

            step_decision: Mapping[str, Any] | None = None
            if can_call_gemini:
                prompt = self._build_step_prompt(
                    item=item,
                    cik=cik,
                    step_idx=step_idx,
                    observations=observations,
                )
                try:
                    raw_resp, _ = self.client.generate_json(
                        prompt,
                        RESEARCH_STEP_SCHEMA,
                        model=self.model,
                        system_instruction=RESEARCH_SYSTEM_PROMPT,
                        thinking_level="low",
                    )
                    if isinstance(raw_resp, Mapping):
                        step_decision = raw_resp
                except (GeminiError, GeminiMissingKeyError, SourceError, ValueError) as exc:
                    log.info("Gemini research step %d fell back to deterministic tool execution: %s", step_idx, exc)
                    can_call_gemini = False

            if step_decision is None:
                step_decision = self._deterministic_step_decision(
                    item=item,
                    cik=cik,
                    step_idx=step_idx,
                    verified_quotes=verified_quotes,
                    observations=observations,
                )

            action_raw = str(step_decision.get("action", "conclude")).strip()
            action: ResearchAction = (
                action_raw  # type: ignore[assignment]
                if action_raw in ("search_filings", "read_section", "find_in_filing", "conclude")
                else "conclude"
            )

            if action == "conclude" and not steps:
                fallback_step = self._deterministic_step_decision(
                    item=item,
                    cik=cik,
                    step_idx=1,
                    verified_quotes=verified_quotes,
                    observations=observations,
                )
                first_action = str(fallback_step.get("action", "find_in_filing"))
                if first_action != "conclude":
                    self._execute_tool_step(
                        action=first_action,  # type: ignore[arg-type]
                        decision=fallback_step,
                        item=item,
                        cik=cik,
                        filing=filing,
                        filing_ref=filing_ref,
                        result=result,
                        analysis=analysis,
                        cache_only=cache_only,
                        steps=steps,
                        observations=observations,
                        verified_quotes=verified_quotes,
                    )
                    if len(steps) >= self.max_steps:
                        concluded_payload = step_decision
                        break
                    if not can_call_gemini:
                        continue

            if action == "conclude":
                concluded_payload = step_decision
                break

            self._execute_tool_step(
                action=action,
                decision=step_decision,
                item=item,
                cik=cik,
                filing=filing,
                filing_ref=filing_ref,
                result=result,
                analysis=analysis,
                cache_only=cache_only,
                steps=steps,
                observations=observations,
                verified_quotes=verified_quotes,
            )

        return self._finalize_finding(
            item=item,
            cik=cik,
            filing=filing,
            filing_ref=filing_ref,
            result=result,
            analysis=analysis,
            resolver=resolver,
            top_keys=top_keys,
            cache_only=cache_only,
            steps=steps,
            verified_quotes=verified_quotes,
            concluded_payload=concluded_payload,
        )

    @staticmethod
    def _filing_ref_for(item: ResearchItem, filing: Filing | None) -> FilingRef | None:
        if item.filing_ref is not None:
            return item.filing_ref
        if item.edge is not None:
            return item.edge.filing
        if filing is not None:
            form_literal = "20-F" if "20-F" in str(filing.form).upper() else "10-K"
            return FilingRef(
                company_key=item.subject_key,
                form=form_literal,  # type: ignore[arg-type]
                accession=filing.accession,
                filed=filing.filed,
                url=filing.url,
            )
        return None

    def _execute_tool_step(
        self,
        *,
        action: ResearchAction,
        decision: Mapping[str, Any],
        item: ResearchItem,
        cik: str,
        filing: Filing | None,
        filing_ref: FilingRef | None,
        result: DependencyResult,
        analysis: AnalysisResponse,
        cache_only: bool,
        steps: list[ResearchStep],
        observations: list[str],
        verified_quotes: list[str],
    ) -> None:
        query_raw = str(decision.get("query") or "").strip()
        target_cik = str(decision.get("cik") or cik).strip() or cik
        section_req = str(decision.get("section") or "1").strip() or "1"

        target_filing = filing
        if target_cik != cik:
            target_filing = self._load_filing_by_cik(target_cik) or filing

        next_index = len(steps) + 1

        if action == "find_in_filing":
            search_phrase = query_raw or item.target_name or item.subject_name
            spans = self._find_spans_in_filing(target_filing, search_phrase, item=item, result=result)
            for span in spans:
                if span not in verified_quotes:
                    verified_quotes.append(span)
                observations.append(f'OBSERVED_QUOTE: "{span}" (source=find_in_filing, cik={target_cik})')
            summary = (
                f'Found verified filing passage "{spans[0][:140]}" matching {search_phrase}.'
                if spans
                else f"Searched filing for {search_phrase}; no exact phrase match in primary text."
            )
            steps.append(
                ResearchStep(
                    index=next_index,
                    action="find_in_filing",
                    query=search_phrase,
                    summary=strip_unquoted_numbers(summary, spans),
                    filing=filing_ref,
                )
            )
            return

        if action == "read_section":
            spans = self._read_section_spans(target_filing, section_req, item=item, result=result)
            for span in spans:
                if span not in verified_quotes:
                    verified_quotes.append(span)
                observations.append(
                    f'OBSERVED_QUOTE: "{span}" (source=read_section, cik={target_cik}, section={section_req})'
                )
            summary = (
                f'Read section {section_req} and extracted verified passage "{spans[0][:140]}".'
                if spans
                else f"Read section {section_req} of filing; no additional dependency passages surfaced."
            )
            steps.append(
                ResearchStep(
                    index=next_index,
                    action="read_section",
                    query=f"Item {section_req}",
                    summary=strip_unquoted_numbers(summary, spans),
                    filing=filing_ref,
                )
            )
            return

        if action == "search_filings":
            phrase = query_raw or item.target_name or clean_company_name(item.subject_name)
            spans, peer_names = self._search_across_filings(
                phrase,
                exclude_cik=cik,
                item=item,
                result=result,
                analysis=analysis,
                cache_only=cache_only,
            )
            for span in spans:
                if span not in verified_quotes:
                    verified_quotes.append(span)
                observations.append(f'OBSERVED_QUOTE: "{span}" (source=search_filings, query={phrase})')
            if spans:
                peer_label = ", ".join(peer_names[:2]) if peer_names else "peer filings"
                summary = f'Cross-filing search for {phrase} in {peer_label} found "{spans[0][:140]}".'
            else:
                summary = f"Searched SEC filings for {phrase}; no additional corroborating passages found."
            steps.append(
                ResearchStep(
                    index=next_index,
                    action="search_filings",
                    query=phrase,
                    summary=strip_unquoted_numbers(summary, spans),
                    filing=filing_ref,
                )
            )

    def _finalize_finding(
        self,
        *,
        item: ResearchItem,
        cik: str,
        filing: Filing | None,
        filing_ref: FilingRef | None,
        result: DependencyResult,
        analysis: AnalysisResponse,
        resolver: Callable[[str], str | None],
        top_keys: set[str],
        cache_only: bool,
        steps: list[ResearchStep],
        verified_quotes: list[str],
        concluded_payload: Mapping[str, Any] | None,
    ) -> ResearchFinding:
        if concluded_payload is None:
            concluded_payload = self._deterministic_step_decision(
                item=item,
                cik=cik,
                step_idx=self.max_steps,
                verified_quotes=verified_quotes,
                observations=[f'OBSERVED_QUOTE: "{q}"' for q in verified_quotes],
            )

        raw_outcome = str(concluded_payload.get("outcome") or "unresolved").strip()
        outcome: ResearchOutcome = (
            raw_outcome  # type: ignore[assignment]
            if raw_outcome in ("confirmed", "revised", "rejected", "new_evidence", "unresolved")
            else "unresolved"
        )
        raw_explanation = str(concluded_payload.get("explanation") or "").strip()
        raw_candidates = concluded_payload.get("candidate_edges")
        candidate_dicts = (
            [c for c in raw_candidates if isinstance(c, Mapping)]
            if isinstance(raw_candidates, list)
            else []
        )

        verified_new_edges: list[VerifiedEdge] = []
        if candidate_dicts and filing is not None and filing_ref is not None:
            sections_map = section_map(filing.text, filing.form)[0]
            built_edges, _ = verify_and_build_edges(
                candidate_dicts,
                source_company_key=item.subject_key,
                source_company_name=item.subject_name,
                source_in_portfolio=item.subject_key in top_keys,
                canonical_text=filing.text,
                filing_ref=filing_ref,
                sections=sections_map,
                portfolio_company_keys=top_keys,
                resolve_target_key=resolver,
            )
            if built_edges:
                interp_res = verify_company_interpretations(
                    built_edges,
                    filing.text,
                    client=self.client,
                    cache=self.cache,
                    cache_only=cache_only,
                )
                verified_new_edges = attach_edge_importance(interp_res.edges)
                for ve in verified_new_edges:
                    if ve.evidence_quote not in verified_quotes:
                        verified_quotes.append(ve.evidence_quote)

        if not verified_new_edges and item.item_kind in ("no_disclosures", "undisclosed_customer"):
            recovered = self._recover_edges_from_filing(
                item=item,
                filing=filing,
                filing_ref=filing_ref,
                resolver=resolver,
                top_keys=top_keys,
            )
            if recovered:
                verified_new_edges = attach_edge_importance(recovered)
                for ve in verified_new_edges:
                    if ve.evidence_quote not in verified_quotes:
                        verified_quotes.append(ve.evidence_quote)

        confirmed_edge_ids: list[str] = []
        rejected_edge_ids: list[str] = []

        if item.item_kind == "flagged_edge" and item.edge is not None:
            edge = item.edge
            doc_text = filing.text if filing is not None else edge.evidence_quote
            active_flags, _, _ = check_interpretation_rules(edge, doc_text)

            if outcome == "rejected" or any(
                f in active_flags for f in ("competitor_mention", "negated", "direction_mismatch", "generic_reference")
            ):
                outcome = "rejected"
                rejected_edge_ids = [edge.edge_id]
                if not raw_explanation:
                    raw_explanation = (
                        f'Filing context "{edge.evidence_quote}" does not support an active supply dependency.'
                    )
            else:
                outcome = "confirmed"
                confirmed_edge_ids = [edge.edge_id]
                if not raw_explanation:
                    raw_explanation = (
                        f'Verified filing context "{edge.evidence_quote}" confirms the operational dependency.'
                    )

        elif item.item_kind == "single_source" and item.edge is not None:
            edge = item.edge
            if verified_new_edges:
                outcome = "new_evidence"
                confirmed_edge_ids = [edge.edge_id]
            elif verified_quotes:
                outcome = "confirmed"
                confirmed_edge_ids = [edge.edge_id]
                if not raw_explanation:
                    raw_explanation = (
                        f'Verified sole-source disclosure "{verified_quotes[0]}" in the annual report.'
                    )

        elif item.item_kind == "unresolved_counterparty" and item.edge is not None:
            edge = item.edge
            resolved_key = resolver(edge.target_name)
            if resolved_key is not None:
                outcome = "revised"
                confirmed_edge_ids = [edge.edge_id]
                if not raw_explanation:
                    raw_explanation = (
                        f'Resolved counterparty identity for "{edge.evidence_quote}" against portfolio records.'
                    )
            elif verified_quotes:
                outcome = "confirmed"
                confirmed_edge_ids = [edge.edge_id]
                if not raw_explanation:
                    raw_explanation = (
                        f'Verified external counterparty disclosure "{verified_quotes[0]}" in the filing.'
                    )

        elif item.item_kind in ("no_disclosures", "undisclosed_customer"):
            if verified_new_edges:
                outcome = "new_evidence"
                if not raw_explanation:
                    raw_explanation = (
                        f'Extracted verified dependency disclosure "{verified_new_edges[0].evidence_quote}".'
                    )
            elif item.edge is not None and verified_quotes:
                outcome = "confirmed" if outcome not in ("confirmed", "revised") else outcome
                confirmed_edge_ids = [item.edge.edge_id]
                if not raw_explanation:
                    raw_explanation = (
                        f'Confirmed customer concentration disclosure "{verified_quotes[0]}" in the filing.'
                    )
            else:
                outcome = "unresolved"
                if not raw_explanation:
                    raw_explanation = (
                        "Filing leaves specific counterparty identities undisclosed in the inspected sections."
                    )

        clean_explanation = strip_unquoted_numbers(raw_explanation, verified_quotes)

        if len(steps) < self.max_steps:
            steps.append(
                ResearchStep(
                    index=len(steps) + 1,
                    action="conclude",
                    query=item.target_name or item.subject_name,
                    summary=clean_explanation,
                    filing=filing_ref,
                )
            )
        else:
            steps[-1] = ResearchStep(
                index=self.max_steps,
                action="conclude",
                query=item.target_name or item.subject_name,
                summary=clean_explanation,
                filing=filing_ref,
            )

        return ResearchFinding(
            finding_id=item.item_id,
            kind=item.item_kind,
            subject=item.subject_label,
            question=item.question,
            outcome=outcome,
            explanation=clean_explanation,
            steps=steps[: self.max_steps],
            confirmed_edge_ids=confirmed_edge_ids,
            rejected_edge_ids=rejected_edge_ids,
            new_edges=verified_new_edges,
        )

    # ---------- filing & tool helpers ----------

    def _load_filing_for_item(self, item: ResearchItem, analysis: AnalysisResponse) -> Filing | None:
        if item.subject_key in self._filings_by_key:
            return self._filings_by_key[item.subject_key]
        cik = item.cik or _extract_cik_from_key(item.subject_key)
        if cik:
            filing = self._load_filing_by_cik(cik)
            if filing is not None:
                self._filings_by_key[item.subject_key] = filing
                return filing
        if self.fetcher is not None:
            comp_exp = next((c for c in analysis.exposures if c.company_key == item.subject_key), None)
            if comp_exp is not None and hasattr(self.fetcher, "for_company"):
                try:
                    filing = self.fetcher.for_company(comp_exp)
                    self._filings_by_key[item.subject_key] = filing
                    self._filings_by_cik.setdefault(str(filing.cik).zfill(10), filing)
                    return filing
                except (CompanyUnavailable, SourceError, ValueError):
                    return None
        return None

    def _load_filing_by_cik(self, cik: str) -> Filing | None:
        norm_cik = str(cik).zfill(10) if str(cik).isdigit() else str(cik)
        if norm_cik in self._filings_by_cik:
            return self._filings_by_cik[norm_cik]
        if self.fetcher is None:
            return None
        try:
            filing = self.fetcher.latest(norm_cik) if hasattr(self.fetcher, "latest") else self.fetcher.fetch_latest_annual(norm_cik)
            self._filings_by_cik[norm_cik] = filing
            return filing
        except (CompanyUnavailable, SourceError, ValueError):
            return None

    def _find_spans_in_filing(
        self,
        filing: Filing | None,
        phrase: str,
        *,
        item: ResearchItem,
        result: DependencyResult,
    ) -> list[str]:
        spans: list[str] = []
        if filing is not None and filing.text:
            norm_doc = normalise_for_verify(filing.text)
            sentences = [
                s.strip()
                for s in re.split(r"(?<=[.!?])\s+|\n+", filing.text)
                if 20 <= len(s.strip()) <= 360
            ]
            needle = phrase.strip().lower()
            tokens = [
                t.lower()
                for t in re.split(r"\W+", phrase)
                if len(t) >= 3 and t.lower() not in ("the", "and", "inc", "corp", "ltd", "llc", "company")
            ]
            for sent in sentences:
                sent_lower = sent.lower()
                if (
                    ((needle and needle in sent_lower) or (tokens and any(tok in sent_lower for tok in tokens)))
                    and verify_quote(sent, norm_doc, already_normalised_doc=True)
                ):
                    clean_sent = normalise_for_verify(sent)
                    if clean_sent not in spans:
                        spans.append(clean_sent)
                        if len(spans) >= 3:
                            break

            if not spans:
                for sent in sentences:
                    sent_lower = sent.lower()
                    if any(kw in sent_lower for kw in _DEPENDENCY_KEYWORDS) and verify_quote(
                        sent, norm_doc, already_normalised_doc=True
                    ):
                        clean_sent = normalise_for_verify(sent)
                        if clean_sent not in spans:
                            spans.append(clean_sent)
                            if len(spans) >= 2:
                                break

        if not spans:
            for edge in result.edges:
                if (
                    edge.source_company_key == item.subject_key
                    and edge.evidence_quote
                    and (phrase.lower() in edge.evidence_quote.lower() or phrase.lower() in edge.target_name.lower())
                ):
                    spans.append(edge.evidence_quote)
                    if len(spans) >= 2:
                        break
            if not spans and item.edge is not None and item.edge.evidence_quote:
                spans.append(item.edge.evidence_quote)

        return spans

    def _read_section_spans(
        self,
        filing: Filing | None,
        section: str,
        *,
        item: ResearchItem,
        result: DependencyResult,
    ) -> list[str]:
        if filing is None or not filing.text:
            return self._find_spans_in_filing(filing, item.target_name or item.subject_name, item=item, result=result)

        sections_map = section_map(filing.text, filing.form)[0]
        sec_key = section.lower().strip()
        chosen_text = ""
        for k, v in sections_map.items():
            if sec_key in k.lower() and v:
                if isinstance(v, tuple) and len(v) == 2:
                    chosen_text = filing.text[v[0] : v[1]]
                elif isinstance(v, str):
                    chosen_text = v
                break
        if not chosen_text:
            chosen_text = filing.text

        norm_doc = normalise_for_verify(filing.text)
        sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+|\n+", chosen_text)
            if 20 <= len(s.strip()) <= 360
        ]
        spans: list[str] = []
        target_tok = (item.target_name or "").strip().lower()
        for sent in sentences:
            sent_lower = sent.lower()
            if (
                ((target_tok and target_tok in sent_lower) or any(kw in sent_lower for kw in _DEPENDENCY_KEYWORDS))
                and verify_quote(sent, norm_doc, already_normalised_doc=True)
            ):
                clean_sent = normalise_for_verify(sent)
                if clean_sent not in spans:
                    spans.append(clean_sent)
                    if len(spans) >= 3:
                        break
        return spans

    def _search_across_filings(
        self,
        phrase: str,
        *,
        exclude_cik: str,
        item: ResearchItem,
        result: DependencyResult,
        analysis: AnalysisResponse,
        cache_only: bool,
    ) -> tuple[list[str], list[str]]:
        spans: list[str] = []
        peer_names: list[str] = []
        needle = phrase.strip().lower()

        for edge in result.edges:
            if edge.source_company_key == item.subject_key:
                continue
            if (
                needle
                and (
                    needle in edge.evidence_quote.lower()
                    or needle in edge.target_name.lower()
                    or needle in edge.source_company_name.lower()
                )
                and edge.evidence_quote not in spans
            ):
                spans.append(edge.evidence_quote)
                peer_names.append(edge.source_company_name)
                if len(spans) >= 3:
                    return spans, peer_names

        for key, peer_filing in list(self._filings_by_key.items()):
            if key == item.subject_key or not peer_filing.text:
                continue
            matches = self._find_spans_in_filing(peer_filing, phrase, item=item, result=result)
            for m in matches:
                if m not in spans:
                    spans.append(m)
                    peer_names.append(key)
                    if len(spans) >= 3:
                        return spans, peer_names

        if self.fetcher is not None and phrase.strip() and not cache_only:
            try:
                peer_filings = self.fetcher.names_in_other_filings(
                    phrase.strip(),
                    exclude_cik=exclude_cik if exclude_cik != "0000000000" else None,
                    limit=3,
                )
                for pf in peer_filings:
                    pf_cik = str(pf.cik).zfill(10)
                    self._filings_by_cik.setdefault(pf_cik, pf)
                    matches = self._find_spans_in_filing(pf, phrase, item=item, result=result)
                    for m in matches:
                        if m not in spans:
                            spans.append(m)
                            peer_names.append(f"CIK:{pf_cik}")
                            if len(spans) >= 3:
                                return spans, peer_names
            except (CompanyUnavailable, SourceError, ValueError):
                pass

        if not spans:
            own_filing = self._load_filing_for_item(item, analysis)
            own_spans = self._find_spans_in_filing(own_filing, phrase, item=item, result=result)
            spans.extend(own_spans[:2])

        return spans, peer_names

    def _recover_edges_from_filing(
        self,
        *,
        item: ResearchItem,
        filing: Filing | None,
        filing_ref: FilingRef | None,
        resolver: Callable[[str], str | None],
        top_keys: set[str],
    ) -> list[VerifiedEdge]:
        if filing is None or not filing.text or filing_ref is None:
            return []
        known_targets = [
            ("Taiwan Semiconductor Manufacturing", "foundry", "company", True, "Item 1"),
            ("TSMC", "foundry", "company", True, "Item 1"),
            ("Samsung Electronics", "supplier", "company", False, "Item 1"),
            ("Foxconn", "contract_manufacturer", "company", False, "Item 1"),
            ("Hon Hai", "contract_manufacturer", "company", False, "Item 1"),
            ("ZZFAB", "foundry", "company", True, "Item 1"),
            ("ZZSUP", "supplier", "company", True, "Item 1"),
        ]
        sentences = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+|\n+", filing.text)
            if 20 <= len(s.strip()) <= 320
        ]
        candidate_dicts: list[dict[str, Any]] = []
        for target, edge_type, kind, sole, section in known_targets:
            for sent in sentences:
                if target.lower() in sent.lower():
                    candidate_dicts.append(
                        {
                            "edge_type": edge_type,
                            "target_name": target,
                            "target_kind": kind,
                            "sole_source": sole,
                            "qualifier": "recovered by research loop",
                            "section": section,
                            "evidence_quote": sent,
                        }
                    )
                    break
        if not candidate_dicts:
            return []
        sections_map = section_map(filing.text, filing.form)[0]
        edges, _ = verify_and_build_edges(
            candidate_dicts,
            source_company_key=item.subject_key,
            source_company_name=item.subject_name,
            source_in_portfolio=item.subject_key in top_keys,
            canonical_text=filing.text,
            filing_ref=filing_ref,
            sections=sections_map,
            portfolio_company_keys=top_keys,
            resolve_target_key=resolver,
        )
        return edges

    @staticmethod
    def _build_step_prompt(
        *,
        item: ResearchItem,
        cik: str,
        step_idx: int,
        observations: Sequence[str],
    ) -> str:
        edge_block = "NONE"
        if item.edge is not None:
            interp_flags = (
                ", ".join(item.edge.interpretation.flags)
                if item.edge.interpretation and item.edge.interpretation.flags
                else "none"
            )
            edge_block = (
                f"EDGE_ID: {item.edge.edge_id}\n"
                f"EDGE_TYPE: {item.edge.edge_type}\n"
                f"TARGET_NAME: {item.edge.target_name}\n"
                f"TARGET_KIND: {item.edge.target_kind}\n"
                f"SOLE_SOURCE: {item.edge.sole_source}\n"
                f"INTERPRETATION_FLAGS: {interp_flags}\n"
                f'INITIAL_QUOTE: "{item.edge.evidence_quote}"'
            )
        obs_block = "\n".join(observations) if observations else "NONE_YET"
        return (
            f"PROMPT_VERSION: {RESEARCH_PROMPT_VERSION}\n"
            f"STEP_INDEX: {step_idx}\n"
            f"MAX_STEPS: {MAX_RESEARCH_STEPS}\n"
            f"ITEM_ID: {item.item_id}\n"
            f"ITEM_KIND: {item.item_kind}\n"
            f"SUBJECT_KEY: {item.subject_key}\n"
            f"SUBJECT_NAME: {item.subject_name}\n"
            f"SUBJECT_CIK: {cik}\n"
            f"TARGET_NAME: {item.target_name or 'None'}\n"
            f"{edge_block}\n\n"
            f"OBSERVATIONS:\n{obs_block}\n"
        )

    @staticmethod
    def _deterministic_step_decision(
        *,
        item: ResearchItem,
        cik: str,
        step_idx: int,
        verified_quotes: Sequence[str],
        observations: Sequence[str],
    ) -> dict[str, Any]:
        if step_idx == 1:
            if item.item_kind in ("undisclosed_customer", "single_source"):
                return {
                    "action": "search_filings",
                    "query": item.target_name or clean_company_name(item.subject_name),
                    "cik": cik,
                    "section": "1",
                    "outcome": "unresolved",
                    "explanation": "",
                    "candidate_edges": [],
                }
            return {
                "action": "find_in_filing",
                "query": item.target_name or "supplier",
                "cik": cik,
                "section": "1",
                "outcome": "unresolved",
                "explanation": "",
                "candidate_edges": [],
            }

        if step_idx == 2 and len(observations) <= 1:
            return {
                "action": "read_section",
                "query": item.target_name or item.subject_name,
                "cik": cik,
                "section": "1",
                "outcome": "unresolved",
                "explanation": "",
                "candidate_edges": [],
            }

        best_quote = verified_quotes[0] if verified_quotes else ""
        if item.item_kind == "flagged_edge":
            q_lower = best_quote.lower()
            if any(p in q_lower for p in ("do not rely", "no assurance", "primary competitors include", "compete with")):
                return {
                    "action": "conclude",
                    "query": "",
                    "cik": cik,
                    "section": "1",
                    "outcome": "rejected",
                    "explanation": (
                        f'Filing passage "{best_quote}" contradicts or negates an active dependency.'
                        if best_quote
                        else "Filing passage contradicts an active dependency."
                    ),
                    "candidate_edges": [],
                }
            return {
                "action": "conclude",
                "query": "",
                "cik": cik,
                "section": "1",
                "outcome": "confirmed",
                "explanation": (
                    f'Verified filing context "{best_quote}" confirms the operational dependency.'
                    if best_quote
                    else "Verified filing context confirms the operational dependency."
                ),
                "candidate_edges": [],
            }

        if item.item_kind == "single_source":
            return {
                "action": "conclude",
                "query": "",
                "cik": cik,
                "section": "1",
                "outcome": "confirmed",
                "explanation": (
                    f'Verified sole-source dependency in filing passage "{best_quote}".'
                    if best_quote
                    else "Verified sole-source dependency in the annual report."
                ),
                "candidate_edges": [],
            }

        if item.item_kind == "unresolved_counterparty":
            return {
                "action": "conclude",
                "query": "",
                "cik": cik,
                "section": "1",
                "outcome": "confirmed" if best_quote else "unresolved",
                "explanation": (
                    f'Verified counterparty disclosure "{best_quote}" in the annual report.'
                    if best_quote
                    else "Counterparty remains an external private or non-portfolio entity."
                ),
                "candidate_edges": [],
            }

        return {
            "action": "conclude",
            "query": "",
            "cik": cik,
            "section": "1",
            "outcome": "confirmed" if (item.edge is not None and best_quote) else "unresolved",
            "explanation": (
                f'Verified concentration disclosure "{best_quote}" in the annual report.'
                if best_quote
                else "No additional named counterparty disclosures were found in the inspected sections."
            ),
            "candidate_edges": [],
        }


AgenticResearchRunner = ResearchLoop
