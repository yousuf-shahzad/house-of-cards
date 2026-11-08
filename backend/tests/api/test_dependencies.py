"""I-API: dependency jobs (hoc.jobs) and their routes, over SYNTHETIC fixtures and a fake pipeline."""

from __future__ import annotations

import threading
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from hoc.api.app import create_app
from hoc.config import Settings
from hoc.contract import (
    CompanyUnavailable,
    DependencyRequest,
    FilingRef,
    Insights,
    MetricFact,
    PortfolioRequest,
    VerifiedEdge,
)
from hoc.examples import ExampleDefinition
from hoc.jobs import DependencyJobs, Extraction, InlineExecutor

HOLDINGS = [{"ticker": "ZZAAA", "allocation": 0.5}, {"ticker": "ZZBBB", "allocation": 0.3},
            {"ticker": "ZZCCC", "allocation": 0.2}]


class FakePipeline:
    prompt_version = "test-v1"

    def __init__(self, *, unavailable=None, crash=(), cached=True, insights_crash=False, gate=None):
        self.unavailable = unavailable or {}
        self.crash = set(crash)
        self.cached = cached
        self.insights_crash = insights_crash
        self.gate = gate
        self.calls: list[tuple[str, bool]] = []

    def filing(self, company):
        if company.company_key in self.unavailable:
            raise CompanyUnavailable(self.unavailable[company.company_key], "synthetic reason")
        return FilingRef(company_key=company.company_key, form="10-K", accession=f"0000-{company.company_key}",
                         filed=date(2026, 2, 1), url="https://example.invalid/filing")

    def extract(self, company, filing, *, cache_only):
        self.calls.append((company.company_key, cache_only))
        if self.gate is not None:
            self.gate.wait(10)
        if company.company_key in self.crash:
            raise RuntimeError("extractor bug")
        if cache_only and not self.cached:
            raise CompanyUnavailable("missing_api_key", "not cached and no key used at warm-up")

        def edge(edge_id):
            return VerifiedEdge(edge_id=edge_id, source_company_key=company.company_key,
                                source_company_name=company.company_name, source_in_portfolio=True,
                                edge_type="supplier", target_name="ZZ Foundry", target_kind="company",
                                evidence_quote="We rely on ZZ Foundry for substantially all of our wafers.",
                                section="Item 1A", filing=filing)

        return Extraction(edges=[edge(f"e-{company.company_key}"), edge("e-shared")], rejected=1,
                          quality="sections", cached=self.cached)

    def insights(self, analysis, edges, *, cache_only):
        if self.insights_crash:
            raise RuntimeError("orchestrator bug")
        return [MetricFact(metric_id="m1", label="synthetic", value=0.1, unit="fraction")], \
            Insights(status="metrics_only")


@pytest.fixture
def setup(make_service):
    """setup(pipeline, inline=True) -> (TestClient, service, pipeline)."""

    def make(pipeline, *, inline=True):
        service, _ = make_service()
        service.dependency_pipeline = pipeline
        if inline:
            service._jobs = DependencyJobs(service.analyse, pipeline, runner=InlineExecutor(),
                                           workers=InlineExecutor())
        return TestClient(create_app(lambda: service, Settings())), service, pipeline

    return make


def post(client, holdings=HOLDINGS, top_n=3):
    return client.post("/api/dependencies", json={"holdings": holdings, "top_n": top_n})


def test_all_cached_run_is_200_done_with_counts(setup):
    client, _, _ = setup(FakePipeline())
    response = post(client)
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "done" and (job["progress_done"], job["progress_total"]) == (3, 3)
    assert {c["status"] for c in job["companies"]} == {"cached"}
    result = job["result"]
    assert len(result["edges"]) == 4  # three own edges + one shared edge, deduplicated by edge_id
    assert result["counts"] == {"companies_requested": 3, "companies_analysed": 3, "companies_skipped": 0,
                                "verified_edges": 4, "rejected_edges": 3, "unresolved_counterparties": 1}
    assert result["insights"]["status"] == "metrics_only" and result["metrics"][0]["metric_id"] == "m1"
    assert client.get(f"/api/dependencies/{job['job_id']}").json() == job  # POST and GET share one shape


def test_each_company_reports_its_own_status(setup, make_service):
    service, _ = make_service()
    keys = [c.company_key for c in service.analyse(PortfolioRequest(holdings=HOLDINGS)).exposures[:3]]
    client, _, _ = setup(FakePipeline(unavailable={keys[0]: "no_sec_filing"}, crash={keys[1]}))
    job = post(client).json()
    statuses = {c["company_key"]: (c["status"], c["message"]) for c in job["companies"]}
    assert statuses[keys[0]] == ("no_sec_filing", "synthetic reason")
    assert statuses[keys[1]][0] == "error" and "RuntimeError" in statuses[keys[1]][1]
    assert statuses[keys[2]][0] == "cached"
    assert job["status"] == "done" and job["result"]["counts"]["companies_skipped"] == 2


