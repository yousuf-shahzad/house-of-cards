"""I-API v3 (c): research jobs (hoc.jobs.ResearchJobs) and their routes, over SYNTHETIC fixtures, a fake dependency
pipeline and a fake research runner. The real runner (A-RES, hoc.research) plugs in behind ResearchRunner."""

from __future__ import annotations

import threading
from datetime import date

import pytest
from fastapi.testclient import TestClient

from hoc.api.app import create_app
from hoc.config import Settings
from hoc.contract import FilingRef, Insights, MetricFact, ResearchFinding, ResearchStep, VerifiedEdge
from hoc.jobs import DependencyJobs, Extraction, InlineExecutor, ResearchJobs

HOLDINGS = [{"ticker": "ZZAAA", "allocation": 0.5}, {"ticker": "ZZBBB", "allocation": 0.3},
            {"ticker": "ZZCCC", "allocation": 0.2}]


class CachedPipeline:
    """Every company is cached with one SYNTHETIC supplier edge."""

    prompt_version = "test-v1"

    def filing(self, company):
        return FilingRef(company_key=company.company_key, form="10-K", accession=f"0000-{company.company_key}",
                         filed=date(2026, 2, 1), url="https://example.invalid/filing")

    def extract(self, company, filing, *, cache_only):
        edge = VerifiedEdge(edge_id=f"e-{company.company_key}", source_company_key=company.company_key,
                            source_company_name=company.company_name, source_in_portfolio=True,
                            edge_type="supplier", target_name="ZZ Foundry", target_kind="company",
                            evidence_quote="We rely on ZZ Foundry (synthetic).", section="1", filing=filing)
        return Extraction(edges=[edge], quality="sections", cached=True)

    def insights(self, analysis, edges, *, cache_only):
        return [MetricFact(metric_id="m1", label="synthetic", value=0.1, unit="fraction")], Insights(status="ok")


def finding(index: int, outcome: str = "confirmed") -> ResearchFinding:
    return ResearchFinding(
        finding_id=f"f{index}", kind="flagged_edge", subject="ZZ Foundry", question="Is ZZ Foundry a supplier?",
        outcome=outcome, explanation="SYNTHETIC: the quote names ZZ Foundry as the sole wafer supplier.",
        steps=[ResearchStep(index=0, action="find_in_filing", query="ZZ Foundry", summary="1 match in Item 1"),
               ResearchStep(index=1, action="conclude", summary="confirmed")],
        confirmed_edge_ids=[f"e-{index}"] if outcome == "confirmed" else [])


class FakeRunner:
    prompt_version = "research-test-v1"

    def __init__(self, *, items=2, crash=False, gate=None):
        self.items, self.crash, self.gate = items, crash, gate
        self.calls: list[dict] = []

    def run(self, result, analysis, *, max_items, cache_only, progress):
        self.calls.append({"max_items": max_items, "cache_only": cache_only, "edges": len(result.edges)})
        if self.gate is not None:
            self.gate.wait(10)
        if self.crash:
            raise RuntimeError("synthetic research bug")
        total = min(self.items, max_items)
        found = []
        for i in range(total):
            found.append(finding(i))
            progress(i + 1, total, found)
        merged = result.model_copy(update={"insights": Insights(status="ok", model="research-merged")})
        return found, merged


@pytest.fixture
def setup(make_service):
    """setup(runner, inline=True) -> (TestClient, service, runner)."""

    def make(runner, *, inline=True):
        service, _ = make_service()
        service.dependency_pipeline = CachedPipeline()
        service.research_runner = runner
        service._jobs = DependencyJobs(service.analyse, service.dependency_pipeline, runner=InlineExecutor(),
                                       workers=InlineExecutor())
        if inline:
            service._research = ResearchJobs(service._jobs, runner, executor=InlineExecutor())
        return TestClient(create_app(lambda: service, Settings())), service, runner

    return make


def finished_dependency_job(client) -> str:
    job = client.post("/api/dependencies", json={"holdings": HOLDINGS, "top_n": 3}).json()
    assert job["status"] == "done"
    return job["job_id"]


def test_research_on_a_finished_job_returns_findings_and_a_merged_result(setup):
    client, _, runner = setup(FakeRunner(items=2))
    job_id = finished_dependency_job(client)
    response = client.post(f"/api/dependencies/{job_id}/research", json={"max_items": 4})
    assert response.status_code == 200, response.text
    research = response.json()
    assert research["status"] == "done" and research["dependency_job_id"] == job_id
    assert (research["progress_done"], research["progress_total"]) == (2, 2)
    assert [f["finding_id"] for f in research["findings"]] == ["f0", "f1"]
    assert research["findings"][0]["steps"][-1]["action"] == "conclude"
    assert research["result"]["insights"]["model"] == "research-merged"
    assert runner.calls == [{"max_items": 4, "cache_only": False, "edges": 3}]
    assert client.get(f"/api/research/{research['research_id']}").json() == research  # POST and GET share one shape


