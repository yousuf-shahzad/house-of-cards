"""I-API v3: POST /api/compare wiring (two analyses -> cached extractions -> hoc.portfolio.compare), over the
SYNTHETIC ZZ fixtures. The cache read is replaced by a spy: the route must never fetch a filing or call Gemini."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from hoc.ai import PROMPT_VERSION
from hoc.api.app import create_app
from hoc.config import Settings
from hoc.contract import FilingRef, VerifiedEdge

BASELINE = [{"ticker": "ZZAAA", "allocation": 0.6}, {"ticker": "ZZBBB", "allocation": 0.4}]
CANDIDATE = [{"ticker": "ZZAAA", "allocation": 0.3}, {"ticker": "ZZBBB", "allocation": 0.4},
             {"ticker": "ZZCCC", "allocation": 0.3}]


def foundry_edge(company_key: str) -> VerifiedEdge:
    """A verified SYNTHETIC edge: <company> depends on the fictional foundry ZZ Epsilon."""
    return VerifiedEdge(
        edge_id=f"{company_key}->eps", source_company_key=company_key, source_company_name=company_key,
        source_in_portfolio=True, edge_type="foundry", target_name="ZZ Epsilon Foundry", target_kind="company",
        evidence_quote="SYNTHETIC: we rely on ZZ Epsilon Foundry for all wafers.", section="1",
        filing=FilingRef(company_key=company_key, form="10-K", accession="0000000000-26-000001",
                         filed=date(2026, 2, 1), url="https://example.invalid/10k"),
    )


class NoPipeline:
    """Any attribute access fails the test: compare must not touch filings, Gemini or dependency jobs."""

    def __getattr__(self, name):
        raise AssertionError(f"compare touched the dependency pipeline ({name})")


@pytest.fixture
def compared(make_service, monkeypatch):
    def make(cached: dict[str, list[VerifiedEdge]]):
        service, _ = make_service()
        service.dependency_pipeline = NoPipeline()
        calls: list[dict] = []

        def spy(cache_dir, company_keys, *, models, prompt_version):
            calls.append({"cache_dir": cache_dir, "keys": set(company_keys), "models": tuple(models),
                          "prompt_version": prompt_version})
            return {k: v for k, v in cached.items() if k in set(company_keys)}

        monkeypatch.setattr("hoc.service.read_cached_extractions", spy)
        return TestClient(create_app(lambda: service, Settings())), service, calls

    return make


def test_compare_reads_only_the_cache_for_both_top_n(compared):
    client, service, calls = compared({})
    response = client.post("/api/compare", json={"baseline": BASELINE, "candidate": CANDIDATE, "top_n": 3})
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    call = calls[0]
    assert call["cache_dir"] == service.settings.cache_dir
    assert call["prompt_version"] == PROMPT_VERSION
    assert call["models"][0] == service.settings.gemini_extractor_model
    before = client.post("/api/analysis", json={"holdings": BASELINE}).json()["exposures"][:3]
    after = client.post("/api/analysis", json={"holdings": CANDIDATE}).json()["exposures"][:3]
    assert call["keys"] == {c["company_key"] for c in before} | {c["company_key"] for c in after}


def test_nothing_cached_is_partial_with_concentration_and_unanalysed(compared):
    client, _, _ = compared({})
    body = client.post("/api/compare", json={"baseline": BASELINE, "candidate": CANDIDATE, "top_n": 3}).json()
    assert body["status"] == "partial"
    # No cached edges: no dependency, critical or facility exposure on either side (summary counts stay 0).
    assert not [d for d in body["dependency_deltas"] if d["metric_id"].startswith(("dep.", "critical.", "facility."))]
    assert all(d["delta"] in (0, None) for d in body["dependency_deltas"])
    assert [d["name"] for d in body["concentration_deltas"]] == [
        "top5", "top10", "top20", "effective_n", "largest_company", "top_sector"]
    assert len(body["candidate_unanalysed"]) == 3
    assert 0 < body["candidate_top_n_weight"] <= 1 and 0 < body["baseline_top_n_weight"] <= 1


def test_cached_edges_produce_dependency_deltas(compared):
    # SYM:ZZALP is the largest company on both sides; less ZZAAA means less dependent weight via it.
    client, _, _ = compared({"SYM:ZZALP": [foundry_edge("SYM:ZZALP")]})
    body = client.post("/api/compare", json={"baseline": BASELINE, "candidate": CANDIDATE, "top_n": 3}).json()
    deltas = {d["metric_id"]: d for d in body["dependency_deltas"]}
    dep = [d for metric_id, d in deltas.items() if metric_id.startswith("dep.")]
    assert dep, body["dependency_deltas"]
    assert dep[0]["baseline"] is not None and dep[0]["candidate"] is not None
    assert dep[0]["delta"] == pytest.approx(dep[0]["candidate"] - dep[0]["baseline"])
    assert dep[0]["delta"] < 0  # ZZALP's look-through weight falls from 0.34 to 0.25


def test_unknown_candidate_ticker_is_a_422(compared):
    client, _, calls = compared({})
    bad = [{"ticker": "ZZAAA", "allocation": 0.5}, {"ticker": "NOPEX", "allocation": 0.5}]
    response = client.post("/api/compare", json={"baseline": BASELINE, "candidate": bad})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNKNOWN_TICKER"
    assert calls == []


def test_invalid_allocations_are_a_422(compared):
    client, _, _ = compared({})
    response = client.post("/api/compare", json={"baseline": BASELINE,
                                                 "candidate": [{"ticker": "ZZAAA", "allocation": 0.5}]})
    assert response.status_code == 422
