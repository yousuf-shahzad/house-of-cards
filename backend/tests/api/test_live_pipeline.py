"""I-API: LivePipeline wiring G-DOC -> G-AI -> G-ORCH through the job runner, end to end and offline.

Real extractor, quote verifier, extraction cache and orchestrator; only Gemini (FakeGeminiClient) and the SEC
fetch (a SYNTHETIC filing) are faked. No network, no key.
"""

from __future__ import annotations

import hashlib
from datetime import date

from fastapi.testclient import TestClient

from hoc.ai import DependencyExtractor, ExtractionCache
from hoc.ai.client import FakeGeminiClient
from hoc.api.app import create_app
from hoc.config import Settings
from hoc.contract import PortfolioRequest
from hoc.core.cache import DiskCache
from hoc.filings.fetch import Filing, FilingUnavailable
from hoc.filings.text import normalise
from hoc.graph import DependencyOrchestrator
from hoc.jobs import DependencyJobs, InlineExecutor, LivePipeline

TEXT = normalise(
    "Item 1. Business. We design SYNTHETIC test processors. We rely on ZZ Foundry Co. as our sole wafer "
    "foundry for all leading-edge nodes, and we purchase memory from ZZ Memory Inc. "
    "One direct customer accounted for 22% of total revenue. "
    "Item 2. Properties. Our principal assembly and test operations are located in Taiwan and Arizona."
)
HOLDINGS = [{"ticker": "ZZAAA", "allocation": 0.5}, {"ticker": "ZZBBB", "allocation": 0.3},
            {"ticker": "ZZCCC", "allocation": 0.2}]


class FakeFetcher:
    def __init__(self, no_filing=()):
        self.no_filing = set(no_filing)
        self.calls = []

    def for_company(self, company):
        self.calls.append(company.company_key)
        if company.company_key in self.no_filing:
            raise FilingUnavailable("no_sec_filing", "files no SEC 10-K or 20-F (synthetic)")
        number = int(hashlib.sha256(company.company_key.encode()).hexdigest(), 16) % 10**6
        split = TEXT.find("Item 2.")
        return Filing(cik=f"999{number:07d}", form="10-K", accession=f"9990000-26-{number:06d}",
                      filed=date(2026, 2, 1), url=f"https://example.invalid/{number}.htm", text=TEXT,
                      sha256=hashlib.sha256(TEXT.encode()).hexdigest(),
                      sections={"1": (0, split), "2": (split, len(TEXT))}, quality="sections")


def build(service, tmp_path, *, has_key=True, no_filing=()):
    extractor = DependencyExtractor(FakeGeminiClient(include_mutated_quotes=True, has_api_key=has_key),
                                    ExtractionCache(DiskCache(tmp_path / "cache")))
    pipeline = LivePipeline(FakeFetcher(no_filing), extractor,
                            DependencyOrchestrator(ai_client=FakeGeminiClient(has_api_key=has_key),
                                                   cache_dir=tmp_path / "cache"))
    service.dependency_pipeline = pipeline
    service._jobs = DependencyJobs(service.analyse, pipeline, runner=InlineExecutor(), workers=InlineExecutor())
    return TestClient(create_app(lambda: service, Settings())), pipeline


def test_live_pipeline_end_to_end_offline(make_service, tmp_path):
    service, _ = make_service()
    top = service.analyse(PortfolioRequest(holdings=HOLDINGS)).exposures
    skipped = top[1].company_key
    client, _ = build(service, tmp_path, no_filing={skipped})
    job = client.post("/api/dependencies", json={"holdings": HOLDINGS, "top_n": 3}).json()
    assert job["status"] == "done", job
    statuses = {c["company_key"]: c for c in job["companies"]}
    assert statuses[skipped]["status"] == "no_sec_filing"
    analysed = [c for c in job["companies"] if c["status"] in ("done", "cached")]
    assert len(analysed) == 2
    assert all(c["filing"]["form"] == "10-K" and c["rejected_edges"] > 0 for c in analysed)  # mutated quotes dropped
    edges = job["result"]["edges"]
    assert edges and all(normalise(e["evidence_quote"]) in TEXT for e in edges)  # only verified quotes survive
    assert all(e["source_in_portfolio"] for e in edges)
    assert job["result"]["insights"]["status"] in ("ok", "metrics_only")
    assert job["result"]["counts"]["companies_skipped"] == 1


def test_cached_extractions_replay_without_a_key(make_service, tmp_path):
    service, _ = make_service()
    client, _ = build(service, tmp_path)
    first = client.post("/api/dependencies", json={"holdings": HOLDINGS, "top_n": 2}).json()
    assert {c["status"] for c in first["companies"]} == {"done"}
    replay_service, _ = make_service()
    replay, _ = build(replay_service, tmp_path, has_key=False)  # same disk cache, no Gemini key
    job = replay.post("/api/dependencies", json={"holdings": HOLDINGS, "top_n": 2}).json()
    assert {c["status"] for c in job["companies"]} == {"cached"}
    assert len(job["result"]["edges"]) == len(first["result"]["edges"])


def test_no_key_and_nothing_cached_is_a_status_not_a_500(make_service, tmp_path):
    service, _ = make_service()
    client, _ = build(service, tmp_path, has_key=False)
    response = client.post("/api/dependencies", json={"holdings": HOLDINGS, "top_n": 2})
    assert response.status_code == 200
    job = response.json()
    assert {c["status"] for c in job["companies"]} == {"missing_api_key"}
    assert job["result"]["insights"]["status"] in ("no_verified_edges", "missing_api_key")


def test_live_pipeline_resolves_names_against_the_job_portfolio(make_service, tmp_path):
    service, _ = make_service()
    portfolio = service.analyse(PortfolioRequest(holdings=HOLDINGS)).exposures
    _, pipeline = build(service, tmp_path)
    resolve = pipeline.resolver_for(portfolio)
    first = portfolio[0]
    assert resolve(first.company_name) == first.company_key
    assert resolve("contract manufacturers") is None
