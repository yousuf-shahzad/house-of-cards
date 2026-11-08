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
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

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
    CompanyExposure,
    CompanyRunStatus,
    CompanyUnavailable,
    Concentration,
    Coverage,
    DependencyCounts,
    DependencyRequest,
    DependencyResult,
    EdgeInterpretation,
    FilingRef,
    Insights,
    Overlap,
    PortfolioItem,
    PortfolioRequest,
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

RESEARCH_PROMPT_VERSION = "hoc-v3.1-research-2"
RESEARCH_CACHE_NAMESPACE = "research"
RESEARCH_COMPANY_CACHE_NAMESPACE = "research_company"
MAX_RESEARCH_STEPS = 4
DEFAULT_CALL_TIMEOUT_SECONDS = 45.0
DEFAULT_ITEM_TIMEOUT_SECONDS = 40.0
DEFAULT_TOTAL_TIMEOUT_SECONDS = 90.0
DEFAULT_INSIGHTS_TIMEOUT_SECONDS = 75.0

ResearchDepthOption = Literal["none", "light", "thorough"]
RESEARCH_DEPTH_PRESETS: dict[str, tuple[int, int]] = {
    "none": (0, 0),
    "light": (2, 3),
    "thorough": (4, 4),
}
RESEARCH_DEPTH_TIMEOUT_SECONDS: dict[str, float] = {
    "none": 0.0,
    "light": 40.0,
    "thorough": 85.0,
}

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
- `conclude`: finish the investigation ONLY after completing at least `MIN_TOOL_CALLS` tool steps (and at least one `search_filings` step when `REQUIRE_SEARCH_FILINGS: true`), unless a tool step already found a direct rejection/contradiction.

STRICT GROUNDING RULES WHEN CONCLUDING (`action == "conclude"`):
1. `outcome` MUST be one of: `"confirmed"`, `"revised"`, `"rejected"`, `"new_evidence"`, `"unresolved"`.
2. Re-finding only the initial extraction quote (`INITIAL_QUOTE`) in the same filing is NOT a confirmation; confirming requires a different passage in the filing or another company's filing via `search_filings`. Otherwise choose `"unresolved"`.
3. `explanation` MUST NOT contain ANY numbers or percentages outside double-quoted (`"..."`) verbatim passages from the observed filing text.
4. Every item in `candidate_edges` MUST have an `evidence_quote` (20-400 characters) copied character-for-character from an observed filing passage, and MUST refer to a single counterparty or single unnamed customer (never a plural group like "three largest customers" or "five distributors").
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


@dataclass(frozen=True)
class CompanyResearch:
    """Per-company agentic research result for v3.1 (A1 <-> A2/A3 seam)."""

    findings: list[ResearchFinding]
    edges: list[VerifiedEdge]
    rejected_edge_ids: list[str]
    cached: bool = False
    steps_done: int = 0
    steps_total: int = 0
    interpretation_rejected: int = 0
    rejected: int = 0
    quality: Literal["sections", "fallback"] | None = None
    model: str | None = None


CompanyResearchResult = CompanyResearch


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


_ALREADY_UNNAMED_RE = re.compile(r"^unnamed\s+customer(?:\s*\((.+)\))?$", re.IGNORECASE)
_ANONYMISED_CUSTOMER_LABEL_RE = re.compile(
    r"^(?:"
    r"(?:end\s+|direct\s+|major\s+|top\s+)?(?:customer|client|distributor|reseller|channel\s+partner)\s*(?:[a-z0-9#]+|one|two|three|alpha|beta|gamma)"
    r"|"
    r"(?:a|an|one|single|the)?\s*"
    r"(?:single\s+|sole\s+|major\s+|largest\s+|significant\s+|primary\s+|principal\s+|individual\s+|unnamed\s+|undisclosed\s+|direct\s+|indirect\s+|channel\s+)*"
    r"(?:customer|client|distributor|reseller|partner)"
    r")$",
    re.IGNORECASE,
)
_CUSTOMER_GROUP_RE = re.compile(
    r"\b(?:"
    r"(?:two|three|four|five|six|seven|eight|nine|ten|multiple|several|various|numerous|certain|many|group\s+of|top|[2-9]|\d{2,})\s+"
    r"(?:[\w\-]+\s+){0,4}(?:customers|clients|distributors|resellers|partners|suppliers|vendors|accounts)"
    r"|"
    r"(?:customers|clients|distributors|resellers)"
    r")\b",
    re.IGNORECASE,
)
_CORROBORATION_STOP_WORDS = frozenset({
    "inc",
    "corp",
    "corporation",
    "ltd",
    "limited",
    "llc",
    "plc",
    "company",
    "companies",
    "the",
    "and",
    "group",
    "organization",
    "organizations",
    "partner",
    "partners",
    "supplier",
    "suppliers",
    "vendor",
    "vendors",
    "customer",
    "customers",
    "client",
    "clients",
    "distributor",
    "distributors",
    "third",
    "party",
    "parties",
    "various",
    "certain",
    "other",
    "multiple",
    "unnamed",
    "undisclosed",
    "single",
    "sole",
    "major",
    "largest",
    "primary",
})


def _is_customer_group_target(target_name: str | None) -> bool:
    """Return True if `target_name` refers to a multi-entity group of customers/distributors (FIX-14)."""
    if not target_name:
        return False
    cleaned = normalise_for_verify(target_name).strip()
    if not cleaned:
        return False
    already = _ALREADY_UNNAMED_RE.match(cleaned)
    inner = (already.group(1) or "").strip() if already else cleaned
    return bool(_CUSTOMER_GROUP_RE.search(inner))


def _is_same_as_initial_quote(span: str, initial_quote: str | None) -> bool:
    """Return True if `span` is merely the edge's own initial quote (or contained in / containing it)."""
    if not span or not initial_quote:
        return False
    norm_span = normalise_for_verify(span).strip().casefold()
    norm_init = normalise_for_verify(initial_quote).strip().casefold()
    if not norm_span or not norm_init:
        return False
    return norm_span == norm_init or norm_span in norm_init or norm_init in norm_span


def _corroboration_tokens(target_name: str | None) -> list[str]:
    if not target_name:
        return []
    norm = normalise_for_verify(target_name).casefold()
    return [
        t
        for t in re.split(r"[^a-z0-9]+", norm)
        if len(t) >= 3 and t not in _CORROBORATION_STOP_WORDS
    ]


def _span_mentions_target(span: str, target_name: str | None) -> bool:
    tokens = _corroboration_tokens(target_name)
    if not tokens:
        return False
    span_cf = normalise_for_verify(span).casefold()
    return any(tok in span_cf for tok in tokens)


def _span_corroborates_item(
    span: str,
    *,
    item: ResearchItem,
    initial_quote: str | None,
    from_other_filing: bool,
) -> bool:
    """Return True iff `span` is non-circular corroboration (different passage in filing or peer filing)."""
    if not span or not span.strip():
        return False
    if from_other_filing:
        return True
    if _is_same_as_initial_quote(span, initial_quote):
        return False
    if item.item_kind in ("no_disclosures", "undisclosed_customer"):
        span_cf = span.casefold()
        return any(kw in span_cf for kw in _DEPENDENCY_KEYWORDS) or bool(_PERCENT_NUMBER_RE.search(span))
    target = item.target_name or (item.edge.target_name if item.edge is not None else None)
    return _span_mentions_target(span, target)


def _format_anonymised_customer_target(target_name: str) -> str | None:
    """If `target_name` is an anonymised customer/distributor label (Q2), return
    `'Unnamed customer (<label>)'` (or `'Unnamed customer'`), else `None`.
    """
    cleaned = normalise_for_verify(target_name).strip()
    if not cleaned or _is_customer_group_target(cleaned):
        return None
    already = _ALREADY_UNNAMED_RE.match(cleaned)
    if already:
        inner = (already.group(1) or "").strip()
        if _is_customer_group_target(inner):
            return None
        return f"Unnamed customer ({inner})" if inner else "Unnamed customer"
    if _ANONYMISED_CUSTOMER_LABEL_RE.match(cleaned):
        if cleaned.casefold() in ("unnamed customer", "undisclosed customer"):
            return "Unnamed customer"
        return f"Unnamed customer ({cleaned})"
    return None


def _normalise_candidate_dict_for_q2(cand: Mapping[str, Any]) -> dict[str, Any]:
    """Rewrite anonymised customer labels in raw candidate dicts to `unnamed_customer` (Q2) and drop customer groups (FIX-14)."""
    out = dict(cand)
    raw_target = str(out.get("target_name") or out.get("object_name_as_written") or "").strip()
    raw_quote = str(out.get("evidence_quote") or "").strip()
    if _is_customer_group_target(raw_target):
        out["evidence_quote"] = ""
        return out
    anon_name = _format_anonymised_customer_target(raw_target)
    if anon_name is not None:
        norm_quote_cf = normalise_for_verify(raw_quote).casefold()
        already = _ALREADY_UNNAMED_RE.match(normalise_for_verify(raw_target).strip())
        inner_label = (already.group(1) or "").strip() if already else raw_target
        if (
            inner_label
            and inner_label.casefold() not in ("unnamed customer", "undisclosed customer")
            and normalise_for_verify(inner_label).casefold() not in norm_quote_cf
        ):
            out["evidence_quote"] = ""
            return out
        out["target_name"] = anon_name
        out["target_kind"] = "unnamed_customer"
        out["edge_type"] = "customer"
        raw_qual = str(out.get("qualifier") or "").strip()
        if not raw_qual:
            out["qualifier"] = raw_target
    return out


def _normalise_anonymised_customer_edge(edge: VerifiedEdge) -> VerifiedEdge:
    """Ensure any edge with an anonymised customer target has `target_kind='unnamed_customer'`,
    `target_name='Unnamed customer (<label>)'`, and `target_key=None` (Q2).
    """
    anon_name = _format_anonymised_customer_target(edge.target_name)
    if anon_name is None and edge.target_kind != "unnamed_customer":
        return edge
    final_name = anon_name or edge.target_name
    return edge.model_copy(
        update={
            "target_name": final_name,
            "target_kind": "unnamed_customer",
            "edge_type": "customer",
            "target_key": None,
            "target_in_portfolio": False,
        }
    )


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


_BUDGET_STOP_CUES: tuple[str, ...] = (
    "not finished in time",
    "step budget expired",
    "time budget reached",
    "time budget was reached",
    "wall-clock budget reached",
)


def _is_budget_stopped_finding(finding: ResearchFinding) -> bool:
    """Return True if `finding` stopped early because a step or wall-clock budget expired (FIX-22)."""
    if finding.outcome != "unresolved":
        return False
    exp_low = (finding.explanation or "").lower()
    if any(cue in exp_low for cue in _BUDGET_STOP_CUES):
        return True
    if finding.steps:
        last_sum = (finding.steps[-1].summary or "").lower()
        if any(cue in last_sum for cue in _BUDGET_STOP_CUES):
            return True
    return False


