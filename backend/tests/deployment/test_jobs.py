"""Queue deliveries use fresh objects, with no network or provider keys."""

import json
import threading
import time
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from hoc.contract import (
    AnalysisResponse,
    CompanyExposure,
    CompanyUnavailable,
    Coverage,
    DependencyRequest,
    FilingRef,
    Insights,
    Overlap,
    PortfolioRequest,
    ResearchRequest,
    SourcesUnavailableError,
    VerifiedEdge,
)
from hoc.deployment.jobs import JobStore, QueuedDependencyJobs, QueuedResearchJobs
from hoc.deployment.runner import Worker
from hoc.deployment.storage import Stored
from hoc.graph.metrics import compute_dependency_metrics
from hoc.jobs import DependencyJobs, Extraction, InlineExecutor
from hoc.portfolio.concentration import concentration


class MemoryStore:
    def __init__(self):
        self.data, self.lock, self.version = {}, threading.Lock(), 0
        self.list_calls = 0

    def get(self, key):
        return self.data.get(key)

    def put(self, key, body, *, overwrite=True):
        with self.lock:
            if not overwrite and key in self.data:
                return False
            self.version += 1
            self.data[key] = Stored(body, str(self.version))
            return True

    def delete(self, key, *, etag):
        with self.lock:
            assert self.data[key].etag == etag
            del self.data[key]

    def keys(self, prefix):
        self.list_calls += 1
        return sorted(k for k in self.data if k.startswith(prefix))


class Publisher:
    def __init__(self):
        self.messages, self.seen, self.fail = [], set(), False

    def send(self, topic, payload, *, key):
        if self.fail:
            raise OSError("synthetic queue outage")
        if key not in self.seen:
            self.seen.add(key)
            self.messages.append((topic, payload))


class Pipeline:
    prompt_version = "synthetic-vercel-1"

    def __init__(self):
        self.calls = []
        self.unavailable = set()

    def filing(self, company):
        if company.company_key in self.unavailable:
            raise CompanyUnavailable("no_sec_filing", "Synthetic company has no filing")
        return FilingRef(
            company_key=company.company_key,
            form="10-K",
            accession="9990000001-26-000001",
            filed=date(2026, 10, 30),
            url="https://example.invalid/filing",
        )

    def extract(self, company, filing, *, cache_only):
        self.calls.append(company.company_key)
        edge = VerifiedEdge(
            edge_id="edge-" + company.company_key,
            source_company_key=company.company_key,
            source_company_name=company.company_name,
            source_in_portfolio=True,
            edge_type="supplier",
            target_kind="company",
            target_name="ZZ Supplier",
            evidence_quote="We buy inputs from ZZ Supplier.",
            section="Item 1",
            filing=filing,
        )
        return Extraction(edges=[edge], quality="sections", cached=True)

    def insights(self, analysis, edges, *, cache_only):
        return compute_dependency_metrics(analysis.exposures, edges), Insights(status="metrics_only")


@pytest.fixture
def rig():
    exposures = [
        CompanyExposure(
            rank=i,
            company_key=f"CIK:999000000{i}",
            company_name=f"ZZ Company {i}",
            identity_status="resolved",
            symbols=[f"ZZ{i}"],
            sector="industrials",
            exposure=weight,
            etf_count=1,
            contributions=[],
            securities=[],
        )
        for i, weight in [(1, 0.6), (2, 0.4)]
    ]
    request = PortfolioRequest(holdings=[{"ticker": "ZZFUND", "allocation": 1}])
    analysis = AnalysisResponse(
        generated_at=datetime(2026, 11, 8, tzinfo=UTC),
        as_of_date=date(2026, 11, 8),
        request=request,
        etfs=[],
        coverage=Coverage(
            total_allocation=1,
            loaded_allocation=1,
            missing_allocation=0,
            covered_weight=1,
            excluded_weight=0,
            unexplained_weight=0,
            unmatched_weight=0,
            sector_known_weight=1,
        ),
        exposures=exposures,
        sectors=[],
        overlap=Overlap(etfs=["ZZFUND"], matrix=[[1.0]], pairs=[]),
        concentration=concentration(exposures),
        exposures_truncated=False,
        other_exposure=0,
        gaps=[],
        warnings=[],
        attributions=[],
    )
    objects, publisher, pipeline = MemoryStore(), Publisher(), Pipeline()
    store = JobStore(objects, publisher)
    service = SimpleNamespace(dependency_pipeline=pipeline)
    deps = lambda: QueuedDependencyJobs(lambda _: analysis, pipeline, store)
    return SimpleNamespace(
        analysis=analysis,
        objects=objects,
        publisher=publisher,
        pipeline=pipeline,
        store=store,
        service=service,
        deps=deps,
        request=DependencyRequest(holdings=request.holdings, top_n=2),
    )


