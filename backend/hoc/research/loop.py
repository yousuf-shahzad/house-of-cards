"""Bounded agentic research loop for House of Cards v3 (package A-RES).

Owner: Kendrick's Gemini (`@kendricklow2008 (Gemini)`).
Rules (docs/hoc/PLAN-v3.md §6 & docs/hoc/CONTRACT.md §8):
- Python selects up to `max_items` (default 6) uncertain items ranked strictly by `importance * exposure`
  (ties broken by `item_id`) across 5 `ResearchItemKind`s (`flagged_edge`, `undisclosed_customer`,
  `single_source`, `no_disclosures`, `unresolved_counterparty`).
- For each item, Gemini runs a bounded multi-step loop (at most `MAX_RESEARCH_STEPS = 4` steps)
  choosing one structured `ResearchAction` per step (`search_filings`, `read_section`,
  `find_in_filing`, `conclude`), and Python executes the filing tools against `FilingFetcher`.
- Every proposed edge in `ResearchFinding.new_edges` must pass `verify_quote` (against `Filing.text`),
  `verify_company_interpretations` (V-INT), and `attach_edge_importance` (R-IMP).
- `_finalize_finding` never marks an edge `confirmed` or `rejected` on its own: interpretation status comes
  only from `verify_edge_interpretation` / `verify_company_interpretations`, and the exact verifier verdict
  is carried into `merge_research_findings`. Unresolved or unclear edges stay `flagged`.
- Every `ResearchFinding.explanation` carries NO numbers except inside `"..."` quotes of verified evidence.
- Findings merge into a new `DependencyResult` (`merge_research_findings`) that updates `edges`,
  `companies`, `counts`, `metrics`, `insights`, and `coverage`.
- Matches the exact `ResearchRunner` protocol in `hoc.jobs`:
  `run(result, analysis, *, max_items, cache_only, progress) -> tuple[list[ResearchFinding], DependencyResult]`.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from hoc.ai.cache import ExtractionCache
from hoc.ai.client import (
    DEFAULT_EXTRACTOR_MODEL,
    GeminiClient,
    GeminiError,
    GeminiMissingKeyError,
)
from hoc.ai.extractor import EXTRACTION_SCHEMA, verify_and_build_edges
from hoc.ai.interpretation import (
    check_interpretation_rules,
    verify_company_interpretations,
    verify_edge_interpretation,
)
from hoc.ai.verifier import find_quote_span, normalise_for_verify, verify_quote
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
    SourceUnavailable,
    VerifiedEdge,
)
from hoc.contract.dependencies import ResearchAction, ResearchItemKind, ResearchOutcome
from hoc.core.cache import DiskCache
from hoc.core.http import CachedResponse, HttpClient
from hoc.filings.fetch import Filing, FilingFetcher
from hoc.filings.names import NameResolver
from hoc.filings.sections import section_map
from hoc.graph.coverage import compute_coverage_report
from hoc.graph.importance import attach_edge_importance, score_edge_importance
from hoc.graph.metrics import compute_dependency_metrics
from hoc.identity.resolver import Aliases, clean_company_name, load_aliases

log = logging.getLogger(__name__)

RESEARCH_PROMPT_VERSION = "hoc-v3-research-1"
RESEARCH_CACHE_NAMESPACE = "research"
MAX_RESEARCH_STEPS = 4
DEFAULT_CALL_TIMEOUT_SECONDS = 45.0
DEFAULT_ITEM_TIMEOUT_SECONDS = 25.0
DEFAULT_TOTAL_TIMEOUT_SECONDS = 90.0

_RECENT_VERIFIED_INTERPRETATIONS: dict[str, EdgeInterpretation] = {}

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
_PERCENT_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent\b)", re.IGNORECASE)
_WORD_GE_10_PERCENT_RE = re.compile(
    r"\b(ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)\s+percent\b",
    re.IGNORECASE,
)


def _call_with_timeout(fn: Callable[[], Any], timeout_s: float) -> Any:
    """Run `fn()` in a single-worker pool bounded by `timeout_s` wall-clock seconds."""
    if timeout_s <= 0:
        raise FuturesTimeoutError("Research budget exhausted before call")
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    except FuturesTimeoutError:
        future.cancel()
        raise
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


class _ClampedHttpxClient:
    """Proxy around `httpx.Client` that clamps per-request `timeout` to `max_timeout_s`."""

    def __init__(self, client: Any, max_timeout_s: float) -> None:
        self._client = client
        self._max_timeout_s = max_timeout_s

    def request(self, method: str, url: str, **kwargs: Any) -> Any:
        req_timeout = kwargs.get("timeout")
        if isinstance(req_timeout, (int, float)):
            kwargs["timeout"] = min(float(req_timeout), self._max_timeout_s)
        else:
            kwargs["timeout"] = self._max_timeout_s
        return self._client.request(method, url, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class _BoundedResearchHttpClient:
    """Wraps an `HttpClient` to cap research transport calls to `timeout_s` (default 45s, never 900s)."""

    def __init__(self, inner: HttpClient, timeout_s: float = DEFAULT_CALL_TIMEOUT_SECONDS) -> None:
        self.timeout_s = max(0.001, float(timeout_s))
        if hasattr(inner, "_client"):
            cloned = copy.copy(inner)
            cloned._client = _ClampedHttpxClient(inner._client, self.timeout_s)  # type: ignore[attr-defined]
            self.inner = cloned
        else:
            self.inner = inner

    def get(
        self,
        url: str,
        *,
        source: str,
        ttl: timedelta | None,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, str] | None = None,
    ) -> CachedResponse:
        try:
            return _call_with_timeout(
                lambda: self.inner.get(url, source=source, ttl=ttl, headers=headers, params=params),
                self.timeout_s,
            )
        except FuturesTimeoutError as exc:
            raise SourceUnavailable(f"Research HTTP GET timed out after {self.timeout_s:.2f}s") from exc

    def post_json(
        self,
        url: str,
        payload: Any,
        *,
        source: str,
        ttl: timedelta | None,
        headers: Mapping[str, str] | None = None,
    ) -> CachedResponse:
        try:
            return _call_with_timeout(
                lambda: self.inner.post_json(url, payload, source=source, ttl=ttl, headers=headers),
                self.timeout_s,
            )
        except FuturesTimeoutError as exc:
            raise SourceUnavailable(f"Research HTTP POST timed out after {self.timeout_s:.2f}s") from exc


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


def _has_material_customer_share(edge: VerifiedEdge) -> bool:
    """Return True iff the edge's qualifier or verified quote states >= 10% customer revenue share."""
    combined = f"{edge.qualifier or ''} {edge.evidence_quote or ''}"
    for match in _PERCENT_NUMBER_RE.finditer(combined):
        try:
            if float(match.group(1)) >= 10.0:
                return True
        except ValueError:
            continue
    return bool(_WORD_GE_10_PERCENT_RE.search(combined))