_CONTRADICTORY_PROSE_BY_OUTCOME: dict[str, tuple[str, ...]] = {
    "unresolved": (
        "is rejected",
        "was rejected",
        "be rejected",
        "are rejected",
        "reject this",
        "reject the",
        "rejected as",
        "rejected because",
        "should be rejected",
        "must be rejected",
        "does not establish",
        "should not be recorded",
        "cannot be recorded",
        "not an active",
        "not an established",
        "contradicts an active",
        "contradicts the",
        "does not support an active",
        "is confirmed",
        "was confirmed",
        "confirms the",
        "corroborates the",
    ),
    "confirmed": (
        "is rejected",
        "was rejected",
        "be rejected",
        "remains unresolved",
        "remains uncorroborated",
        "remains ambiguous",
        "could not confirm",
        "unable to confirm",
        "not finished in time",
        "contradicts an active",
        "does not establish",
        "should not be recorded",
    ),
    "revised": (
        "is rejected",
        "was rejected",
        "remains unresolved",
        "not finished in time",
    ),
    "rejected": (
        "is confirmed",
        "was confirmed",
        "confirms the operational",
        "corroborates the",
        "remains unresolved",
        "not finished in time",
    ),
    "new_evidence": (
        "is rejected",
        "was rejected",
        "remains unresolved",
        "no additional",
        "leaves specific counterparty identities undisclosed",
        "not finished in time",
    ),
}


def _explanation_matches_outcome(explanation: str, outcome: ResearchOutcome) -> bool:
    """Return True if the unquoted prose of `explanation` does not contradict `outcome` (FIX-22)."""
    if not explanation or not explanation.strip():
        return False
    unquoted = re.sub(r'"[^"]*"', " ", explanation).lower()
    unquoted = re.sub(r"\s+", " ", unquoted)
    forbidden = _CONTRADICTORY_PROSE_BY_OUTCOME.get(outcome, ())
    return not any(phrase in unquoted for phrase in forbidden)


def _format_budget_stop_text(text: str, default_body: str = "research step budget expired before completing verification.") -> str:
    """Ensure budget-stopped explanations and summaries begin with `'Not finished in time: ...'` (FIX-22)."""
    stripped = (text or "").strip()
    if not stripped:
        return f"Not finished in time: {default_body}"
    if stripped.lower().startswith("not finished in time"):
        return stripped
    lowered_first = stripped[0].lower() + stripped[1:] if len(stripped) > 1 else stripped.lower()
    return f"Not finished in time: {lowered_first}"


def _sanitize_finding(finding: ResearchFinding) -> ResearchFinding:
    """Normalize budget-stopped labels and fix any outcome/explanation mismatch on `finding` (FIX-22)."""
    if _is_budget_stopped_finding(finding):
        new_exp = _format_budget_stop_text(finding.explanation)
        new_steps = list(finding.steps)
        if new_steps and new_steps[-1].action == "conclude":
            last_s = new_steps[-1]
            new_steps[-1] = last_s.model_copy(
                update={
                    "summary": _format_budget_stop_text(
                        last_s.summary if any(c in (last_s.summary or "").lower() for c in _BUDGET_STOP_CUES) else new_exp
                    )
                }
            )
        if new_exp != finding.explanation or new_steps != finding.steps:
            return finding.model_copy(update={"explanation": new_exp, "steps": new_steps})
        return finding

    if _explanation_matches_outcome(finding.explanation, finding.outcome):
        return finding

    quotes = re.findall(r'"([^"]+)"', finding.explanation or "")
    first_quote = quotes[0] if quotes else ""
    if finding.outcome == "unresolved":
        new_exp = (
            f'Filing passage "{first_quote}" uses conditional or uncorroborated wording, so the relationship remains unresolved.'
            if first_quote
            else "Filing context remains ambiguous or uncorroborated in the inspected sections, so the item remains unresolved."
        )
    elif finding.outcome == "confirmed":
        new_exp = (
            f'Verified filing passage "{first_quote}" corroborates the operational relationship.'
            if first_quote
            else "Verified filing passages corroborate the operational relationship."
        )
    elif finding.outcome == "rejected":
        new_exp = (
            f'Filing context "{first_quote}" does not support an active operational dependency, so the link is rejected.'
            if first_quote
            else "Filing context does not support an active operational dependency, so the link is rejected."
        )
    elif finding.outcome == "new_evidence":
        new_exp = (
            f'Extracted verified dependency disclosure "{first_quote}" from the filing.'
            if first_quote
            else "Extracted verified dependency disclosure from the filing."
        )
    else:
        new_exp = (
            f'Resolved counterparty identity for "{first_quote}" against portfolio records.'
            if first_quote
            else "Resolved counterparty identity against portfolio records."
        )

    new_steps = list(finding.steps)
    if new_steps and new_steps[-1].action == "conclude":
        new_steps[-1] = new_steps[-1].model_copy(update={"summary": new_exp})
    return finding.model_copy(update={"explanation": new_exp, "steps": new_steps})


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


def _build_single_company_context(
    company: CompanyExposure,
    filing_ref: FilingRef | None,
    edges: Sequence[VerifiedEdge],
    analysis: AnalysisResponse | None = None,
    portfolio: Sequence[CompanyExposure] | None = None,
) -> tuple[AnalysisResponse, DependencyResult]:
    """Construct a minimal `(AnalysisResponse, DependencyResult)` scoped to `company`."""
    own_edges = [
        e for e in edges if e.source_company_key == company.company_key
    ] or list(edges)
    exp_val = float(company.exposure) if company.exposure > 0 else 1.0
    comp_status = CompanyRunStatus(
        company_key=company.company_key,
        company_name=company.company_name,
        exposure=min(max(exp_val, 0.0), 1.0),
        status="done",
        filing=filing_ref or (own_edges[0].filing if own_edges else None),
        verified_edges=len(own_edges),
        rejected_edges=0,
    )
    if analysis is not None:
        scoped_analysis = analysis
    else:
        exposures = list(portfolio) if portfolio is not None else [company]
        if all(c.company_key != company.company_key for c in exposures):
            exposures.insert(0, company)
        scoped_analysis = AnalysisResponse(
            generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
            as_of_date=date(2026, 1, 1),
            request=PortfolioRequest(
                holdings=[PortfolioItem(ticker="PORT", allocation=1.0)],
            ),
            etfs=[],
            coverage=Coverage(
                total_allocation=1.0,
                loaded_allocation=1.0,
                missing_allocation=0.0,
                covered_weight=1.0,
                excluded_weight=0.0,
                unexplained_weight=0.0,
                unmatched_weight=0.0,
                sector_known_weight=1.0,
            ),
            exposures=exposures,
            exposures_truncated=False,
            other_exposure=0.0,
            overlap=Overlap(etfs=["PORT"], matrix=[[1.0]], pairs=[]),
            concentration=Concentration(
                top5=1.0,
                top10=1.0,
                top20=1.0,
                hhi=1.0,
                effective_companies=float(max(1, len(exposures))),
                distinct_securities=max(1, len(exposures)),
                distinct_companies=max(1, len(exposures)),
            ),
            sectors=[],
            gaps=[],
            warnings=[],
            attributions=[],
        )

    scoped_result = DependencyResult(
        as_of_date=scoped_analysis.as_of_date,
        request=DependencyRequest(
            holdings=scoped_analysis.request.holdings,
            top_n=max(1, min(len(scoped_analysis.exposures), 30)),
        ),
        companies=[comp_status],
        edges=list(own_edges),
        metrics=[],
        insights=Insights(status="ok", suggestions=[], flaws=[]),
        counts=DependencyCounts(
            companies_requested=1,
            companies_analysed=1,
            companies_skipped=0,
            verified_edges=len(own_edges),
            rejected_edges=0,
            interpretation_rejected=0,
            unresolved_counterparties=len(
                {
                    e.target_name.casefold()
                    for e in own_edges
                    if e.target_kind == "company" and e.target_key is None
                }
            ),
        ),
    )
    return scoped_analysis, scoped_result


def select_company_research_items(
    company: CompanyExposure,
    filing_ref: FilingRef | None,
    edges: Sequence[VerifiedEdge],
    *,
    max_items: int = 2,
    analysis: AnalysisResponse | None = None,
    portfolio: Sequence[CompanyExposure] | None = None,
) -> list[ResearchItem]:
    """Select up to `max_items` uncertain/critical research items for a single company (v3.1 A1).

    Picks the highest-priority item per `ResearchItemKind` first, then fills any remaining slots up to
    `max_items` from remaining candidate items of that company ordered by kind priority and score.
    """
    if max_items <= 0:
        return []
    scoped_analysis, scoped_result = _build_single_company_context(
        company, filing_ref, edges, analysis=analysis, portfolio=portfolio
    )
    first_pass = select_research_items(scoped_result, scoped_analysis, max_items=max_items)
    if len(first_pass) >= max_items or not scoped_result.edges:
        return first_pass[:max_items]

    chosen_ids = {item.item_id for item in first_pass}
    selected = list(first_pass)
    remaining_edges = [
        e for e in scoped_result.edges if all(item.edge is None or item.edge.edge_id != e.edge_id for item in selected)
    ]
    while len(selected) < max_items and remaining_edges:
        sub_result = scoped_result.model_copy(update={"edges": remaining_edges})
        more = select_research_items(sub_result, scoped_analysis, max_items=max_items - len(selected))
        new_items = [m for m in more if m.item_id not in chosen_ids and m.item_kind != "no_disclosures"]
        if not new_items:
            break
        for ni in new_items:
            chosen_ids.add(ni.item_id)
            selected.append(ni)
            if len(selected) >= max_items:
                break
        remaining_edges = [
            e
            for e in remaining_edges
            if all(item.edge is None or item.edge.edge_id != e.edge_id for item in selected)
        ]

    selected.sort(key=lambda item: (_KIND_PRIORITY.get(item.item_kind, 99), -item.priority_score, item.item_id))
    return selected[:max_items]


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
        vint = (
            (verified_interpretations or {}).get(edge.edge_id)
            or _RECENT_VERIFIED_INTERPRETATIONS.get(edge.edge_id)
        )
        if vint is not None and vint.status != "rejected":
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

    unnamed_quote_keys: set[tuple[str, str, str]] = {
        (
            e.source_company_key,
            e.edge_type,
            normalise_for_verify(e.evidence_quote).strip().casefold(),
        )
        for e in merged_by_id.values()
    }

    for raw_new_edge in added_edges:
        if _is_customer_group_target(raw_new_edge.target_name):
            continue
        new_edge = _normalise_anonymised_customer_edge(raw_new_edge)
        if _is_customer_group_target(new_edge.target_name):
            continue
        # B2: Missing interpretation is never defaulted to confirmed (treat as unverified -> don't merge)
        if new_edge.interpretation is None or new_edge.interpretation.status == "rejected":
            continue
        rule_flags, _, _ = check_interpretation_rules(new_edge, new_edge.evidence_quote)
        if rule_flags and new_edge.interpretation.method == "rules":
            continue
        if new_edge.target_kind == "unnamed_customer":
            u_key = (
                new_edge.source_company_key,
                new_edge.edge_type,
                normalise_for_verify(new_edge.evidence_quote).strip().casefold(),
            )
            if u_key in unnamed_quote_keys and new_edge.edge_id not in merged_by_id:
                continue
            unnamed_quote_keys.add(u_key)
        target_key = None if new_edge.target_kind == "unnamed_customer" else new_edge.target_key
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
                cand_metrics, cand_insights = _call_with_timeout(
                    lambda: orchestrator.insights(analysis, merged_edges, cache_only=cache_only),
                    timeout_s,
                )
            else:
                cand_metrics, cand_insights = orchestrator.insights(analysis, merged_edges, cache_only=cache_only)
            metrics = cand_metrics
            # Q1: Keep previous result.insights unchanged if synthesis timed out or degraded
            if cand_insights.status == "ok" or result.insights.status != "ok":
                insights = cand_insights
            else:
                insights = result.insights
        except Exception:  # noqa: BLE001
            log.info("orchestrator.insights timed out or failed during research merge; keeping previous insights")
            insights = result.insights
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