def drain(rig):
    while rig.publisher.messages:
        topic, payload = rig.publisher.messages.pop(0)
        # A new worker simulates a different function instance for every delivery.
        worker = Worker(rig.service, JobStore(rig.objects, rig.publisher))
        (worker.aggregate if topic == "hoc-progress" else worker.handle)(payload)


def test_fresh_instances_complete_and_match_existing_pipeline(rig):
    initial = rig.deps().submit(rig.request)
    assert initial.status == "queued" and rig.pipeline.calls == []
    drain(rig)
    completed = rig.deps().get(initial.job_id)
    inline = InlineExecutor()
    expected = DependencyJobs(
        lambda _: rig.analysis, Pipeline(), runner=inline, workers=inline, research_workers=inline
    ).submit(rig.request)
    assert completed.status == "done"
    assert completed.result.model_dump() == expected.result.model_dump()
    assert len(rig.pipeline.calls) == 2
    analysis, result = rig.deps().finished(initial.job_id)
    assert analysis == rig.analysis and result == completed.result


def test_duplicate_submit_and_delivery_do_not_repeat_extraction(rig):
    first = rig.deps().submit(rig.request)
    second = rig.deps().submit(rig.request)
    assert first.job_id == second.job_id and len(rig.publisher.messages) == 1
    drain(rig)
    pointer = rig.store.read("dependencies", first.job_id)
    Worker(rig.service, rig.store).handle({"run_id": pointer["run_id"], "task": "company", "index": 0})
    assert len(rig.pipeline.calls) == 2
    assert rig.deps().submit(rig.request).result is not None


def test_submit_interrupted_before_queue_send_is_repaired(rig):
    rig.publisher.fail = True
    with pytest.raises(SourcesUnavailableError):
        rig.deps().submit(rig.request)
    rig.publisher.fail = False
    job = rig.deps().submit(rig.request)
    drain(rig)
    assert rig.deps().get(job.job_id).status == "done"


def test_one_company_without_filing_remains_an_explicit_gap(rig):
    rig.pipeline.unavailable.add("CIK:9990000001")
    job = rig.deps().submit(rig.request)
    drain(rig)
    result = rig.deps().get(job.job_id).result
    assert result.counts.companies_skipped == 1
    assert result.companies[0].status == "no_sec_filing"
    assert sum(bucket.weight for bucket in result.coverage.buckets) == pytest.approx(1)


def test_expired_delivery_is_visible_error_and_retry_gets_new_generation(rig):
    job = rig.deps().submit(rig.request)
    path = rig.store.pointer("dependencies", job.job_id)
    record = json.loads(rig.objects.get(path).body)
    old_run = record["run_id"]
    record["created_at"] = time.time() - 3601
    rig.objects.put(path, json.dumps(record).encode())
    assert rig.deps().get(job.job_id).status == "error"
    retried = rig.deps().submit(rig.request)
    assert rig.store.read("dependencies", retried.job_id)["run_id"] != old_run
    drain(rig)
    assert rig.deps().get(job.job_id).status == "done"


def test_research_can_read_finished_dependencies_from_a_fresh_instance(rig):
    job = rig.deps().submit(rig.request)
    drain(rig)
    rig.service.research_runner = SimpleNamespace(
        prompt_version="synthetic-research", run=lambda result, analysis, **kwargs: ([], result)
    )
    research = QueuedResearchJobs(rig.deps(), rig.service.research_runner, rig.store)
    started = research.submit(job.job_id, ResearchRequest())
    drain(rig)
    assert research.get(started.research_id).status == "done"


def test_installed_sdk_can_discover_private_queue_subscribers():
    queue = pytest.importorskip("vercel.queue")

    import hoc.deployment.worker  # noqa: F401 - import performs SDK build-time validation

    subscriptions = {s.topic: s for s in queue.get_subscriptions()}
    assert subscriptions["hoc-work"].max_concurrency == 4
    assert subscriptions["hoc-progress"].max_concurrency == 1