def _is_unnamed_customer_edge(edge: VerifiedEdge) -> bool:
    is_unnamed = False
    if edge.target_kind == "unnamed_customer":
        is_unnamed = True
    elif edge.edge_type == "customer":
        lower_name = edge.target_name.lower()
        is_unnamed = any(tok in lower_name for tok in _UNNAMED_CUSTOMER_PATTERNS)
    if not is_unnamed:
        return False
    return _has_material_customer_share(edge)


_KIND_PRIORITY: dict[ResearchItemKind, int] = {
    "flagged_edge": 0,
    "undisclosed_customer": 1,
    "no_disclosures": 2,
    "unresolved_counterparty": 3,
    "single_source": 4,
}


def select_research_items(
    result: DependencyResult,
    analysis: AnalysisResponse | None = None,
    *,
    max_items: int = 6,
) -> list[ResearchItem]:
    """Deterministically select and rank up to `max_items` research items (F2).

    Order: kind priority `flagged_edge > undisclosed_customer (>=10%) > no_disclosures >
    unresolved_counterparty > single_source`, then raw `importance * exposure` (no floor or rounding),
    ties by `item_id`, with at most ONE item per `(company, kind)`.
    """
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
        exp = exposure_by_key.get(edge.source_company_key, 0.0)
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
                    priority_score=imp.score * exp,
                    edge=edge,
                    target_name=edge.target_name,
                    cik=cik,
                    filing_ref=edge.filing,
                )
            )
            used_primary_edge_ids.add(edge.edge_id)

    # 2. Undisclosed customers (`target_kind == "unnamed_customer"` or unnamed customer cue with >=10% share)
    for edge in result.edges:
        if edge.edge_id in used_primary_edge_ids:
            continue
        if _is_unnamed_customer_edge(edge):
            imp = edge.importance if edge.importance is not None else score_edge_importance(edge)
            exp = exposure_by_key.get(edge.source_company_key, 0.0)
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
                    priority_score=imp.score * exp,
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
            exp = exposure_by_key.get(edge.source_company_key, 0.0)
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
                    priority_score=imp.score * exp,
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
            exp = float(comp.exposure) if comp.exposure > 0 else exposure_by_key.get(comp.company_key, 0.0)
            cik = cik_by_key.get(comp.company_key) or _extract_cik_from_key(comp.company_key)
            candidates.append(
                ResearchItem(
                    item_id=f"res_nodisc_{comp.company_key}",
                    item_kind="no_disclosures",
                    subject_key=comp.company_key,
                    subject_name=comp.company_name,
                    subject_label=f"{comp.company_name} (no verified disclosures)",
                    question=f"Does {comp.company_name}'s annual report or peer filings contain verifiable dependency disclosures?",
                    priority_score=1.0 * exp,
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
            exp = exposure_by_key.get(edge.source_company_key, 0.0)
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
                    priority_score=imp.score * exp,
                    edge=edge,
                    target_name=edge.target_name,
                    cik=cik,
                    filing_ref=edge.filing,
                )
            )

    candidates.sort(key=lambda item: (_KIND_PRIORITY.get(item.item_kind, 99), -item.priority_score, item.item_id))
    deduped: list[ResearchItem] = []
    seen_company_kind: set[tuple[str, ResearchItemKind]] = set()
    for item in candidates:
        ck = (item.subject_key, item.item_kind)
        if ck in seen_company_kind:
            continue
        seen_company_kind.add(ck)
        deduped.append(item)
        if len(deduped) >= max_items:
            break
    return deduped


