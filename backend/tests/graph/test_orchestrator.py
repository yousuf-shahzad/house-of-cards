"""Tests for the G-ORCH dependency orchestrator & claim verifier (backend/hoc/graph/orchestrator.py)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from hoc.ai.client import FakeGeminiClient
from hoc.config import Settings
from hoc.contract.api import (
    AnalysisResponse,
    CompanyExposure,
    Concentration,
    Contribution,
    Coverage,
    EtfReport,
    Overlap,
    PortfolioItem,
    PortfolioRequest,
    SecurityExposure,
)
from hoc.contract.dependencies import FilingRef, VerifiedEdge
from hoc.contract.units import Sector
from hoc.graph import (
    DependencyOrchestrator,
    compute_dependency_summary,
    compute_orchestrator_cache_key,
    insights,
    prompt_version,
)


def _sample_analysis() -> AnalysisResponse:
    exposures = [
        CompanyExposure(
            rank=1,
            company_key="CIK:9990000001",
            company_name="ZZ Alpha Corp",
            identity_status="resolved",
            symbols=["ZZALP"],
            sector=Sector.information_technology,
            country="US",
            exposure=0.34,
            etf_count=2,
            contributions=[
                Contribution(
                    etf_ticker="ZZAAA",
                    weight_in_etf=0.40,
                    contribution=0.24,
                    security_keys=["SEC:ZZALP"],
                ),
                Contribution(
                    etf_ticker="ZZBBB",
                    weight_in_etf=0.25,
                    contribution=0.10,
                    security_keys=["SEC:ZZALP"],
                ),
            ],
            securities=[
                SecurityExposure(
                    security_key="SEC:ZZALP",
                    security_id="ZZALP",
                    security_id_type="symbol",
                    symbol="ZZALP",
                    name="ZZ Alpha Corp",
                    exposure=0.34,
                )
            ],
        ),
        CompanyExposure(
            rank=2,
            company_key="CIK:9990000002",
            company_name="ZZ Beta Holdings",
            identity_status="resolved",
            symbols=["ZZBET"],
            sector=Sector.information_technology,
            country="US",
            exposure=0.24,
            etf_count=2,
            contributions=[
                Contribution(
                    etf_ticker="ZZAAA",
                    weight_in_etf=0.2333,
                    contribution=0.14,
                    security_keys=["SEC:ZZBET"],
                ),
                Contribution(
                    etf_ticker="ZZBBB",
                    weight_in_etf=0.25,
                    contribution=0.10,
                    security_keys=["SEC:ZZBET"],
                ),
            ],
            securities=[
                SecurityExposure(
                    security_key="SEC:ZZBET",
                    security_id="ZZBET",
                    security_id_type="symbol",
                    symbol="ZZBET",
                    name="ZZ Beta Holdings",
                    exposure=0.24,
                )
            ],
        ),
        CompanyExposure(
            rank=3,
            company_key="ALIAS:ZZEPSILON",
            company_name="ZZ Epsilon Semiconductor",
            identity_status="resolved",
            symbols=["ZZEPS"],
            sector=Sector.information_technology,
            country="TW",
            exposure=0.088,
            etf_count=1,
            contributions=[
                Contribution(
                    etf_ticker="ZZBBB",
                    weight_in_etf=0.22,
                    contribution=0.088,
                    security_keys=["SEC:ZZEPS"],
                )
            ],
            securities=[
                SecurityExposure(
                    security_key="SEC:ZZEPS",
                    security_id="ZZEPS",
                    security_id_type="symbol",
                    symbol="ZZEPS",
                    name="ZZ Epsilon Semiconductor",
                    exposure=0.088,
                )
            ],
        ),
    ]
    req = PortfolioRequest(
        holdings=[
            PortfolioItem(ticker="ZZAAA", allocation=0.60),
            PortfolioItem(ticker="ZZBBB", allocation=0.40),
        ]
    )
    return AnalysisResponse(
        generated_at=datetime(2026, 11, 8, 0, 0, tzinfo=UTC),
        as_of_date=date(2026, 11, 8),
        request=req,
        etfs=[
            EtfReport(ticker="ZZAAA", name="Synthetic Core ETF", allocation=0.60, status="ok"),
            EtfReport(ticker="ZZBBB", name="Synthetic Tech ETF", allocation=0.40, status="ok"),
        ],
        coverage=Coverage(
            total_allocation=1.0,
            loaded_allocation=1.0,
            missing_allocation=0.0,
            covered_weight=0.668,
            excluded_weight=0.0,
            unexplained_weight=0.332,
            unmatched_weight=0.0,
            sector_known_weight=0.668,
        ),
        exposures=exposures,
        exposures_truncated=False,
        other_exposure=0.0,
        overlap=Overlap(etfs=["ZZAAA", "ZZBBB"], matrix=[[0.6, 0.2], [0.2, 0.4]], pairs=[]),
        concentration=Concentration(
            top5=0.668,
            top10=0.668,
            top20=0.668,
            hhi=0.18,
            effective_companies=5.5,
            distinct_securities=3,
            distinct_companies=3,
        ),
        sectors=[],
        gaps=[],
        warnings=[],
        attributions=[],
    )


def _sample_edges() -> list[VerifiedEdge]:
    f1 = FilingRef(
        company_key="CIK:9990000001",
        form="10-K",
        accession="9990000001-26-000001",
        filed=date(2026, 10, 30),
        url="https://example.invalid/synthetic/zzalp-10k",
    )
    f2 = FilingRef(
        company_key="CIK:9990000002",
        form="10-K",
        accession="9990000002-26-000001",
        filed=date(2026, 2, 20),
        url="https://example.invalid/synthetic/zzbet-10k",
    )
    return [
        VerifiedEdge(
            edge_id="e-alp-foundry-eps",
            source_company_key="CIK:9990000001",
            source_company_name="ZZ Alpha Corp",
            source_in_portfolio=True,
            edge_type="foundry",
            target_name="ZZ Epsilon Semiconductor",
            target_kind="company",
            target_key="ALIAS:ZZEPSILON",
            target_in_portfolio=True,
            sole_source=True,
            evidence_quote="We rely on ZZ Epsilon Semiconductor as the sole foundry for our processors.",
            section="Item 1A",
            filing=f1,
        ),
        VerifiedEdge(
            edge_id="e-alp-facility-tw",
            source_company_key="CIK:9990000001",
            source_company_name="ZZ Alpha Corp",
            source_in_portfolio=True,
            edge_type="facility",
            target_name="Taiwan",
            target_kind="country",
            target_key=None,
            target_in_portfolio=False,
            sole_source=False,
            evidence_quote="Substantially all of our final assembly is performed by partners located in Taiwan.",
            section="Item 1",
            filing=f1,
        ),
        VerifiedEdge(
            edge_id="e-bet-foundry-eps",
            source_company_key="CIK:9990000002",
            source_company_name="ZZ Beta Holdings",
            source_in_portfolio=True,
            edge_type="foundry",
            target_name="ZZ Epsilon Semiconductor",
            target_kind="company",
            target_key="ALIAS:ZZEPSILON",
            target_in_portfolio=True,
            sole_source=False,
            evidence_quote="ZZ Epsilon Semiconductor manufactures our custom chips.",
            section="Item 1",
            filing=f2,
        ),
    ]


def test_placeholder_interpolation_and_rejection_of_invented_numbers_and_unknown_names(
    tmp_path: Path,
) -> None:
    """Valid {{metric:<id>}} claims expand cleanly; invented numbers, bad IDs, and outside tickers are dropped."""
    analysis = _sample_analysis()
    edges = _sample_edges()

    def fake_llm(**_: Any) -> dict[str, Any]:
        return {
            "flaws": [
                # 1. Valid flaw using {{metric:<id>}} placeholders and whitelisted 10-K/Item 1A
                {
                    "title": "Shared foundry bottleneck on ZZ Epsilon Semiconductor",
                    "text": (
                        "{{metric:dep.ALIAS:ZZEPSILON}} of your portfolio across "
                        "{{metric:dep.ALIAS:ZZEPSILON.companies}} holdings (ZZ Alpha Corp, ZZ Beta Holdings) "
                        "relies on ZZ Epsilon Semiconductor per 10-K Item 1A disclosures."
                    ),
                    "severity": "critical",
                    "cited_metric_ids": ["dep.ALIAS:ZZEPSILON", "dep.ALIAS:ZZEPSILON.companies"],
                    "cited_edge_ids": ["e-alp-foundry-eps", "e-bet-foundry-eps"],
                    "entities": ["ZZ Epsilon Semiconductor", "ZZ Alpha Corp", "ZZ Beta Holdings"],
                },
                # 2. INVALID: contains an invented literal percentage ("42.5%") not from {{metric:<id>}}
                {
                    "title": "Invented number claim",
                    "text": "42.5% of your portfolio depends on ZZ Epsilon Semiconductor.",
                    "severity": "critical",
                    "cited_metric_ids": ["dep.ALIAS:ZZEPSILON"],
                    "cited_edge_ids": ["e-alp-foundry-eps"],
                },
                # 3. INVALID: cites an unknown metric_id
                {
                    "title": "Unknown metric claim",
                    "text": "{{metric:dep.DOES_NOT_EXIST}} of your portfolio is at risk.",
                    "severity": "warning",
                    "cited_metric_ids": ["dep.DOES_NOT_EXIST"],
                    "cited_edge_ids": ["e-alp-foundry-eps"],
                },
                # 4. INVALID: cites an unknown edge_id
                {
                    "title": "Unknown edge claim",
                    "text": "{{metric:dep.ALIAS:ZZEPSILON}} depends on ZZ Epsilon Semiconductor.",
                    "severity": "warning",
                    "cited_metric_ids": ["dep.ALIAS:ZZEPSILON"],
                    "cited_edge_ids": ["e-nonexistent-edge"],
                },
            ],
            "suggestions": [
                # 1. Valid suggestion using {{metric:facility.TW}}
                {
                    "title": "Assembly concentrated in Taiwan",
                    "text": (
                        "{{metric:facility.TW}} of your portfolio relies on final assembly in Taiwan; "
                        "consider holdings with manufacturing diversified across other regions."
                    ),
                    "severity": "warning",
                    "cited_metric_ids": ["facility.TW"],
                    "cited_edge_ids": ["e-alp-facility-tw"],
                    "entities": ["Taiwan", "ZZ Alpha Corp"],
                },
                # 2. INVALID: mentions an outside ticker (INTC) not in portfolio or verified edges
                {
                    "title": "Outside ticker suggestion",
                    "text": (
                        "With {{metric:facility.TW}} in Taiwan, shift exposure toward INTC foundries."
                    ),
                    "severity": "info",
                    "cited_metric_ids": ["facility.TW"],
                    "cited_edge_ids": ["e-alp-facility-tw"],
                },
            ],
        }

    orch = DependencyOrchestrator(ai_client=fake_llm, cache_dir=tmp_path)
    metrics, result = orch.insights(analysis, edges)

    assert len(metrics) > 0
    assert result.status == "ok"
    assert result.rejected_claims_count == 4  # 3 invalid flaws + 1 invalid suggestion
    assert len(result.flaws) == 1
    assert len(result.suggestions) == 1

    flaw = result.flaws[0]
    assert flaw.kind == "flaw"
    assert flaw.severity == "critical"
    assert "58.00%" in flaw.text
    assert "2 holdings" in flaw.text
    assert "{{metric:" not in flaw.text
    assert flaw.cited_metric_ids == ["dep.ALIAS:ZZEPSILON", "dep.ALIAS:ZZEPSILON.companies"]
    assert flaw.cited_edge_ids == ["e-alp-foundry-eps", "e-bet-foundry-eps"]

    sugg = result.suggestions[0]
    assert sugg.kind == "suggestion"
    assert "34.00% of your portfolio relies on final assembly in Taiwan" in sugg.text

    # Second run with no AI client and cache_only=True should replay from disk cache with status="ok"
    orch_cached = DependencyOrchestrator(ai_client=None, cache_dir=tmp_path)
    _, cached_result = orch_cached.insights(analysis, edges, cache_only=True)
    assert cached_result.status == "ok"
    assert len(cached_result.flaws) == 1
    assert cached_result.flaws[0].text == flaw.text


def test_missing_api_key_and_empty_edges_fallbacks(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """When GEMINI_API_KEY is missing or edges are empty, insights() never raises and returns enum statuses."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    analysis = _sample_analysis()
    edges = _sample_edges()
    settings = Settings(cache_dir=tmp_path, gemini_api_key=None)

    # 1. Empty edges -> status="no_verified_edges"
    empty_metrics, empty_insights = insights(analysis, [], settings=settings)
    assert empty_insights.status == "no_verified_edges"
    assert empty_insights.flaws == []
    assert empty_insights.suggestions == []
    assert any(m.metric_id == "summary.verified_edges" and m.value == 0.0 for m in empty_metrics)

    # 2. Missing key (uncached) -> status="missing_api_key", populated with deterministic metric claims
    _, no_key_insights = insights(analysis, edges, settings=settings)
    assert no_key_insights.status == "missing_api_key"
    assert no_key_insights.rejected_claims_count == 0
    assert len(no_key_insights.flaws) >= 1
    assert len(no_key_insights.suggestions) >= 1
    assert "58.00%" in no_key_insights.flaws[0].text

    # 3. cache_only=True (uncached) -> status="metrics_only"
    _, cache_only_insights = insights(analysis, edges, cache_only=True, settings=settings)
    assert cache_only_insights.status == "metrics_only"
    assert len(cache_only_insights.flaws) >= 1


