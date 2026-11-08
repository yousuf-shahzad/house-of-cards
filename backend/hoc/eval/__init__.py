"""v3 Unseen-data evaluation harness (package E-RUN, Bekarys's Gemini).

Public API:
- `run_evaluation(...) -> EvalRunReport`
- `run_eval_cli(argv) -> int`
- `build_eval_arg_parser(parser) -> ArgumentParser`
- `run_eval_from_args(args) -> int`
- `evaluate_company(gold_doc, predicted_edges, *, vint_rejected_edges=()) -> CompanyEvalBundle`
- `aggregate_eval_report(bundles, ...) -> EvalRunReport`
- `render_eval_markdown(report) -> str`
- `write_eval_outputs(report, *, markdown_path, json_path)`
"""

from __future__ import annotations

from hoc.eval.matching import (
    AnnotatorAgreementSummary,
    SinglePassMatchResult,
    canonical_eval_name_key,
    compare_annotator_docs,
    compatible_edge_types,
    edge_matches_negative,
    fallback_importance_tier,
    infer_edge_direction,
    match_predictions_to_gold,
    resolve_edge_importance_tier,
    targets_match,
    targets_match_name,
)
from hoc.eval.metrics import (
    CompanyEvalBundle,
    aggregate_eval_report,
    bootstrap_ci,
    compute_weighted_kappa,
    evaluate_agentic_acceptance,
    evaluate_company,
    format_agentic_acceptance_summary,
    safe_prf,
)
from hoc.eval.report import render_eval_markdown, write_eval_outputs
from hoc.eval.runner import (
    DEFAULT_EVAL_JSON,
    DEFAULT_EVAL_MD,
    DEFAULT_GOLD_DIR,
    DEFAULT_RECORDED_DIR,
    build_eval_arg_parser,
    build_synthetic_held_out_fixture,
    format_console_summary,
    load_recorded_predictions,
    run_eval_cli,
    run_eval_from_args,
    run_evaluation,
    save_recorded_prediction,
)
from hoc.eval.schema import (
    HELD_OUT_BY_CIK,
    HELD_OUT_BY_TICKER,
    HELD_OUT_COMPANIES,
    AgenticAcceptanceReport,
    CompanyEvalSummary,
    EdgeMatchDetail,
    EvalErrorDetail,
    EvalRunReport,
    GoldCompany,
    GoldDirection,
    GoldDocument,
    GoldFiling,
    GoldNegative,
    GoldRelationship,
    HeldOutCompany,
    MetricWithCI,
    PooledCandidate,
    PRFMetrics,
    RecordedCompanyPrediction,
    load_gold_directory,
    load_gold_document,
    verify_gold_quotes,
)

__all__ = [
    "DEFAULT_EVAL_JSON",
    "DEFAULT_EVAL_MD",
    "DEFAULT_GOLD_DIR",
    "DEFAULT_RECORDED_DIR",
    "HELD_OUT_BY_CIK",
    "HELD_OUT_BY_TICKER",
    "HELD_OUT_COMPANIES",
    "AgenticAcceptanceReport",
    "AnnotatorAgreementSummary",
    "CompanyEvalBundle",
    "CompanyEvalSummary",
    "EdgeMatchDetail",
    "EvalErrorDetail",
    "EvalRunReport",
    "GoldCompany",
    "GoldDirection",
    "GoldDocument",
    "GoldFiling",
    "GoldNegative",
    "GoldRelationship",
    "HeldOutCompany",
    "MetricWithCI",
    "PRFMetrics",
    "PooledCandidate",
    "RecordedCompanyPrediction",
    "SinglePassMatchResult",
    "aggregate_eval_report",
    "bootstrap_ci",
    "build_eval_arg_parser",
    "build_synthetic_held_out_fixture",
    "canonical_eval_name_key",
    "compare_annotator_docs",
    "compatible_edge_types",
    "compute_weighted_kappa",
    "edge_matches_negative",
    "evaluate_agentic_acceptance",
    "evaluate_company",
    "fallback_importance_tier",
    "format_agentic_acceptance_summary",
    "format_console_summary",
    "infer_edge_direction",
    "load_gold_directory",
    "load_gold_document",
    "load_recorded_predictions",
    "match_predictions_to_gold",
    "render_eval_markdown",
    "resolve_edge_importance_tier",
    "run_eval_cli",
    "run_eval_from_args",
    "run_evaluation",
    "safe_prf",
    "save_recorded_prediction",
    "targets_match",
    "targets_match_name",
    "verify_gold_quotes",
    "write_eval_outputs",
]