def _company_extraction_hash(
    company_key: str,
    accession: str,
    edges: Sequence[VerifiedEdge],
) -> str:
    """Compute a deterministic hash of a company's initial extracted edges for `(extraction_hash, depth, prompt_version)` caching."""
    sorted_edges = sorted(edges, key=lambda e: e.edge_id)
    edge_records = [
        {
            "edge_id": e.edge_id,
            "edge_type": e.edge_type,
            "target_name": e.target_name,
            "target_kind": e.target_kind,
            "target_key": e.target_key,
            "sole_source": e.sole_source,
            "qualifier": e.qualifier,
            "evidence_quote": e.evidence_quote,
            "section": e.section,
            "interp_status": e.interpretation.status if e.interpretation is not None else None,
            "interp_flags": list(e.interpretation.flags) if e.interpretation is not None else [],
        }
        for e in sorted_edges
    ]
    payload = json.dumps(
        {
            "company_key": company_key,
            "accession": accession,
            "edges": edge_records,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _company_research_cache_key(
    company_key: str,
    accession: str,
    edges: Sequence[VerifiedEdge],
    depth: str,
    prompt_version: str,
) -> tuple[str, str]:
    extraction_hash = _company_extraction_hash(company_key, accession, edges)
    return extraction_hash, f"{company_key}:{accession}:{extraction_hash}:{depth}:{prompt_version}"


def _invoke_company_progress(
    progress: Callable[..., None] | None,
    on_step: Callable[[int, int, ResearchStep | None, ResearchFinding | None], None] | None,
    steps_done: int,
    steps_total: int,
    findings: list[ResearchFinding],
    step: ResearchStep | None,
    finding: ResearchFinding | None,
) -> None:
    if on_step is not None:
        on_step(steps_done, steps_total, step, finding)
    if progress is not None:
        try:
            progress(steps_done, steps_total)
        except TypeError:
            progress(steps_done, steps_total, list(findings))


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
        insights_timeout_s: float = DEFAULT_INSIGHTS_TIMEOUT_SECONDS,
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
        self._company_replay_cache: dict[str, CompanyResearch] = {}
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
        self.insights_timeout_s = max(0.001, float(insights_timeout_s))

    @classmethod
    def from_settings(cls, http: HttpClient, settings: Any) -> ResearchLoop:
        """Construct a production `ResearchLoop` from `HttpClient` and `Settings`."""
        from hoc.graph import DependencyOrchestrator

        bounded_http = _BoundedResearchHttpClient(http, timeout_s=DEFAULT_CALL_TIMEOUT_SECONDS)
        insights_http = _BoundedResearchHttpClient(http, timeout_s=DEFAULT_INSIGHTS_TIMEOUT_SECONDS)
        disk_cache = DiskCache(settings.cache_dir)
        client = GeminiClient(bounded_http, settings)
        cache = ExtractionCache(disk_cache)
        fetcher = FilingFetcher(bounded_http, settings)
        aliases = load_aliases()
        orchestrator = DependencyOrchestrator(http=insights_http, settings=settings)
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
                    findings = [_sanitize_finding(ResearchFinding.model_validate(f)) for f in data.get("findings", [])]
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

    def _get_cached_company_run(self, cache_key: str) -> CompanyResearch | None:
        if cache_key in self._company_replay_cache:
            cached = self._company_replay_cache[cache_key]
            return replace(
                cached,
                findings=list(cached.findings),
                edges=list(cached.edges),
                rejected_edge_ids=list(cached.rejected_edge_ids),
                cached=True,
            )
        if self._disk_cache is not None:
            entry = self._disk_cache.get(RESEARCH_COMPANY_CACHE_NAMESPACE, cache_key)
            if entry is not None:
                try:
                    data = json.loads(entry.body.decode("utf-8"))
                    raw_findings = [ResearchFinding.model_validate(f) for f in data.get("findings", [])]
                    findings = [_sanitize_finding(f) for f in raw_findings]
                    edges = [VerifiedEdge.model_validate(e) for e in data.get("edges", [])]
                    rejected_edge_ids = [str(rid) for rid in data.get("rejected_edge_ids", [])]
                    steps_done = int(data.get("steps_done", sum(len(f.steps) for f in findings)))
                    steps_total = int(data.get("steps_total", steps_done))
                    interp_rej = int(data.get("interpretation_rejected", len(rejected_edge_ids)))
                    rejected = int(data.get("rejected", 0))
                    quality_raw = data.get("quality")
                    quality: Literal["sections", "fallback"] | None = (
                        quality_raw if quality_raw in ("sections", "fallback") else None
                    )
                    model_val = data.get("model")
                    res = CompanyResearch(
                        findings=findings,
                        edges=edges,
                        rejected_edge_ids=rejected_edge_ids,
                        cached=True,
                        steps_done=steps_done,
                        steps_total=steps_total,
                        interpretation_rejected=interp_rej,
                        rejected=rejected,
                        quality=quality,
                        model=str(model_val) if model_val else self.model,
                    )
                    if findings != raw_findings:
                        self._put_cached_company_run(cache_key, res)
                    else:
                        self._company_replay_cache[cache_key] = res
                    return res
                except Exception:  # noqa: BLE001
                    log.warning("Failed to deserialize cached company research for %s", cache_key)
        return None

    def _put_cached_company_run(self, cache_key: str, res: CompanyResearch) -> None:
        self._company_replay_cache[cache_key] = res
        if self._disk_cache is not None:
            try:
                payload = {
                    "findings": [f.model_dump(mode="json") for f in res.findings],
                    "edges": [e.model_dump(mode="json") for e in res.edges],
                    "rejected_edge_ids": list(res.rejected_edge_ids),
                    "steps_done": res.steps_done,
                    "steps_total": res.steps_total,
                    "interpretation_rejected": res.interpretation_rejected,
                    "rejected": res.rejected,
                    "quality": res.quality,
                    "model": res.model,
                }
                body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                self._disk_cache.put(
                    RESEARCH_COMPANY_CACHE_NAMESPACE,
                    cache_key,
                    body,
                    {"prompt_version": self.prompt_version},
                )
            except Exception:  # noqa: BLE001
                log.warning("Failed to write company research to disk cache for %s", cache_key)

    def research_company(
        self,
        company: CompanyExposure,
        filing: FilingRef | Filing | None,
        edges: Sequence[VerifiedEdge],
        *,
        depth: ResearchDepthOption = "light",
        cache_only: bool = False,
        progress: Callable[..., None] | None = None,
        on_step: Callable[[int, int, ResearchStep | None, ResearchFinding | None], None] | None = None,
        analysis: AnalysisResponse | None = None,
        portfolio: Sequence[CompanyExposure] | None = None,
        resolve_target_key: Callable[[str], str | None] | None = None,
        filing_obj: Filing | None = None,
    ) -> CompanyResearch:
        """Run the v3.1 per-company agentic sub-agent loop (A1 <-> A2/A3 seam).

        - Depth presets: `'light'` (`max_items=2, max_steps=3`, ~40s budget),
          `'thorough'` (`max_items=4, max_steps=4`, ~85s budget), `'none'` (`0, 0`).
        - Cached in `DiskCache` per `(extraction_hash, depth, prompt_version)` so `cache_only=True`
          replays without calling Gemini and switching from `'light'` to `'thorough'` reuses the extraction.
        - Raises `CompanyUnavailable('missing_api_key', ...)` when uncached and either `cache_only=True`
          or `not client.has_api_key`.
        """
        actual_filing: Filing | None = filing_obj
        filing_ref: FilingRef | None = None

        if isinstance(filing, Filing):
            actual_filing = filing
            form_literal = "20-F" if "20-F" in str(filing.form).upper() else "10-K"
            filing_ref = FilingRef(
                company_key=company.company_key,
                form=form_literal,  # type: ignore[arg-type]
                accession=filing.accession,
                filed=filing.filed,
                url=filing.url,
            )
            self._filings_by_key[company.company_key] = filing
            if filing.cik:
                self._filings_by_cik[str(filing.cik).zfill(10)] = filing
        elif isinstance(filing, FilingRef):
            filing_ref = filing
            if actual_filing is None:
                actual_filing = self._filings_by_key.get(company.company_key)
                if actual_filing is None:
                    cik_hint = _extract_cik_from_key(company.company_key)
                    if cik_hint and cik_hint in self._filings_by_cik:
                        actual_filing = self._filings_by_cik[cik_hint]
        else:
            if actual_filing is None:
                actual_filing = self._filings_by_key.get(company.company_key)
            if actual_filing is not None:
                self._filings_by_key[company.company_key] = actual_filing
                if actual_filing.cik:
                    self._filings_by_cik[str(actual_filing.cik).zfill(10)] = actual_filing
                form_literal = "20-F" if "20-F" in str(actual_filing.form).upper() else "10-K"
                filing_ref = FilingRef(
                    company_key=company.company_key,
                    form=form_literal,  # type: ignore[arg-type]
                    accession=actual_filing.accession,
                    filed=actual_filing.filed,
                    url=actual_filing.url,
                )
            elif edges:
                filing_ref = edges[0].filing

        initial_edges = [
            _normalise_anonymised_customer_edge(e)
            for e in edges
            if e.source_company_key == company.company_key or not e.source_company_key
        ]
        if not initial_edges and edges:
            initial_edges = [_normalise_anonymised_customer_edge(e) for e in edges]

        if depth == "none":
            scored = attach_edge_importance(initial_edges)
            _invoke_company_progress(progress, on_step, 0, 0, [], None, None)
            return CompanyResearch(
                findings=[],
                edges=scored,
                rejected_edge_ids=[],
                cached=True,
                steps_done=0,
                steps_total=0,
                interpretation_rejected=0,
                model=self.model,
            )

        max_items, item_max_steps = RESEARCH_DEPTH_PRESETS.get(depth, (2, 3))
        accession = (
            filing_ref.accession
            if filing_ref is not None
            else (actual_filing.accession if actual_filing is not None else "no_filing")
        )
        _, cache_key = _company_research_cache_key(
            company.company_key,
            accession,
            initial_edges,
            depth,
            self.prompt_version,
        )

        cached_res = self._get_cached_company_run(cache_key)
        if cached_res is not None and (
            cache_only or not any(_is_budget_stopped_finding(f) for f in cached_res.findings)
        ):
            replay_total = sum(max(1, len(f.steps)) for f in cached_res.findings)
            _invoke_company_progress(progress, on_step, 0, replay_total, [], None, None)
            done_so_far = 0
            replayed_findings: list[ResearchFinding] = []
            for finding in cached_res.findings:
                steps_list = finding.steps or [
                    ResearchStep(
                        index=1,
                        action="conclude",
                        query=company.company_name,
                        summary=finding.explanation,
                        filing=filing_ref,
                    )
                ]
                for step_idx_in_finding, step in enumerate(steps_list):
                    done_so_far += 1
                    is_last = step_idx_in_finding == len(steps_list) - 1
                    if is_last:
                        replayed_findings.append(finding)
                    _invoke_company_progress(
                        progress,
                        on_step,
                        done_so_far,
                        replay_total,
                        replayed_findings,
                        step,
                        finding if is_last else None,
                    )
            return replace(
                cached_res,
                cached=True,
                steps_done=replay_total,
                steps_total=replay_total,
            )

        has_key = bool(getattr(self.client, "has_api_key", True))
        if cache_only:
            raise CompanyUnavailable(
                "missing_api_key",
                f"Agentic research for {company.company_key} ({depth}) is not in cache (cache_only=True).",
            )
        if not has_key:
            raise CompanyUnavailable(
                "missing_api_key",
                f"HOC_GEMINI_API_KEY is not set and research for {company.company_key} ({depth}) is not cached.",
            )

        completed_same_depth_by_id: dict[str, ResearchFinding] = (
            {f.finding_id: f for f in cached_res.findings if not _is_budget_stopped_finding(f)}
            if cached_res is not None
            else {}
        )

        cached_light: CompanyResearch | None = None
        if depth == "thorough":
            _, light_cache_key = _company_research_cache_key(
                company.company_key,
                accession,
                initial_edges,
                "light",
                self.prompt_version,
            )
            cached_light = self._get_cached_company_run(light_cache_key)

        scoped_analysis, scoped_result = _build_single_company_context(
            company,
            filing_ref,
            initial_edges,
            analysis=analysis,
            portfolio=portfolio,
        )
        items = select_company_research_items(
            company,
            filing_ref,
            initial_edges,
            max_items=max_items,
            analysis=scoped_analysis,
            portfolio=portfolio,
        )

        if not items:
            base_edges = list(cached_light.edges) if cached_light is not None else list(initial_edges)
            scored = attach_edge_importance(base_edges)
            _invoke_company_progress(progress, on_step, 0, 0, [], None, None)
            empty_res = CompanyResearch(
                findings=list(cached_light.findings) if cached_light is not None else [],
                edges=scored,
                rejected_edge_ids=list(cached_light.rejected_edge_ids) if cached_light is not None else [],
                cached=False,
                steps_done=0,
                steps_total=0,
                interpretation_rejected=len(cached_light.rejected_edge_ids) if cached_light is not None else 0,
                model=self.model,
            )
            self._put_cached_company_run(cache_key, empty_res)
            return empty_res

        aliases = self.aliases if self.aliases is not None else load_aliases()
        resolver = resolve_target_key or NameResolver(scoped_analysis.exposures, aliases).resolve
        top_keys = {c.company_key for c in scoped_analysis.exposures if c.exposure > 0}
        if company.company_key:
            top_keys.add(company.company_key)

        preset_timeout = RESEARCH_DEPTH_TIMEOUT_SECONDS.get(depth, 40.0)
        company_timeout_s = (
            min(self.total_timeout_s, preset_timeout)
            if self.total_timeout_s >= DEFAULT_TOTAL_TIMEOUT_SECONDS
            else self.total_timeout_s
        )
        min_tool_calls = 3 if depth == "thorough" else 2
        require_search_filings = depth == "thorough"
        light_findings_by_id: dict[str, ResearchFinding] = (
            {f.finding_id: f for f in cached_light.findings if not _is_budget_stopped_finding(f)}
            if cached_light is not None
            else {}
        )

        started = time.monotonic()
        verified_interps: dict[str, EdgeInterpretation] = {}
        findings: list[ResearchFinding] = []
        steps_done = 0
        steps_total = len(items) * item_max_steps
        _invoke_company_progress(progress, on_step, steps_done, steps_total, findings, None, None)

        for idx, item in enumerate(items):
            remaining_items_after = len(items) - idx - 1
            elapsed = time.monotonic() - started
            completed_same_depth = completed_same_depth_by_id.get(item.item_id)
            prior_finding = light_findings_by_id.get(item.item_id)

            def _on_tool_step(step: ResearchStep, cur_total: int = steps_total) -> None:
                nonlocal steps_done
                steps_done += 1
                _invoke_company_progress(progress, on_step, steps_done, cur_total, findings, step, None)

            if completed_same_depth is not None:
                # Re-use already-completed finding from a partial prior run at the same depth
                for step in completed_same_depth.steps[:-1]:
                    _on_tool_step(step)
                finding = completed_same_depth
            elif prior_finding is not None and prior_finding.outcome == "rejected":
                # Keep already-verified rejection from light without re-spending steps
                for step in prior_finding.steps[:-1]:
                    _on_tool_step(step)
                finding = prior_finding
            elif elapsed >= company_timeout_s:
                finding = prior_finding if prior_finding is not None else self._timeout_finding(item)
            else:
                try:
                    finding = self._investigate_item(
                        item=item,
                        result=scoped_result,
                        analysis=scoped_analysis,
                        resolver=resolver,
                        top_keys=top_keys,
                        cache_only=cache_only,
                        run_started=started,
                        verified_interpretations=verified_interps,
                        max_steps_override=item_max_steps,
                        total_timeout_override=company_timeout_s,
                        on_tool_step=_on_tool_step,
                        min_tool_calls=min_tool_calls,
                        require_search_filings=require_search_filings,
                        prior_finding=prior_finding,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("company research item %s failed: %s", item.item_id, exc)
                    finding = (
                        prior_finding
                        if prior_finding is not None
                        else ResearchFinding(
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
                    )

            steps_done += 1
            steps_total = steps_done + remaining_items_after * item_max_steps
            findings.append(finding)
            conclude_step = finding.steps[-1] if finding.steps else None
            _invoke_company_progress(
                progress,
                on_step,
                steps_done,
                steps_total,
                findings,
                conclude_step,
                finding,
            )

        if cached_light is not None:
            seen_finding_ids = {f.finding_id for f in findings}
            for lf in cached_light.findings:
                if lf.finding_id not in seen_finding_ids:
                    findings.append(lf)

        rejected_ids_list: list[str] = []
        rejected_ids_set: set[str] = set()
        if cached_light is not None:
            for rid in cached_light.rejected_edge_ids:
                if rid and rid not in rejected_ids_set:
                    rejected_ids_set.add(rid)
                    rejected_ids_list.append(rid)
        for finding in findings:
            for rid in finding.rejected_edge_ids:
                if not rid or rid in rejected_ids_set:
                    continue
                vint_check = verified_interps.get(rid) or _RECENT_VERIFIED_INTERPRETATIONS.get(rid)
                if vint_check is not None and vint_check.status != "rejected":
                    continue
                rejected_ids_set.add(rid)
                rejected_ids_list.append(rid)

        portfolio_names = {c.company_key: c.company_name for c in scoped_analysis.exposures}
        portfolio_keys = set(portfolio_names)
        merged_by_id: dict[str, VerifiedEdge] = {}

        seed_edges: list[VerifiedEdge] = list(initial_edges)
        if cached_light is not None:
            existing_seed_ids = {e.edge_id for e in seed_edges}
            for le in cached_light.edges:
                if le.edge_id not in existing_seed_ids:
                    seed_edges.append(le)
                    existing_seed_ids.add(le.edge_id)

        for edge in seed_edges:
            if edge.edge_id in rejected_ids_set:
                continue
            updated = edge
            vint = verified_interps.get(edge.edge_id) or _RECENT_VERIFIED_INTERPRETATIONS.get(edge.edge_id)
            if vint is not None and vint.status != "rejected":
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
            updated = _normalise_anonymised_customer_edge(updated)
            updated = updated.model_copy(update={"importance": score_edge_importance(updated)})
            merged_by_id[updated.edge_id] = updated

        unnamed_quote_keys: set[tuple[str, str, str]] = {
            (
                e.source_company_key,
                e.edge_type,
                normalise_for_verify(e.evidence_quote).strip().casefold(),
            )
            for e in merged_by_id.values()
        }

        for finding in findings:
            for raw_new_edge in finding.new_edges:
                if raw_new_edge.edge_id in rejected_ids_set:
                    continue
                if _is_customer_group_target(raw_new_edge.target_name):
                    continue
                new_edge = _normalise_anonymised_customer_edge(raw_new_edge)
                if _is_customer_group_target(new_edge.target_name):
                    continue
                if new_edge.interpretation is None or new_edge.interpretation.status != "confirmed":
                    continue
                rule_flags, _, _ = check_interpretation_rules(new_edge, new_edge.evidence_quote)
                if rule_flags and new_edge.interpretation.method == "rules":
                    continue
                if new_edge.target_kind == "unnamed_customer":
                    u_key = (
                        new_edge.source_company_key,
                        new_edge.edge_type,
                        normalise_for_verify(new_edge.evidence_quote).strip().casefold(),
                    )
                    if u_key in unnamed_quote_keys and new_edge.edge_id not in merged_by_id:
                        continue
                    unnamed_quote_keys.add(u_key)
                target_key = None if new_edge.target_kind == "unnamed_customer" else new_edge.target_key
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

        final_edges = list(merged_by_id.values())
        company_res = CompanyResearch(
            findings=findings,
            edges=final_edges,
            rejected_edge_ids=rejected_ids_list,
            cached=False,
            steps_done=steps_done,
            steps_total=steps_total,
            interpretation_rejected=len(rejected_ids_list),
            model=self.model,
        )
        self._put_cached_company_run(cache_key, company_res)
        return company_res

    run_company = research_company

    def run(
        self,
        result: DependencyResult,
        analysis: AnalysisResponse,
        *,
        max_items: int = 6,
        depth: ResearchDepthOption | None = None,
        cache_only: bool = False,
        progress: Callable[[int, int, list[ResearchFinding]], None] | None = None,
        on_finding: Callable[[ResearchFinding], None] | None = None,
    ) -> tuple[list[ResearchFinding], DependencyResult]:
        """Run the bounded research loop on up to `max_items` uncertain items and return `(findings, merged_result)`."""
        effective_max_steps = self.max_steps
        if depth is not None and depth in RESEARCH_DEPTH_PRESETS:
            preset_items, preset_steps = RESEARCH_DEPTH_PRESETS[depth]
            max_items = preset_items
            effective_max_steps = preset_steps if preset_steps > 0 else self.max_steps
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
        _RECENT_VERIFIED_INTERPRETATIONS.clear()
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
                        max_steps_override=effective_max_steps,
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

        # Q1: Give the final synthesis its own budget (~75s, separate from the item budget),
        # while still respecting explicitly shortened test budgets when total_timeout_s < DEFAULT_TOTAL_TIMEOUT_SECONDS.
        insights_budget = (
            self.insights_timeout_s
            if self.total_timeout_s >= DEFAULT_TOTAL_TIMEOUT_SECONDS
            else min(self.insights_timeout_s, self.total_timeout_s)
        )
        merged = merge_research_findings(
            result,
            analysis,
            findings,
            orchestrator=self.orchestrator,
            resolver=resolver,
            cache_only=cache_only,
            verified_interpretations=verified_interps,
            timeout_s=insights_budget,
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
            explanation="Not finished in time: research wall-clock budget reached before completing verification.",
            steps=[
                ResearchStep(
                    index=1,
                    action="conclude",
                    query=item.target_name or item.subject_name,
                    summary="Not finished in time: skipped remaining steps because the research time budget was reached.",
                    filing=item.filing_ref,
                )
            ],
        )

    def _remaining_budget(
        self,
        *,
        run_started: float,
        item_started: float,
        total_timeout_s: float | None = None,
    ) -> float:
        effective_total = total_timeout_s if total_timeout_s is not None else self.total_timeout_s
        rem_total = effective_total - (time.monotonic() - run_started)
        rem_item = self.item_timeout_s - (time.monotonic() - item_started)
        return min(self.call_timeout_s, rem_total, rem_item)

    @staticmethod
    def _is_early_rejection_allowed(
        item: ResearchItem,
        decision: Mapping[str, Any],
        observed_quotes: Sequence[str],
    ) -> bool:
        """Return True if an early `conclude` is a grounded rejection of a flagged edge."""
        if item.item_kind != "flagged_edge":
            return False
        if str(decision.get("outcome", "")).strip() != "rejected":
            return False
        cues = ("do not rely", "no assurance", "primary competitors include", "compete with")
        if any(any(c in q.lower() for c in cues) for q in observed_quotes):
            return True
        return bool(
            item.edge is not None
            and item.edge.interpretation is not None
            and any(
                f in item.edge.interpretation.flags
                for f in ("negated", "competitor_mention", "direction_mismatch", "subject_mismatch")
            )
        )

    @staticmethod
    def _next_complementary_tool_decision(
        *,
        item: ResearchItem,
        cik: str,
        steps: Sequence[ResearchStep],
        require_search_filings: bool,
        min_tool_calls: int,
    ) -> dict[str, Any]:
        """Choose the next complementary tool step when enforcing `min_tool_calls` and `require_search_filings`."""
        used_actions = [s.action for s in steps]
        used_set = set(used_actions)
        target_query = (
            clean_company_name(item.subject_name)
            if item.item_kind in ("undisclosed_customer", "no_disclosures")
            or _format_anonymised_customer_target(item.target_name or "") is not None
            else (item.target_name or clean_company_name(item.subject_name))
        )

        # If on the last required tool step and search_filings is required, enforce search_filings
        if require_search_filings and "search_filings" not in used_set and len(steps) >= max(0, min_tool_calls - 1):
            return {
                "action": "search_filings",
                "query": target_query,
                "cik": cik,
                "section": "1",
                "outcome": "unresolved",
                "explanation": "",
                "candidate_edges": [],
            }

        if "find_in_filing" not in used_set:
            find_query = (
                "customer"
                if item.item_kind in ("undisclosed_customer", "no_disclosures")
                else (item.target_name or "supplier")
            )
            return {
                "action": "find_in_filing",
                "query": find_query,
                "cik": cik,
                "section": "1",
                "outcome": "unresolved",
                "explanation": "",
                "candidate_edges": [],
            }

        if "read_section" not in used_set:
            sec = (
                "1A"
                if item.edge is not None
                and "1" in (item.edge.section or "")
                and "1A" not in (item.edge.section or "")
                else "1"
            )
            return {
                "action": "read_section",
                "query": item.target_name or item.subject_name,
                "cik": cik,
                "section": sec,
                "outcome": "unresolved",
                "explanation": "",
                "candidate_edges": [],
            }

        if "search_filings" not in used_set:
            return {
                "action": "search_filings",
                "query": target_query,
                "cik": cik,
                "section": "1",
                "outcome": "unresolved",
                "explanation": "",
                "candidate_edges": [],
            }

        # Fallback additional section read
        read_1a = any(s.action == "read_section" and "1A" in s.query for s in steps)
        return {
            "action": "read_section",
            "query": item.target_name or item.subject_name,
            "cik": cik,
            "section": "1" if read_1a else "1A",
            "outcome": "unresolved",
            "explanation": "",
            "candidate_edges": [],
        }

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
        max_steps_override: int | None = None,
        total_timeout_override: float | None = None,
        on_tool_step: Callable[[ResearchStep], None] | None = None,
        min_tool_calls: int | None = None,
        require_search_filings: bool | None = None,
        prior_finding: ResearchFinding | None = None,
    ) -> ResearchFinding:
        effective_max_steps = max(
            1,
            min(int(max_steps_override if max_steps_override is not None else self.max_steps), MAX_RESEARCH_STEPS),
        )
        default_min_tools = (
            3
            if effective_max_steps >= 4
            else (2 if effective_max_steps == 3 else max(0, effective_max_steps - 1))
        )
        min_tools = (
            max(0, min(int(min_tool_calls), max(0, effective_max_steps - 1)))
            if min_tool_calls is not None
            else default_min_tools
        )
        req_search = (
            bool(require_search_filings)
            if require_search_filings is not None
            else (effective_max_steps >= 4 and min_tools >= 3)
        )

        item_started = time.monotonic()
        init_budget = self._remaining_budget(
            run_started=run_started,
            item_started=item_started,
            total_timeout_s=total_timeout_override,
        )
        if init_budget <= 0:
            return prior_finding if prior_finding is not None else self._timeout_finding(item)
        try:
            filing = _call_with_timeout(
                lambda: self._load_filing_for_item(item, analysis),
                init_budget,
            )
        except FuturesTimeoutError:
            return prior_finding if prior_finding is not None else self._timeout_finding(item)

        cik = (
            (filing.cik if filing is not None else None)
            or item.cik
            or _extract_cik_from_key(item.subject_key)
            or "0000000000"
        )
        cik = str(cik).zfill(10) if str(cik).isdigit() else str(cik)
        filing_ref = self._filing_ref_for(item, filing)
        initial_quote = item.edge.evidence_quote if item.edge is not None and item.edge.evidence_quote else None

        steps: list[ResearchStep] = []
        observations: list[str] = []
        verified_quotes: list[str] = []
        corroborating_quotes: list[str] = []
        collected_candidate_edges: list[Mapping[str, Any]] = []

        has_key = bool(getattr(self.client, "has_api_key", True))
        can_call_gemini = has_key and not cache_only

        # FIX-22: When upgrading from light to thorough (effective_max_steps >= 4) and prior_finding
        # has completed tool steps, replay up to (effective_max_steps - 2) prior tool steps in Python
        # so thorough continues directly from step 3 (`search_filings`) instead of re-spending Gemini calls.
        if (
            prior_finding is not None
            and not _is_budget_stopped_finding(prior_finding)
            and effective_max_steps >= 4
        ):
            prior_tool_steps = [
                ps
                for ps in prior_finding.steps
                if ps.action in ("find_in_filing", "read_section", "search_filings")
            ]
            for ps in prior_tool_steps[: max(0, effective_max_steps - 2)]:
                sec_val = "1"
                if ps.action == "read_section":
                    sec_val = re.sub(r"^item\s+", "", ps.query, flags=re.IGNORECASE).strip() or "1"
                replay_decision: dict[str, Any] = {
                    "action": ps.action,
                    "query": ps.query,
                    "cik": cik,
                    "section": sec_val,
                    "outcome": "unresolved",
                    "explanation": "",
                    "candidate_edges": [],
                }
                prev_len = len(steps)
                self._execute_tool_step(
                    action=ps.action,
                    decision=replay_decision,
                    item=item,
                    cik=cik,
                    filing=filing,
                    filing_ref=filing_ref,
                    result=result,
                    analysis=analysis,
                    resolver=resolver,
                    cache_only=True,
                    steps=steps,
                    observations=observations,
                    verified_quotes=verified_quotes,
                    corroborating_quotes=corroborating_quotes,
                    initial_quote=initial_quote,
                )
                if on_tool_step is not None and len(steps) > prev_len and len(steps) < effective_max_steps:
                    on_tool_step(steps[-1])

        concluded_payload: Mapping[str, Any] | None = None
        timed_out_or_failed = False
        start_step_idx = len(steps) + 1

        for step_idx in range(start_step_idx, effective_max_steps + 1):
            budget = self._remaining_budget(
                run_started=run_started,
                item_started=item_started,
                total_timeout_s=total_timeout_override,
            )
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
                    max_steps=effective_max_steps,
                    min_tool_calls=min_tools,
                    require_search_filings=req_search,
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
                    verified_quotes=corroborating_quotes or verified_quotes,
                    observations=observations,
                    has_api_key=has_key,
                    min_tool_calls=min_tools,
                    require_search_filings=req_search,
                    steps=steps,
                )

            raw_cands = step_decision.get("candidate_edges")
            if isinstance(raw_cands, list):
                for rc in raw_cands:
                    if isinstance(rc, Mapping):
                        collected_candidate_edges.append(rc)

            action_raw = str(step_decision.get("action", "conclude")).strip()
            action: ResearchAction = (
                action_raw  # type: ignore[assignment]
                if action_raw in ("search_filings", "read_section", "find_in_filing", "conclude")
                else "conclude"
            )

            used_actions = {s.action for s in steps}
            needs_more_tools = len(steps) < min_tools or (
                req_search and "search_filings" not in used_actions
            )

            if action == "conclude":
                if not needs_more_tools or self._is_early_rejection_allowed(item, step_decision, verified_quotes):
                    concluded_payload = step_decision
                    break
                # FIX-1 (1b/1c): Reject early conclude with a tool message and execute a complementary tool
                observations.append(
                    "TOOL_MESSAGE: Early `conclude` rejected — re-finding the initial quote or stopping before "
                    f"{min_tools} tool calls is insufficient. Running another tool to check for independent "
                    "corroboration in the filing or peer SEC filings."
                )
                step_decision = self._next_complementary_tool_decision(
                    item=item,
                    cik=cik,
                    steps=steps,
                    require_search_filings=req_search,
                    min_tool_calls=min_tools,
                )
                action = step_decision["action"]  # type: ignore[assignment]
            elif step_idx == effective_max_steps and not needs_more_tools:
                # Final slot reached after all required tool calls; conclude now instead of overwriting a tool step
                concluded_payload = step_decision
                break
            elif (
                req_search
                and "search_filings" not in used_actions
                and len(steps) == max(0, min_tools - 1)
                and action != "search_filings"
            ):
                # Enforce at least one search_filings call in thorough depth
                step_decision = self._next_complementary_tool_decision(
                    item=item,
                    cik=cik,
                    steps=steps,
                    require_search_filings=True,
                    min_tool_calls=min_tools,
                )
                action = "search_filings"

            tool_budget = self._remaining_budget(
                run_started=run_started,
                item_started=item_started,
                total_timeout_s=total_timeout_override,
            )
            if tool_budget <= 0:
                timed_out_or_failed = True
                break
            prev_len = len(steps)
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
                        resolver=resolver,
                        cache_only=cache_only,
                        steps=steps,
                        observations=observations,
                        verified_quotes=verified_quotes,
                        corroborating_quotes=corroborating_quotes,
                        initial_quote=initial_quote,
                    ),
                    tool_budget,
                )
            except FuturesTimeoutError:
                timed_out_or_failed = True
                break
            if on_tool_step is not None and len(steps) > prev_len and len(steps) < effective_max_steps:
                on_tool_step(steps[-1])

        if timed_out_or_failed and concluded_payload is None:
            concluded_payload = {
                "action": "conclude",
                "query": item.target_name or item.subject_name,
                "outcome": "unresolved",
                "explanation": "Not finished in time: research step budget expired before completing verification.",
                "candidate_edges": [],
            }

        if initial_quote and initial_quote not in verified_quotes:
            verified_quotes.append(initial_quote)

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
            corroborating_quotes=corroborating_quotes,
            collected_candidate_edges=collected_candidate_edges,
            concluded_payload=concluded_payload,
            run_started=run_started,
            item_started=item_started,
            verified_interpretations=verified_interpretations,
            max_steps_override=effective_max_steps,
            total_timeout_override=total_timeout_override,
            prior_finding=prior_finding,
            timed_out=timed_out_or_failed,
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
        resolver: Callable[[str], str | None],
        cache_only: bool,
        steps: list[ResearchStep],
        observations: list[str],
        verified_quotes: list[str],
        corroborating_quotes: list[str],
        initial_quote: str | None,
    ) -> None:
        query_raw = str(decision.get("query") or "").strip()
        target_cik = str(decision.get("cik") or cik).strip() or cik
        section_req = str(decision.get("section") or "1").strip() or "1"

        target_filing = filing
        if target_cik != cik:
            target_filing = self._load_filing_by_cik(target_cik) or filing

        next_index = len(steps) + 1
        from_other_filing = target_cik != cik and target_filing is not filing

        if action == "find_in_filing":
            search_phrase = query_raw or item.target_name or item.subject_name
            spans = self._find_spans_in_filing(target_filing, search_phrase, item=item, result=result)
            corroborating_in_step: list[str] = []
            for span in spans:
                is_corroborating = _span_corroborates_item(
                    span,
                    item=item,
                    initial_quote=initial_quote,
                    from_other_filing=from_other_filing,
                )
                if is_corroborating:
                    corroborating_in_step.append(span)
                    if span not in corroborating_quotes:
                        corroborating_quotes.append(span)
                    if span not in verified_quotes:
                        verified_quotes.insert(0, span)
                    observations.append(
                        f'OBSERVED_QUOTE: "{span}" (source=find_in_filing, cik={target_cik}, corroborating=true)'
                    )
                else:
                    if span not in verified_quotes:
                        verified_quotes.append(span)
                    observations.append(
                        f'OBSERVED_QUOTE: "{span}" (source=find_in_filing, cik={target_cik}, corroborating=false, note=same_as_initial_quote)'
                    )
            if corroborating_in_step:
                summary = f'Found independent filing passage "{corroborating_in_step[0][:140]}" matching {search_phrase}.'
            elif spans:
                summary = f"Searched filing for {search_phrase}; only the initial extraction passage matched (no second independent passage)."
            else:
                summary = f"Searched filing for {search_phrase}; no exact phrase match in primary text."
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
            corroborating_in_step = []
            for span in spans:
                is_corroborating = _span_corroborates_item(
                    span,
                    item=item,
                    initial_quote=initial_quote,
                    from_other_filing=from_other_filing,
                )
                if is_corroborating:
                    corroborating_in_step.append(span)
                    if span not in corroborating_quotes:
                        corroborating_quotes.append(span)
                    if span not in verified_quotes:
                        verified_quotes.insert(0, span)
                    observations.append(
                        f'OBSERVED_QUOTE: "{span}" (source=read_section, cik={target_cik}, section={section_req}, corroborating=true)'
                    )
                else:
                    if span not in verified_quotes:
                        verified_quotes.append(span)
                    observations.append(
                        f'OBSERVED_QUOTE: "{span}" (source=read_section, cik={target_cik}, section={section_req}, corroborating=false)'
                    )
            display_span = corroborating_in_step[0] if corroborating_in_step else (spans[0] if spans else "")
            summary = (
                f'Read section {section_req} and extracted verified passage "{display_span[:140]}".'
                if display_span
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
            raw_phrase = query_raw or item.target_name or clean_company_name(item.subject_name)
            if (
                item.item_kind in ("undisclosed_customer", "no_disclosures")
                or _format_anonymised_customer_target(raw_phrase) is not None
                or not _corroboration_tokens(raw_phrase)
            ):
                phrase = clean_company_name(item.subject_name) or item.subject_name
            else:
                phrase = raw_phrase
            spans, peer_names = self._search_across_filings(
                phrase,
                exclude_cik=cik,
                item=item,
                result=result,
                analysis=analysis,
                resolver=resolver,
                cache_only=cache_only,
            )
            for span in spans:
                if span not in corroborating_quotes:
                    corroborating_quotes.append(span)
                if span not in verified_quotes:
                    verified_quotes.insert(0, span)
                observations.append(
                    f'OBSERVED_QUOTE: "{span}" (source=search_filings, query={phrase}, corroborating=true)'
                )
            if spans:
                peer_label = ", ".join(peer_names[:2]) if peer_names else "peer filings"
                summary = f'Cross-filing search for {phrase} in {peer_label} found "{spans[0][:140]}".'
            else:
                summary = f"Searched peer SEC filings for {phrase}; no additional corroborating passages found."
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
        corroborating_quotes: list[str],
        collected_candidate_edges: Sequence[Mapping[str, Any]],
        concluded_payload: Mapping[str, Any] | None,
        run_started: float,
        item_started: float,
        verified_interpretations: dict[str, EdgeInterpretation],
        max_steps_override: int | None = None,
        total_timeout_override: float | None = None,
        prior_finding: ResearchFinding | None = None,
        timed_out: bool = False,
    ) -> ResearchFinding:
        effective_max_steps = max(
            1,
            min(int(max_steps_override if max_steps_override is not None else self.max_steps), MAX_RESEARCH_STEPS),
        )
        has_key = bool(getattr(self.client, "has_api_key", True))
        if concluded_payload is None:
            concluded_payload = self._deterministic_step_decision(
                item=item,
                cik=cik,
                step_idx=effective_max_steps,
                verified_quotes=corroborating_quotes or verified_quotes,
                observations=[f'OBSERVED_QUOTE: "{q}"' for q in (corroborating_quotes or verified_quotes)],
                has_api_key=has_key,
                min_tool_calls=0,
                require_search_filings=False,
                steps=steps,
            )

        raw_outcome = str(concluded_payload.get("outcome") or "unresolved").strip()
        outcome: ResearchOutcome = (
            raw_outcome  # type: ignore[assignment]
            if raw_outcome in ("confirmed", "revised", "rejected", "new_evidence", "unresolved")
            else "unresolved"
        )
        model_outcome: ResearchOutcome = outcome
        raw_explanation = str(concluded_payload.get("explanation") or "").strip()

        combined_raw_candidates: list[Mapping[str, Any]] = list(collected_candidate_edges)
        final_cands = concluded_payload.get("candidate_edges")
        if isinstance(final_cands, list):
            for fc in final_cands:
                if isinstance(fc, Mapping):
                    combined_raw_candidates.append(fc)

        candidate_dicts = [
            _normalise_candidate_dict_for_q2(c)
            for c in combined_raw_candidates
            if isinstance(c, Mapping)
        ]

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
            built_edges = [e for e in built_edges if not _is_customer_group_target(e.target_name)]
            if built_edges:
                budget = self._remaining_budget(
                    run_started=run_started,
                    item_started=item_started,
                    total_timeout_s=total_timeout_override,
                )
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
                            if e.interpretation is not None
                            and e.interpretation.status == "confirmed"
                            and not _is_customer_group_target(e.target_name)
                        ]
                        verified_new_edges = [
                            _normalise_anonymised_customer_edge(e)
                            for e in attach_edge_importance(confirmed_built)
                        ]
                        for ve in verified_new_edges:
                            if ve.evidence_quote not in verified_quotes:
                                verified_quotes.insert(0, ve.evidence_quote)
                    except FuturesTimeoutError:
                        log.info("V-INT on candidate_edges timed out")

        # FIX-2: Carry forward verified new_edges from cached light finding if present
        if prior_finding is not None and prior_finding.new_edges:
            existing_new_ids = {e.edge_id for e in verified_new_edges}
            for pe in prior_finding.new_edges:
                if _is_customer_group_target(pe.target_name):
                    continue
                if pe.edge_id not in existing_new_ids:
                    verified_new_edges.append(pe)
                    existing_new_ids.add(pe.edge_id)
                    if pe.evidence_quote not in verified_quotes:
                        verified_quotes.insert(0, pe.evidence_quote)

        # F4 + FIX-14: A candidate edge in new_edges whose edge_id (or identical source/target/type/accession,
        # or unnamed_customer with same source/type/normalised quote) already exists in result.edges
        # counts as matching the existing edge, not new_evidence.
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
        existing_by_unnamed_quote: dict[tuple[str, str, str], VerifiedEdge] = {
            (
                e.source_company_key,
                e.edge_type,
                normalise_for_verify(e.evidence_quote).strip().casefold(),
            ): e
            for e in result.edges
        }
        refound_existing_ids: list[str] = []
        if verified_new_edges:
            truly_new_edges: list[VerifiedEdge] = []
            seen_new_unnamed_quotes: set[tuple[str, str, str]] = set()
            for ve in verified_new_edges:
                if _is_customer_group_target(ve.target_name):
                    continue
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
                unnamed_tup = (
                    ve.source_company_key,
                    ve.edge_type,
                    normalise_for_verify(ve.evidence_quote).strip().casefold(),
                )
                matched_existing = (
                    existing_by_id.get(ve.edge_id)
                    or existing_by_tuple.get(tup)
                    or existing_by_name_tuple.get(name_tup)
                    or (existing_by_unnamed_quote.get(unnamed_tup) if ve.target_kind == "unnamed_customer" else None)
                )
                if matched_existing is not None:
                    eid = matched_existing.edge_id
                    if (
                        not _is_same_as_initial_quote(ve.evidence_quote, matched_existing.evidence_quote)
                        and ve.evidence_quote not in corroborating_quotes
                    ):
                        corroborating_quotes.append(ve.evidence_quote)
                    if eid not in refound_existing_ids:
                        refound_existing_ids.append(eid)
                    if ve.interpretation is not None and ve.interpretation.status == "confirmed":
                        verified_interpretations[eid] = ve.interpretation
                        _RECENT_VERIFIED_INTERPRETATIONS[eid] = ve.interpretation
                else:
                    if ve.target_kind == "unnamed_customer":
                        if unnamed_tup in seen_new_unnamed_quotes:
                            continue
                        seen_new_unnamed_quotes.add(unnamed_tup)
                    truly_new_edges.append(ve)
            verified_new_edges = truly_new_edges

        # FIX-1 (1a): Non-circular confirmation requires a different passage in the filing OR a peer filing quote.
        has_corroboration = bool(corroborating_quotes)
        best_corroborating_quote = corroborating_quotes[0] if corroborating_quotes else ""

        confirmed_edge_ids: list[str] = []
        rejected_edge_ids: list[str] = []

        if item.item_kind == "flagged_edge" and item.edge is not None:
            edge = item.edge
            doc_text = filing.text if filing is not None else edge.evidence_quote
            budget = self._remaining_budget(
                run_started=run_started,
                item_started=item_started,
                total_timeout_s=total_timeout_override,
            )
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

            if outcome == "unresolved" or vint_interp is None:
                outcome = "unresolved"
                if vint_interp is not None and vint_interp.status != "confirmed":
                    verified_interpretations[edge.edge_id] = vint_interp
                    _RECENT_VERIFIED_INTERPRETATIONS[edge.edge_id] = vint_interp
                if outcome != model_outcome or not _explanation_matches_outcome(raw_explanation, outcome):
                    raw_explanation = ""
                if not raw_explanation:
                    raw_explanation = (
                        f'Filing context for "{edge.evidence_quote}" remains ambiguous or unresolved.'
                    )
            elif vint_interp.status == "rejected":
                verified_interpretations[edge.edge_id] = vint_interp
                _RECENT_VERIFIED_INTERPRETATIONS[edge.edge_id] = vint_interp
                outcome = "rejected"
                rejected_edge_ids = [edge.edge_id]
                if outcome != model_outcome or not _explanation_matches_outcome(raw_explanation, outcome):
                    raw_explanation = ""
                if not raw_explanation:
                    raw_explanation = (
                        f'Filing context "{edge.evidence_quote}" does not support an active supply dependency.'
                    )
            elif (
                vint_interp.status == "confirmed"
                and has_corroboration
                and (outcome in ("confirmed", "revised") or edge.edge_id in refound_existing_ids)
            ):
                verified_interpretations[edge.edge_id] = vint_interp
                _RECENT_VERIFIED_INTERPRETATIONS[edge.edge_id] = vint_interp
                outcome = "confirmed"
                confirmed_edge_ids = [edge.edge_id]
                if outcome != model_outcome or not _explanation_matches_outcome(raw_explanation, outcome):
                    raw_explanation = ""
                if not raw_explanation:
                    raw_explanation = (
                        f'Verified corroborating passage "{best_corroborating_quote}" confirms the operational dependency.'
                    )
            else:
                if vint_interp.status == "flagged":
                    verified_interpretations[edge.edge_id] = vint_interp
                    _RECENT_VERIFIED_INTERPRETATIONS[edge.edge_id] = vint_interp
                outcome = "unresolved"
                if outcome != model_outcome or not _explanation_matches_outcome(raw_explanation, outcome):
                    raw_explanation = ""
                if not raw_explanation or not has_corroboration:
                    is_hypo = (vint_interp is not None and "hypothetical" in vint_interp.flags) or (
                        edge.interpretation is not None and "hypothetical" in edge.interpretation.flags
                    )
                    if is_hypo:
                        raw_explanation = (
                            f'Filing context "{edge.evidence_quote}" describes a prospective or uncompleted arrangement and remains unresolved.'
                        )
                    else:
                        raw_explanation = (
                            f'Filing context "{edge.evidence_quote}" remains uncorroborated by an independent passage and is unresolved.'
                        )

        elif item.item_kind == "single_source" and item.edge is not None:
            edge = item.edge
            edge_is_confirmed = edge.interpretation is not None and edge.interpretation.status == "confirmed"
            if verified_new_edges:
                outcome = "new_evidence"
                if edge_is_confirmed and has_corroboration:
                    confirmed_edge_ids = [edge.edge_id]
                if outcome != model_outcome or not _explanation_matches_outcome(raw_explanation, outcome):
                    raw_explanation = (
                        f'Extracted verified dependency disclosure "{verified_new_edges[0].evidence_quote}".'
                    )
            elif (
                has_corroboration
                and edge_is_confirmed
                and (outcome in ("confirmed", "revised") or edge.edge_id in refound_existing_ids)
            ):
                outcome = "confirmed"
                if edge.edge_id not in confirmed_edge_ids:
                    confirmed_edge_ids.append(edge.edge_id)
                if outcome != model_outcome or not _explanation_matches_outcome(raw_explanation, outcome):
                    raw_explanation = ""
                if not raw_explanation:
                    raw_explanation = (
                        f'Verified sole-source disclosure "{best_corroborating_quote}" in the annual report.'
                    )
            else:
                outcome = "unresolved"
                if outcome != model_outcome or not _explanation_matches_outcome(raw_explanation, outcome):
                    raw_explanation = ""
                if not raw_explanation or not has_corroboration:
                    raw_explanation = (
                        f'Initial disclosure "{edge.evidence_quote}" was not corroborated by a second passage or peer filing.'
                    )

        elif item.item_kind == "unresolved_counterparty" and item.edge is not None:
            edge = item.edge
            edge_is_confirmed = edge.interpretation is not None and edge.interpretation.status == "confirmed"
            resolved_key = resolver(edge.target_name)
            if resolved_key is not None and outcome != "unresolved":
                outcome = "revised"
                if edge_is_confirmed:
                    confirmed_edge_ids = [edge.edge_id]
                if outcome != model_outcome or not _explanation_matches_outcome(raw_explanation, outcome):
                    raw_explanation = ""
                if not raw_explanation:
                    raw_explanation = (
                        f'Resolved counterparty identity for "{edge.evidence_quote}" against portfolio records.'
                    )
            elif (
                has_corroboration
                and edge_is_confirmed
                and (outcome in ("confirmed", "revised") or edge.edge_id in refound_existing_ids)
            ):
                outcome = "confirmed"
                if edge.edge_id not in confirmed_edge_ids:
                    confirmed_edge_ids.append(edge.edge_id)
                if outcome != model_outcome or not _explanation_matches_outcome(raw_explanation, outcome):
                    raw_explanation = ""
                if not raw_explanation:
                    raw_explanation = (
                        f'Verified external counterparty disclosure "{best_corroborating_quote}" in the filing.'
                    )
            else:
                outcome = "unresolved"
                if outcome != model_outcome or not _explanation_matches_outcome(raw_explanation, outcome):
                    raw_explanation = ""
                if not raw_explanation or not has_corroboration:
                    raw_explanation = (
                        f'Counterparty in "{edge.evidence_quote}" remains unresolved as an external entity.'
                    )

        elif item.item_kind in ("no_disclosures", "undisclosed_customer"):
            if verified_new_edges:
                outcome = "new_evidence"
                if (
                    not raw_explanation
                    or outcome != model_outcome
                    or not _explanation_matches_outcome(raw_explanation, outcome)
                    or "no additional" in raw_explanation.lower()
                    or "undisclosed" in raw_explanation.lower()
                ):
                    raw_explanation = (
                        f'Extracted verified dependency disclosure "{verified_new_edges[0].evidence_quote}".'
                    )
            elif (
                has_corroboration
                and item.edge is not None
                and item.edge.interpretation is not None
                and item.edge.interpretation.status == "confirmed"
                and (outcome in ("confirmed", "revised") or item.edge.edge_id in refound_existing_ids)
            ):
                outcome = "confirmed"
                if item.edge.edge_id not in confirmed_edge_ids:
                    confirmed_edge_ids.append(item.edge.edge_id)
                if outcome != model_outcome or not _explanation_matches_outcome(raw_explanation, outcome):
                    raw_explanation = ""
                if not raw_explanation:
                    raw_explanation = (
                        f'Confirmed customer concentration disclosure "{best_corroborating_quote}" in the filing.'
                    )
            else:
                outcome = "unresolved"
                if outcome != model_outcome or not _explanation_matches_outcome(raw_explanation, outcome):
                    raw_explanation = ""
                if not raw_explanation or not has_corroboration:
                    raw_explanation = (
                        "Filing leaves specific counterparty identities undisclosed in the inspected sections."
                    )

        if has_corroboration:
            for refound_id in refound_existing_ids:
                if refound_id not in rejected_edge_ids and refound_id not in confirmed_edge_ids:
                    confirmed_edge_ids.append(refound_id)

        # FIX-2: Preserve confirmed_edge_ids from cached light finding if not rejected
        if prior_finding is not None and outcome != "rejected":
            for cid in prior_finding.confirmed_edge_ids:
                if cid not in rejected_edge_ids and cid not in confirmed_edge_ids:
                    confirmed_edge_ids.append(cid)
            if outcome == "unresolved" and prior_finding.outcome in ("confirmed", "revised", "new_evidence"):
                outcome = "new_evidence" if verified_new_edges else prior_finding.outcome
                if prior_finding.explanation:
                    raw_explanation = prior_finding.explanation
                    for pq in re.findall(r'"([^"]+)"', prior_finding.explanation):
                        if pq not in verified_quotes:
                            verified_quotes.append(pq)

        # FIX-22: Ensure budget stops always surface "Not finished in time: ..." instead of generic unresolved text
        if timed_out and outcome == "unresolved":
            raw_explanation = "Not finished in time: research step budget expired before completing verification."

        clean_explanation = strip_unquoted_numbers(raw_explanation, verified_quotes)

        if len(steps) < effective_max_steps:
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
                index=effective_max_steps,
                action="conclude",
                query=item.target_name or item.subject_name,
                summary=clean_explanation,
                filing=filing_ref,
            )

        return _sanitize_finding(
            ResearchFinding(
                finding_id=item.item_id,
                kind=item.item_kind,
                subject=item.subject_label,
                question=item.question,
                outcome=outcome,
                explanation=clean_explanation,
                steps=steps[:effective_max_steps],
                confirmed_edge_ids=confirmed_edge_ids,
                rejected_edge_ids=rejected_edge_ids,
                new_edges=verified_new_edges,
            )
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
        exclude_initial_quote: bool = False,
    ) -> list[str]:
        needle = normalise_for_verify(phrase).strip().casefold()
        if not needle or filing is None or not filing.text:
            return []

        initial_quote = (
            item.edge.evidence_quote
            if item.edge is not None
            and item.edge.evidence_quote
            and filing.accession == item.edge.filing.accession
            else None
        )
        norm_doc = normalise_for_verify(filing.text)
        raw_sentences = [
            normalise_for_verify(s).strip()
            for s in re.split(r"(?<=[.!?])\s+|\n+", filing.text)
            if normalise_for_verify(s).strip()
            and not re.match(r"^item\s+\d+[a-z]?\b", normalise_for_verify(s).strip(), re.IGNORECASE)
        ]

        distinct_spans: list[str] = []
        initial_spans: list[str] = []

        for idx, sent in enumerate(raw_sentences):
            sent_cf = sent.casefold()
            if needle not in sent_cf:
                continue

            is_initial = _is_same_as_initial_quote(sent, initial_quote)
            if is_initial and exclude_initial_quote:
                continue

            # F3: Require the queried phrase, derive ±1 sentence of context around the actual match,
            # and verify via find_quote_span against Filing.text.
            prev_s = raw_sentences[idx - 1] if idx > 0 else ""
            next_s = raw_sentences[idx + 1] if idx + 1 < len(raw_sentences) else ""
            if not is_initial and initial_quote:
                if _is_same_as_initial_quote(prev_s, initial_quote):
                    prev_s = ""
                if _is_same_as_initial_quote(next_s, initial_quote):
                    next_s = ""

            candidates = [
                " ".join(p for p in (prev_s, sent, next_s) if p),
                " ".join(p for p in (sent, next_s) if p),
                " ".join(p for p in (prev_s, sent) if p),
                sent,
            ]
            chosen: str | None = None
            for cand in candidates:
                if (
                    20 <= len(cand) <= 360
                    and find_quote_span(cand, norm_doc, already_normalised_doc=True) is not None
                    and verify_quote(cand, norm_doc, already_normalised_doc=True)
                ):
                    chosen = cand
                    break
            if chosen is None and len(sent) > 360:
                pos = sent_cf.find(needle)
                win_start = max(0, pos - 120)
                win_end = min(len(sent), win_start + 300)
                window = sent[win_start:win_end].strip()
                if (
                    20 <= len(window) <= 360
                    and find_quote_span(window, norm_doc, already_normalised_doc=True) is not None
                    and verify_quote(window, norm_doc, already_normalised_doc=True)
                ):
                    chosen = window

            target_list = initial_spans if is_initial else distinct_spans
            if chosen and chosen not in target_list:
                target_list.append(chosen)
            if (
                sent != chosen
                and 20 <= len(sent) <= 360
                and sent not in target_list
                and find_quote_span(sent, norm_doc, already_normalised_doc=True) is not None
            ):
                target_list.append(sent)
            if len(distinct_spans) >= 3:
                break

        combined = list(distinct_spans)
        if not exclude_initial_quote:
            for sp in initial_spans:
                if sp not in combined:
                    combined.append(sp)
        return combined[:3]

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

        initial_quote = (
            item.edge.evidence_quote
            if item.edge is not None
            and item.edge.evidence_quote
            and filing.accession == item.edge.filing.accession
            else None
        )
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
        target_distinct: list[str] = []
        keyword_distinct: list[str] = []
        initial_matches: list[str] = []
        target_name = item.target_name or (item.edge.target_name if item.edge is not None else None)

        for sent in sentences:
            sent_lower = sent.lower()
            mentions_target = _span_mentions_target(sent, target_name)
            has_kw = any(kw in sent_lower for kw in _DEPENDENCY_KEYWORDS) or bool(_PERCENT_NUMBER_RE.search(sent))
            if not (mentions_target or has_kw):
                continue
            if not verify_quote(sent, norm_doc, already_normalised_doc=True):
                continue
            clean_sent = normalise_for_verify(sent)
            if _is_same_as_initial_quote(clean_sent, initial_quote):
                if clean_sent not in initial_matches:
                    initial_matches.append(clean_sent)
            elif mentions_target:
                if clean_sent not in target_distinct:
                    target_distinct.append(clean_sent)
                    if len(target_distinct) >= 3:
                        break
            else:
                if clean_sent not in keyword_distinct:
                    keyword_distinct.append(clean_sent)

        out: list[str] = []
        for s in (*target_distinct, *keyword_distinct, *initial_matches):
            if s not in out:
                out.append(s)
                if len(out) >= 3:
                    break
        return out

    def _search_across_filings(
        self,
        phrase: str,
        *,
        exclude_cik: str,
        item: ResearchItem,
        result: DependencyResult,
        analysis: AnalysisResponse,
        resolver: Callable[[str], str | None] | None = None,
        cache_only: bool,
    ) -> tuple[list[str], list[str]]:
        spans: list[str] = []
        peer_names: list[str] = []
        needle = phrase.strip().lower()
        subj_clean = clean_company_name(item.subject_name) or item.subject_name

        # 1. Check existing edges from OTHER companies in result.edges
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

        # 2. If the edge's counterparty resolves to a CIK (e.g. TSMC's 20-F for Broadcom->TSMC),
        # check the counterparty's own filing directly.
        counterparty_cik: str | None = None
        if item.edge is not None:
            cp_key = item.edge.target_key or (resolver(item.edge.target_name) if resolver else None)
            counterparty_cik = _extract_cik_from_key(cp_key)
        if counterparty_cik is None and resolver is not None and phrase.strip():
            counterparty_cik = _extract_cik_from_key(resolver(phrase.strip()))
        if counterparty_cik and counterparty_cik != exclude_cik:
            cp_filing = self._load_filing_by_cik(counterparty_cik)
            if cp_filing is not None and cp_filing.text:
                cp_queries = [
                    q
                    for q in (
                        subj_clean,
                        phrase.strip(),
                        clean_company_name(item.target_name or ""),
                        "customer",
                        "foundry",
                        "wafer",
                    )
                    if q
                ]
                for cp_q in cp_queries:
                    matches = self._find_spans_in_filing(cp_filing, cp_q, item=item, result=result)
                    for m in matches:
                        if m not in spans:
                            spans.append(m)
                            peer_names.append(f"CIK:{counterparty_cik}")
                            if len(spans) >= 3:
                                return spans, peer_names
                    if spans:
                        break

        # 3. Check all already-loaded peer filings in _filings_by_key and _filings_by_cik
        seen_peer_ciks: set[str] = {exclude_cik}
        for key, peer_filing in list(self._filings_by_key.items()):
            peer_cik = str(peer_filing.cik).zfill(10) if peer_filing.cik else ""
            if key == item.subject_key or peer_cik == exclude_cik or not peer_filing.text:
                continue
            if peer_cik:
                seen_peer_ciks.add(peer_cik)
            for q_cand in (phrase, subj_clean):
                if not q_cand:
                    continue
                matches = self._find_spans_in_filing(peer_filing, q_cand, item=item, result=result)
                for m in matches:
                    if m not in spans:
                        spans.append(m)
                        peer_names.append(key)
                        if len(spans) >= 3:
                            return spans, peer_names
                if spans:
                    break

        for peer_cik, peer_filing in list(self._filings_by_cik.items()):
            if peer_cik in seen_peer_ciks or not peer_filing.text:
                continue
            seen_peer_ciks.add(peer_cik)
            for q_cand in (phrase, subj_clean):
                if not q_cand:
                    continue
                matches = self._find_spans_in_filing(peer_filing, q_cand, item=item, result=result)
                for m in matches:
                    if m not in spans:
                        spans.append(m)
                        peer_names.append(f"CIK:{peer_cik}")
                        if len(spans) >= 3:
                            return spans, peer_names
                if spans:
                    break

        # 4. Search other companies' filings via EDGAR full-text search (never fall back to own_filing)
        if self.fetcher is not None and phrase.strip() and not cache_only:
            try:
                peer_filings = self.fetcher.names_in_other_filings(
                    phrase.strip(),
                    exclude_cik=exclude_cik if exclude_cik != "0000000000" else None,
                    limit=2,
                )
                for pf in peer_filings:
                    pf_cik = str(pf.cik).zfill(10)
                    if pf_cik == exclude_cik:
                        continue
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

        return spans, peer_names

    @staticmethod
    def _build_step_prompt(
        *,
        item: ResearchItem,
        cik: str,
        step_idx: int,
        observations: Sequence[str],
        max_steps: int = MAX_RESEARCH_STEPS,
        min_tool_calls: int = 2,
        require_search_filings: bool = False,
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
            f"MAX_STEPS: {max_steps}\n"
            f"MIN_TOOL_CALLS: {min_tool_calls}\n"
            f"REQUIRE_SEARCH_FILINGS: {'true' if require_search_filings else 'false'}\n"
            f"ITEM_ID: {item.item_id}\n"
            f"ITEM_KIND: {item.item_kind}\n"
            f"SUBJECT_KEY: {item.subject_key}\n"
            f"SUBJECT_NAME: {item.subject_name}\n"
            f"SUBJECT_CIK: {cik}\n"
            f"TARGET_NAME: {item.target_name or 'None'}\n"
            f"{edge_block}\n\n"
            f"OBSERVATIONS:\n{obs_block}\n"
        )

    @classmethod
    def _deterministic_step_decision(
        cls,
        *,
        item: ResearchItem,
        cik: str,
        step_idx: int,
        verified_quotes: Sequence[str],
        observations: Sequence[str],
        has_api_key: bool = True,
        min_tool_calls: int = 2,
        require_search_filings: bool = False,
        steps: Sequence[ResearchStep] = (),
    ) -> dict[str, Any]:
        used_actions = {s.action for s in steps}
        needs_more_tools = len(steps) < min_tool_calls or (
            require_search_filings and "search_filings" not in used_actions
        )
        if needs_more_tools:
            return cls._next_complementary_tool_decision(
                item=item,
                cik=cik,
                steps=steps,
                require_search_filings=require_search_filings,
                min_tool_calls=min_tool_calls,
            )

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
                "outcome": "confirmed" if best_quote else "unresolved",
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
                "outcome": "confirmed" if best_quote else "unresolved",
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


