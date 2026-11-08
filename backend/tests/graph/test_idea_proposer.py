"""Unit tests for FIX-17 AI change-idea proposer and deterministic rationale verifier."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from hoc.config import DEFAULT_ORCHESTRATOR_MODEL, Settings
from hoc.contract.api import (
    AnalysisResponse,
    CompanyExposure,
    Concentration,
    Coverage,
    Overlap,
    PortfolioItem,
    PortfolioRequest,
    SectorExposure,
)
from hoc.contract.dependencies import MetricFact
from hoc.contract.holdings import EtfHoldings, NormalisedHolding
from hoc.contract.units import Sector
from hoc.graph.idea_proposer import (
    DEFAULT_PROPOSER_MODEL,
    IDEA_PROPOSER_PROMPT_VERSION,
    PINNED_ETF_UNIVERSE,
    EtfUniverseEntry,
    IdeaProposer,
    PortfolioIssue,
    build_portfolio_issues,
    compute_idea_proposer_cache_key,
    enrich_universe_from_loaded,
    propose_change_ideas,
    verify_and_render_proposal_rationale,
    verify_raw_proposals,
)


def _sample_holdings() -> list[PortfolioItem]:
    return [
        PortfolioItem(ticker="IVV", allocation=0.40),
        PortfolioItem(ticker="QQQ", allocation=0.25),
        PortfolioItem(ticker="XLK", allocation=0.15),
        PortfolioItem(ticker="EEM", allocation=0.20),
    ]


def _sample_analysis() -> AnalysisResponse:
    return AnalysisResponse(
        generated_at=datetime(2026, 11, 8, 6, 0, tzinfo=UTC),
        as_of_date=date(2026, 11, 8),
        request=PortfolioRequest(holdings=_sample_holdings()),
        etfs=[],
        coverage=Coverage(
            total_allocation=1.0,
            loaded_allocation=1.0,
            covered_weight=0.999,
            excluded_weight=0.001,
            missing_allocation=0.0,
            unexplained_weight=0.0,
            unmatched_weight=0.0,
            sector_known_weight=0.80,
        ),
        concentration=Concentration(
            top5=0.26,
            top10=0.3714,
            top20=0.48,
            hhi=0.0201,
            effective_companies=49.8,
            distinct_securities=200,
            distinct_companies=190,
        ),
        exposures=[
            CompanyExposure(
                rank=1,
                company_key="CIK:0000320193",
                company_name="Apple Inc.",
                identity_status="resolved",
                symbols=["AAPL"],
                sector=Sector.information_technology,
                exposure=0.0737,
                etf_count=3,
                contributions=[],
                securities=[],
            )
        ],
        exposures_truncated=False,
        other_exposure=0.0,
        sectors=[
            SectorExposure(sector=Sector.information_technology, weight=0.5064, by_etf=[]),
            SectorExposure(sector=Sector.financials, weight=0.1240, by_etf=[]),
        ],
        overlap=Overlap(etfs=["IVV", "QQQ", "XLK", "EEM"], matrix=[[1.0] * 4 for _ in range(4)], pairs=[]),
        gaps=[],
        warnings=[],
        attributions=[],
    )


def _sample_dep_metrics() -> list[MetricFact]:
    return [
        MetricFact(
            metric_id="dep.ALIAS:TSMC",
            label="Portfolio exposure dependent on Taiwan Semiconductor Manufacturing Co., Ltd.",
            value=0.1239,
            unit="fraction",
            supporting_edge_ids=["e1"],
        ),
        MetricFact(
            metric_id="dep.ALIAS:SAMSUNG_ELEC",
            label="Portfolio exposure dependent on Samsung Electronics Co., Ltd.",
            value=0.0942,
            unit="fraction",
            supporting_edge_ids=["e2"],
        ),
    ]


def test_build_portfolio_issues_prioritises_top_sector_at_40pct_without_95pct_gate() -> None:
    """build_portfolio_issues uses the same >=40% rule as diversificationVerdict even when sector_known_weight < 95%."""
    analysis = _sample_analysis()
    issues = build_portfolio_issues(analysis, _sample_dep_metrics())
    assert issues[0].issue_id == "top_sector"
    assert issues[0].addresses == "top_sector"
    assert issues[0].label == "Largest industry (Technology)"
    assert issues[0].formatted_value == "50.64%"
    assert issues[1].issue_id == "dep.ALIAS:TSMC"
    assert issues[1].addresses == "dependency"
    assert any(i.issue_id == "top10" for i in issues)
    assert any(i.issue_id == "effective_n" for i in issues)
    assert DEFAULT_PROPOSER_MODEL == DEFAULT_ORCHESTRATOR_MODEL == "gemini-4-argon"


def test_verify_raw_proposals_accepts_valid_and_rejects_traps() -> None:
    holdings = _sample_holdings()
    issues = build_portfolio_issues(_sample_analysis(), _sample_dep_metrics())

    raw_payload = {
        "proposals": [
            # 1. Valid ADD proposal
            {
                "action": "add",
                "ticker": "RSP",
                "fraction": 0.2,
                "swap_from": "",
                "issue_id": "top_sector",
                "title": "Add equal-weight US stocks with RSP",
                "rationale": (
                    "Adding equal-weight US stocks reduces your {{metric:top_sector}} Technology concentration."
                ),
                "cited_metric_ids": ["top_sector"],
            },
            # 2. Valid SWAP proposal
            {
                "action": "swap",
                "ticker": "VTV",
                "fraction": 0.1,
                "swap_from": "XLK",
                "issue_id": "dep.ALIAS:TSMC",
                "title": "Swap tech-heavy XLK into value VTV",
                "rationale": (
                    "Shifting out of XLK into VTV lowers your {{metric:dep.ALIAS:TSMC}} chip foundry reliance."
                ),
                "cited_metric_ids": ["dep.ALIAS:TSMC"],
            },
            # 3. Invalid: ticker outside universe
            {
                "action": "add",
                "ticker": "ZZZZ",
                "fraction": 0.1,
                "issue_id": "top_sector",
                "title": "Add ZZZZ",
                "rationale": "Reduces {{metric:top_sector}}.",
                "cited_metric_ids": ["top_sector"],
            },
            # 4. Invalid: unverified literal number in rationale
            {
                "action": "add",
                "ticker": "XLV",
                "fraction": 0.2,
                "issue_id": "top_sector",
                "title": "Add health care with XLV",
                "rationale": "Cuts Technology from 50.6% to 40.5% right away.",
                "cited_metric_ids": ["top_sector"],
            },
            # 5. Invalid: swap_from not held / fraction > held allocation
            {
                "action": "swap",
                "ticker": "XLU",
                "fraction": 0.3,
                "swap_from": "XLK",  # XLK is only 0.15
                "issue_id": "top_sector",
                "title": "Swap XLK into utilities XLU",
                "rationale": "Lowers {{metric:top_sector}}.",
                "cited_metric_ids": ["top_sector"],
            },
        ]
    }

    verified, rejected = verify_raw_proposals(
        raw_payload,
        holdings=holdings,
        issues=issues,
        universe=PINNED_ETF_UNIVERSE,
    )
    assert len(verified) == 2
    assert verified[0].ticker == "RSP"
    assert verified[0].action == "add"
    assert verified[0].fraction == 0.2
    assert verified[0].addresses == "top_sector"
    assert verified[0].metric_id is None

    assert verified[1].ticker == "VTV"
    assert verified[1].action == "swap"
    assert verified[1].swap_from == "XLK"
    assert verified[1].addresses == "dependency"
    assert verified[1].metric_id == "dep.ALIAS:TSMC"

    assert len(rejected) == 3
    reasons = [r["reason"] for r in rejected]
    assert any("outside_universe" in r for r in reasons)
    assert "unverified_literal_number" in reasons
    assert any("swap_fraction_exceeds_holding" in r for r in reasons)

    # Render verified rationale with baseline/candidate metrics
    metrics_lookup: dict[str, PortfolioIssue | str] = {i.metric_id: i for i in issues}
    rendered, err = verify_and_render_proposal_rationale(
        verified[0].rationale_template,
        metrics_by_id=metrics_lookup,
    )
    assert err is None
    assert rendered == "Adding equal-weight US stocks reduces your 50.64% Technology concentration."


def test_idea_proposer_disk_cache_and_fallback_statuses(tmp_path: Path) -> None:
    holdings = _sample_holdings()
    analysis = _sample_analysis()
    issues = build_portfolio_issues(analysis, _sample_dep_metrics())

    calls: list[str] = []

    def fake_argon(*, model: str, **_: Any) -> dict[str, Any]:
        calls.append(model)
        return {
            "proposals": [
                {
                    "action": "add",
                    "ticker": "XLV",
                    "fraction": 0.2,
                    "swap_from": "",
                    "issue_id": "top_sector",
                    "title": "Add health care stocks with XLV",
                    "rationale": "Adding health care lowers your {{metric:top_sector}} Technology share.",
                    "cited_metric_ids": ["top_sector"],
                }
            ]
        }

    proposer = IdeaProposer(ai_client=fake_argon, cache_dir=tmp_path)
    assert proposer.read_cached(holdings, issues) is None

    res = proposer.propose(holdings, issues, analysis=analysis)
    assert res.ai_status == "ok"
    assert res.model == "gemini-4-argon"
    assert res.prompt_version == IDEA_PROPOSER_PROMPT_VERSION
    assert len(res.proposals) == 1
    assert len(calls) == 1

    # Synchronous cache hit via read_cached or propose(cache_only=True) makes 0 AI calls
    cached = proposer.read_cached(holdings, issues)
    assert cached is not None
    assert cached.ai_status == "ok"
    assert len(cached.proposals) == 1
    assert len(calls) == 1

    replay = IdeaProposer(ai_client=None, cache_dir=tmp_path).propose(
        holdings, issues, cache_only=True
    )
    assert replay.ai_status == "ok"
    assert len(replay.proposals) == 1

    # Missing API key on uncached portfolio returns ai_status="missing_api_key"
    other_holdings = [PortfolioItem(ticker="IVV", allocation=0.60), PortfolioItem(ticker="QQQ", allocation=0.40)]
    no_key = IdeaProposer(
        ai_client=None,
        settings=Settings(gemini_api_key=None, cache_dir=tmp_path),
        cache_dir=tmp_path,
        api_key="",
    ).propose(other_holdings, issues)
    assert no_key.ai_status == "missing_api_key"
    assert no_key.proposals == []

    # Cache key changes when model or holdings change
    k1 = compute_idea_proposer_cache_key(holdings, issues, model="gemini-4-argon")
    k2 = compute_idea_proposer_cache_key(holdings, issues, model="gemini-3.8-flash")
    k3 = compute_idea_proposer_cache_key(other_holdings, issues, model="gemini-4-argon")
    assert k1 != k2
    assert k1 != k3

    # Convenience function works identically
    conv = propose_change_ideas(holdings, issues, cache_dir=tmp_path, cache_only=True)
    assert conv.ai_status == "ok"
    assert len(conv.proposals) == 1


def test_verify_rationale_rejects_made_up_company_name() -> None:
    """verify_and_render_proposal_rationale and verify_raw_proposals reject invented company names."""
    issues = build_portfolio_issues(_sample_analysis(), _sample_dep_metrics())
    metrics_lookup: dict[str, PortfolioIssue | str] = {i.metric_id: i for i in issues}
    allowed_tickers = {"IVV", "QQQ", "XLK", "EEM", "VTV", "RSP", "TSMC"}
    allowed_entities = {"taiwan semiconductor manufacturing", "tsmc", "apple"}

    # Grounded entity and normal sentence-start verbs (e.g. "Consider") pass
    consider_text, consider_err = verify_and_render_proposal_rationale(
        "Consider broader exposure for {{metric:top_sector}}.",
        metrics_by_id={"top_sector": 0.51},
        allowed_entities={"technology"},
    )
    assert consider_err is None
    assert consider_text == "Consider broader exposure for 51.0%."

    ok_text, ok_err = verify_and_render_proposal_rationale(
        "Shifting out of XLK into VTV lowers your {{metric:dep.ALIAS:TSMC}} Taiwan Semiconductor reliance.",
        metrics_by_id=metrics_lookup,
        allowed_tickers=allowed_tickers,
        allowed_entities=allowed_entities,
    )
    assert ok_err is None
    assert ok_text is not None and "12.39%" in ok_text

    # Invented company name in rationale is rejected
    bad_text, bad_err = verify_and_render_proposal_rationale(
        "Shifting out of XLK into VTV lowers your {{metric:dep.ALIAS:TSMC}} Cyberdyne reliance.",
        metrics_by_id=metrics_lookup,
        allowed_tickers=allowed_tickers,
        allowed_entities=allowed_entities,
    )
    assert bad_text is None
    assert bad_err == "unknown_entity:Cyberdyne"

    # Also rejected in verify_raw_proposals
    verified, rejected = verify_raw_proposals(
        {
            "proposals": [
                {
                    "action": "add",
                    "ticker": "RSP",
                    "fraction": 0.2,
                    "swap_from": "",
                    "issue_id": "top_sector",
                    "title": "Add equal-weight US stocks with RSP",
                    "rationale": "Adding RSP reduces your {{metric:top_sector}} reliance on FakeMegaCorp.",
                    "cited_metric_ids": ["top_sector"],
                }
            ]
        },
        holdings=_sample_holdings(),
        issues=issues,
    )
    assert verified == []
    assert len(rejected) == 1
    assert rejected[0]["reason"] == "unknown_entity:FakeMegaCorp"


def test_enrich_universe_uses_authoritative_fund_reported_sector_breakdown() -> None:
    """enrich_universe_from_loaded uses hoc.portfolio.sectors.etf_sectors (including fund_reported weights)."""
    holding_line = NormalisedHolding(
        etf_ticker="VTV",
        security_key="SYM:BRK.B",
        security_id="BRK.B",
        security_id_type="symbol",
        symbol="BRK.B",
        name="Berkshire Hathaway",
        company_key="CIK:0001067983",
        company_key_basis="cik",
        company_name="Berkshire Hathaway Inc.",
        identity_status="resolved",
        weight=0.98,
        sector=Sector.unknown,
        sector_source="none",
        source="sec_nport",
        as_of=date(2026, 10, 31),
    )
    etf = EtfHoldings(
        etf_ticker="VTV",
        etf_name="Vanguard Value ETF",
        source="sec_nport",
        as_of=date(2026, 10, 31),
        retrieved_at=datetime(2026, 11, 8, 0, 0, tzinfo=UTC),
        source_url="https://example.invalid/vtv",
        holdings=[holding_line],
        reported_weight=0.98,
        holdings_weight=0.98,
        excluded_weight=0.0,
        unmatched_weight=0.0,
        sector_basis="fund_reported",
        sector_weights={
            Sector.health_care: 0.35,
            Sector.financials: 0.22,
        },
        raw_line_count=1,
        normaliser_version="1",
    )
    custom_universe = (
        EtfUniverseEntry("VTV", "Vanguard Value ETF", "US large-cap value", "Financials"),
    )
    enriched = enrich_universe_from_loaded({"VTV": etf}, universe=custom_universe)
    assert len(enriched) == 1
    assert enriched[0].largest_industry == "Health Care"


def test_proposer_builds_real_gemini_client_and_classifies_timeout_by_type(tmp_path: Path) -> None:
    """FIX-24: IdeaProposer instantiates the real GeminiClient over an HTTP double and classifies timeouts by type."""
    import json

    import httpx

    from hoc.contract import SourceUnavailable

    holdings = _sample_holdings()
    analysis = _sample_analysis()
    issues = build_portfolio_issues(analysis, _sample_dep_metrics())

    class _FakeResponse:
        status = 200

        def json(self) -> dict[str, Any]:
            return {
                "output_text": json.dumps(
                    {
                        "proposals": [
                            {
                                "action": "add",
                                "ticker": "RSP",
                                "fraction": 0.2,
                                "swap_from": "",
                                "issue_id": "top_sector",
                                "title": "Add equal-weight US stocks with RSP",
                                "rationale": "Consider broader exposure for {{metric:top_sector}}.",
                                "cited_metric_ids": ["top_sector"],
                            }
                        ]
                    }
                )
            }

    class _FakeHttpClient:
        def __init__(self) -> None:
            self.calls = 0

        def post_json(self, url: str, payload: Any, **kwargs: Any) -> _FakeResponse:
            self.calls += 1
            return _FakeResponse()

    http_double = _FakeHttpClient()
    settings = Settings(gemini_api_key="SYNTHETIC-test-key", cache_dir=tmp_path / "ok")
    proposer = IdeaProposer(http_double, settings)
    res = proposer.propose(holdings, issues, analysis=analysis)
    assert res.ai_status == "ok"
    assert len(res.proposals) == 1
    assert res.proposals[0].ticker == "RSP"
    assert http_double.calls == 1

    # TypeError whose message contains 'timeout' must be classified as 'failed', NOT 'timeout'
    def _bad_type_error(**_: Any) -> dict[str, Any]:
        raise TypeError("GeminiClient.__init__() got an unexpected keyword argument 'timeout'")

    type_err_res = IdeaProposer(ai_client=_bad_type_error, cache_dir=tmp_path / "err").propose(
        holdings, issues, analysis=analysis
    )
    assert type_err_res.ai_status == "failed"

    # Real httpx.ReadTimeout wrapped in SourceUnavailable -> GeminiError is classified as 'timeout'
    class _TimeoutHttpClient:
        def post_json(self, url: str, payload: Any, **kwargs: Any) -> Any:
            try:
                raise httpx.ReadTimeout("timed out")
            except httpx.TimeoutException as exc:
                raise SourceUnavailable("gemini", "timed out") from exc

    timeout_res = IdeaProposer(
        _TimeoutHttpClient(),
        Settings(gemini_api_key="SYNTHETIC-test-key", cache_dir=tmp_path / "to"),
    ).propose(holdings, issues, analysis=analysis)
    assert timeout_res.ai_status == "timeout"