def test_429_rate_limit_falls_back_from_argon_to_flash(tmp_path: Path) -> None:
    """On HTTP 429 from gemini-4-argon, DependencyOrchestrator retries with gemini-3.8-flash."""
    analysis = _sample_analysis()
    edges = _sample_edges()
    called_models: list[str] = []

    def rate_limited_client(*, model: str, **_: Any) -> dict[str, Any]:
        called_models.append(model)
        if model == "gemini-4-argon":
            raise RuntimeError("HTTP 429 Too Many Requests: quota exhausted")
        return {
            "flaws": [
                {
                    "title": "One foundry behind two holdings",
                    "text": "{{metric:dep.ALIAS:ZZEPSILON}} of your portfolio depends on ZZ Epsilon Semiconductor.",
                    "severity": "critical",
                    "cited_metric_ids": ["dep.ALIAS:ZZEPSILON"],
                    "cited_edge_ids": ["e-alp-foundry-eps", "e-bet-foundry-eps"],
                }
            ],
            "suggestions": [],
        }

    orch = DependencyOrchestrator(ai_client=rate_limited_client, cache_dir=tmp_path)
    _, res = orch.insights(analysis, edges)
    assert called_models == ["gemini-4-argon", "gemini-3.8-flash"]
    assert res.status == "ok"
    assert res.model == "gemini-3.8-flash"
    assert len(res.flaws) == 1
    assert "58.00%" in res.flaws[0].text


