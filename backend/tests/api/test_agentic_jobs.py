"""v3.1 A2: the per-company research agents inside dependency jobs (depth, phases, steps, merge, skips).

SYNTHETIC fixtures and a fake pipeline; the real agents (hoc.research, A1) are tested in their own package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pytest

from hoc.contract import (
    CompanyUnavailable,
    DependencyRequest,
    FilingRef,
    Insights,
    MetricFact,
    ResearchFinding,
    VerifiedEdge,
)
from hoc.jobs import DependencyJobs, Extraction, InlineExecutor

HOLDINGS = [{"ticker": "ZZAAA", "allocation": 0.5}, {"ticker": "ZZBBB", "allocation": 0.3},
            {"ticker": "ZZCCC", "allocation": 0.2}]


def edge(company, filing, edge_id, target="ZZ Foundry"):
    return VerifiedEdge(edge_id=edge_id, source_company_key=company.company_key,
                        source_company_name=company.company_name, source_in_portfolio=True, edge_type="foundry",
                        target_name=target, target_kind="company",
                        evidence_quote=f"We rely on {target} for our wafers (synthetic).", section="1", filing=filing)


@dataclass
class Found:
    findings: list
    edges: list
    rejected_edge_ids: list = field(default_factory=list)
    cached: bool = False
    interpretation_rejected: int = 0


class AgenticPipeline:
    prompt_version = "test-agentic"

    def __init__(self, *, unavailable=None, research_error=None, steps=3):
        self.unavailable = unavailable  # CompanyUnavailable status raised by research_company, if any
        self.research_error = research_error
        self.steps = steps
        self.research_calls: list[dict] = []
        self.observe = None  # called while reading and after each agent step (FIX-18 test)

    def filing(self, company):
        return FilingRef(company_key=company.company_key, form="10-K", accession=f"0000-{company.company_key}",
                         filed=date(2026, 2, 1), url="https://example.invalid/filing")

    def extract(self, company, filing, *, cache_only):
        if self.observe:
            self.observe()
        return Extraction(edges=[edge(company, filing, f"keep-{company.company_key}"),
                                 edge(company, filing, f"drop-{company.company_key}", "ZZ Rival")], cached=True)

    def research_company(self, company, filing, edges, *, depth, cache_only, progress, analysis):
        self.research_calls.append({"company": company.company_key, "depth": depth, "cache_only": cache_only,
                                    "edges": [e.edge_id for e in edges], "has_analysis": analysis is not None})
        if self.unavailable:
            raise CompanyUnavailable(self.unavailable, "no key")
        if self.research_error:
            raise self.research_error
        for step in range(1, self.steps + 1):
            progress(step, self.steps)
            if self.observe:
                self.observe()
        new = edge(company, filing, f"new-{company.company_key}", "ZZ Second Source")
        finding = ResearchFinding(finding_id=f"f-{company.company_key}", kind="single_source", subject="ZZ Foundry",
                                  question="Is ZZ Foundry the only foundry?", outcome="revised",
                                  explanation="The filing names a second source.", confirmed_edge_ids=[edges[0].edge_id],
                                  rejected_edge_ids=[f"drop-{company.company_key}"], new_edges=[new])
        return Found(findings=[finding], edges=[*edges, new], rejected_edge_ids=[f"drop-{company.company_key}"],
                     interpretation_rejected=1)

    def insights(self, analysis, edges, *, cache_only):
        return [MetricFact(metric_id="m1", label="synthetic", value=0.1, unit="fraction")], \
            Insights(status="metrics_only")


@pytest.fixture
def jobs(make_service):
    def make(pipeline):
        service, _ = make_service()
        service.dependency_pipeline = pipeline
        service._jobs = DependencyJobs(service.analyse, pipeline, runner=InlineExecutor(), workers=InlineExecutor())
        return service

    return make


def submit(service, depth="light", top_n=2, **kw):
    return service.submit_dependencies(DependencyRequest(holdings=HOLDINGS, top_n=top_n, depth=depth), **kw)


@pytest.mark.parametrize("agent_steps", [3, 8])  # fewer than the light estimate (2 x 3 = 6), and more
def test_progress_never_goes_backwards(jobs, agent_steps):
    """FIX-18: steps_total starts at its full estimate (read + every agent's reserved steps + synth) and only
    falls, so the bar's % never drops, whether an agent reports fewer steps than reserved or more."""
    pipeline = AgenticPipeline(steps=agent_steps)
    service = jobs(pipeline)
    seen: list[tuple[int, int]] = []
    pipeline.observe = lambda: seen.extend((j.steps_done, j.steps_total)
                                           for j in map(service._jobs.get, list(service._jobs._jobs)))
    job = submit(service)
    seen.append((job.steps_done, job.steps_total))
    assert seen[0][1] == 2 + 2 * 6 + 1  # reserved before any agent reported
    totals = [total for _, total in seen]
    assert totals == sorted(totals, reverse=True)
    ratios = [done / total for done, total in seen]
    assert ratios == sorted(ratios) and ratios[-1] == 1
    assert job.steps_total == 2 + 2 * min(agent_steps, 6) + 1


def test_light_run_merges_research_and_reports_progress(jobs):
    pipeline = AgenticPipeline()
    job = submit(jobs(pipeline))
    assert job.status == "done" and job.phase == "done"
    result = job.result
    ids = {e.edge_id for e in result.edges}
    keys = [c.company_key for c in job.companies]
    assert all(f"keep-{k}" in ids and f"new-{k}" in ids and f"drop-{k}" not in ids for k in keys)
    assert [f.finding_id for f in result.research] == [f"f-{k}" for k in keys]
    assert result.research_depth == "light"
    assert {c.status for c in job.companies} == {"cached"}  # research never changes what was read
    assert all(c.verified_edges == 2 and c.rejected_edges == 1 for c in job.companies)
    assert result.counts.interpretation_rejected == 2
    assert (job.steps_done, job.steps_total) == (2 + 2 * 3 + 1, 2 + 2 * 3 + 1)  # read 2 + research 3 each + synth
    assert all(call["depth"] == "light" and call["has_analysis"] for call in pipeline.research_calls)


def test_depth_is_part_of_the_job_and_reaches_the_agents(jobs):
    pipeline = AgenticPipeline()
    service = jobs(pipeline)
    light, thorough = submit(service, "light"), submit(service, "thorough")
    assert light.job_id != thorough.job_id
    assert thorough.result.research_depth == "thorough"
    assert [c["depth"] for c in pipeline.research_calls] == ["light", "light", "thorough", "thorough"]


def test_cache_only_warm_up_without_cached_research_never_downgrades(jobs):
    """Lead rule: research missing from the cache (or no key) leaves companies 'cached' with their edges."""
    pipeline = AgenticPipeline(unavailable="missing_api_key")
    job = submit(jobs(pipeline), cache_only=True)
    assert job.status == "done" and job.error is None
    assert {c.status for c in job.companies} == {"cached"}
    assert job.result.research == [] and job.result.research_depth == "none"
    assert all("Double-check skipped" in c.message for c in job.companies)
    assert {e.edge_id for e in job.result.edges} >= {f"drop-{c.company_key}" for c in job.companies}  # untouched
    assert job.steps_done == job.steps_total  # skipped agents still complete the bar


def test_no_key_on_a_live_click_says_so(jobs):
    job = submit(jobs(AgenticPipeline(unavailable="missing_api_key")))
    assert all("no AI key" in c.message for c in job.companies) and job.result.research_depth == "none"


def test_a_failing_agent_costs_only_its_double_check(jobs):
    job = submit(jobs(AgenticPipeline(research_error=RuntimeError("agent bug"))))
    assert job.status == "done" and {c.status for c in job.companies} == {"cached"}
    assert all("failed" in c.message for c in job.companies) and job.result.research == []


def test_research_budget_skips_agents_not_started(jobs, monkeypatch):
    monkeypatch.setattr("hoc.jobs.RESEARCH_BUDGET_SECONDS", {"light": -1.0, "thorough": -1.0})
    pipeline = AgenticPipeline()
    job = submit(jobs(pipeline))
    assert pipeline.research_calls == []
    assert all("time budget" in c.message for c in job.companies)
    assert job.result.research_depth == "none" and job.steps_done == job.steps_total


def test_pipelines_without_agents_keep_v3_behaviour(jobs):
    class Plain(AgenticPipeline):
        research_company = None

    job = submit(jobs(Plain()))
    assert job.result.research == [] and job.result.research_depth == "none"
    assert (job.steps_done, job.steps_total) == (3, 3)  # read 2 + synth 1


def test_live_pipeline_uses_the_runner_entry_point_only_when_it_exists(make_service):
    from hoc.contract import PortfolioRequest
    from hoc.jobs import LivePipeline

    service, _ = make_service()
    analysis = service.analyse(PortfolioRequest(holdings=HOLDINGS))
    pipeline = LivePipeline(fetcher=None, extractor=type("E", (), {"prompt_version": "e"})(),
                            orchestrator=type("O", (), {"prompt_version": "o"})())
    assert pipeline.research_company is None  # no runner yet: the job skips research as in v3
    pipeline.researcher = object()
    assert pipeline.research_company is None  # a runner without A1's entry point: still skipped
    seen = {}

    class Runner:
        def research_company(self, company, filing, edges, **kwargs):
            seen.update(kwargs)
            return "ok"

    pipeline.researcher = Runner()
    first = analysis.exposures[0]
    assert pipeline.research_company(first, None, [], depth="thorough", cache_only=True, progress=print,
                                     analysis=analysis) == "ok"
    assert seen["depth"] == "thorough" and seen["cache_only"] and seen["analysis"] is analysis
    assert seen["resolve_target_key"](first.company_name) == first.company_key
