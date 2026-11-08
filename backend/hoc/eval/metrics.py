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
from collections.abc import Callable, Sequence
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
    CompanyEvalSummary,
    EvalRunReport,
    GoldDocument,
    MetricWithCI,
    PRFMetrics,
)

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
) -> CompanyEvalBundle:
    """Evaluate one company's predicted edges (before and after V-INT) against its `GoldDocument`."""
    edges_before, edges_after, edges_rejected = _partition_vint_edges(
        predicted_edges, vint_rejected_edges
    )

    match_before = match_predictions_to_gold(edges_before, gold_doc)
    match_after = match_predictions_to_gold(edges_after, gold_doc)

    blind_rels = [r for r in gold_doc.relationships if r.source.strip().lower() != "pooled"]
    gold_doc_blind = gold_doc.model_copy(update={"relationships": blind_rels})
    match_blind_after = match_predictions_to_gold(edges_after, gold_doc_blind)

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

    return EvalRunReport(
        mode=mode,
        git_commit=git_commit,
        extractor_prompt_version=extractor_prompt_version,
        judge_prompt_version=judge_prompt_version,
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