def test_cache_key_changes_when_allocations_or_edges_change() -> None:
    analysis = _sample_analysis()
    edges = _sample_edges()
    k1 = compute_orchestrator_cache_key(
        analysis.exposures, edges, holdings=analysis.request.holdings
    )
    k2 = compute_orchestrator_cache_key(
        analysis.exposures,
        edges[:2],
        holdings=analysis.request.holdings,
    )
    k3 = compute_orchestrator_cache_key(
        analysis.exposures,
        edges,
        holdings=[
            PortfolioItem(ticker="ZZAAA", allocation=0.50),
            PortfolioItem(ticker="ZZBBB", allocation=0.50),
        ],
    )
    assert k1 != k2
    assert k1 != k3
    assert prompt_version == "hoc-orch-v2.1"
    assert compute_dependency_summary(analysis.exposures, edges).verified_edges_count == 3


def test_fake_gemini_client_default_orchestrator_response_integration(
    tmp_path: Path,
) -> None:
    """FakeGeminiClient._default_orchestrator_response() works seamlessly with DependencyOrchestrator."""
    analysis = _sample_analysis()
    edges = _sample_edges()
    orch = DependencyOrchestrator(ai_client=FakeGeminiClient(), cache_dir=tmp_path)
    _, res = orch.insights(analysis, edges)
    assert res.status == "ok"
    assert len(res.flaws) == 1
    assert len(res.suggestions) == 1
    assert res.rejected_claims_count == 1  # Rejects the 99.99% lunar mining hallucination
    assert "58.00%" in res.flaws[0].text
    assert res.flaws[0].cited_metric_ids == ["dep.ALIAS:ZZEPSILON"]
    assert res.flaws[0].cited_edge_ids == ["e-alp-foundry-eps"]



