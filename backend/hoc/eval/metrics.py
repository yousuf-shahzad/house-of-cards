"""Evaluation metrics and 95% bootstrap confidence intervals for package E-RUN.

Owner: Bekarys's Gemini (E-RUN).
Rules (docs/hoc/PLAN-v3.md §1 & docs/hoc/eval/ADJUDICATION.md):
- Recall counts `'core'` gold relationships only (`tp_core / gold_core_count`; missing `'extended'`
  items are optional and do not count as false negatives).
- Precision treats a prediction as a true positive when it matches either a `'core'` or `'extended'`
  gold relationship (`(tp_core + tp_extended) / predicted_count`).
- Micro and macro Precision, Recall, and F1 overall and per `edge_type`.
- Direction accuracy (`depends_on_target` vs `target_depends_on_company`).
- Hard-negative false-positive rate (fraction of `negatives` falsely extracted, before and after V-INT).
- Facility-country accuracy (ISO-2 country match on facility/country relationships).
- Importance-tier agreement (weighted Cohen's kappa over `low < medium < high < critical`).
- Precision/Recall/F1 before vs. after V-INT.
- 95% bootstrap confidence intervals across companies (`B = 2000`, deterministic seed `20261108`).
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from hoc.ai.extractor import EDGE_TYPES
from hoc.contract.dependencies import EdgeType, VerifiedEdge
from hoc.eval.matching import (
    SinglePassMatchResult,
    build_error_lists,
    build_pooled_candidates,
    match_predictions_to_gold,
)
from hoc.eval.schema import (
    IMPORTANCE_TO_SCORE,
    AgenticAcceptanceReport,
    CompanyEvalSummary,
    EvalRunReport,
    GoldDocument,
    MetricWithCI,
    PRFMetrics,
    RecordedCompanyPrediction,
)
from hoc.filings.text import normalise

DEFAULT_BOOTSTRAP_ITERATIONS = 2000
DEFAULT_BOOTSTRAP_SEED = 20261108


def safe_prf(
    tp: int,
    fp: int,
    fn: int,
    *,
    tp_core: int | None = None,
) -> tuple[float, float, float]:
    """Compute `(precision, recall, f1)` safely without division-by-zero.

    - `tp`: total matched relationships (`tp_core + tp_extended`), used for precision.
    - `tp_core`: matched core relationships, used for recall (defaults to `tp` when omitted).
    - `fp`: unmatched predicted edges.
    - `fn`: unmatched core gold relationships.
    """
    core_hits = tp if tp_core is None else tp_core
    if tp + fp == 0:
        precision = 1.0 if fn == 0 else 0.0
    else:
        precision = tp / (tp + fp)

    if core_hits + fn == 0:
        recall = 1.0 if fp == 0 else 0.0
    else:
        recall = core_hits / (core_hits + fn)

    if precision + recall == 0.0:
        f1 = 0.0
    else:
        f1 = 2.0 * precision * recall / (precision + recall)
    return precision, recall, f1


def compute_weighted_kappa(
    pairs: Sequence[tuple[str, str]],
    *,
    weights: Literal["quadratic", "linear"] = "quadratic",
) -> float:
    """Compute linear or quadratic weighted Cohen's kappa over ordinal importance tiers
    `('low', 'medium', 'high', 'critical')`."""
    n = len(pairs)
    if n == 0:
        return 1.0

    k = 4
    obs = [[0.0 for _ in range(k)] for _ in range(k)]
    row_totals = [0.0 for _ in range(k)]
    col_totals = [0.0 for _ in range(k)]

    for gold_tier, pred_tier in pairs:
        gi = IMPORTANCE_TO_SCORE.get(gold_tier, 1)
        pi = IMPORTANCE_TO_SCORE.get(pred_tier, 1)
        obs[gi][pi] += 1.0
        row_totals[gi] += 1.0
        col_totals[pi] += 1.0

    disagree_obs = 0.0
    disagree_exp = 0.0
    max_dist = float(k - 1)
    for i in range(k):
        for j in range(k):
            if weights == "quadratic":
                w = ((i - j) / max_dist) ** 2
            else:
                w = abs(i - j) / max_dist
            disagree_obs += w * (obs[i][j] / n)
            expected_ij = (row_totals[i] * col_totals[j]) / (n * n)
            disagree_exp += w * expected_ij

    if disagree_exp <= 1e-12:
        return 1.0 if disagree_obs <= 1e-12 else 0.0
    kappa = 1.0 - (disagree_obs / disagree_exp)
    return max(-1.0, min(1.0, kappa))


def bootstrap_ci(
    items: Sequence[Any],
    stat_fn: Callable[[Sequence[Any]], float],
    *,
    iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
    numerator: int | None = None,
    denominator: int | None = None,
) -> MetricWithCI:
    """Compute point estimate and 95% bootstrap confidence interval across company evaluation units."""
    point = round(float(stat_fn(items)), 4)
    if not items or iterations <= 0 or len(items) == 1:
        return MetricWithCI(
            value=point,
            ci_low=point,
            ci_high=point,
            numerator=numerator,
            denominator=denominator,
        )

    rng = random.Random(seed)
    n = len(items)
    samples: list[float] = []
    for _ in range(iterations):
        resample = [items[rng.randrange(n)] for _ in range(n)]
        samples.append(float(stat_fn(resample)))
    samples.sort()

    low_idx = max(0, int(0.025 * (iterations - 1)))
    high_idx = min(iterations - 1, int(0.975 * (iterations - 1)))
    ci_low = round(min(point, samples[low_idx]), 4)
    ci_high = round(max(point, samples[high_idx]), 4)
    return MetricWithCI(
        value=point,
        ci_low=ci_low,
        ci_high=ci_high,
        numerator=numerator,
        denominator=denominator,
    )


@dataclass
class CompanyEvalBundle:
    """Internal per-company evaluation bundle retaining both before- and after-V-INT match results
    for bootstrap resampling."""

    gold_doc: GoldDocument
    edges_before_vint: list[VerifiedEdge]
    edges_after_vint: list[VerifiedEdge]
    vint_rejected_edges: list[VerifiedEdge]
    match_before: SinglePassMatchResult
    match_after: SinglePassMatchResult
    summary: CompanyEvalSummary
    negatives_triggered_before_by_kind: dict[str, int] = field(default_factory=dict)
    negatives_triggered_after_by_kind: dict[str, int] = field(default_factory=dict)
    negatives_total_by_kind: dict[str, int] = field(default_factory=dict)
    edges_before_agentic: list[VerifiedEdge] = field(default_factory=list)
    agentic_findings: list[dict[str, Any]] = field(default_factory=list)


def _partition_vint_edges(
    predicted_edges: Sequence[VerifiedEdge],
    explicit_vint_rejected: Sequence[VerifiedEdge] = (),
) -> tuple[list[VerifiedEdge], list[VerifiedEdge], list[VerifiedEdge]]:
    """Return `(edges_before_vint, edges_after_vint, vint_rejected_edges)` deduplicated by `edge_id`."""
    after_by_id: dict[str, VerifiedEdge] = {}
    rejected_by_id: dict[str, VerifiedEdge] = {}

    for edge in explicit_vint_rejected:
        rejected_by_id[edge.edge_id] = edge

    for edge in predicted_edges:
        if edge.interpretation is not None and edge.interpretation.status == "rejected":
            rejected_by_id[edge.edge_id] = edge
        elif edge.edge_id not in rejected_by_id:
            after_by_id[edge.edge_id] = edge

    before_by_id: dict[str, VerifiedEdge] = {**after_by_id, **rejected_by_id}
    return (
        list(before_by_id.values()),
        list(after_by_id.values()),
        list(rejected_by_id.values()),
    )


def evaluate_company(
    gold_doc: GoldDocument,
    predicted_edges: Sequence[VerifiedEdge],
    *,
    vint_rejected_edges: Sequence[VerifiedEdge] = (),
    before_agentic_edges: Sequence[VerifiedEdge] | None = None,
    agentic_findings: Sequence[Mapping[str, Any]] = (),
    agentic_findings_count: int = 0,
    agentic_steps_done: int = 0,
    agentic_steps_total: int = 0,
    agentic_new_edges_count: int = 0,
    agentic_rejected_edges_count: int = 0,
) -> CompanyEvalBundle:
    """Evaluate one company's predicted edges (before and after V-INT, and before and after agentic)
    against its `GoldDocument`."""
    edges_before, edges_after, edges_rejected = _partition_vint_edges(
        predicted_edges, vint_rejected_edges
    )

    match_before = match_predictions_to_gold(edges_before, gold_doc)
    match_after = match_predictions_to_gold(edges_after, gold_doc)

    blind_rels = [r for r in gold_doc.relationships if r.source.strip().lower() != "pooled"]
    gold_doc_blind = gold_doc.model_copy(update={"relationships": blind_rels})
    match_blind_after = match_predictions_to_gold(edges_after, gold_doc_blind)

    # Before-agentic vs after-agentic (defaults to edges_after when before_agentic_edges is None)
    edges_pre_agentic = (
        _partition_vint_edges(before_agentic_edges, ())[1]
        if before_agentic_edges is not None
        else edges_after
    )
    match_pre_agentic = match_predictions_to_gold(edges_pre_agentic, gold_doc)
    match_blind_pre_agentic = match_predictions_to_gold(edges_pre_agentic, gold_doc_blind)

    gold_total = len(gold_doc.relationships)
    gold_core_total = sum(1 for r in gold_doc.relationships if r.tier == "core")
    gold_extended_total = sum(1 for r in gold_doc.relationships if r.tier == "extended")
    gold_core_by_source: dict[str, int] = {}
    for rel in gold_doc.relationships:
        if rel.tier == "core":
            src = rel.source.strip().lower() or "gold"
            gold_core_by_source[src] = gold_core_by_source.get(src, 0) + 1

    gold_pooled = sum(1 for r in gold_doc.relationships if r.source.strip().lower() == "pooled")
    gold_blind = gold_total - gold_pooled
    neg_total = len(gold_doc.negatives)

    tp_before = match_before.tp_total
    tp_core_before = match_before.tp_core
    tp_ext_before = match_before.tp_extended
    fp_before = len(match_before.unmatched_edges)
    fn_before = len(match_before.unmatched_core_gold)
    p_before, r_before, f1_before = safe_prf(
        tp_before, fp_before, fn_before, tp_core=tp_core_before
    )

    tp_after = match_after.tp_total
    tp_core_after = match_after.tp_core
    tp_ext_after = match_after.tp_extended
    fp_after = len(match_after.unmatched_edges)
    fn_after = len(match_after.unmatched_core_gold)
    p_after, r_after, f1_after = safe_prf(
        tp_after, fp_after, fn_after, tp_core=tp_core_after
    )

    tp_blind_after = match_blind_after.tp_total
    fp_blind_after = len(match_blind_after.unmatched_edges)
    p_blind_after, _r_blind_after, f1_blind_after = safe_prf(
        tp_blind_after,
        fp_blind_after,
        len(match_blind_after.unmatched_core_gold),
        tp_core=match_blind_after.tp_core,
    )

    # Pre-agentic metrics
    tp_pre_ag = match_pre_agentic.tp_total
    tp_core_pre_ag = match_pre_agentic.tp_core
    tp_ext_pre_ag = match_pre_agentic.tp_extended
    fp_pre_ag = len(match_pre_agentic.unmatched_edges)
    fn_pre_ag = len(match_pre_agentic.unmatched_core_gold)
    p_pre_ag, r_pre_ag, f1_pre_ag = safe_prf(
        tp_pre_ag, fp_pre_ag, fn_pre_ag, tp_core=tp_core_pre_ag
    )
    tp_blind_pre_ag = match_blind_pre_agentic.tp_total
    fp_blind_pre_ag = len(match_blind_pre_agentic.unmatched_edges)
    p_blind_pre_ag, _r_blind_pre_ag, f1_blind_pre_ag = safe_prf(
        tp_blind_pre_ag,
        fp_blind_pre_ag,
        len(match_blind_pre_agentic.unmatched_core_gold),
        tp_core=match_blind_pre_agentic.tp_core,
    )

    dir_correct = sum(1 for m in match_after.matches if m.direction_correct)
    dir_total = len(match_after.matches)

    ticker = gold_doc.company.ticker.upper()
    company_key = gold_doc.company.company_key

    false_positives, false_negatives, hard_neg_leaks, vint_filtered = build_error_lists(
        match_after,
        ticker=ticker,
        vint_rejected_edges=edges_rejected,
        gold_doc=gold_doc,
    )
    hard_neg_edge_ids = {edge.edge_id for _neg, edge in match_after.triggered_negatives}
    pooled = build_pooled_candidates(
        match_after.unmatched_edges,
        ticker=ticker,
        evaluated_company_key=company_key,
        hard_negative_edge_ids=hard_neg_edge_ids,
        exclude_adjudicated_rejections=True,
    )

    neg_total_by_kind: dict[str, int] = {}
    for neg in gold_doc.negatives:
        neg_total_by_kind[neg.kind] = neg_total_by_kind.get(neg.kind, 0) + 1

    neg_before_by_kind: dict[str, int] = {}
    for neg, _edge in match_before.triggered_negatives:
        neg_before_by_kind[neg.kind] = neg_before_by_kind.get(neg.kind, 0) + 1

    neg_after_by_kind: dict[str, int] = {}
    for neg, _edge in match_after.triggered_negatives:
        neg_after_by_kind[neg.kind] = neg_after_by_kind.get(neg.kind, 0) + 1

    annotator_label = (
        gold_doc.annotator
        or (", ".join(gold_doc.annotators) if gold_doc.annotators else "")
    )

    summary = CompanyEvalSummary(
        ticker=ticker,
        company_name=gold_doc.company.name,
        cik=gold_doc.company.normalised_cik,
        accession=gold_doc.filing.accession,
        annotator=annotator_label,
        gold_total=gold_total,
        gold_core_total=gold_core_total,
        gold_extended_total=gold_extended_total,
        gold_core_by_source=gold_core_by_source,
        gold_blind_count=gold_blind,
        gold_pooled_count=gold_pooled,
        negatives_total=neg_total,
        predicted_before_vint=len(edges_before),
        predicted_after_vint=len(edges_after),
        vint_rejected_count=len(edges_rejected),
        tp_before_vint=tp_before,
        tp_core_before_vint=tp_core_before,
        tp_extended_before_vint=tp_ext_before,
        fp_before_vint=fp_before,
        fn_before_vint=fn_before,
        tp_after_vint=tp_after,
        tp_core_after_vint=tp_core_after,
        tp_extended_after_vint=tp_ext_after,
        fp_after_vint=fp_after,
        fn_after_vint=fn_after,
        precision_before_vint=round(p_before, 4),
        recall_before_vint=round(r_before, 4),
        f1_before_vint=round(f1_before, 4),
        precision_after_vint=round(p_after, 4),
        recall_after_vint=round(r_after, 4),
        f1_after_vint=round(f1_after, 4),
        tp_blind_after_vint=tp_blind_after,
        fp_blind_after_vint=fp_blind_after,
        precision_blind_after_vint=round(p_blind_after, 4),
        f1_blind_after_vint=round(f1_blind_after, 4),
        predicted_before_agentic=len(edges_pre_agentic),
        predicted_after_agentic=len(edges_after),
        tp_before_agentic=tp_pre_ag,
        tp_core_before_agentic=tp_core_pre_ag,
        tp_extended_before_agentic=tp_ext_pre_ag,
        fp_before_agentic=fp_pre_ag,
        fn_before_agentic=fn_pre_ag,
        tp_blind_before_agentic=tp_blind_pre_ag,
        fp_blind_before_agentic=fp_blind_pre_ag,
        precision_before_agentic=round(p_pre_ag, 4),
        precision_blind_before_agentic=round(p_blind_pre_ag, 4),
        recall_before_agentic=round(r_pre_ag, 4),
        f1_before_agentic=round(f1_pre_ag, 4),
        f1_blind_before_agentic=round(f1_blind_pre_ag, 4),
        tp_after_agentic=tp_after,
        tp_core_after_agentic=tp_core_after,
        tp_extended_after_agentic=tp_ext_after,
        fp_after_agentic=fp_after,
        fn_after_agentic=fn_after,
        tp_blind_after_agentic=tp_blind_after,
        fp_blind_after_agentic=fp_blind_after,
        precision_after_agentic=round(p_after, 4),
        precision_blind_after_agentic=round(p_blind_after, 4),
        recall_after_agentic=round(r_after, 4),
        f1_after_agentic=round(f1_after, 4),
        f1_blind_after_agentic=round(f1_blind_after, 4),
        agentic_findings_count=agentic_findings_count,
        agentic_steps_done=agentic_steps_done,
        agentic_steps_total=agentic_steps_total,
        agentic_new_edges_count=agentic_new_edges_count,
        agentic_rejected_edges_count=agentic_rejected_edges_count,
        direction_correct=dir_correct,
        direction_total=dir_total,
        hard_neg_fp_before_vint=len(match_before.triggered_negatives),
        hard_neg_fp_after_vint=len(match_after.triggered_negatives),
        facility_country_correct=match_after.facility_country_correct,
        facility_country_total=match_after.facility_country_total,
        matches=match_after.matches,
        false_positives=false_positives,
        false_negatives=false_negatives,
        hard_negative_leaks=hard_neg_leaks,
        vint_filtered=vint_filtered,
        pooled_candidates=pooled,
    )

    return CompanyEvalBundle(
        gold_doc=gold_doc,
        edges_before_vint=edges_before,
        edges_after_vint=edges_after,
        vint_rejected_edges=edges_rejected,
        match_before=match_before,
        match_after=match_after,
        summary=summary,
        negatives_triggered_before_by_kind=neg_before_by_kind,
        negatives_triggered_after_by_kind=neg_after_by_kind,
        negatives_total_by_kind=neg_total_by_kind,
        edges_before_agentic=list(edges_pre_agentic),
        agentic_findings=[dict(f) for f in agentic_findings],
    )


def _build_micro_prf_metrics(
    bundles: Sequence[CompanyEvalBundle],
    *,
    after_vint: bool,
    iterations: int,
    seed: int,
) -> PRFMetrics:
    def _counts(
        seq: Sequence[CompanyEvalBundle],
    ) -> tuple[int, int, int, int, int, int, int, int]:
        if after_vint:
            tp = sum(b.summary.tp_after_vint for b in seq)
            tp_core = sum(b.summary.tp_core_after_vint for b in seq)
            tp_ext = sum(b.summary.tp_extended_after_vint for b in seq)
            fp = sum(b.summary.fp_after_vint for b in seq)
            fn = sum(b.summary.fn_after_vint for b in seq)
            pred = sum(b.summary.predicted_after_vint for b in seq)
        else:
            tp = sum(b.summary.tp_before_vint for b in seq)
            tp_core = sum(b.summary.tp_core_before_vint for b in seq)
            tp_ext = sum(b.summary.tp_extended_before_vint for b in seq)
            fp = sum(b.summary.fp_before_vint for b in seq)
            fn = sum(b.summary.fn_before_vint for b in seq)
            pred = sum(b.summary.predicted_before_vint for b in seq)
        gold_core = sum(b.summary.gold_core_total for b in seq)
        gold_ext = sum(b.summary.gold_extended_total for b in seq)
        return tp, tp_core, tp_ext, fp, fn, gold_core, gold_ext, pred

    tp, tp_core, tp_ext, fp, fn, gold_core, gold_ext, pred_cnt = _counts(bundles)
    p_ci = bootstrap_ci(
        bundles,
        lambda seq: safe_prf(_counts(seq)[0], _counts(seq)[3], _counts(seq)[4], tp_core=_counts(seq)[1])[0],
        iterations=iterations,
        seed=seed,
        numerator=tp,
        denominator=tp + fp,
    )
    r_ci = bootstrap_ci(
        bundles,
        lambda seq: safe_prf(_counts(seq)[0], _counts(seq)[3], _counts(seq)[4], tp_core=_counts(seq)[1])[1],
        iterations=iterations,
        seed=seed + 1,
        numerator=tp_core,
        denominator=tp_core + fn,
    )
    f1_ci = bootstrap_ci(
        bundles,
        lambda seq: safe_prf(_counts(seq)[0], _counts(seq)[3], _counts(seq)[4], tp_core=_counts(seq)[1])[2],
        iterations=iterations,
        seed=seed + 2,
    )
    return PRFMetrics(
        precision=p_ci,
        recall=r_ci,
        f1=f1_ci,
        tp=tp,
        tp_core=tp_core,
        tp_extended=tp_ext,
        fp=fp,
        fn=fn,
        gold_core_count=gold_core,
        gold_extended_count=gold_ext,
        gold_count=gold_core + gold_ext,
        predicted_count=pred_cnt,
    )


def _build_macro_prf_metrics(
    bundles: Sequence[CompanyEvalBundle],
    *,
    after_vint: bool,
    iterations: int,
    seed: int,
) -> PRFMetrics:
    def _macro_p(seq: Sequence[CompanyEvalBundle]) -> float:
        if not seq:
            return 0.0
        vals = [
            b.summary.precision_after_vint if after_vint else b.summary.precision_before_vint
            for b in seq
        ]
        return sum(vals) / len(vals)

    def _macro_r(seq: Sequence[CompanyEvalBundle]) -> float:
        if not seq:
            return 0.0
        vals = [
            b.summary.recall_after_vint if after_vint else b.summary.recall_before_vint
            for b in seq
        ]
        return sum(vals) / len(vals)

    def _macro_f1(seq: Sequence[CompanyEvalBundle]) -> float:
        if not seq:
            return 0.0
        vals = [
            b.summary.f1_after_vint if after_vint else b.summary.f1_before_vint
            for b in seq
        ]
        return sum(vals) / len(vals)

    if after_vint:
        tp = sum(b.summary.tp_after_vint for b in bundles)
        tp_core = sum(b.summary.tp_core_after_vint for b in bundles)
        tp_ext = sum(b.summary.tp_extended_after_vint for b in bundles)
        fp = sum(b.summary.fp_after_vint for b in bundles)
        fn = sum(b.summary.fn_after_vint for b in bundles)
        pred_cnt = sum(b.summary.predicted_after_vint for b in bundles)
    else:
        tp = sum(b.summary.tp_before_vint for b in bundles)
        tp_core = sum(b.summary.tp_core_before_vint for b in bundles)
        tp_ext = sum(b.summary.tp_extended_before_vint for b in bundles)
        fp = sum(b.summary.fp_before_vint for b in bundles)
        fn = sum(b.summary.fn_before_vint for b in bundles)
        pred_cnt = sum(b.summary.predicted_before_vint for b in bundles)
    gold_core = sum(b.summary.gold_core_total for b in bundles)
    gold_ext = sum(b.summary.gold_extended_total for b in bundles)

    return PRFMetrics(
        precision=bootstrap_ci(bundles, _macro_p, iterations=iterations, seed=seed + 10),
        recall=bootstrap_ci(bundles, _macro_r, iterations=iterations, seed=seed + 11),
        f1=bootstrap_ci(bundles, _macro_f1, iterations=iterations, seed=seed + 12),
        tp=tp,
        tp_core=tp_core,
        tp_extended=tp_ext,
        fp=fp,
        fn=fn,
        gold_core_count=gold_core,
        gold_extended_count=gold_ext,
        gold_count=gold_core + gold_ext,
        predicted_count=pred_cnt,
    )


def _build_blind_micro_prf_metrics(
    bundles: Sequence[CompanyEvalBundle],
    *,
    iterations: int,
    seed: int,
) -> PRFMetrics:
    def _counts(
        seq: Sequence[CompanyEvalBundle],
    ) -> tuple[int, int, int, int, int, int, int, int]:
        tp = sum(b.summary.tp_blind_after_vint for b in seq)
        tp_core = sum(b.summary.tp_core_after_vint for b in seq)
        tp_ext = max(0, tp - tp_core)
        fp = sum(b.summary.fp_blind_after_vint for b in seq)
        fn = sum(b.summary.fn_after_vint for b in seq)
        pred = sum(b.summary.predicted_after_vint for b in seq)
        gold_core = sum(b.summary.gold_core_total for b in seq)
        gold_ext = sum(b.summary.gold_blind_count - b.summary.gold_core_total for b in seq)
        return tp, tp_core, tp_ext, fp, fn, gold_core, gold_ext, pred

    tp, tp_core, tp_ext, fp, fn, gold_core, gold_ext, pred_cnt = _counts(bundles)
    p_ci = bootstrap_ci(
        bundles,
        lambda seq: safe_prf(_counts(seq)[0], _counts(seq)[3], _counts(seq)[4], tp_core=_counts(seq)[1])[0],
        iterations=iterations,
        seed=seed,
        numerator=tp,
        denominator=tp + fp,
    )
    r_ci = bootstrap_ci(
        bundles,
        lambda seq: safe_prf(_counts(seq)[0], _counts(seq)[3], _counts(seq)[4], tp_core=_counts(seq)[1])[1],
        iterations=iterations,
        seed=seed + 1,
        numerator=tp_core,
        denominator=tp_core + fn,
    )
    f1_ci = bootstrap_ci(
        bundles,
        lambda seq: safe_prf(_counts(seq)[0], _counts(seq)[3], _counts(seq)[4], tp_core=_counts(seq)[1])[2],
        iterations=iterations,
        seed=seed + 2,
    )
    return PRFMetrics(
        precision=p_ci,
        recall=r_ci,
        f1=f1_ci,
        tp=tp,
        tp_core=tp_core,
        tp_extended=tp_ext,
        fp=fp,
        fn=fn,
        gold_core_count=gold_core,
        gold_extended_count=gold_ext,
        gold_count=gold_core + gold_ext,
        predicted_count=pred_cnt,
    )


def _build_blind_macro_prf_metrics(
    bundles: Sequence[CompanyEvalBundle],
    *,
    iterations: int,
    seed: int,
) -> PRFMetrics:
    def _macro_p(seq: Sequence[CompanyEvalBundle]) -> float:
        return (
            sum(b.summary.precision_blind_after_vint for b in seq) / len(seq)
            if seq
            else 0.0
        )

    def _macro_r(seq: Sequence[CompanyEvalBundle]) -> float:
        return (
            sum(b.summary.recall_after_vint for b in seq) / len(seq)
            if seq
            else 0.0
        )

    def _macro_f1(seq: Sequence[CompanyEvalBundle]) -> float:
        return (
            sum(b.summary.f1_blind_after_vint for b in seq) / len(seq)
            if seq
            else 0.0
        )

    tp = sum(b.summary.tp_blind_after_vint for b in bundles)
    tp_core = sum(b.summary.tp_core_after_vint for b in bundles)
    tp_ext = max(0, tp - tp_core)
    fp = sum(b.summary.fp_blind_after_vint for b in bundles)
    fn = sum(b.summary.fn_after_vint for b in bundles)
    pred_cnt = sum(b.summary.predicted_after_vint for b in bundles)
    gold_core = sum(b.summary.gold_core_total for b in bundles)
    gold_ext = sum(b.summary.gold_blind_count - b.summary.gold_core_total for b in bundles)

    return PRFMetrics(
        precision=bootstrap_ci(bundles, _macro_p, iterations=iterations, seed=seed + 10),
        recall=bootstrap_ci(bundles, _macro_r, iterations=iterations, seed=seed + 11),
        f1=bootstrap_ci(bundles, _macro_f1, iterations=iterations, seed=seed + 12),
        tp=tp,
        tp_core=tp_core,
        tp_extended=tp_ext,
        fp=fp,
        fn=fn,
        gold_core_count=gold_core,
        gold_extended_count=gold_ext,
        gold_count=gold_core + gold_ext,
        predicted_count=pred_cnt,
    )


def _build_agentic_micro_prf_metrics(
    bundles: Sequence[CompanyEvalBundle],
    *,
    after_agentic: bool,
    blind: bool,
    iterations: int,
    seed: int,
) -> PRFMetrics:
    def _counts(
        seq: Sequence[CompanyEvalBundle],
    ) -> tuple[int, int, int, int, int, int, int, int]:
        if after_agentic:
            tp_core = sum(b.summary.tp_core_after_agentic for b in seq)
            fn = sum(b.summary.fn_after_agentic for b in seq)
            pred = sum(b.summary.predicted_after_agentic for b in seq)
            if blind:
                tp = sum(b.summary.tp_blind_after_agentic for b in seq)
                fp = sum(b.summary.fp_blind_after_agentic for b in seq)
                tp_ext = max(0, tp - tp_core)
            else:
                tp = sum(b.summary.tp_after_agentic for b in seq)
                fp = sum(b.summary.fp_after_agentic for b in seq)
                tp_ext = sum(b.summary.tp_extended_after_agentic for b in seq)
        else:
            tp_core = sum(b.summary.tp_core_before_agentic for b in seq)
            fn = sum(b.summary.fn_before_agentic for b in seq)
            pred = sum(b.summary.predicted_before_agentic for b in seq)
            if blind:
                tp = sum(b.summary.tp_blind_before_agentic for b in seq)
                fp = sum(b.summary.fp_blind_before_agentic for b in seq)
                tp_ext = max(0, tp - tp_core)
            else:
                tp = sum(b.summary.tp_before_agentic for b in seq)
                fp = sum(b.summary.fp_before_agentic for b in seq)
                tp_ext = sum(b.summary.tp_extended_before_agentic for b in seq)
        gold_core = sum(b.summary.gold_core_total for b in seq)
        gold_ext = (
            sum(b.summary.gold_blind_count - b.summary.gold_core_total for b in seq)
            if blind
            else sum(b.summary.gold_extended_total for b in seq)
        )
        return tp, tp_core, tp_ext, fp, fn, gold_core, gold_ext, pred

    tp, tp_core, tp_ext, fp, fn, gold_core, gold_ext, pred_cnt = _counts(bundles)
    p_ci = bootstrap_ci(
        bundles,
        lambda seq: safe_prf(_counts(seq)[0], _counts(seq)[3], _counts(seq)[4], tp_core=_counts(seq)[1])[0],
        iterations=iterations,
        seed=seed,
        numerator=tp,
        denominator=tp + fp,
    )
    r_ci = bootstrap_ci(
        bundles,
        lambda seq: safe_prf(_counts(seq)[0], _counts(seq)[3], _counts(seq)[4], tp_core=_counts(seq)[1])[1],
        iterations=iterations,
        seed=seed + 1,
        numerator=tp_core,
        denominator=tp_core + fn,
    )
    f1_ci = bootstrap_ci(
        bundles,
        lambda seq: safe_prf(_counts(seq)[0], _counts(seq)[3], _counts(seq)[4], tp_core=_counts(seq)[1])[2],
        iterations=iterations,
        seed=seed + 2,
    )
    return PRFMetrics(
        precision=p_ci,
        recall=r_ci,
        f1=f1_ci,
        tp=tp,
        tp_core=tp_core,
        tp_extended=tp_ext,
        fp=fp,
        fn=fn,
        gold_core_count=gold_core,
        gold_extended_count=gold_ext,
        gold_count=gold_core + gold_ext,
        predicted_count=pred_cnt,
    )


def _build_agentic_macro_prf_metrics(
    bundles: Sequence[CompanyEvalBundle],
    *,
    after_agentic: bool,
    blind: bool,
    iterations: int,
    seed: int,
) -> PRFMetrics:
    def _macro_p(seq: Sequence[CompanyEvalBundle]) -> float:
        if not seq:
            return 0.0
        if after_agentic:
            vals = [
                b.summary.precision_blind_after_agentic if blind else b.summary.precision_after_agentic
                for b in seq
            ]
        else:
            vals = [
                b.summary.precision_blind_before_agentic if blind else b.summary.precision_before_agentic
                for b in seq
            ]
        return sum(vals) / len(vals)

    def _macro_r(seq: Sequence[CompanyEvalBundle]) -> float:
        if not seq:
            return 0.0
        vals = [
            b.summary.recall_after_agentic if after_agentic else b.summary.recall_before_agentic
            for b in seq
        ]
        return sum(vals) / len(vals)

    def _macro_f1(seq: Sequence[CompanyEvalBundle]) -> float:
        if not seq:
            return 0.0
        if after_agentic:
            vals = [
                b.summary.f1_blind_after_agentic if blind else b.summary.f1_after_agentic
                for b in seq
            ]
        else:
            vals = [
                b.summary.f1_blind_before_agentic if blind else b.summary.f1_before_agentic
                for b in seq
            ]
        return sum(vals) / len(vals)

    micro = _build_agentic_micro_prf_metrics(
        bundles,
        after_agentic=after_agentic,
        blind=blind,
        iterations=0,
        seed=seed,
    )
    return PRFMetrics(
        precision=bootstrap_ci(bundles, _macro_p, iterations=iterations, seed=seed + 10),
        recall=bootstrap_ci(bundles, _macro_r, iterations=iterations, seed=seed + 11),
        f1=bootstrap_ci(bundles, _macro_f1, iterations=iterations, seed=seed + 12),
        tp=micro.tp,
        tp_core=micro.tp_core,
        tp_extended=micro.tp_extended,
        fp=micro.fp,
        fn=micro.fn,
        gold_core_count=micro.gold_core_count,
        gold_extended_count=micro.gold_extended_count,
        gold_count=micro.gold_count,
        predicted_count=micro.predicted_count,
    )


def _type_counts_for_bundles(
    seq: Sequence[CompanyEvalBundle],
    edge_type: EdgeType,
) -> tuple[int, int, int, int, int, int, int, int]:
    """Return `(tp_gold_total, tp_gold_core, tp_gold_ext, tp_pred, fp_pred, fn_gold_core, gold_core_cnt, gold_ext_cnt)`."""
    gold_core_cnt = sum(
        1 for b in seq for r in b.gold_doc.relationships if r.edge_type == edge_type and r.tier == "core"
    )
    gold_ext_cnt = sum(
        1 for b in seq for r in b.gold_doc.relationships if r.edge_type == edge_type and r.tier == "extended"
    )
    tp_gold_core = sum(
        1
        for b in seq
        for m in b.match_after.matches
        if m.is_primary_gold_match and m.gold_edge_type == edge_type and m.gold_tier == "core"
    )
    tp_gold_ext = sum(
        1
        for b in seq
        for m in b.match_after.matches
        if m.is_primary_gold_match and m.gold_edge_type == edge_type and m.gold_tier == "extended"
    )
    tp_pred = sum(
        1 for b in seq for m in b.match_after.matches if m.pred_edge_type == edge_type
    )
    fp_pred = sum(
        1 for b in seq for e in b.match_after.unmatched_edges if e.edge_type == edge_type
    )
    fn_gold_core = sum(
        1 for b in seq for r in b.match_after.unmatched_core_gold if r.edge_type == edge_type
    )
    return (
        tp_gold_core + tp_gold_ext,
        tp_gold_core,
        tp_gold_ext,
        tp_pred,
        fp_pred,
        fn_gold_core,
        gold_core_cnt,
        gold_ext_cnt,
    )


def _type_prf(
    seq: Sequence[CompanyEvalBundle],
    edge_type: EdgeType,
) -> tuple[float, float, float]:
    (
        _tp_gold_tot,
        tp_gold_core,
        _tp_gold_ext,
        tp_pred,
        fp_pred,
        fn_gold_core,
        _gold_core_cnt,
        _gold_ext_cnt,
    ) = _type_counts_for_bundles(seq, edge_type)
    if tp_pred + fp_pred == 0:
        precision = 1.0 if fn_gold_core == 0 else 0.0
    else:
        precision = tp_pred / (tp_pred + fp_pred)

    if tp_gold_core + fn_gold_core == 0:
        recall = 1.0 if fp_pred == 0 else 0.0
    else:
        recall = tp_gold_core / (tp_gold_core + fn_gold_core)

    f1 = (2.0 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def aggregate_eval_report(
    bundles: Sequence[CompanyEvalBundle],
    *,
    mode: Literal["replay", "live", "synthetic_baseline"] = "replay",
    git_commit: str = "unknown",
    extractor_prompt_version: str = "",
    judge_prompt_version: str = "",
    research_depth: str = "light",
    bootstrap_iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> EvalRunReport:
    """Aggregate company-level evaluation bundles into the full `EvalRunReport` with 95% CIs."""
    overall_after = _build_micro_prf_metrics(
        bundles,
        after_vint=True,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed,
    )
    overall_before = _build_micro_prf_metrics(
        bundles,
        after_vint=False,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 100,
    )
    macro_after = _build_macro_prf_metrics(
        bundles,
        after_vint=True,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 200,
    )
    macro_before = _build_macro_prf_metrics(
        bundles,
        after_vint=False,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 300,
    )
    blind_overall_after = _build_blind_micro_prf_metrics(
        bundles,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 50,
    )
    blind_macro_after = _build_blind_macro_prf_metrics(
        bundles,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 250,
    )

    overall_before_ag = _build_agentic_micro_prf_metrics(
        bundles,
        after_agentic=False,
        blind=False,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 700,
    )
    blind_overall_before_ag = _build_agentic_micro_prf_metrics(
        bundles,
        after_agentic=False,
        blind=True,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 720,
    )
    macro_before_ag = _build_agentic_macro_prf_metrics(
        bundles,
        after_agentic=False,
        blind=False,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 740,
    )
    blind_macro_before_ag = _build_agentic_macro_prf_metrics(
        bundles,
        after_agentic=False,
        blind=True,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 760,
    )

    overall_after_ag = _build_agentic_micro_prf_metrics(
        bundles,
        after_agentic=True,
        blind=False,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 800,
    )
    blind_overall_after_ag = _build_agentic_micro_prf_metrics(
        bundles,
        after_agentic=True,
        blind=True,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 820,
    )
    macro_after_ag = _build_agentic_macro_prf_metrics(
        bundles,
        after_agentic=True,
        blind=False,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 840,
    )
    blind_macro_after_ag = _build_agentic_macro_prf_metrics(
        bundles,
        after_agentic=True,
        blind=True,
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 860,
    )

    per_edge_type: dict[str, PRFMetrics] = {}
    for idx, et in enumerate(EDGE_TYPES):
        (
            _tp_gold_tot,
            tp_gold_core,
            tp_gold_ext,
            tp_pred,
            fp_pred,
            fn_gold_core,
            gold_core_cnt,
            gold_ext_cnt,
        ) = _type_counts_for_bundles(bundles, et)
        base_seed = bootstrap_seed + 400 + idx * 10
        p_ci = bootstrap_ci(
            bundles,
            lambda seq, _et=et: _type_prf(seq, _et)[0],
            iterations=bootstrap_iterations,
            seed=base_seed,
            numerator=tp_pred,
            denominator=tp_pred + fp_pred,
        )
        r_ci = bootstrap_ci(
            bundles,
            lambda seq, _et=et: _type_prf(seq, _et)[1],
            iterations=bootstrap_iterations,
            seed=base_seed + 1,
            numerator=tp_gold_core,
            denominator=tp_gold_core + fn_gold_core,
        )
        f1_ci = bootstrap_ci(
            bundles,
            lambda seq, _et=et: _type_prf(seq, _et)[2],
            iterations=bootstrap_iterations,
            seed=base_seed + 2,
        )
        per_edge_type[et] = PRFMetrics(
            precision=p_ci,
            recall=r_ci,
            f1=f1_ci,
            tp=tp_pred,
            tp_core=tp_gold_core,
            tp_extended=tp_gold_ext,
            fp=fp_pred,
            fn=fn_gold_core,
            gold_core_count=gold_core_cnt,
            gold_extended_count=gold_ext_cnt,
            gold_count=gold_core_cnt + gold_ext_cnt,
            predicted_count=tp_pred + fp_pred,
        )

    # Direction accuracy
    dir_num = sum(b.summary.direction_correct for b in bundles)
    dir_den = sum(b.summary.direction_total for b in bundles)
    direction_accuracy = bootstrap_ci(
        bundles,
        lambda seq: (
            sum(b.summary.direction_correct for b in seq)
            / sum(b.summary.direction_total for b in seq)
            if sum(b.summary.direction_total for b in seq) > 0
            else 1.0
        ),
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 600,
        numerator=dir_num,
        denominator=dir_den,
    )

    # Hard-negative FP rate (before and after V-INT)
    hn_before_num = sum(b.summary.hard_neg_fp_before_vint for b in bundles)
    hn_after_num = sum(b.summary.hard_neg_fp_after_vint for b in bundles)
    hn_den = sum(b.summary.negatives_total for b in bundles)

    hard_neg_before = bootstrap_ci(
        bundles,
        lambda seq: (
            sum(b.summary.hard_neg_fp_before_vint for b in seq)
            / sum(b.summary.negatives_total for b in seq)
            if sum(b.summary.negatives_total for b in seq) > 0
            else 0.0
        ),
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 610,
        numerator=hn_before_num,
        denominator=hn_den,
    )
    hard_neg_after = bootstrap_ci(
        bundles,
        lambda seq: (
            sum(b.summary.hard_neg_fp_after_vint for b in seq)
            / sum(b.summary.negatives_total for b in seq)
            if sum(b.summary.negatives_total for b in seq) > 0
            else 0.0
        ),
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 620,
        numerator=hn_after_num,
        denominator=hn_den,
    )

    all_neg_kinds = sorted(
        {kind for b in bundles for kind in b.negatives_total_by_kind}
    )
    hard_negative_by_kind: dict[str, dict[str, Any]] = {}
    for kind in all_neg_kinds:
        tot_k = sum(b.negatives_total_by_kind.get(kind, 0) for b in bundles)
        bef_k = sum(b.negatives_triggered_before_by_kind.get(kind, 0) for b in bundles)
        aft_k = sum(b.negatives_triggered_after_by_kind.get(kind, 0) for b in bundles)
        hard_negative_by_kind[kind] = {
            "total": tot_k,
            "fp_before_vint": bef_k,
            "fp_after_vint": aft_k,
            "rate_before_vint": round(bef_k / tot_k, 4) if tot_k > 0 else 0.0,
            "rate_after_vint": round(aft_k / tot_k, 4) if tot_k > 0 else 0.0,
        }

    # Facility-country accuracy
    fac_num = sum(b.summary.facility_country_correct for b in bundles)
    fac_den = sum(b.summary.facility_country_total for b in bundles)
    facility_country_accuracy = bootstrap_ci(
        bundles,
        lambda seq: (
            sum(b.summary.facility_country_correct for b in seq)
            / sum(b.summary.facility_country_total for b in seq)
            if sum(b.summary.facility_country_total for b in seq) > 0
            else 1.0
        ),
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 630,
        numerator=fac_num,
        denominator=fac_den,
    )

    # Importance-tier agreement (quadratic weighted kappa, linear weighted kappa, exact agreement) on blind gold matches
    def _imp_pairs(seq: Sequence[CompanyEvalBundle]) -> list[tuple[str, str]]:
        return [
            (m.gold_importance, m.pred_importance)
            for b in seq
            for m in b.match_after.matches
            if m.is_primary_gold_match and m.gold_source != "pooled"
        ]

    all_imp_pairs = _imp_pairs(bundles)
    imp_exact_num = sum(1 for g, p in all_imp_pairs if g == p)
    imp_den = len(all_imp_pairs)

    importance_weighted_kappa = bootstrap_ci(
        bundles,
        lambda seq: compute_weighted_kappa(_imp_pairs(seq), weights="quadratic"),
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 640,
        numerator=imp_exact_num,
        denominator=imp_den,
    )
    importance_linear_kappa = bootstrap_ci(
        bundles,
        lambda seq: compute_weighted_kappa(_imp_pairs(seq), weights="linear"),
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 641,
        numerator=imp_exact_num,
        denominator=imp_den,
    )
    importance_exact_agreement = bootstrap_ci(
        bundles,
        lambda seq: (
            sum(1 for g, p in _imp_pairs(seq) if g == p) / len(_imp_pairs(seq))
            if _imp_pairs(seq)
            else 1.0
        ),
        iterations=bootstrap_iterations,
        seed=bootstrap_seed + 642,
        numerator=imp_exact_num,
        denominator=imp_den,
    )

    summaries = [b.summary for b in bundles]
    all_fps = [err for s in summaries for err in s.false_positives]
    all_fns = [err for s in summaries for err in s.false_negatives]
    all_hn_leaks = [err for s in summaries for err in s.hard_negative_leaks]
    all_vint_filtered = [err for s in summaries for err in s.vint_filtered]
    all_pooled = [cand for s in summaries for cand in s.pooled_candidates]

    agg_core_by_source: dict[str, int] = {}
    for s in summaries:
        for src, cnt in s.gold_core_by_source.items():
            agg_core_by_source[src] = agg_core_by_source.get(src, 0) + cnt

    all_findings = [f for b in bundles for f in b.agentic_findings]
    all_after_edges = [e for b in bundles for e in b.edges_after_vint]
    all_before_edges = [e for b in bundles for e in b.edges_before_agentic]
    agentic_acceptance = evaluate_agentic_acceptance(
        findings=all_findings,
        edges=all_after_edges,
        initial_edges=all_before_edges,
        depth=research_depth,
    )

    return EvalRunReport(
        mode=mode,
        git_commit=git_commit,
        extractor_prompt_version=extractor_prompt_version,
        judge_prompt_version=judge_prompt_version,
        research_depth=research_depth,
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
        companies_evaluated=len(summaries),
        gold_relationships_total=sum(s.gold_total for s in summaries),
        gold_core_total=sum(s.gold_core_total for s in summaries),
        gold_extended_total=sum(s.gold_extended_total for s in summaries),
        gold_core_by_source=agg_core_by_source,
        gold_blind_total=sum(s.gold_blind_count for s in summaries),
        gold_pooled_total=sum(s.gold_pooled_count for s in summaries),
        gold_negatives_total=sum(s.negatives_total for s in summaries),
        overall_after_vint=overall_after,
        overall_before_vint=overall_before,
        macro_after_vint=macro_after,
        macro_before_vint=macro_before,
        blind_overall_after_vint=blind_overall_after,
        blind_macro_after_vint=blind_macro_after,
        overall_before_agentic=overall_before_ag,
        blind_overall_before_agentic=blind_overall_before_ag,
        macro_before_agentic=macro_before_ag,
        blind_macro_before_agentic=blind_macro_before_ag,
        overall_after_agentic=overall_after_ag,
        blind_overall_after_agentic=blind_overall_after_ag,
        macro_after_agentic=macro_after_ag,
        blind_macro_after_agentic=blind_macro_after_ag,
        agentic_findings_total=sum(s.agentic_findings_count for s in summaries),
        agentic_steps_done_total=sum(s.agentic_steps_done for s in summaries),
        agentic_steps_total=sum(s.agentic_steps_total for s in summaries),
        agentic_new_edges_total=sum(s.agentic_new_edges_count for s in summaries),
        agentic_rejected_edges_total=sum(s.agentic_rejected_edges_count for s in summaries),
        agentic_acceptance=agentic_acceptance,
        per_edge_type=per_edge_type,
        direction_accuracy=direction_accuracy,
        hard_negative_fp_rate_before_vint=hard_neg_before,
        hard_negative_fp_rate_after_vint=hard_neg_after,
        hard_negative_by_kind=hard_negative_by_kind,
        facility_country_accuracy=facility_country_accuracy,
        importance_weighted_kappa=importance_weighted_kappa,
        importance_linear_kappa=importance_linear_kappa,
        importance_exact_agreement=importance_exact_agreement,
        companies=summaries,
        false_positives=all_fps,
        false_negatives=all_fns,
        hard_negative_leaks=all_hn_leaks,
        vint_filtered=all_vint_filtered,
        pooled_candidates=all_pooled,
    )


_GROUP_CUSTOMER_RE = re.compile(
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten|several|multiple|combined|group\s+of|\d+)\s+"
    r"(?:largest\s+|major\s+|top\s+|principal\s+|primary\s+|combined\s+|significant\s+)*"
    r"(?:customers?|clients?|distributors?|resellers?)\b",
    re.IGNORECASE,
)
_QUOTED_SPAN_RE = re.compile(r'"([^"\n]{12,})"')
_PRIMARY_EDGE_ID_RE = re.compile(r"^res_(?:flagged|undisclosed|unresolved|single)_(.+)$")


def _extract_source_parts(
    source: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], set[str], str]:
    """Extract `(findings_dicts, edges_dicts, initial_edges_dicts, rejected_ids, depth)` from
    a `DependencyResult`, `DependencyJob`, `Mapping`, or sequence of `RecordedCompanyPrediction`."""
    if source is None:
        return [], [], [], set(), "light"

    # Unwrap DependencyJob -> .result
    if hasattr(source, "result") and getattr(source, "result") is not None:
        source = getattr(source, "result")
    elif isinstance(source, Mapping) and isinstance(source.get("result"), Mapping):
        source = source["result"]

    # Sequence of RecordedCompanyPrediction (or dicts with agentic_findings)
    if isinstance(source, Sequence) and not isinstance(source, (str, bytes, Mapping)):
        findings: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        init_edges: list[dict[str, Any]] = []
        rej_ids: set[str] = set()
        depth = "light"
        for item in source:
            if isinstance(item, RecordedCompanyPrediction):
                d = item.model_dump(mode="json")
            elif hasattr(item, "model_dump"):
                d = item.model_dump(mode="json")
            elif isinstance(item, Mapping):
                d = dict(item)
            else:
                continue
            depth = str(d.get("research_depth") or depth)
            for f in d.get("agentic_findings") or d.get("findings") or ():
                f_dict = f.model_dump(mode="json") if hasattr(f, "model_dump") else dict(f)
                findings.append(f_dict)
                for rid in f_dict.get("rejected_edge_ids") or ():
                    rej_ids.add(str(rid))
            raw_init = list(d.get("edges") or ())
            raw_after = d.get("agentic_edges")
            if raw_after is None:
                raw_after = raw_init
            init_edges.extend(
                e.model_dump(mode="json") if hasattr(e, "model_dump") else dict(e) for e in raw_init
            )
            edges.extend(
                e.model_dump(mode="json") if hasattr(e, "model_dump") else dict(e) for e in raw_after
            )
            for rid in d.get("agentic_rejected_edge_ids") or ():
                rej_ids.add(str(rid))
        return findings, edges, init_edges, rej_ids, depth

    # DependencyResult or Mapping
    if hasattr(source, "model_dump"):
        data = source.model_dump(mode="json")
    elif isinstance(source, Mapping):
        data = dict(source)
    else:
        return [], [], [], set(), "light"

    depth = str(data.get("research_depth") or data.get("depth") or "light")
    raw_findings = data.get("research") or data.get("agentic_findings") or data.get("findings") or []
    findings_list = [
        f.model_dump(mode="json") if hasattr(f, "model_dump") else dict(f) for f in raw_findings
    ]
    raw_edges = data.get("agentic_edges") if data.get("agentic_edges") is not None else (data.get("edges") or [])
    edges_list = [
        e.model_dump(mode="json") if hasattr(e, "model_dump") else dict(e) for e in raw_edges
    ]
    raw_init_edges = data.get("edges") or []
    init_edges_list = [
        e.model_dump(mode="json") if hasattr(e, "model_dump") else dict(e) for e in raw_init_edges
    ]
    rej_ids: set[str] = {str(rid) for rid in (data.get("rejected_edge_ids") or data.get("agentic_rejected_edge_ids") or ())}
    for f in findings_list:
        for rid in f.get("rejected_edge_ids") or ():
            rej_ids.add(str(rid))
    return findings_list, edges_list, init_edges_list, rej_ids, depth


def evaluate_agentic_acceptance(
    source: Any = None,
    thorough_source: Any = None,
    *,
    findings: Sequence[Mapping[str, Any] | Any] | None = None,
    edges: Sequence[Mapping[str, Any] | VerifiedEdge] | None = None,
    initial_edges: Sequence[Mapping[str, Any] | VerifiedEdge] | None = None,
    thorough_edges: Sequence[Mapping[str, Any] | VerifiedEdge] | None = None,
    thorough_rejected_edge_ids: Sequence[str] = (),
    depth: str | None = None,
) -> AgenticAcceptanceReport:
    """Compute numeric agentic acceptance metrics for FIX-1, FIX-2, and FIX-14.

    - FIX-1: tool calls per finding (`>= 2` for light, `>= 3` for thorough unless rejected with evidence),
      `search_filings` usage, and non-circular confirmations (re-finding only the initial edge's own quote
      in the same filing is not a confirmation).
    - FIX-2: when `thorough_source` (or `thorough_edges`) is supplied alongside `source` (`light`),
      every surviving `light` edge ID (not rejected in `thorough`) must be present in `thorough`.
    - FIX-14: no duplicate `unnamed_customer` edges sharing `(source_company_key, edge_type, normalised_quote)`,
      and no customer-group `unnamed_customer` edges (e.g. `'three largest customers'`).
    """
    src_findings, src_edges, src_init_edges, _src_rej, src_depth = _extract_source_parts(source)

    if findings is not None:
        findings_dicts = [
            f.model_dump(mode="json") if hasattr(f, "model_dump") else dict(f) for f in findings
        ]
    else:
        findings_dicts = src_findings

    if edges is not None:
        edges_dicts = [
            e.model_dump(mode="json") if hasattr(e, "model_dump") else dict(e) for e in edges
        ]
    else:
        edges_dicts = src_edges

    if initial_edges is not None:
        init_edges_dicts = [
            e.model_dump(mode="json") if hasattr(e, "model_dump") else dict(e) for e in initial_edges
        ]
    else:
        init_edges_dicts = src_init_edges or edges_dicts

    effective_depth = (depth or src_depth or "light").strip().lower()
    req_min_tools = 3 if effective_depth == "thorough" else 2

    # Index initial edges by edge_id for circular-confirmation check
    edge_by_id: dict[str, dict[str, Any]] = {}
    for e in init_edges_dicts:
        eid = str(e.get("edge_id") or "")
        if eid:
            edge_by_id[eid] = e
    for e in edges_dicts:
        eid = str(e.get("edge_id") or "")
        if eid and eid not in edge_by_id:
            edge_by_id[eid] = e

    findings_total = len(findings_dicts)
    tool_counts: list[int] = []
    single_lookup_count = 0
    meeting_min_count = 0
    search_filings_total = 0
    findings_with_search = 0
    read_section_total = 0
    find_in_filing_total = 0
    circular_confirmations = 0

    for f in findings_dicts:
        steps = list(f.get("steps") or ())
        tool_steps = [
            s for s in steps
            if str((s.get("action") if isinstance(s, Mapping) else getattr(s, "action", "")) or "") != "conclude"
        ]
        n_tools = len(tool_steps)
        tool_counts.append(n_tools)

        f_search = 0
        for s in tool_steps:
            act = str((s.get("action") if isinstance(s, Mapping) else getattr(s, "action", "")) or "")
            if act == "search_filings":
                search_filings_total += 1
                f_search += 1
            elif act == "read_section":
                read_section_total += 1
            elif act == "find_in_filing":
                find_in_filing_total += 1
        if f_search > 0:
            findings_with_search += 1

        outcome = str(f.get("outcome") or "")
        rej_ids = list(f.get("rejected_edge_ids") or ())
        is_valid_rejection = outcome == "rejected" and (n_tools >= 1 or len(rej_ids) > 0)

        if is_valid_rejection:
            meeting_min_count += 1
        else:
            if n_tools <= 1:
                single_lookup_count += 1
            if n_tools >= req_min_tools:
                meeting_min_count += 1

        # Circular confirmation check (FIX-1a): outcome == "confirmed" that only re-finds the edge's own quote
        if outcome == "confirmed":
            fid = str(f.get("finding_id") or "")
            m = _PRIMARY_EDGE_ID_RE.match(fid)
            primary_edge = edge_by_id.get(m.group(1)) if m else None
            if primary_edge is None:
                conf_ids = list(f.get("confirmed_edge_ids") or ())
                if conf_ids:
                    primary_edge = edge_by_id.get(str(conf_ids[0]))
            own_quote_norm = (
                normalise(str(primary_edge.get("evidence_quote") or "")).casefold()
                if primary_edge is not None
                else ""
            )
            explanation = str(f.get("explanation") or "")
            quoted_spans = [normalise(q).casefold() for q in _QUOTED_SPAN_RE.findall(explanation) if q.strip()]
            if n_tools == 0:
                circular_confirmations += 1
            elif f_search == 0 and own_quote_norm:
                if quoted_spans and all(
                    q in own_quote_norm or own_quote_norm in q for q in quoted_spans
                ) and n_tools <= 1:
                    circular_confirmations += 1

    tool_calls_total = sum(tool_counts)
    avg_tools = round(tool_calls_total / findings_total, 2) if findings_total > 0 else 0.0
    min_tools = min(tool_counts) if tool_counts else 0
    max_tools = max(tool_counts) if tool_counts else 0

    # FIX-14: Duplicate unnamed_customer edges on same (source_company_key, edge_type, normalised_quote)
    # and group unnamed_customer edges ('three largest customers', etc.)
    seen_unnamed_by_quote: dict[tuple[str, str, str], str] = {}
    dup_unnamed_ids: list[str] = []
    group_unnamed_ids: list[str] = []

    init_edge_ids = {str(e.get("edge_id") or "") for e in init_edges_dicts}
    new_edge_ids_from_findings = {
        str((ne.get("edge_id") if isinstance(ne, Mapping) else getattr(ne, "edge_id", "")) or "")
        for f in findings_dicts
        for ne in (f.get("new_edges") or ())
    }

    for e in edges_dicts:
        eid = str(e.get("edge_id") or "")
        tkind = str(e.get("target_kind") or "")
        if tkind != "unnamed_customer":
            continue
        src_key = str(e.get("source_company_key") or "")
        etype = str(e.get("edge_type") or "customer")
        q_norm = normalise(str(e.get("evidence_quote") or "")).casefold()
        key = (src_key, etype, q_norm)
        if q_norm:
            if key in seen_unnamed_by_quote:
                dup_unnamed_ids.append(eid)
            else:
                seen_unnamed_by_quote[key] = eid

        tname = str(e.get("target_name") or "")
        qual = str(e.get("qualifier") or "")
        is_agentic_new = (eid in new_edge_ids_from_findings) or (
            bool(init_edge_ids) and eid not in init_edge_ids
        )
        if _GROUP_CUSTOMER_RE.search(tname) or (is_agentic_new and _GROUP_CUSTOMER_RE.search(qual)):
            group_unnamed_ids.append(eid)

    # FIX-2: Thorough contains Light
    thorough_eval = thorough_source is not None or thorough_edges is not None
    light_surviving_cnt = len(edges_dicts)
    thorough_cnt = 0
    missing_light_ids: list[str] = []

    if thorough_eval:
        _tf, t_edges_src, _ti, t_rej_src, _td = _extract_source_parts(thorough_source)
        if thorough_edges is not None:
            t_edges_dicts = [
                e.model_dump(mode="json") if hasattr(e, "model_dump") else dict(e)
                for e in thorough_edges
            ]
        else:
            t_edges_dicts = t_edges_src
        t_rej_all = set(t_rej_src) | {str(r) for r in thorough_rejected_edge_ids}
        t_edge_ids = {str(e.get("edge_id") or "") for e in t_edges_dicts if e.get("edge_id")}
        thorough_cnt = len(t_edge_ids)
        surviving_light = [
            str(e.get("edge_id") or "")
            for e in edges_dicts
            if e.get("edge_id") and str(e.get("edge_id")) not in t_rej_all
        ]
        light_surviving_cnt = len(surviving_light)
        missing_light_ids = [eid for eid in surviving_light if eid not in t_edge_ids]

    fix_1_ok = (
        single_lookup_count == 0
        and circular_confirmations == 0
        and (effective_depth != "thorough" or findings_total == 0 or search_filings_total >= 1)
    )
    fix_2_ok = len(missing_light_ids) == 0
    fix_14_ok = len(dup_unnamed_ids) == 0 and len(group_unnamed_ids) == 0

    return AgenticAcceptanceReport(
        depth=effective_depth,
        findings_total=findings_total,
        tool_calls_total=tool_calls_total,
        avg_tool_calls_per_finding=avg_tools,
        min_tool_calls_per_finding=min_tools,
        max_tool_calls_per_finding=max_tools,
        single_lookup_findings_count=single_lookup_count,
        findings_meeting_min_tool_calls=meeting_min_count,
        search_filings_calls_total=search_filings_total,
        findings_with_search_filings=findings_with_search,
        read_section_calls_total=read_section_total,
        find_in_filing_calls_total=find_in_filing_total,
        circular_confirmations_count=circular_confirmations,
        duplicate_unnamed_customer_edges_count=len(dup_unnamed_ids),
        duplicate_unnamed_customer_edge_ids=dup_unnamed_ids,
        group_unnamed_customer_edges_count=len(group_unnamed_ids),
        group_unnamed_customer_edge_ids=group_unnamed_ids,
        thorough_evaluated=thorough_eval,
        light_surviving_edges_count=light_surviving_cnt,
        thorough_edges_count=thorough_cnt,
        thorough_missing_light_edge_ids=missing_light_ids,
        thorough_contains_light=fix_2_ok,
        fix_1_pass=fix_1_ok,
        fix_2_pass=fix_2_ok,
        fix_14_pass=fix_14_ok,
        all_passed=(fix_1_ok and fix_2_ok and fix_14_ok),
    )


def format_agentic_acceptance_summary(acc: AgenticAcceptanceReport) -> str:
    """Format a concise console summary of `AgenticAcceptanceReport` for FIX-1, FIX-2, and FIX-14."""
    f1_status = "PASS" if acc.fix_1_pass else "FAIL"
    f2_status = (
        ("PASS" if acc.fix_2_pass else "FAIL")
        if acc.thorough_evaluated
        else "N/A (single depth)"
    )
    f14_status = "PASS" if acc.fix_14_pass else "FAIL"
    overall = "PASS" if acc.all_passed else "FAIL"
    lines = [
        f"Agentic Sub-Agent Acceptance Check (depth={acc.depth}) : {overall}",
        (
            f"  FIX-1  Multi-step & non-circular : {f1_status} | "
            f"findings={acc.findings_total}, avg_tools={acc.avg_tool_calls_per_finding:.2f} "
            f"(min={acc.min_tool_calls_per_finding}, max={acc.max_tool_calls_per_finding}), "
            f"single_lookup={acc.single_lookup_findings_count}/{acc.findings_total}, "
            f"meeting_min={acc.findings_meeting_min_tool_calls}/{acc.findings_total}, "
            f"search_filings={acc.search_filings_calls_total} ({acc.findings_with_search_filings} findings), "
            f"circular_confirmed={acc.circular_confirmations_count}"
        ),
        (
            f"  FIX-2  Thorough contains Light   : {f2_status} | "
            f"light_surviving={acc.light_surviving_edges_count}, thorough_edges={acc.thorough_edges_count}, "
            f"missing_light_ids={acc.thorough_missing_light_edge_ids}"
        ),
        (
            f"  FIX-14 No dup/group unnamed cust : {f14_status} | "
            f"duplicate_unnamed={acc.duplicate_unnamed_customer_edges_count} ({acc.duplicate_unnamed_customer_edge_ids}), "
            f"group_unnamed={acc.group_unnamed_customer_edges_count} ({acc.group_unnamed_customer_edge_ids})"
        ),
    ]
    return "\n".join(lines)
