"""v3 smoke checks against warmed production data, with no Gemini or network calls."""
from __future__ import annotations

import math
import socket
from dataclasses import replace

import pytest

from hoc.ai import GeminiClient
from hoc.contract import CompareRequest, DependencyRequest, PortfolioItem
from hoc.examples import EXAMPLES
from hoc.jobs import DependencyJobs, InlineExecutor
from hoc.service import EtfService

pytestmark = pytest.mark.live


@pytest.fixture
def cache_only_service(live_settings, monkeypatch):
    attempts = []

    def refuse_gemini(*args, **kwargs):
        attempts.append("Gemini")
        raise AssertionError("v3 smoke tests must never call Gemini")

    real_connect = socket.socket.connect
    real_create_connection = socket.create_connection

    def check_address(address):
        if isinstance(address, tuple) and str(address[0]).lower() not in {"127.0.0.1", "::1", "localhost"}:
            attempts.append("external socket")
            raise AssertionError("v3 smoke tests must use the existing cache without network access")

    def guarded_connect(sock, address):
        check_address(address)
        return real_connect(sock, address)

    def guarded_create_connection(address, *args, **kwargs):
        check_address(address)
        return real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(GeminiClient, "generate_json", refuse_gemini)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "HOC_GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    settings = replace(
        live_settings, offline=True, gemini_api_key=None,
        # The fetcher requires a nonempty contact even for disk reads. This
        # sentinel is only used offline; the socket guards prohibit sending it.
        sec_contact=live_settings.sec_contact or "cache-only@example.invalid",
    )
    assert settings.cache_dir.is_dir(), "Set HOC_LIVE_CACHE_DIR to a warmed production cache"
    yield EtfService.from_settings(settings)
    # Production steps can catch exceptions and return partial results. Catch
    # forbidden attempts even when the pipeline swallowed the guard's error.
    assert attempts == [], f"Forbidden calls during cache replay: {attempts}"


def _baseline():
    definition = next(example for example in EXAMPLES if example.id == "us-core-tilt")
    return [PortfolioItem(ticker=ticker, allocation=allocation) for ticker, allocation in definition.holdings]


def test_cached_compare_reduces_tsmc_exposure(cache_only_service, record_property):
    request = CompareRequest(
        baseline=_baseline(),
        candidate=[PortfolioItem(ticker=ticker, allocation=allocation) for ticker, allocation in (
            ("IVV", 0.40), ("QQQ", 0.10), ("VTV", 0.30), ("EEM", 0.20),
        )],
        top_n=15,
    )
    result = cache_only_service.compare(request)
    tsmc = next((metric for metric in result.dependency_deltas if metric.metric_id == "dep.ALIAS:TSMC"), None)
    assert tsmc is not None, "Warm the us-core-tilt extraction cache before running this smoke test"
    assert tsmc.unit == "fraction"
    assert tsmc.baseline is not None and tsmc.candidate is not None and tsmc.delta is not None
    assert 0 < tsmc.candidate < tsmc.baseline <= 1
    assert tsmc.delta == pytest.approx(tsmc.candidate - tsmc.baseline)
    assert tsmc.delta < 0
    record_property("tsmc_baseline", tsmc.baseline)
    record_property("tsmc_candidate", tsmc.candidate)
    record_property("tsmc_delta", tsmc.delta)


def test_cached_dependency_edges_and_coverage(cache_only_service, record_property):
    # Inline executors keep all real pipeline work inside the guard's lifetime
    # and leave no background workers running after fixture teardown.
    jobs = DependencyJobs(
        cache_only_service.analyse, cache_only_service.dependency_pipeline,
        runner=InlineExecutor(), workers=InlineExecutor(),
    )
    job = jobs.submit(DependencyRequest(holdings=_baseline(), top_n=15), cache_only=True)
    assert job.status == "done", job.error
    result = job.result
    assert result is not None
    assert job.progress_done == job.progress_total == 15
    unexpected = [(c.company_name, c.status, c.message) for c in result.companies
                  if c.status not in {"cached", "no_sec_filing", "unsupported_form"}]
    assert unexpected == [], f"Incomplete production cache or replay regression: {unexpected}"
    assert result.edges, "Warm the us-core-tilt dependency cache before running this smoke test"
    assert result.counts.verified_edges == len(result.edges)
    assert result.counts.interpretation_rejected >= 0
    for edge in result.edges:
        assert edge.importance is not None, edge.edge_id
        assert edge.interpretation is not None, edge.edge_id
        assert edge.interpretation.status in {"confirmed", "flagged"}, edge.edge_id
        if edge.interpretation.status == "flagged":
            assert edge.importance.tier in {"medium", "low"}, edge.edge_id
            assert edge.importance.score <= 0.55, edge.edge_id

    coverage = result.coverage
    assert coverage is not None
    buckets = {bucket.kind: bucket for bucket in coverage.buckets}
    assert len(buckets) == len(coverage.buckets) == 5
    assert set(buckets) == {"verified", "no_disclosures", "no_sec_filing", "not_analysed", "outside_top_n"}
    assert math.fsum(bucket.weight for bucket in coverage.buckets) == pytest.approx(1.0, abs=1e-6)
    assert buckets["verified"].weight > 0
    assert buckets["not_analysed"].weight == pytest.approx(0.0)
    record_property("verified_edges", len(result.edges))
    record_property("coverage_sum", math.fsum(bucket.weight for bucket in coverage.buckets))