def test_same_click_twice_is_one_job_and_new_weights_a_new_one(setup):
    client, _, pipeline = setup(FakePipeline())
    first, second = post(client).json(), post(client).json()
    assert first["job_id"] == second["job_id"] and len(pipeline.calls) == 3  # no double spend
    other = post(client, [{"ticker": "ZZAAA", "allocation": 0.6}, {"ticker": "ZZBBB", "allocation": 0.4}]).json()
    assert other["job_id"] != first["job_id"]


def test_unknown_job_is_404(setup):
    client, _, _ = setup(FakePipeline())
    response = client.get("/api/dependencies/" + "0" * 64)
    assert response.status_code == 404 and response.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_slow_run_is_202_then_polls_to_done(setup, monkeypatch):
    monkeypatch.setattr("hoc.jobs.SUBMIT_WAIT_SECONDS", 0.05)
    monkeypatch.setattr("hoc.service.SUBMIT_WAIT_SECONDS", 0.05)
    gate = threading.Event()
    client, _, _ = setup(FakePipeline(cached=False, gate=gate), inline=False)
    response = post(client)
    assert response.status_code == 202 and response.json()["status"] in ("queued", "running")
    gate.set()
    deadline = time.monotonic() + 10
    while (job := client.get(f"/api/dependencies/{response.json()['job_id']}").json())["status"] != "done":
        assert time.monotonic() < deadline, job
        time.sleep(0.02)
    assert {c["status"] for c in job["companies"]} == {"done"}


def test_pipeline_crash_fails_the_job_not_the_server(setup):
    client, _, _ = setup(FakePipeline(insights_crash=True))
    response = post(client)
    assert response.status_code == 200
    assert response.json()["status"] == "error" and response.json()["error"]["code"] == "INTERNAL_ERROR"


def test_bad_portfolio_is_rejected_like_analysis(setup):
    client, _, pipeline = setup(FakePipeline())
    response = post(client, [{"ticker": "ZZNOPE", "allocation": 1}])
    assert response.status_code == 422 and response.json()["error"]["code"] == "UNKNOWN_TICKER"
    assert pipeline.calls == []


def test_not_wired_pipeline_reports_every_company(make_service):
    service, _ = make_service()
    job = TestClient(create_app(lambda: service, Settings())).post(
        "/api/dependencies", json={"holdings": HOLDINGS, "top_n": 2}).json()
    assert job["status"] == "done"
    assert all(c["status"] == "error" and "not wired" in c["message"] for c in job["companies"])


def test_warm_up_replays_from_cache_only_and_a_click_upgrades_it(make_service, monkeypatch):
    holdings = (("ZZAAA", 0.6), ("ZZBBB", 0.4))
    monkeypatch.setattr("hoc.service.EXAMPLES", (ExampleDefinition("zz", "ZZ", "synthetic", holdings),))
    service, _ = make_service()
    pipeline = FakePipeline(cached=False)
    service.dependency_pipeline = pipeline
    app = create_app(lambda: service, Settings(), warm=True)
    with TestClient(app) as client:
        app.state.warm_up_thread.join(timeout=20)
        assert pipeline.calls and all(cache_only for _, cache_only in pipeline.calls)  # never spends credit
        warm_calls = len(pipeline.calls)
        job = client.post("/api/dependencies", json={
            "holdings": [{"ticker": t, "allocation": a} for t, a in holdings],
            "top_n": Settings().deps_top_n}).json()
        while job["status"] not in ("done", "error"):
            time.sleep(0.02)
            job = client.get(f"/api/dependencies/{job['job_id']}").json()
    assert not any(cache_only for _, cache_only in pipeline.calls[warm_calls:])  # the click ran for real
    assert {c["status"] for c in job["companies"]} == {"done"}


