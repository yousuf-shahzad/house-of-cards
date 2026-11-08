"""C0-v3 contract checks (docs/hoc/PLAN-v3.md): models, bounds, and the frontend fixtures' invariants."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from hoc.contract import (
    CompareRequest,
    CompareResponse,
    DependencyJob,
    EdgeImportance,
    PortfolioItem,
    ResearchJob,
    ResearchRequest,
)
from hoc.contract.errors import ResearchNotFoundError

FIXTURES = Path(__file__).resolve().parents[2] / "frontend" / "api" / "__fixtures__"
TIERS = (("critical", 0.8), ("high", 0.6), ("medium", 0.4), ("low", 0.0))


def _load(name: str) -> dict:
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    data.pop("_comment", None)
    return data


def _tier_for(score: float) -> str:
    return next(tier for tier, floor in TIERS if score >= floor)


def test_importance_score_is_bounded_and_finite():
    EdgeImportance(score=0.0, tier="low")
    EdgeImportance(score=1.0, tier="critical")
    for bad in (-0.01, 1.01, math.nan, math.inf):
        with pytest.raises(ValidationError):
            EdgeImportance(score=bad, tier="low")


def test_request_bounds():
    items = [PortfolioItem(ticker="ZZAAA", allocation=1.0)]
    assert CompareRequest(baseline=items, candidate=items).top_n == 15
    for bad in (0, 31):
        with pytest.raises(ValidationError):
            CompareRequest(baseline=items, candidate=items, top_n=bad)
    with pytest.raises(ValidationError):
        CompareRequest(baseline=[], candidate=items)
    assert ResearchRequest().max_items == 6
    for bad in (0, 11):
        with pytest.raises(ValidationError):
            ResearchRequest(max_items=bad)


def test_research_not_found_is_a_404_with_its_own_code():
    assert (ResearchNotFoundError.code, ResearchNotFoundError.status) == ("RESEARCH_NOT_FOUND", 404)


def test_dependencies_fixture_v3_invariants():
    result = DependencyJob.model_validate(_load("synthetic-dependencies.json")).result
    assert result is not None and result.coverage is not None
    for edge in result.edges:
        assert edge.importance is not None and edge.interpretation is not None
        assert edge.interpretation.status != "rejected"  # rejected edges are only counted
        assert edge.importance.tier == _tier_for(edge.importance.score)
        if edge.interpretation.status == "flagged":
            assert edge.importance.tier in ("medium", "low")  # flagged edges are capped at medium
    assert result.counts.interpretation_rejected >= 0
    buckets = result.coverage.buckets
    assert abs(math.fsum(b.weight for b in buckets) - 1.0) <= 1e-6
    assert len({b.kind for b in buckets}) == len(buckets)
    assert all(0.0 <= e.verified_weight <= 1.0 for e in result.coverage.by_etf)
    assert len(result.coverage.largest_unanalysed) <= 10
    ids = {m.metric_id for m in result.metrics}
    for m in result.metrics:
        if m.metric_id.startswith("critical.") and not m.metric_id.endswith(".companies"):
            assert m.metric_id.replace("critical.", "dep.", 1) in ids  # a critical metric has its dep twin


def test_research_fixture_merges_its_findings():
    job = ResearchJob.model_validate(_load("synthetic-research.json"))
    assert job.status == "done" and job.result is not None
    result_ids = {e.edge_id for e in job.result.edges}
    for finding in job.findings:
        assert [s.index for s in finding.steps] == list(range(1, len(finding.steps) + 1))
        assert finding.steps and finding.steps[-1].action == "conclude"
        for edge in finding.new_edges:
            assert edge.edge_id in result_ids
            assert edge.interpretation is not None and edge.interpretation.status != "rejected"
        assert not set(finding.rejected_edge_ids) & result_ids


def test_compare_fixture_invariants():
    resp = CompareResponse.model_validate(_load("synthetic-compare.json"))
    assert (resp.status == "partial") == bool(resp.candidate_unanalysed)
    for d in resp.dependency_deltas:
        if d.baseline is not None and d.candidate is not None:
            assert d.delta is not None and abs(d.delta - (d.candidate - d.baseline)) <= 1e-9
        else:
            assert d.delta is None
    units = [d.unit for d in resp.dependency_deltas]
    assert units == sorted(units, key=lambda u: u != "fraction")  # fractions first, then counts
    for unit in set(units):
        mags = [abs(d.delta) if d.delta is not None else abs(d.candidate if d.candidate is not None else d.baseline or 0.0)
                for d in resp.dependency_deltas if d.unit == unit]
        assert mags == sorted(mags, reverse=True)
    for c in resp.concentration_deltas:
        assert abs(c.delta - (c.candidate - c.baseline)) <= 1e-9


# ---------- C0-v3.1 ----------

def test_v31_request_depth_defaults_light_and_is_bounded():
    items = [PortfolioItem(ticker="ZZAAA", allocation=1.0)]
    from hoc.contract import DependencyRequest
    assert DependencyRequest(holdings=items).depth == "light"
    assert DependencyRequest(holdings=items, depth="thorough").depth == "thorough"
    with pytest.raises(ValidationError):
        DependencyRequest(holdings=items, depth="deep")


def test_v31_job_progress_and_research_fields():
    job = DependencyJob.model_validate(_load("synthetic-dependencies.json"))
    assert job.phase in ("queued", "reading", "researching", "synthesising", "done")
    assert 0 <= job.steps_done <= job.steps_total
    result = job.result
    assert result is not None and result.research_depth in ("none", "light", "thorough")
    edge_ids = {e.edge_id for e in result.edges}
    for finding in result.research:
        assert finding.steps and finding.steps[-1].action == "conclude"
        assert set(finding.confirmed_edge_ids) <= edge_ids
    # Defaults keep v3 payloads valid.
    assert DependencyJob(job_id="x", status="queued").phase == "queued"


def test_v31_plain_insight_fields_are_short():
    import re
    result = DependencyJob.model_validate(_load("synthetic-dependencies.json")).result
    for claim in result.insights.flaws + result.insights.suggestions:
        if claim.plain_title is not None:
            assert len(claim.plain_title.split()) <= 8
        if claim.plain_text is not None:
            assert len(claim.plain_text.split()) <= 25
            assert "{{metric:" not in claim.plain_text  # rendered, like `text`
            assert len(re.findall(r"\d+(?:\.\d+)?%?", claim.plain_text)) <= 1


def test_v31_compare_top_sector_delta():
    resp = CompareResponse.model_validate(_load("synthetic-compare.json"))
    top = [c for c in resp.concentration_deltas if c.name == "top_sector"]
    assert len(top) == 1 and abs(top[0].delta - (top[0].candidate - top[0].baseline)) <= 1e-9
