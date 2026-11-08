"""Dependency graph metrics, importance, coverage, and Gemini orchestrator (packages G-ORCH, R-IMP, C-COV)."""

from __future__ import annotations

from hoc.graph.coverage import compute_coverage_report
from hoc.graph.importance import (
    attach_edge_importance,
    score_edge_importance,
    tier_for_score,
)
from hoc.graph.metrics import (
    DependencyGraphSummary,
    FacilityCountrySummary,
    SinglePointOfFailureSummary,
    SupplierDependencySummary,
    canonical_country_info,
    canonical_target_identity,
    compute_dependency_metrics,
    compute_dependency_summary,
    format_metric_value,
    slugify_metric_token,
)
from hoc.graph.orchestrator import (
    ORCHESTRATOR_PROMPT_VERSION,
    ORCHESTRATOR_RESPONSE_SCHEMA,
    ORCHESTRATOR_SYSTEM_INSTRUCTION,
    DependencyOrchestrator,
    OrchestratorAiClient,
    build_allowed_vocabulary,
    build_deterministic_raw_claims,
    build_user_prompt,
    compute_orchestrator_cache_key,
    insights,
    prompt_version,
    verify_and_build_insights,
    verify_and_render_claim,
)

__all__ = [
    "ORCHESTRATOR_PROMPT_VERSION",
    "ORCHESTRATOR_RESPONSE_SCHEMA",
    "ORCHESTRATOR_SYSTEM_INSTRUCTION",
    "DependencyGraphSummary",
    "DependencyOrchestrator",
    "FacilityCountrySummary",
    "OrchestratorAiClient",
    "SinglePointOfFailureSummary",
    "SupplierDependencySummary",
    "attach_edge_importance",
    "build_allowed_vocabulary",
    "build_deterministic_raw_claims",
    "build_user_prompt",
    "canonical_country_info",
    "canonical_target_identity",
    "compute_coverage_report",
    "compute_dependency_metrics",
    "compute_dependency_summary",
    "compute_orchestrator_cache_key",
    "format_metric_value",
    "insights",
    "prompt_version",
    "score_edge_importance",
    "slugify_metric_token",
    "tier_for_score",
    "verify_and_build_insights",
    "verify_and_render_claim",
]