class NamingPipeline(FakePipeline):
    """Emits one edge per counterparty spelling, and resolves names like G-DOC's deterministic resolver."""

    NAMES = ("ZZ Foundry", "ZZ Foundry Manufacturing Company Limited", "contract manufacturers")

    def __init__(self, foundry_key):
        super().__init__()
        self.foundry_key = foundry_key
        self.seen_portfolios = []

    def extract(self, company, filing, *, cache_only):
        edges = [VerifiedEdge(edge_id=f"{company.company_key}-{i}", source_company_key=company.company_key,
                              source_company_name=company.company_name, source_in_portfolio=False,
                              edge_type="foundry", target_name=name, target_kind="company",
                              evidence_quote=f"We rely on {name} for our wafers (synthetic).", section="1",
                              filing=filing)
                 for i, name in enumerate(self.NAMES)]
        # A material whose name exact-matches a holding must never be resolved to it (lead check on #96).
        edges.append(VerifiedEdge(edge_id=f"{company.company_key}-material", source_company_key=company.company_key,
                                  source_company_name=company.company_name, source_in_portfolio=False,
                                  edge_type="key_input", target_name="ZZ Foundry", target_kind="material",
                                  evidence_quote="We buy ZZ Foundry grade silicon (synthetic).", section="1",
                                  filing=filing))
        return Extraction(edges=edges, cached=True)

    def resolver_for(self, portfolio):
        self.seen_portfolios.append([c.company_key for c in portfolio])
        names = {"zz foundry": self.foundry_key, "zz foundry manufacturing company limited": self.foundry_key}
        return lambda name: names.get(name.casefold())


def test_name_variants_resolve_to_one_portfolio_key(setup, make_service):
    service, _ = make_service()
    foundry_key = service.analyse(PortfolioRequest(holdings=HOLDINGS)).exposures[2].company_key
    client, _, pipeline = setup(NamingPipeline(foundry_key))
    edges = post(client, top_n=1).json()["result"]["edges"]
    material = next(e for e in edges if e["target_kind"] == "material")
    assert material["target_key"] is None and material["target_in_portfolio"] is False
    by_name = {e["target_name"]: e for e in edges if e["target_kind"] == "company"}
    assert by_name["ZZ Foundry"]["target_key"] == by_name["ZZ Foundry Manufacturing Company Limited"]["target_key"] \
        == foundry_key
    assert by_name["ZZ Foundry"]["target_in_portfolio"] and by_name["ZZ Foundry"]["source_in_portfolio"]
    assert by_name["contract manufacturers"]["target_key"] is None  # generic noun: never guessed
    assert by_name["contract manufacturers"]["target_in_portfolio"] is False
    assert foundry_key in pipeline.seen_portfolios[0]  # the resolver saw this job's whole portfolio


class ReversePipeline(FakePipeline):
    """Forward as FakePipeline; reverse finds one other filer naming each company, or fails for `broken`."""

    def __init__(self, *, broken=(), **kwargs):
        super().__init__(**kwargs)
        self.broken = set(broken)
        self.reverse_calls: list[tuple[str, bool]] = []

    def reverse(self, company, *, cache_only):
        self.reverse_calls.append((company.company_key, cache_only))
        if company.company_key in self.broken:
            raise CompanyUnavailable("sec_contact_missing", "Set HOC_SEC_CONTACT")
        filing = FilingRef(company_key="CIK:9990000099", form="10-K", accession="9990000099-26-000001",
                           filed=date(2026, 3, 1), url="https://example.invalid/other")
        edge = VerifiedEdge(edge_id=f"rev-{company.company_key}", source_company_key="CIK:9990000099",
                            source_company_name="ZZ Other Filer", source_in_portfolio=False, edge_type="foundry",
                            target_name=company.company_name, target_kind="company",
                            target_key=company.company_key, target_in_portfolio=True,
                            evidence_quote=f"We rely on {company.company_name} (synthetic).", section="1",
                            filing=filing)
        return Extraction(edges=[edge], rejected=1)


def test_reverse_links_cover_companies_without_their_own_filing(setup, make_service):
    service, _ = make_service()
    keys = [c.company_key for c in service.analyse(PortfolioRequest(holdings=HOLDINGS)).exposures[:3]]
    client, _, pipeline = setup(ReversePipeline(unavailable={keys[0]: "no_sec_filing"}, broken={keys[2]}))
    job = post(client).json()
    companies = {c["company_key"]: c for c in job["companies"]}
    no_filing = companies[keys[0]]
    assert no_filing["status"] == "no_sec_filing" and no_filing["verified_edges"] == 1
    assert "1 link(s) found in other companies' filings" in no_filing["message"]
    assert companies[keys[1]]["status"] == "cached" and companies[keys[1]]["verified_edges"] == 3  # 2 forward + 1
    assert companies[keys[2]]["status"] == "cached"  # its reverse failed: forward status unchanged
    edge_ids = {e["edge_id"] for e in job["result"]["edges"]}
    assert {f"rev-{keys[0]}", f"rev-{keys[1]}"} <= edge_ids and f"rev-{keys[2]}" not in edge_ids
    reverse_edge = next(e for e in job["result"]["edges"] if e["edge_id"] == f"rev-{keys[0]}")
    assert reverse_edge["target_in_portfolio"] and not reverse_edge["source_in_portfolio"]
    assert sorted(k for k, _ in pipeline.reverse_calls) == sorted(keys)
    # rejected: keys[0] reverse 1 (no forward) + keys[1] forward 1 + reverse 1 + keys[2] forward 1 (reverse failed)
    assert job["result"]["counts"]["rejected_edges"] == 4


