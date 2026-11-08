"""Deterministic matching between predicted VerifiedEdges and gold relationships/negatives (package E-RUN).

Owner: Bekarys's Gemini (E-RUN).
Rules (docs/hoc/PLAN-v3.md §1 & docs/hoc/eval/ADJUDICATION.md):
- A predicted edge matches a gold relationship when it has the same company, a matching target
  (`name_key(target)` against `target_name` or any entry in `aliases[]`, or the same canonical ISO-2
  country for facility/country items including explicit `gold.country`), and a compatible `edge_type`
  (including `edge_type_alternatives[]`).
- Compatible edge_type pairs:
  1. Exact match against `gold.edge_type` or any type in `gold.edge_type_alternatives`
  2. `supplier` / `key_input` / sole-source `supplier`
  3. `foundry` / `contract_manufacturer`
- `tier`: `'core'` counts for recall (missing = FN); `'extended'` is optional (matching prediction = TP,
  missing prediction is not an FN). Core relationships are prioritized first in 1-to-1 matching.
- A prediction matching a `GoldNegative` is always a false positive and never pooled.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from hoc.contract.dependencies import EdgeType, ImportanceTier, VerifiedEdge
from hoc.eval.schema import (
    EdgeMatchDetail,
    EvalErrorDetail,
    GoldDirection,
    GoldDocument,
    GoldNegative,
    GoldRelationship,
    PooledCandidate,
)
from hoc.filings.names import MANUAL, name_key
from hoc.filings.text import normalise
from hoc.graph.metrics import FACILITY_TARGET_KINDS, canonical_country_info

_SUPPLIER_COMPAT_GROUP: frozenset[str] = frozenset({"supplier", "key_input"})
_FOUNDRY_CM_COMPAT_GROUP: frozenset[str] = frozenset({"foundry", "contract_manufacturer"})
_TRAILING_PAREN_RE = re.compile(r"\s*\([^()]*\)\s*$")
_HOLDING_SUFFIX_TOKENS: frozenset[str] = frozenset({"holdings", "holding", "group"})
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

_EXTRA_COUNTRY_FALLBACKS: tuple[tuple[str, str], ...] = (
    ("waterloo, iowa", "US"),
    ("türkiye", "TR"),
    ("turkiye", "TR"),
    ("cambodia", "KH"),
    ("phnom penh", "KH"),
    ("nanchang", "CN"),
)

_POOLED_REJECTED_REASONS: dict[str, str] = {
    "edge_d3ccd3a1052a": "Pooled review: reject — customer group ('three largest customers outside the US'), not one counterparty (policy 3)",
    "edge_db8132253be5": "Pooled review: reject — Air Manufacturing Innovation is a wholly-owned Nike subsidiary, not an external supplier",
    "edge_55810b619d12": "Pooled review: reject — Sojitz America provides import-export financing and holds preferred stock; not a supply dependency",
    "edge_83e00ad1aec8": "Pooled review: reject — Takata appears only in an industry-wide NHTSA study; filing does not state Takata supplies Ford",
}

_SOLE_SOURCE_CUES: tuple[str, ...] = (
    "sole source",
    "sole-source",
    "single source",
    "single-source",
    "only supplier",
    "sole supplier",
    "single supplier",
    "exclusively from",
    "no alternative",
)
_FOUNDRY_FAB_CUES: tuple[str, ...] = (
    "foundry",
    "foundries",
    "wafer",
    "wafers",
    "fab",
    "fabrication",
)
_STRONG_DEPENDENCY_CUES: tuple[str, ...] = (
    "substantially all",
    "primary",
    "principal",
    "majority",
    "significant portion",
    "critical",
    "key supplier",
)


def canonical_eval_name_key(raw_name: str) -> str:
    """Normalise a target name via `hoc.filings.names.name_key` + `MANUAL` alias table."""
    base = name_key(raw_name)
    mapped = MANUAL.get(base, base)
    return name_key(mapped)


def _strip_holding_tokens(norm_key: str) -> str:
    words = norm_key.split()
    while len(words) > 1 and words[-1] in _HOLDING_SUFFIX_TOKENS:
        words.pop()
    return " ".join(words)


def targets_match_name(pred_name: str, gold_name: str) -> bool:
    """Deterministic target name match using `name_key` + `MANUAL` + parenthetical/holding stripping."""
    k_pred = canonical_eval_name_key(pred_name)
    k_gold = canonical_eval_name_key(gold_name)
    if not k_pred or not k_gold:
        return False
    if k_pred == k_gold:
        return True
    s_pred = _strip_holding_tokens(k_pred)
    s_gold = _strip_holding_tokens(k_gold)
    if s_pred == s_gold:
        return True
    if len(k_gold) >= 4 and len(k_pred) >= 4 and (
        k_pred.startswith(f"{k_gold} of ")
        or k_gold.startswith(f"{k_pred} of ")
        or s_pred.startswith(f"{s_gold} of ")
        or s_gold.startswith(f"{s_pred} of ")
    ):
        return True
    pred_no_paren = canonical_eval_name_key(_TRAILING_PAREN_RE.sub("", pred_name))
    gold_no_paren = canonical_eval_name_key(_TRAILING_PAREN_RE.sub("", gold_name))
    return bool(
        pred_no_paren
        and gold_no_paren
        and (
            pred_no_paren == gold_no_paren
            or _strip_holding_tokens(pred_no_paren) == _strip_holding_tokens(gold_no_paren)
        )
    )


def _fallback_country_code(*texts: str | None) -> str | None:
    for text in texts:
        if not text:
            continue
        low = text.casefold()
        for phrase, code in _EXTRA_COUNTRY_FALLBACKS:
            if phrase in low:
                return code
    return None


def resolve_gold_country(rel: GoldRelationship) -> str | None:
    """Resolve ISO-2 country code for a gold relationship (preferring explicit `rel.country`)."""
    if rel.country and rel.country.strip():
        return rel.country.strip().upper()
    fb = _fallback_country_code(rel.target_name, rel.qualifier)
    if fb is not None:
        return fb
    info = canonical_country_info(
        rel.target_name,
        target_key=None,
        qualifier=rel.qualifier,
        evidence_quote=None,
    )
    if info is not None:
        return info[0]
    info_with_quote = canonical_country_info(
        rel.target_name,
        target_key=None,
        qualifier=rel.qualifier,
        evidence_quote=rel.quote,
    )
    if info_with_quote is not None:
        return info_with_quote[0]
    return _fallback_country_code(rel.quote)


def resolve_pred_country(edge: VerifiedEdge) -> str | None:
    """Resolve ISO-2 country code for a predicted VerifiedEdge when applicable."""
    fb = _fallback_country_code(edge.target_name, edge.qualifier)
    if fb is not None:
        return fb
    info = canonical_country_info(
        edge.target_name,
        target_key=edge.target_key,
        qualifier=edge.qualifier,
        evidence_quote=None,
    )
    if info is not None:
        return info[0]
    info_with_quote = canonical_country_info(
        edge.target_name,
        target_key=edge.target_key,
        qualifier=edge.qualifier,
        evidence_quote=edge.evidence_quote,
    )
    if info_with_quote is not None:
        return info_with_quote[0]
    return _fallback_country_code(edge.evidence_quote)


def _extract_percentages(text: str | None) -> set[str]:
    if not text:
        return set()
    return {m.group(1) for m in _PCT_RE.finditer(text)}


def targets_match(pred: VerifiedEdge, gold: GoldRelationship) -> bool:
    """Return True if `pred` and `gold` refer to the same target entity, alias, facility country,
    or unnamed customer."""
    # 1. Unnamed customer match (percentage overlap or quote overlap checked before placeholder name)
    if gold.target_kind == "unnamed_customer" or pred.target_kind == "unnamed_customer":
        gold_pcts = (
            _extract_percentages(gold.qualifier)
            | _extract_percentages(gold.quote)
            | _extract_percentages(gold.notes)
        )
        pred_pcts = _extract_percentages(pred.qualifier) | _extract_percentages(pred.evidence_quote)
        if gold.target_kind != "unnamed_customer" or pred.target_kind != "unnamed_customer":
            return bool(
                gold_pcts
                and pred_pcts
                and (gold_pcts & pred_pcts)
                and _quotes_overlap(pred.evidence_quote, gold.quote)
            )
        if gold_pcts and pred_pcts:
            return bool(gold_pcts & pred_pcts)
        return True

    # 2. Facility / country canonical ISO-2 country match (checked before name match when explicit gold.country is set)
    is_facility_or_country = (
        bool(gold.country)
        or gold.edge_type == "facility"
        or pred.edge_type == "facility"
        or gold.target_kind in FACILITY_TARGET_KINDS
        or pred.target_kind in FACILITY_TARGET_KINDS
    )
    if is_facility_or_country:
        gold_country = resolve_gold_country(gold)
        pred_country = resolve_pred_country(pred)
        if gold_country is not None and pred_country is not None:
            return gold_country == pred_country

    # 3. Exact canonical name_key match against target_name or any adjudicated alias
    if targets_match_name(pred.target_name, gold.target_name):
        return True
    return any(targets_match_name(pred.target_name, alias) for alias in gold.aliases)


def _single_pair_compatible(
    pred_type: EdgeType,
    gold_type: EdgeType,
    *,
    pred_sole_source: bool = False,
    gold_sole_source: bool | None = None,
) -> bool:
    if pred_type == gold_type:
        return True
    if pred_type in _SUPPLIER_COMPAT_GROUP and gold_type in _SUPPLIER_COMPAT_GROUP:
        return True
    if pred_type in _FOUNDRY_CM_COMPAT_GROUP and gold_type in _FOUNDRY_CM_COMPAT_GROUP:
        return True
    return bool(
        (pred_sole_source or bool(gold_sole_source))
        and pred_type in (_SUPPLIER_COMPAT_GROUP | _FOUNDRY_CM_COMPAT_GROUP)
        and gold_type in _SUPPLIER_COMPAT_GROUP
    )


def compatible_edge_types(
    pred_type: EdgeType,
    gold_type: EdgeType,
    *,
    pred_sole_source: bool = False,
    gold_sole_source: bool | None = None,
    gold_alternatives: Iterable[EdgeType] = (),
) -> bool:
    """Check whether `pred_type` and `gold_type` (or any type in `gold_alternatives`) are compatible."""
    if _single_pair_compatible(
        pred_type,
        gold_type,
        pred_sole_source=pred_sole_source,
        gold_sole_source=gold_sole_source,
    ):
        return True
    return any(
        _single_pair_compatible(
            pred_type,
            alt,
            pred_sole_source=pred_sole_source,
            gold_sole_source=gold_sole_source,
        )
        for alt in gold_alternatives
    )


def infer_edge_direction(
    edge: VerifiedEdge,
    *,
    evaluated_company_key: str | None = None,
) -> GoldDirection:
    """Infer relationship direction relative to the evaluated company (`depends_on_target` vs `target_depends_on_company`)."""
    if (
        evaluated_company_key
        and edge.source_company_key != evaluated_company_key
        and edge.target_key == evaluated_company_key
    ):
        if edge.edge_type == "customer":
            return "depends_on_target"
        return "target_depends_on_company"
    if edge.edge_type == "customer":
        return "target_depends_on_company"
    return "depends_on_target"


def fallback_importance_tier(edge: VerifiedEdge) -> ImportanceTier:
    """Deterministic importance tier fallback implementing PLAN-v3.md §4 (R-IMP) rules when
    `edge.importance` is None and `hoc.graph.importance` is not yet wired."""
    quote_lower = normalise(edge.evidence_quote).casefold()
    qual_lower = normalise(edge.qualifier or "").casefold()
    combined = f"{qual_lower} {quote_lower}".strip()

    score = 0.30
    if edge.sole_source or any(cue in combined for cue in _SOLE_SOURCE_CUES):
        score = max(score, 0.95)

    for m in _PCT_RE.finditer(combined):
        try:
            pct = float(m.group(1))
        except ValueError:
            continue
        if 10.0 <= pct <= 100.0:
            score = max(score, min(1.0, 0.5 + pct / 100.0))

    if edge.edge_type == "foundry" or any(cue in combined for cue in _FOUNDRY_FAB_CUES):
        score = max(score, 0.75)

    if any(cue in combined for cue in _STRONG_DEPENDENCY_CUES):
        score = max(score, 0.70)

    sec_lower = edge.section.strip().casefold()
    is_risk_factors_only = sec_lower in {"1a", "item 1a", "3d", "item 3.d"}

    if score <= 0.30 and not is_risk_factors_only:
        if edge.edge_type in {
            "supplier",
            "customer",
            "contract_manufacturer",
            "jv_partner",
            "key_input",
        }:
            score = max(score, 0.50)
        elif edge.edge_type == "facility":
            score = max(score, 0.45)

    if score >= 0.80:
        tier: ImportanceTier = "critical"
    elif score >= 0.60:
        tier = "high"
    elif score >= 0.40:
        tier = "medium"
    else:
        tier = "low"

    if (
        edge.interpretation is not None
        and edge.interpretation.status == "flagged"
        and tier in {"critical", "high"}
    ):
        tier = "medium"
    return tier


def resolve_edge_importance_tier(edge: VerifiedEdge) -> ImportanceTier:
    """Return `edge.importance.tier` if populated, else call `hoc.graph.importance.score_edge_importance`
    if available, else deterministic `fallback_importance_tier`."""
    if edge.importance is not None:
        return edge.importance.tier
    try:
        from hoc.graph.importance import score_edge_importance  # type: ignore[import-not-found]

        scored = score_edge_importance(edge)
        if scored is not None and getattr(scored, "tier", None) in {"critical", "high", "medium", "low"}:
            return scored.tier
    except (ImportError, AttributeError, TypeError, ValueError):
        return fallback_importance_tier(edge)
    return fallback_importance_tier(edge)


def _quotes_overlap(quote_a: str, quote_b: str) -> bool:
    na = normalise(quote_a).casefold()
    nb = normalise(quote_b).casefold()
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(shorter) >= 40:
        step = max(1, len(shorter) // 4)
        for start in range(0, len(shorter) - 39, step):
            if shorter[start : start + 40] in longer:
                return True
    return False


def edge_matches_negative(
    edge: VerifiedEdge,
    neg: GoldNegative,
    *,
    is_matched_positive: bool = False,
) -> bool:
    """Return True if `edge` falsely extracted the hard negative `neg`."""
    name_matches = targets_match_name(edge.target_name, neg.target_name)
    quote_overlaps = _quotes_overlap(edge.evidence_quote, neg.quote)
    if is_matched_positive:
        return name_matches and quote_overlaps
    if name_matches:
        return True
    return bool(
        neg.kind in {"negated", "generic"}
        and edge.target_kind == "unnamed_customer"
        and quote_overlaps
    )


@dataclass
class SinglePassMatchResult:
    """Result of matching one set of predicted edges (e.g., before V-INT or after V-INT) against a GoldDocument."""

    matches: list[EdgeMatchDetail] = field(default_factory=list)
    matched_gold_ids: set[str] = field(default_factory=set)
    matched_core_gold_ids: set[str] = field(default_factory=set)
    matched_extended_gold_ids: set[str] = field(default_factory=set)
    matched_edge_ids: set[str] = field(default_factory=set)
    unmatched_edges: list[VerifiedEdge] = field(default_factory=list)
    unmatched_gold: list[GoldRelationship] = field(default_factory=list)
    unmatched_core_gold: list[GoldRelationship] = field(default_factory=list)
    unmatched_extended_gold: list[GoldRelationship] = field(default_factory=list)
    triggered_negatives: list[tuple[GoldNegative, VerifiedEdge]] = field(default_factory=list)
    facility_country_correct: int = 0
    facility_country_total: int = 0

    @property
    def tp_total(self) -> int:
        """Number of matched predicted edges (numerator for Precision: `tp_total / (tp_total + fp)`)."""
        return len(self.matched_edge_ids)

    @property
    def tp_core(self) -> int:
        """Number of unique matched `'core'` gold relationships (numerator for Recall; never double-counts)."""
        return len(self.matched_core_gold_ids)

    @property
    def tp_extended(self) -> int:
        """Number of unique matched `'extended'` gold relationships."""
        return len(self.matched_extended_gold_ids)


def match_predictions_to_gold(
    predicted_edges: Sequence[VerifiedEdge],
    gold_doc: GoldDocument,
) -> SinglePassMatchResult:
    """Perform deterministic matching between `predicted_edges` and `gold_doc`.

    Rules (docs/hoc/PLAN-v3.md §1 & docs/hoc/eval/ADJUDICATION.md):
    1. Any prediction matching a `GoldNegative` is always a false positive (never matches a positive item).
    2. Core relationships (`tier == 'core'`) are matched before extended relationships (`tier == 'extended'`).
    3. Exact `edge_type` matches (or `edge_type_alternatives`) and quote-overlapping matches are prioritized.
    4. Multiple predicted edges matching the same gold relationship (e.g., multiple plants in the same
       country matching a country-level facility gold item) count as matched predictions for Precision
       (not false positives), while each gold relationship is counted at most once for Recall (never
       double-counting recall).
    5. Unmatched `'extended'` gold items are optional and do not count as false negatives (`unmatched_core_gold` = FN).
    """
    ticker = gold_doc.company.ticker.upper()
    company_key = gold_doc.company.company_key
    result = SinglePassMatchResult()

    # Step 1: Identify predictions that match a GoldNegative (always an FP)
    negative_edge_indices: set[int] = set()
    for neg in gold_doc.negatives:
        for p_idx, edge in enumerate(predicted_edges):
            if edge_matches_negative(edge, neg, is_matched_positive=False):
                result.triggered_negatives.append((neg, edge))
                negative_edge_indices.add(p_idx)
                break

    # Step 2: Build candidate bipartite pairs for non-negative predictions
    candidate_pairs: list[tuple[int, int, int, int, int, int]] = []
    # Tuple of (core_rank, exact_rank, primary_name_rank, quote_overlap_rank, gold_idx, pred_idx)
    for g_idx, rel in enumerate(gold_doc.relationships):
        core_rank = 0 if rel.tier == "core" else 1
        for p_idx, edge in enumerate(predicted_edges):
            if p_idx in negative_edge_indices:
                continue
            if not compatible_edge_types(
                edge.edge_type,
                rel.edge_type,
                pred_sole_source=edge.sole_source,
                gold_sole_source=rel.sole_source,
                gold_alternatives=rel.edge_type_alternatives,
            ):
                continue
            if not targets_match(edge, rel):
                continue
            exact_rank = (
                0
                if (edge.edge_type == rel.edge_type or edge.edge_type in rel.edge_type_alternatives)
                else 1
            )
            primary_name_rank = 0 if targets_match_name(edge.target_name, rel.target_name) else 1
            overlap_rank = 0 if _quotes_overlap(edge.evidence_quote, rel.quote) else 1
            candidate_pairs.append(
                (core_rank, exact_rank, primary_name_rank, overlap_rank, g_idx, p_idx)
            )

    candidate_pairs.sort()

    used_gold: set[int] = set()
    used_pred: set[int] = set()

    def _record_match(g_idx: int, p_idx: int, exact_rank: int, *, is_primary: bool) -> None:
        rel = gold_doc.relationships[g_idx]
        edge = predicted_edges[p_idx]
        result.matched_gold_ids.add(rel.id)
        if rel.tier == "core":
            result.matched_core_gold_ids.add(rel.id)
        else:
            result.matched_extended_gold_ids.add(rel.id)
        result.matched_edge_ids.add(edge.edge_id)

        pred_dir = infer_edge_direction(edge, evaluated_company_key=company_key)
        dir_ok = pred_dir == rel.direction
        pred_imp = resolve_edge_importance_tier(edge)

        gold_country: str | None = None
        pred_country: str | None = None
        country_ok: bool | None = None
        if bool(rel.country) or rel.edge_type == "facility" or rel.target_kind in FACILITY_TARGET_KINDS:
            gold_country = resolve_gold_country(rel)
            pred_country = resolve_pred_country(edge)
            if gold_country is not None and is_primary:
                country_ok = pred_country == gold_country
                result.facility_country_total += 1
                if country_ok:
                    result.facility_country_correct += 1
            elif gold_country is not None:
                country_ok = pred_country == gold_country

        result.matches.append(
            EdgeMatchDetail(
                gold_id=rel.id,
                edge_id=edge.edge_id,
                ticker=ticker,
                gold_tier=rel.tier,
                gold_edge_type=rel.edge_type,
                pred_edge_type=edge.edge_type,
                exact_type_match=(exact_rank == 0),
                gold_target_name=rel.target_name,
                pred_target_name=edge.target_name,
                gold_direction=rel.direction,
                pred_direction=pred_dir,
                direction_correct=dir_ok,
                gold_importance=rel.importance,
                pred_importance=pred_imp,
                gold_country=gold_country,
                pred_country=pred_country,
                country_correct=country_ok,
                gold_source=rel.source,
                annotator_ids=list(rel.annotator_ids),
                is_primary_gold_match=is_primary,
            )
        )

    # Pass 1: 1-to-1 greedy bipartite matching to maximize distinct gold relationship coverage
    for _core_rank, exact_rank, _name_rank, _overlap_rank, g_idx, p_idx in candidate_pairs:
        if g_idx in used_gold or p_idx in used_pred:
            continue
        used_gold.add(g_idx)
        used_pred.add(p_idx)
        _record_match(g_idx, p_idx, exact_rank, is_primary=True)

    # Pass 2: Many-to-One matching for remaining predicted edges that validly match an already-covered gold item
    for _core_rank, exact_rank, _name_rank, _overlap_rank, g_idx, p_idx in candidate_pairs:
        if p_idx in used_pred:
            continue
        used_pred.add(p_idx)
        _record_match(g_idx, p_idx, exact_rank, is_primary=False)

    for g_idx, rel in enumerate(gold_doc.relationships):
        if g_idx not in used_gold:
            result.unmatched_gold.append(rel)
            if rel.tier == "core":
                result.unmatched_core_gold.append(rel)
            else:
                result.unmatched_extended_gold.append(rel)

    for p_idx, edge in enumerate(predicted_edges):
        if p_idx not in used_pred:
            result.unmatched_edges.append(edge)

    return result


def build_pooled_candidates(
    unmatched_edges: Sequence[VerifiedEdge],
    *,
    ticker: str,
    evaluated_company_key: str,
    hard_negative_edge_ids: set[str],
    exclude_adjudicated_rejections: bool = False,
) -> list[PooledCandidate]:
    """Collect unmatched positive predictions (excluding hard-negative leaks) into a pooled list for review."""
    pooled: list[PooledCandidate] = []
    for edge in unmatched_edges:
        if edge.edge_id in hard_negative_edge_ids:
            continue
        if exclude_adjudicated_rejections and edge.edge_id in _POOLED_REJECTED_REASONS:
            continue
        vint_status = (
            edge.interpretation.status
            if edge.interpretation is not None
            else "confirmed"
        )
        pooled.append(
            PooledCandidate(
                ticker=ticker,
                edge_id=edge.edge_id,
                edge_type=edge.edge_type,
                target_name=edge.target_name,
                target_kind=edge.target_kind,
                direction=infer_edge_direction(edge, evaluated_company_key=evaluated_company_key),
                quote=edge.evidence_quote,
                section=edge.section,
                importance=resolve_edge_importance_tier(edge),
                vint_status=vint_status,
            )
        )
    return pooled


def build_error_lists(
    match_after: SinglePassMatchResult,
    *,
    ticker: str,
    vint_rejected_edges: Sequence[VerifiedEdge] = (),
    gold_doc: GoldDocument | None = None,
) -> tuple[list[EvalErrorDetail], list[EvalErrorDetail], list[EvalErrorDetail], list[EvalErrorDetail]]:
    """Build `(false_positives, false_negatives, hard_negative_leaks, vint_filtered)` lists for reporting.

    Only unmatched `'core'` relationships are listed in `false_negatives` (unmatched `'extended'`
    relationships are optional per `ADJUDICATION.md`).
    """
    hard_neg_by_edge_id: dict[str, GoldNegative] = {
        edge.edge_id: neg for neg, edge in match_after.triggered_negatives
    }

    false_positives: list[EvalErrorDetail] = []
    for edge in match_after.unmatched_edges:
        neg = hard_neg_by_edge_id.get(edge.edge_id)
        if neg is not None:
            reason = f"Hard negative leak ({neg.kind}: {neg.id})"
        elif edge.edge_id in _POOLED_REJECTED_REASONS:
            reason = _POOLED_REJECTED_REASONS[edge.edge_id]
        else:
            reason = "Unmatched verified prediction (pooled candidate / unannotated or spurious)"
        false_positives.append(
            EvalErrorDetail(
                kind="false_positive",
                ticker=ticker,
                item_id=edge.edge_id,
                edge_type=edge.edge_type,
                target_name=edge.target_name,
                target_kind=edge.target_kind,
                quote=edge.evidence_quote,
                reason=reason,
            )
        )

    false_negatives: list[EvalErrorDetail] = []
    for rel in match_after.unmatched_core_gold:
        false_negatives.append(
            EvalErrorDetail(
                kind="false_negative",
                ticker=ticker,
                item_id=rel.id,
                edge_type=rel.edge_type,
                target_name=rel.target_name,
                target_kind=rel.target_kind,
                quote=rel.quote,
                reason=f"Core gold relationship (importance={rel.importance}, source={rel.source}) not extracted",
            )
        )

    hard_negative_leaks: list[EvalErrorDetail] = []
    for neg, edge in match_after.triggered_negatives:
        hard_negative_leaks.append(
            EvalErrorDetail(
                kind="hard_negative_leak",
                ticker=ticker,
                item_id=neg.id,
                edge_type=edge.edge_type,
                target_name=edge.target_name,
                target_kind=edge.target_kind,
                quote=edge.evidence_quote,
                reason=f"Matched hard negative {neg.id} ({neg.kind}: {neg.target_name})",
            )
        )

    vint_filtered: list[EvalErrorDetail] = []
    for edge in vint_rejected_edges:
        would_match_gold = False
        if gold_doc is not None:
            for rel in gold_doc.relationships:
                if compatible_edge_types(
                    edge.edge_type,
                    rel.edge_type,
                    pred_sole_source=edge.sole_source,
                    gold_sole_source=rel.sole_source,
                    gold_alternatives=rel.edge_type_alternatives,
                ) and targets_match(edge, rel):
                    would_match_gold = True
                    break
        interp_reason = (
            edge.interpretation.reason
            if edge.interpretation and edge.interpretation.reason
            else (
                ", ".join(edge.interpretation.flags)
                if edge.interpretation and edge.interpretation.flags
                else "V-INT rejected"
            )
        )
        vint_filtered.append(
            EvalErrorDetail(
                kind="vint_rejected_tp" if would_match_gold else "vint_rejected_fp",
                ticker=ticker,
                item_id=edge.edge_id,
                edge_type=edge.edge_type,
                target_name=edge.target_name,
                target_kind=edge.target_kind,
                quote=edge.evidence_quote,
                reason=interp_reason,
            )
        )

    return false_positives, false_negatives, hard_negative_leaks, vint_filtered


@dataclass(frozen=True)
class AnnotatorAgreementSummary:
    """Inter-annotator agreement between Annotator A (`<TICKER>.a.json`) and Annotator B (`<TICKER>.b.json`)."""

    ticker: str
    a_count: int
    b_count: int
    matched_count: int
    only_in_a: list[str]
    only_in_b: list[str]
    f1_agreement: float
    direction_agreement: float
    importance_quadratic_kappa: float


def compare_annotator_docs(doc_a: GoldDocument, doc_b: GoldDocument) -> AnnotatorAgreementSummary:
    """Compare two independent GoldDocuments for the same company to aid E-GOLD adjudication."""
    pairs: list[tuple[int, int, int]] = []
    for idx_a, rel_a in enumerate(doc_a.relationships):
        for idx_b, rel_b in enumerate(doc_b.relationships):
            if not compatible_edge_types(
                rel_a.edge_type,
                rel_b.edge_type,
                pred_sole_source=bool(rel_a.sole_source),
                gold_sole_source=rel_b.sole_source,
                gold_alternatives=rel_b.edge_type_alternatives,
            ):
                continue
            name_ok = targets_match_name(rel_a.target_name, rel_b.target_name) or any(
                targets_match_name(rel_a.target_name, alias) for alias in rel_b.aliases
            )
            country_ok = False
            if (
                bool(rel_a.country)
                or bool(rel_b.country)
                or rel_a.edge_type == "facility"
                or rel_b.edge_type == "facility"
                or rel_a.target_kind in FACILITY_TARGET_KINDS
                or rel_b.target_kind in FACILITY_TARGET_KINDS
            ):
                ca = resolve_gold_country(rel_a)
                cb = resolve_gold_country(rel_b)
                country_ok = bool(ca and cb and ca == cb)
            if not (name_ok or country_ok):
                continue
            exact = 0 if rel_a.edge_type == rel_b.edge_type else 1
            pairs.append((exact, idx_a, idx_b))

    pairs.sort()
    used_a: set[int] = set()
    used_b: set[int] = set()
    dir_matches = 0
    imp_pairs: list[tuple[str, str]] = []

    for _exact, idx_a, idx_b in pairs:
        if idx_a in used_a or idx_b in used_b:
            continue
        used_a.add(idx_a)
        used_b.add(idx_b)
        ra = doc_a.relationships[idx_a]
        rb = doc_b.relationships[idx_b]
        if ra.direction == rb.direction:
            dir_matches += 1
        imp_pairs.append((ra.importance, rb.importance))

    matched = len(used_a)
    denom = len(doc_a.relationships) + len(doc_b.relationships)
    f1 = (2.0 * matched / denom) if denom > 0 else 1.0
    dir_acc = (dir_matches / matched) if matched > 0 else 1.0

    from hoc.eval.metrics import compute_weighted_kappa

    kappa = compute_weighted_kappa(imp_pairs, weights="quadratic") if imp_pairs else 1.0
    return AnnotatorAgreementSummary(
        ticker=doc_a.company.ticker.upper(),
        a_count=len(doc_a.relationships),
        b_count=len(doc_b.relationships),
        matched_count=matched,
        only_in_a=[r.id for i, r in enumerate(doc_a.relationships) if i not in used_a],
        only_in_b=[r.id for i, r in enumerate(doc_b.relationships) if i not in used_b],
        f1_agreement=round(f1, 4),
        direction_agreement=round(dir_acc, 4),
        importance_quadratic_kappa=round(kappa, 4),
    )