def strip_unquoted_numbers(explanation: str, verified_quotes: Sequence[str] = ()) -> str:
    """Ensure `explanation` contains NO digits outside exact `"..."` spans of verified evidence."""
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
        return any(norm_inner in vq for vq in norm_verified)

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
    verified_interpretations: Mapping[str, EdgeInterpretation] | None = None,
    timeout_s: float | None = None,
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
            if not rid:
                continue
            vint_check = (
                (verified_interpretations or {}).get(rid)
                or _RECENT_VERIFIED_INTERPRETATIONS.get(rid)
            )
            if vint_check is not None and vint_check.status != "rejected":
                continue
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
            vint = (
                (verified_interpretations or {}).get(edge.edge_id)
                or _RECENT_VERIFIED_INTERPRETATIONS.get(edge.edge_id)
            )
            if vint is not None and vint.status == "confirmed":
                updated = updated.model_copy(update={"interpretation": vint})
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
        # B2: Missing interpretation is never defaulted to confirmed (treat as unverified -> don't merge)
        if new_edge.interpretation is None or new_edge.interpretation.status == "rejected":
            continue
        rule_flags, _, _ = check_interpretation_rules(new_edge, new_edge.evidence_quote)
        if rule_flags and new_edge.interpretation.method == "rules":
            continue
        target_key = new_edge.target_key
        if target_key is None and resolver is not None and new_edge.target_kind == "company":
            target_key = resolver(new_edge.target_name)
        prepared = new_edge.model_copy(
            update={
                "target_key": target_key,
                "source_company_name": portfolio_names.get(
                    new_edge.source_company_key, new_edge.source_company_name
                ),
                "source_in_portfolio": new_edge.source_company_key in portfolio_keys,
                "target_in_portfolio": target_key is not None and target_key in portfolio_keys,
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
            if timeout_s is not None:
                metrics, insights = _call_with_timeout(
                    lambda: orchestrator.insights(analysis, merged_edges, cache_only=cache_only),
                    timeout_s,
                )
            else:
                metrics, insights = orchestrator.insights(analysis, merged_edges, cache_only=cache_only)
        except Exception:  # noqa: BLE001
            log.info("orchestrator.insights timed out or failed during research merge; using deterministic metrics")
            insights = Insights(status="metrics_only")
            try:
                metrics = compute_dependency_metrics(top_exposures, merged_edges)
            except Exception:
                log.exception("compute_dependency_metrics failed during research merge")
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
            if e.target_kind == "company" and e.target_key is None
        }
    )
    prev_interp_rejected = getattr(result.counts, "interpretation_rejected", 0)
    updated_counts = DependencyCounts(
        companies_requested=result.counts.companies_requested,
        companies_analysed=analysed,
        companies_skipped=result.counts.companies_skipped,
        verified_edges=len(merged_edges),
        rejected_edges=result.counts.rejected_edges,
        interpretation_rejected=prev_interp_rejected + len(rejected_ids),
        unresolved_counterparties=unresolved_count,
    )

    return result.model_copy(
        update={
            "companies": updated_companies,
            "edges": merged_edges,
            "metrics": metrics,
            "insights": insights,
            "counts": updated_counts,
            "coverage": coverage,
        }
    )