def test_cache_key_changes_when_target_resolution_changes_but_edge_ids_do_not(tmp_path: Path) -> None:
    """Resolving target_key keeps every edge id but changes the metrics the model sees, so it must miss the cache.

    Live regression (us-core-tilt): a reply cached before name resolution cited dep.NAME:* metrics that no
    longer existed afterwards, and replaying it silently dropped the most important claims.
    """
    analysis = _sample_analysis()
    unresolved = [e.model_copy(update={"target_key": None, "target_in_portfolio": False}) for e in _sample_edges()]
    resolved = _sample_edges()
    assert [e.edge_id for e in unresolved] == [e.edge_id for e in resolved]

    calls: list[str] = []

    def counting_client(*, model: str, **_: Any) -> dict[str, Any]:
        calls.append(model)
        # One claim that verifies with or without resolution (only replies with a verified claim are cached).
        return {"flaws": [], "suggestions": [{
            "title": "Assembly concentrated in Taiwan",
            "text": "{{metric:facility.TW}} of your portfolio relies on final assembly in Taiwan.",
            "severity": "warning",
            "cited_metric_ids": ["facility.TW"],
            "cited_edge_ids": ["e-alp-facility-tw"],
            "entities": ["Taiwan", "ZZ Alpha Corp"],
        }]}

    orch = DependencyOrchestrator(ai_client=counting_client, cache_dir=tmp_path)
    orch.insights(analysis, unresolved)
    orch.insights(analysis, unresolved)  # identical input: replayed from the disk cache
    assert len(calls) == 1
    orch.insights(analysis, resolved)  # same edge ids, new target_key and metrics: must call the model
    assert len(calls) == 2

    # Identical input still replays cache-only, with no client at all (the warm-up path).
    _, replay = DependencyOrchestrator(ai_client=None, cache_dir=tmp_path).insights(analysis, resolved, cache_only=True)
    assert replay.status == "ok"

    # A different orchestrator model is a different reply.
    other = DependencyOrchestrator(ai_client=counting_client, cache_dir=tmp_path, orchestrator_model="gemini-3.8-flash")
    other.insights(analysis, resolved)
    assert len(calls) == 3