def research_company(
    company: CompanyExposure,
    filing: FilingRef | Filing | None,
    edges: Sequence[VerifiedEdge],
    *,
    depth: ResearchDepthOption = "light",
    cache_only: bool = False,
    progress: Callable[..., None] | None = None,
    on_step: Callable[[int, int, ResearchStep | None, ResearchFinding | None], None] | None = None,
    analysis: AnalysisResponse | None = None,
    portfolio: Sequence[CompanyExposure] | None = None,
    resolve_target_key: Callable[[str], str | None] | None = None,
    filing_obj: Filing | None = None,
    loop: ResearchLoop | None = None,
    client: Any = None,
    fetcher: FilingFetcher | None = None,
    cache: ExtractionCache | None = None,
    disk_cache: DiskCache | None = None,
    aliases: Aliases | None = None,
    filings_by_key: Mapping[str, Filing] | None = None,
) -> CompanyResearch:
    """Top-level per-company agentic research helper for v3.1 (A1 <-> A2/A3 seam)."""
    runner = loop or ResearchLoop(
        client=client,
        fetcher=fetcher,
        cache=cache,
        disk_cache=disk_cache,
        aliases=aliases,
        filings_by_key=filings_by_key,
    )
    return runner.research_company(
        company,
        filing,
        edges,
        depth=depth,
        cache_only=cache_only,
        progress=progress,
        on_step=on_step,
        analysis=analysis,
        portfolio=portfolio,
        resolve_target_key=resolve_target_key,
        filing_obj=filing_obj,
    )