def _research_cache_key(result: DependencyResult, max_items: int, prompt_version: str) -> str:
    payload = result.model_dump_json()
    digest = hashlib.sha256(f"{payload}|{max_items}|{prompt_version}".encode()).hexdigest()
    return f"{digest}:{max_items}:{prompt_version}"


class ResearchLoop:
    """Bounded multi-step agentic research runner (`hoc.jobs.ResearchRunner`)."""

    prompt_version: str = RESEARCH_PROMPT_VERSION

    def __init__(
        self,
        *,
        client: Any,
        fetcher: FilingFetcher | None = None,
        edgar: Any = None,
        orchestrator: Any = None,
        cache: ExtractionCache | None = None,
        disk_cache: DiskCache | None = None,
        aliases: Aliases | None = None,
        filings_by_key: Mapping[str, Filing] | None = None,
        filings_by_cik: Mapping[str, Filing] | None = None,
        model: str | None = None,
        max_steps: int = MAX_RESEARCH_STEPS,
        call_timeout_s: float = DEFAULT_CALL_TIMEOUT_SECONDS,
        item_timeout_s: float = DEFAULT_ITEM_TIMEOUT_SECONDS,
        total_timeout_s: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
    ) -> None:
        self.client = client
        self.fetcher = fetcher
        self.edgar = edgar
        self.orchestrator = orchestrator
        self.cache = cache
        self._disk_cache: DiskCache | None = (
            disk_cache or getattr(cache, "disk_cache", None) or getattr(cache, "cache", None)
        )
        self._replay_cache: dict[str, tuple[list[ResearchFinding], DependencyResult]] = {}
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
        self.call_timeout_s = max(0.001, float(call_timeout_s))
        self.item_timeout_s = max(0.001, float(item_timeout_s))
        self.total_timeout_s = max(0.001, float(total_timeout_s))

    @classmethod
    def from_settings(cls, http: HttpClient, settings: Any) -> ResearchLoop:
        """Construct a production `ResearchLoop` from `HttpClient` and `Settings`."""
        from hoc.graph import DependencyOrchestrator

        bounded_http = _BoundedResearchHttpClient(http, timeout_s=DEFAULT_CALL_TIMEOUT_SECONDS)
        disk_cache = DiskCache(settings.cache_dir)
        client = GeminiClient(bounded_http, settings)
        cache = ExtractionCache(disk_cache)
        fetcher = FilingFetcher(bounded_http, settings)
        aliases = load_aliases()
        orchestrator = DependencyOrchestrator(http=bounded_http, settings=settings)
        return cls(
            client=client,
            fetcher=fetcher,
            edgar=None,
            orchestrator=orchestrator,
            cache=cache,
            disk_cache=disk_cache,
            aliases=aliases,
        )

    def _get_cached_run(self, cache_key: str) -> tuple[list[ResearchFinding], DependencyResult] | None:
        if cache_key in self._replay_cache:
            cached_findings, cached_result = self._replay_cache[cache_key]
            return list(cached_findings), cached_result
        if self._disk_cache is not None:
            entry = self._disk_cache.get(RESEARCH_CACHE_NAMESPACE, cache_key)
            if entry is not None:
                try:
                    data = json.loads(entry.body.decode("utf-8"))
                    findings = [ResearchFinding.model_validate(f) for f in data.get("findings", [])]
                    merged = DependencyResult.model_validate(data["result"])
                    self._replay_cache[cache_key] = (findings, merged)
                    return list(findings), merged
                except Exception:  # noqa: BLE001
                    log.warning("Failed to deserialize cached research result for %s", cache_key)
        return None

    def _put_cached_run(
        self,
        cache_key: str,
        findings: list[ResearchFinding],
        merged: DependencyResult,
    ) -> None:
        self._replay_cache[cache_key] = (list(findings), merged)
        if self._disk_cache is not None:
            try:
                payload = {
                    "findings": [f.model_dump(mode="json") for f in findings],
                    "result": merged.model_dump(mode="json"),
                }
                body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                self._disk_cache.put(
                    RESEARCH_CACHE_NAMESPACE,
                    cache_key,
                    body,
                    {"prompt_version": self.prompt_version},
                )
            except Exception:  # noqa: BLE001
                log.warning("Failed to write research result to disk cache for %s", cache_key)

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
        cache_key = _research_cache_key(result, max_items, self.prompt_version)
        cached_pair = self._get_cached_run(cache_key)
        if cached_pair is not None:
            cached_findings, cached_merged = cached_pair
            total = len(cached_findings)
            if progress is not None:
                progress(0, total, [])
            for idx, finding in enumerate(cached_findings, start=1):
                if on_finding is not None:
                    on_finding(finding)
                if progress is not None:
                    progress(idx, total, list(cached_findings[:idx]))
            return cached_findings, cached_merged

        items = select_research_items(result, analysis, max_items=max_items)
        total = len(items)
        findings: list[ResearchFinding] = []
        if progress is not None:
            progress(0, total, [])

        aliases = self.aliases if self.aliases is not None else load_aliases()
        resolver = NameResolver(analysis.exposures, aliases).resolve
        top_keys = {c.company_key for c in analysis.exposures if c.exposure > 0}

        # F1 / Repro 6: on a cache_only miss, items stay 'unresolved'; never fabricate a completed investigation.
        if cache_only:
            for idx, item in enumerate(items, start=1):
                finding = ResearchFinding(
                    finding_id=item.item_id,
                    kind=item.item_kind,
                    subject=item.subject_label,
                    question=item.question,
                    outcome="unresolved",
                    explanation="No cached research result was found in cache_only mode.",
                    steps=[
                        ResearchStep(
                            index=1,
                            action="conclude",
                            query=item.target_name or item.subject_name,
                            summary="Skipped live investigation because cache_only mode was requested.",
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
                cache_only=True,
                timeout_s=self.total_timeout_s,
            )
            return findings, merged

        started = time.monotonic()
        verified_interps: dict[str, EdgeInterpretation] = {}
        for idx, item in enumerate(items, start=1):
            elapsed = time.monotonic() - started
            if elapsed >= self.total_timeout_s:
                finding = self._timeout_finding(item)
            else:
                try:
                    finding = self._investigate_item(
                        item=item,
                        result=result,
                        analysis=analysis,
                        resolver=resolver,
                        top_keys=top_keys,
                        cache_only=cache_only,
                        run_started=started,
                        verified_interpretations=verified_interps,
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

        rem_total = max(0.0, self.total_timeout_s - (time.monotonic() - started))
        merged = merge_research_findings(
            result,
            analysis,
            findings,
            orchestrator=self.orchestrator,
            resolver=resolver,
            cache_only=cache_only,
            verified_interpretations=verified_interps,
            timeout_s=min(self.call_timeout_s, rem_total),
        )
        self._put_cached_run(cache_key, findings, merged)
        return findings, merged

    # ---------- per-item investigation ----------

    @staticmethod
    def _timeout_finding(item: ResearchItem) -> ResearchFinding:
        return ResearchFinding(
            finding_id=item.item_id,
            kind=item.item_kind,
            subject=item.subject_label,
            question=item.question,
            outcome="unresolved",
            explanation="Research wall-clock budget reached before completing verification.",
            steps=[
                ResearchStep(
                    index=1,
                    action="conclude",
                    query=item.target_name or item.subject_name,
                    summary="Skipped remaining steps because the research time budget was reached.",
                    filing=item.filing_ref,
                )
            ],
        )

    def _remaining_budget(self, *, run_started: float, item_started: float) -> float:
        rem_total = self.total_timeout_s - (time.monotonic() - run_started)
        rem_item = self.item_timeout_s - (time.monotonic() - item_started)
        return min(self.call_timeout_s, rem_total, rem_item)

    def _investigate_item(
        self,
        *,
        item: ResearchItem,
        result: DependencyResult,
        analysis: AnalysisResponse,
        resolver: Callable[[str], str | None],
        top_keys: set[str],
        cache_only: bool,
        run_started: float,
        verified_interpretations: dict[str, EdgeInterpretation],
    ) -> ResearchFinding:
        item_started = time.monotonic()
        init_budget = self._remaining_budget(run_started=run_started, item_started=item_started)
        if init_budget <= 0:
            return self._timeout_finding(item)
        try:
            filing = _call_with_timeout(
                lambda: self._load_filing_for_item(item, analysis),
                init_budget,
            )
        except FuturesTimeoutError:
            return self._timeout_finding(item)

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

        concluded_payload: Mapping[str, Any] | None = None
        timed_out_or_failed = False

        for step_idx in range(1, self.max_steps + 1):
            budget = self._remaining_budget(run_started=run_started, item_started=item_started)
            if budget <= 0:
                timed_out_or_failed = True
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
                    raw_resp, _ = _call_with_timeout(
                        lambda p=prompt: self.client.generate_json(
                            p,
                            RESEARCH_STEP_SCHEMA,
                            model=self.model,
                            system_instruction=RESEARCH_SYSTEM_PROMPT,
                            thinking_level="low",
                        ),
                        budget,
                    )
                    if isinstance(raw_resp, Mapping):
                        step_decision = raw_resp
                except FuturesTimeoutError:
                    log.info("Gemini research step %d timed out after %.3fs", step_idx, budget)
                    timed_out_or_failed = True
                    break
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
                    has_api_key=has_key,
                )

            action_raw = str(step_decision.get("action", "conclude")).strip()
            action: ResearchAction = (
                action_raw  # type: ignore[assignment]
                if action_raw in ("search_filings", "read_section", "find_in_filing", "conclude")
                else "conclude"
            )

            if action == "conclude":
                concluded_payload = step_decision
                break

            tool_budget = self._remaining_budget(run_started=run_started, item_started=item_started)
            if tool_budget <= 0:
                timed_out_or_failed = True
                break
            try:
                _call_with_timeout(
                    lambda act=action, dec=step_decision: self._execute_tool_step(
                        action=act,
                        decision=dec,
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
                    ),
                    tool_budget,
                )
            except FuturesTimeoutError:
                timed_out_or_failed = True
                break

        if timed_out_or_failed and concluded_payload is None:
            concluded_payload = {
                "action": "conclude",
                "query": item.target_name or item.subject_name,
                "outcome": "unresolved",
                "explanation": "Research step budget expired before completing verification.",
                "candidate_edges": [],
            }

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
            run_started=run_started,
            item_started=item_started,
            verified_interpretations=verified_interpretations,
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
        run_started: float,
        item_started: float,
        verified_interpretations: dict[str, EdgeInterpretation],
    ) -> ResearchFinding:
        has_key = bool(getattr(self.client, "has_api_key", True))
        if concluded_payload is None:
            concluded_payload = self._deterministic_step_decision(
                item=item,
                cik=cik,
                step_idx=self.max_steps,
                verified_quotes=verified_quotes,
                observations=[f'OBSERVED_QUOTE: "{q}"' for q in verified_quotes],
                has_api_key=has_key,
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
                budget = self._remaining_budget(run_started=run_started, item_started=item_started)
                if budget > 0:
                    try:
                        interp_res = _call_with_timeout(
                            lambda: verify_company_interpretations(
                                [e.model_copy(update={"interpretation": None}) for e in built_edges],
                                filing.text,
                                client=self.client,
                                cache=self.cache,
                                cache_only=cache_only,
                                sample_rate=1.0,
                            ),
                            budget,
                        )
                        # B2: Only keep edges with a confirmed interpretation from V-INT
                        confirmed_built = [
                            e
                            for e in interp_res.edges
                            if e.interpretation is not None and e.interpretation.status == "confirmed"
                        ]
                        verified_new_edges = attach_edge_importance(confirmed_built)
                        for ve in verified_new_edges:
                            if ve.evidence_quote not in verified_quotes:
                                verified_quotes.append(ve.evidence_quote)
                    except FuturesTimeoutError:
                        log.info("V-INT on candidate_edges timed out")

        # F4: A candidate edge in new_edges whose edge_id (or identical source/target/type/accession)
        # already exists in result.edges counts as confirmed, not new_evidence.
        existing_by_id: dict[str, VerifiedEdge] = {e.edge_id: e for e in result.edges}
        existing_by_tuple: dict[tuple[str, str, str, str], VerifiedEdge] = {
            (
                e.source_company_key,
                e.target_key or e.target_name.strip().casefold(),
                e.edge_type,
                e.filing.accession,
            ): e
            for e in result.edges
        }
        existing_by_name_tuple: dict[tuple[str, str, str, str], VerifiedEdge] = {
            (
                e.source_company_key,
                e.target_name.strip().casefold(),
                e.edge_type,
                e.filing.accession,
            ): e
            for e in result.edges
        }
        refound_existing_ids: list[str] = []
        if verified_new_edges:
            truly_new_edges: list[VerifiedEdge] = []
            for ve in verified_new_edges:
                tup = (
                    ve.source_company_key,
                    ve.target_key or ve.target_name.strip().casefold(),
                    ve.edge_type,
                    ve.filing.accession,
                )
                name_tup = (
                    ve.source_company_key,
                    ve.target_name.strip().casefold(),
                    ve.edge_type,
                    ve.filing.accession,
                )
                matched_existing = (
                    existing_by_id.get(ve.edge_id)
                    or existing_by_tuple.get(tup)
                    or existing_by_name_tuple.get(name_tup)
                )
                if matched_existing is not None:
                    eid = matched_existing.edge_id
                    if eid not in refound_existing_ids:
                        refound_existing_ids.append(eid)
                    if ve.interpretation is not None and ve.interpretation.status == "confirmed":
                        verified_interpretations[eid] = ve.interpretation
                        _RECENT_VERIFIED_INTERPRETATIONS[eid] = ve.interpretation
                else:
                    truly_new_edges.append(ve)
            verified_new_edges = truly_new_edges

        confirmed_edge_ids: list[str] = []
        rejected_edge_ids: list[str] = []

        if item.item_kind == "flagged_edge" and item.edge is not None:
            edge = item.edge
            doc_text = filing.text if filing is not None else edge.evidence_quote
            budget = self._remaining_budget(run_started=run_started, item_started=item_started)
            vint_interp: EdgeInterpretation | None = None
            if budget > 0:
                try:
                    vint_interp = _call_with_timeout(
                        lambda: verify_edge_interpretation(
                            edge.model_copy(update={"interpretation": None}),
                            doc_text,
                            client=self.client,
                            cache=self.cache,
                            cache_only=cache_only,
                        ),
                        budget,
                    )
                except FuturesTimeoutError:
                    vint_interp = None

            if vint_interp is not None:
                verified_interpretations[edge.edge_id] = vint_interp
                _RECENT_VERIFIED_INTERPRETATIONS[edge.edge_id] = vint_interp

            # B1 + Codex second review (1 & 2):
            # - Rejection is gated strictly on vint_interp.status == "rejected"; a research conclusion alone
            #   must never delete an edge supported by V-INT.
            # - Confirmation requires both vint_interp.status == "confirmed" and outcome in ("confirmed", "revised"),
            #   and carries the exact verifier verdict into merge_research_findings.
            if outcome == "unresolved" or vint_interp is None:
                outcome = "unresolved"
                if not raw_explanation:
                    raw_explanation = (
                        f'Filing context for "{edge.evidence_quote}" remains ambiguous or unresolved.'
                    )
            elif vint_interp.status == "rejected":
                outcome = "rejected"
                rejected_edge_ids = [edge.edge_id]
                if not raw_explanation:
                    raw_explanation = (
                        f'Filing context "{edge.evidence_quote}" does not support an active supply dependency.'
                    )
            elif vint_interp.status == "confirmed" and (
                outcome in ("confirmed", "revised") or edge.edge_id in refound_existing_ids
            ):
                outcome = "confirmed"
                confirmed_edge_ids = [edge.edge_id]
                if not raw_explanation:
                    raw_explanation = (
                        f'Verified filing context "{edge.evidence_quote}" confirms the operational dependency.'
                    )
            else:
                outcome = "unresolved"
                if not raw_explanation:
                    raw_explanation = (
                        f'Filing context "{edge.evidence_quote}" remains flagged after verification.'
                    )

        elif item.item_kind == "single_source" and item.edge is not None:
            edge = item.edge
            edge_is_confirmed = edge.interpretation is not None and edge.interpretation.status == "confirmed"
            if verified_new_edges:
                outcome = "new_evidence"
                if edge_is_confirmed:
                    confirmed_edge_ids = [edge.edge_id]
            elif (
                refound_existing_ids
                or (verified_quotes and outcome in ("confirmed", "revised") and edge_is_confirmed)
            ):
                outcome = "confirmed"
                if edge_is_confirmed and edge.edge_id not in confirmed_edge_ids:
                    confirmed_edge_ids.append(edge.edge_id)
                if not raw_explanation and verified_quotes:
                    raw_explanation = (
                        f'Verified sole-source disclosure "{verified_quotes[0]}" in the annual report.'
                    )
            else:
                outcome = "unresolved"

        elif item.item_kind == "unresolved_counterparty" and item.edge is not None:
            edge = item.edge
            edge_is_confirmed = edge.interpretation is not None and edge.interpretation.status == "confirmed"
            resolved_key = resolver(edge.target_name)
            if resolved_key is not None and outcome != "unresolved":
                outcome = "revised"
                if edge_is_confirmed:
                    confirmed_edge_ids = [edge.edge_id]
                if not raw_explanation:
                    raw_explanation = (
                        f'Resolved counterparty identity for "{edge.evidence_quote}" against portfolio records.'
                    )
            elif (
                refound_existing_ids
                or (verified_quotes and outcome in ("confirmed", "revised") and edge_is_confirmed)
            ):
                outcome = "confirmed"
                if edge_is_confirmed and edge.edge_id not in confirmed_edge_ids:
                    confirmed_edge_ids.append(edge.edge_id)
                if not raw_explanation and verified_quotes:
                    raw_explanation = (
                        f'Verified external counterparty disclosure "{verified_quotes[0]}" in the filing.'
                    )
            else:
                outcome = "unresolved"

        elif item.item_kind in ("no_disclosures", "undisclosed_customer"):
            if verified_new_edges:
                outcome = "new_evidence"
                if not raw_explanation:
                    raw_explanation = (
                        f'Extracted verified dependency disclosure "{verified_new_edges[0].evidence_quote}".'
                    )
            elif refound_existing_ids or (
                item.edge is not None
                and verified_quotes
                and outcome in ("confirmed", "revised")
                and item.edge.interpretation is not None
                and item.edge.interpretation.status == "confirmed"
            ):
                outcome = "confirmed"
                if (
                    item.edge is not None
                    and item.edge.interpretation is not None
                    and item.edge.interpretation.status == "confirmed"
                    and item.edge.edge_id not in confirmed_edge_ids
                ):
                    confirmed_edge_ids.append(item.edge.edge_id)
                if not raw_explanation and verified_quotes:
                    raw_explanation = (
                        f'Confirmed customer concentration disclosure "{verified_quotes[0]}" in the filing.'
                    )
            else:
                outcome = "unresolved"
                if not raw_explanation:
                    raw_explanation = (
                        "Filing leaves specific counterparty identities undisclosed in the inspected sections."
                    )

        for refound_id in refound_existing_ids:
            if refound_id not in rejected_edge_ids and refound_id not in confirmed_edge_ids:
                confirmed_edge_ids.append(refound_id)

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
            filing = (
                self.fetcher.latest(norm_cik)
                if hasattr(self.fetcher, "latest")
                else self.fetcher.fetch_latest_annual(norm_cik)
            )
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
            raw_sentences = [
                normalise_for_verify(s).strip()
                for s in re.split(r"(?<=[.!?])\s+|\n+", filing.text)
                if normalise_for_verify(s).strip()
                and not re.match(r"^item\s+\d+[a-z]?\b", normalise_for_verify(s).strip(), re.IGNORECASE)
            ]
            needle = normalise_for_verify(phrase).strip().casefold()
            tokens = [
                t.casefold()
                for t in re.split(r"\W+", phrase)
                if len(t) >= 3 and t.casefold() not in ("the", "and", "inc", "corp", "ltd", "llc", "company")
            ]

            for idx, sent in enumerate(raw_sentences):
                sent_cf = sent.casefold()
                has_match = (needle and needle in sent_cf) or (
                    tokens and any(tok in sent_cf for tok in tokens)
                )
                if not has_match:
                    continue

                # F3: Return the sentence containing the queried phrase (verified via find_quote_span)
                # along with ±1 sentence of surrounding context.
                prev_s = raw_sentences[idx - 1] if idx > 0 else ""
                next_s = raw_sentences[idx + 1] if idx + 1 < len(raw_sentences) else ""
                candidates = [
                    sent,
                    " ".join(p for p in (prev_s, sent, next_s) if p),
                    " ".join(p for p in (sent, next_s) if p),
                    " ".join(p for p in (prev_s, sent) if p),
                ]
                added_for_idx = 0
                for cand in candidates:
                    if (
                        20 <= len(cand) <= 360
                        and find_quote_span(cand, norm_doc, already_normalised_doc=True) is not None
                        and verify_quote(cand, norm_doc, already_normalised_doc=True)
                        and cand not in spans
                    ):
                        spans.append(cand)
                        added_for_idx += 1
                        if added_for_idx >= 2 or len(spans) >= 3:
                            break
                if added_for_idx == 0 and len(sent) > 360:
                    pos = sent_cf.find(needle) if needle and needle in sent_cf else 0
                    win_start = max(0, pos - 120)
                    win_end = min(len(sent), win_start + 300)
                    window = sent[win_start:win_end].strip()
                    if (
                        20 <= len(window) <= 360
                        and find_quote_span(window, norm_doc, already_normalised_doc=True) is not None
                        and verify_quote(window, norm_doc, already_normalised_doc=True)
                        and window not in spans
                    ):
                        spans.append(window)
                if len(spans) >= 3:
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
        has_api_key: bool = True,
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

        if not has_api_key:
            return {
                "action": "conclude",
                "query": "",
                "cik": cik,
                "section": "1",
                "outcome": "unresolved",
                "explanation": "Gemini API key is not configured for live research synthesis.",
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