def test_reverse_runs_cache_only_at_warm_up(setup):
    _, service, pipeline = setup(ReversePipeline())
    service.submit_dependencies(DependencyRequest(holdings=HOLDINGS, top_n=2), cache_only=True)
    assert pipeline.reverse_calls and all(cache_only for _, cache_only in pipeline.reverse_calls)


def test_every_forward_step_runs_before_any_reverse_step(setup):
    order = []

    class Ordered(ReversePipeline):
        def extract(self, company, filing, *, cache_only):
            order.append("forward")
            return super().extract(company, filing, cache_only=cache_only)

        def reverse(self, company, *, cache_only):
            order.append("reverse")
            return super().reverse(company, cache_only=cache_only)

    client, _, _ = setup(Ordered())
    post(client)
    assert order == ["forward"] * 3 + ["reverse"] * 3


def test_reverse_is_skipped_once_the_time_budget_is_spent(setup, monkeypatch):
    monkeypatch.setattr("hoc.jobs.REVERSE_BUDGET_SECONDS", -1.0)
    client, _, pipeline = setup(ReversePipeline())
    job = post(client).json()
    assert pipeline.reverse_calls == []
    assert all(c["status"] == "cached" and c["verified_edges"] == 2 for c in job["companies"])  # forward intact
    assert all("time budget" in c["message"] for c in job["companies"])


def test_a_reverse_filer_that_is_a_holding_gets_its_portfolio_name(setup, make_service):
    service, _ = make_service()
    top = service.analyse(PortfolioRequest(holdings=HOLDINGS)).exposures[:2]

    class HoldingFiler(ReversePipeline):
        def reverse(self, company, *, cache_only):
            found = super().reverse(company, cache_only=cache_only)
            filer = top[1] if company.company_key == top[0].company_key else top[0]
            edge = found.edges[0].model_copy(update={"source_company_key": filer.company_key,
                                                     "source_company_name": "ZZ SEC TITLE INC"})
            return Extraction(edges=[edge])

    client, _, _ = setup(HoldingFiler())
    edges = post(client, top_n=2).json()["result"]["edges"]
    reverse_edges = [e for e in edges if e["edge_id"].startswith("rev-")]
    assert reverse_edges and all(e["source_company_name"] != "ZZ SEC TITLE INC" for e in reverse_edges)
    assert {e["source_company_name"] for e in reverse_edges} == {c.company_name for c in top}


class InsightsRecorder(FakePipeline):
    """Records the cache_only flag of every insights call; insights stay metrics_only like a cache-only miss."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.insights_calls: list[bool] = []

    def insights(self, analysis, edges, *, cache_only):
        self.insights_calls.append(cache_only)
        return super().insights(analysis, edges, cache_only=cache_only)


def test_a_click_upgrades_an_all_cached_warm_up_with_metrics_only_insights(setup):
    _, service, pipeline = setup(InsightsRecorder())
    request = DependencyRequest(holdings=HOLDINGS, top_n=2)
    warm = service.submit_dependencies(request, cache_only=True)
    assert {c.status for c in warm.companies} == {"cached"} and warm.result.insights.status == "metrics_only"
    clicked = service.submit_dependencies(request)
    assert clicked.job_id == warm.job_id
    assert pipeline.insights_calls == [True, False]  # the click re-ran the orchestrator live


def test_a_click_joining_a_running_warm_up_finishes_it_live(setup, monkeypatch):
    monkeypatch.setattr("hoc.jobs.SUBMIT_WAIT_SECONDS", 0.0)
    gate = threading.Event()
    _, service, pipeline = setup(InsightsRecorder(gate=gate), inline=False)
    request = DependencyRequest(holdings=HOLDINGS, top_n=2)
    warm = service.submit_dependencies(request, cache_only=True, wait=0)
    clicked = service.submit_dependencies(request, wait=0)
    assert clicked.job_id == warm.job_id and clicked.status in ("queued", "running")
    gate.set()
    deadline = time.monotonic() + 10
    while service.dependency_job(warm.job_id).status != "done":
        assert time.monotonic() < deadline
        time.sleep(0.02)
    assert pipeline.insights_calls == [False]  # one job, finished with the live orchestrator