def test_the_body_is_optional_and_defaults_to_six_items(setup):
    client, _, runner = setup(FakeRunner())
    job_id = finished_dependency_job(client)
    assert client.post(f"/api/dependencies/{job_id}/research").status_code == 200
    assert runner.calls[0]["max_items"] == 6


def test_same_research_twice_is_one_job(setup):
    client, _, runner = setup(FakeRunner())
    job_id = finished_dependency_job(client)
    first = client.post(f"/api/dependencies/{job_id}/research").json()
    second = client.post(f"/api/dependencies/{job_id}/research").json()
    assert first["research_id"] == second["research_id"] and len(runner.calls) == 1


def test_unknown_dependency_job_is_404_and_unknown_research_is_404(setup):
    client, _, _ = setup(FakeRunner())
    response = client.post("/api/dependencies/nope/research")
    assert response.status_code == 404 and response.json()["error"]["code"] == "JOB_NOT_FOUND"
    response = client.get("/api/research/nope")
    assert response.status_code == 404 and response.json()["error"]["code"] == "RESEARCH_NOT_FOUND"


def test_research_before_the_dependency_job_finishes_is_a_422(setup, make_service):
    gate = threading.Event()

    class SlowPipeline(CachedPipeline):
        def extract(self, company, filing, *, cache_only):
            gate.wait(10)
            return super().extract(company, filing, cache_only=cache_only)

    client, service, _ = setup(FakeRunner())
    service.dependency_pipeline = SlowPipeline()
    service._jobs = DependencyJobs(service.analyse, service.dependency_pipeline)  # threaded: stays running
    service._research = ResearchJobs(service._jobs, service.research_runner, executor=InlineExecutor())
    job = client.post("/api/dependencies", json={"holdings": HOLDINGS, "top_n": 3}).json()
    try:
        response = client.post(f"/api/dependencies/{job['job_id']}/research")
        assert response.status_code == 422 and response.json()["error"]["code"] == "VALIDATION_ERROR"
    finally:
        gate.set()


def test_a_runner_crash_fails_the_research_job_not_the_server(setup):
    client, _, _ = setup(FakeRunner(crash=True))
    job_id = finished_dependency_job(client)
    research = client.post(f"/api/dependencies/{job_id}/research").json()
    assert research["status"] == "error" and research["error"]["code"] == "INTERNAL_ERROR"
    assert "synthetic research bug" in research["error"]["message"]


def test_without_a_runner_research_explains_itself(setup, make_service):
    service, _ = make_service()
    service.dependency_pipeline = CachedPipeline()
    service._jobs = DependencyJobs(service.analyse, service.dependency_pipeline, runner=InlineExecutor(),
                                   workers=InlineExecutor())
    service._research = ResearchJobs(service._jobs, service.research_runner, executor=InlineExecutor())
    client = TestClient(create_app(lambda: service, Settings()))
    research = client.post(f"/api/dependencies/{finished_dependency_job(client)}/research").json()
    assert research["status"] == "error" and "not available" in research["error"]["message"]


def test_a_slow_run_is_202_then_polls_to_done(setup, monkeypatch):
    monkeypatch.setattr("hoc.jobs.SUBMIT_WAIT_SECONDS", 0.05)
    gate = threading.Event()
    client, service, _ = setup(FakeRunner(gate=gate), inline=False)
    job_id = finished_dependency_job(client)
    service._research = ResearchJobs(service._jobs, service.research_runner)  # threaded executor
    response = client.post(f"/api/dependencies/{job_id}/research")
    assert response.status_code == 202 and response.json()["status"] in ("queued", "running")
    gate.set()
    research_id = response.json()["research_id"]
    for _ in range(100):
        polled = client.get(f"/api/research/{research_id}").json()
        if polled["status"] == "done":
            break
        threading.Event().wait(0.02)
    assert polled["status"] == "done" and len(polled["findings"]) == 2


def test_real_research_loop_runner_with_fake_client_finishes_done_and_merges(setup):
    from hoc.ai.client import FakeGeminiClient
    from hoc.research import AgenticResearchRunner

    runner = AgenticResearchRunner(client=FakeGeminiClient())
    client, _, _ = setup(runner)
    job_id = finished_dependency_job(client)
    response = client.post(f"/api/dependencies/{job_id}/research", json={"max_items": 2})
    assert response.status_code == 200, response.text
    research = response.json()
    assert research["status"] == "done"
    assert research["dependency_job_id"] == job_id
    assert len(research["findings"]) >= 1
    assert research["findings"][0]["steps"][-1]["action"] == "conclude"
    assert research["result"] is not None
    assert len(research["result"]["edges"]) >= 1
