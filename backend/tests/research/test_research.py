"""Unit tests for v3 package A-RES (`hoc.research`)."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from hoc.ai.client import FakeGeminiClient
from hoc.contract import (
    AnalysisResponse,
    CompanyExposure,
    CompanyRunStatus,
    Concentration,
    Coverage,
    DependencyCounts,
    DependencyRequest,
    DependencyResult,
    EdgeImportance,
    EdgeInterpretation,
    EtfReport,
    FilingRef,
    Insights,
    Overlap,
    PortfolioItem,
    PortfolioRequest,
    VerifiedEdge,
)
from hoc.filings.fetch import Filing
from hoc.research import (
    MAX_RESEARCH_STEPS,
    RESEARCH_PROMPT_VERSION,
    AgenticResearchRunner,
    ResearchLoop,
    select_research_items,
    strip_unquoted_numbers,
)


def _sample_filing(
    *,
    cik: str = "0009990001",
    accession: str = "0009990001-25-000001",
    text: str | None = None,
) -> Filing:
    body = text or (
        "ITEM 1. BUSINESS\n"
        "We rely exclusively on ZZFAB for advanced wafer fabrication of our core processor line.\n"
        "We also purchase memory components from ZZSUP under multi-year supply agreements.\n"
        "ITEM 1A. RISK FACTORS\n"
        "Our primary competitors include ZZCOMP and other regional semiconductor manufacturers.\n"
    )
    return Filing(
        cik=cik,
        form="10-K",
        accession=accession,
        filed=date(2025, 2, 15),
        url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/zz1.htm",
        text=body,
        sha256="a" * 64,
        sections={"1": (0, len(body))},
        quality="sections",
    )


def _make_edge(
    *,
    edge_id: str,
    source_key: str = "CIK:0009990001",
    source_name: str = "ZZ Alpha Corp",
    target_name: str = "ZZFAB",
    target_key: str | None = "CIK:0009990009",
    target_kind: str = "company",
    edge_type: str = "foundry",
    sole_source: bool = True,
    quote: str = "We rely exclusively on ZZFAB for advanced wafer fabrication of our core processor line.",
    interp_status: str = "confirmed",
    interp_flags: list[str] | None = None,
    tier: str = "critical",
    score: float = 0.95,
    accession: str = "0009990001-25-000001",
) -> VerifiedEdge:
    return VerifiedEdge(
        edge_id=edge_id,
        source_company_key=source_key,
        source_company_name=source_name,
        target_name=target_name,
        target_key=target_key,
        target_kind=target_kind,  # type: ignore[arg-type]
        source_in_portfolio=True,
        target_in_portfolio=target_key is not None,
        edge_type=edge_type,  # type: ignore[arg-type]
        sole_source=sole_source,
        qualifier="sole wafer foundry",
        evidence_quote=quote,
        section="Item 1",
        filing=FilingRef(
            company_key=source_key,
            form="10-K",
            accession=accession,
            filed=date(2025, 2, 15),
            url="https://www.sec.gov/Archives/edgar/data/9990001/zz1.htm",
        ),
        importance=EdgeImportance(
            score=score,
            tier=tier,  # type: ignore[arg-type]
            reasons=["Foundry relationship", "Named as the sole source"],
        ),
        interpretation=EdgeInterpretation(
            status=interp_status,  # type: ignore[arg-type]
            method="rules",
            flags=interp_flags or [],  # type: ignore[arg-type]
            reason="Flagged for review" if interp_status == "flagged" else None,
        ),
    )


def _sample_analysis_and_result() -> tuple[AnalysisResponse, DependencyResult]:
    exposures = [
        CompanyExposure(
            rank=1,
            company_key="CIK:0009990001",
            company_name="ZZ Alpha Corp",
            identity_status="resolved",
            symbols=["ZZA"],
            sector="information_technology",
            exposure=0.40,
            etf_count=1,
            contributions=[],
            securities=[],
        ),
        CompanyExposure(
            rank=2,
            company_key="CIK:0009990002",
            company_name="ZZ Beta Corp",
            identity_status="resolved",
            symbols=["ZZB"],
            sector="information_technology",
            exposure=0.35,
            etf_count=1,
            contributions=[],
            securities=[],
        ),
        CompanyExposure(
            rank=3,
            company_key="CIK:0009990003",
            company_name="ZZ Gamma Corp",
            identity_status="resolved",
            symbols=["ZZG"],
            sector="information_technology",
            exposure=0.25,
            etf_count=1,
            contributions=[],
            securities=[],
        ),
    ]
    analysis = AnalysisResponse(
        generated_at=datetime(2025, 3, 1, 12, 0, tzinfo=UTC),
        as_of_date=date(2025, 3, 1),
        request=PortfolioRequest(holdings=[PortfolioItem(ticker="ZZETF", allocation=1.0)]),
        etfs=[
            EtfReport(
                ticker="ZZETF",
                name="ZZ Core ETF",
                allocation=1.0,
                status="ok",
                as_of=date(2025, 3, 1),
                holdings_count=3,
                company_count=3,
                reported_weight=1.0,
                holdings_weight=1.0,
                portfolio_covered_weight=1.0,
            )
        ],
        coverage=Coverage(
            total_allocation=1.0,
            loaded_allocation=1.0,
            missing_allocation=0.0,
            covered_weight=1.0,
            excluded_weight=0.0,
            unexplained_weight=0.0,
            unmatched_weight=0.0,
            sector_known_weight=1.0,
        ),
        exposures=exposures,
        exposures_truncated=False,
        other_exposure=0.0,
        overlap=Overlap(etfs=["ZZETF"], matrix=[[1.0]], pairs=[]),
        concentration=Concentration(
            top5=1.0,
            top10=1.0,
            top20=1.0,
            hhi=0.345,
            effective_companies=2.89,
            distinct_securities=3,
            distinct_companies=3,
        ),
        sectors=[],
        gaps=[],
        warnings=[],
        attributions=[],
    )

    e_flagged = _make_edge(
        edge_id="edge_flagged_1",
        source_key="CIK:0009990001",
        source_name="ZZ Alpha Corp",
        target_name="ZZFAB",
        interp_status="flagged",
        interp_flags=["hypothetical"],
        score=0.55,
        tier="medium",
    )
    e_undisclosed = _make_edge(
        edge_id="edge_undisc_1",
        source_key="CIK:0009990001",
        source_name="ZZ Alpha Corp",
        target_name="Customer A",
        target_key=None,
        target_kind="unnamed_customer",
        edge_type="customer",
        sole_source=False,
        quote="Sales to Customer A accounted for 22% of our consolidated revenue.",
        score=0.90,
        tier="critical",
    )
    e_unresolved = _make_edge(
        edge_id="edge_unres_1",
        source_key="CIK:0009990002",
        source_name="ZZ Beta Corp",
        target_name="ZZSUP",
        target_key=None,
        target_kind="company",
        edge_type="supplier",
        sole_source=True,
        quote="We also purchase memory components from ZZSUP under multi-year supply agreements.",
        score=0.95,
        tier="critical",
    )
    e_single = _make_edge(
        edge_id="edge_single_1",
        source_key="CIK:0009990002",
        source_name="ZZ Beta Corp",
        target_name="ZZFAB",
        target_key="CIK:0009990009",
        target_kind="company",
        edge_type="foundry",
        sole_source=True,
        quote="We rely exclusively on ZZFAB for advanced wafer fabrication of our core processor line.",
        score=0.95,
        tier="critical",
    )

    companies = [
        CompanyRunStatus(
            company_key="CIK:0009990001",
            company_name="ZZ Alpha Corp",
            exposure=0.40,
            status="done",
            verified_edges=2,
            rejected_edges=0,
        ),
        CompanyRunStatus(
            company_key="CIK:0009990002",
            company_name="ZZ Beta Corp",
            exposure=0.35,
            status="done",
            verified_edges=2,
            rejected_edges=0,
        ),
        CompanyRunStatus(
            company_key="CIK:0009990003",
            company_name="ZZ Gamma Corp",
            exposure=0.25,
            status="done",
            verified_edges=0,
            rejected_edges=0,
        ),
    ]

    result = DependencyResult(
        as_of_date=date(2025, 3, 1),
        request=DependencyRequest(holdings=[PortfolioItem(ticker="ZZETF", allocation=1.0)], top_n=10),
        companies=companies,
        edges=[e_flagged, e_undisclosed, e_unresolved, e_single],
        metrics=[],
        insights=Insights(
            status="ok",
            model="fake",
            suggestions=[],
            flaws=[],
        ),
        counts=DependencyCounts(
            companies_requested=3,
            companies_analysed=3,
            companies_skipped=0,
            verified_edges=4,
            rejected_edges=0,
            interpretation_rejected=0,
            unresolved_counterparties=1,
        ),
    )
    return analysis, result


def test_select_research_items_covers_all_five_kinds() -> None:
    analysis, result = _sample_analysis_and_result()
    items = select_research_items(result, analysis, max_items=6)
    kinds = {item.item_kind for item in items}
    assert kinds == {
        "flagged_edge",
        "undisclosed_customer",
        "unresolved_counterparty",
        "no_disclosures",
        "single_source",
    }
    assert [item.item_kind for item in items] == ['flagged_edge', 'undisclosed_customer', 'no_disclosures', 'unresolved_counterparty', 'single_source']


def test_strip_unquoted_numbers_preserves_verified_quotes_only() -> None:
    verified_quote = "Sales to Customer A accounted for 22% of our consolidated revenue in 2024."
    raw = (
        f'We found 3 filings showing 45.2% exposure where "{verified_quote}" '
        'and an unverified quote "We had 99% margin in 2023" was also seen.'
    )
    cleaned = strip_unquoted_numbers(raw, [verified_quote])
    assert f'"{verified_quote}"' in cleaned
    without_verified = cleaned.replace(f'"{verified_quote}"', "")
    assert not re.search(r"\d", without_verified)


def test_research_loop_runs_multi_step_and_merges_findings() -> None:
    analysis, result = _sample_analysis_and_result()
    f1 = _sample_filing(cik="0009990001", accession="0009990001-25-000001")
    f2 = _sample_filing(cik="0009990002", accession="0009990002-25-000001")
    f3 = _sample_filing(cik="0009990003", accession="0009990003-25-000001")

    fake_client = FakeGeminiClient(include_mutated_quotes=True)
    runner = ResearchLoop(
        client=fake_client,
        filings_by_key={
            "CIK:0009990001": f1,
            "CIK:0009990002": f2,
            "CIK:0009990003": f3,
        },
    )
    assert runner.prompt_version == RESEARCH_PROMPT_VERSION
    assert AgenticResearchRunner is ResearchLoop

    progress_events: list[tuple[int, int, int]] = []
    findings, merged = runner.run(
        result,
        analysis,
        max_items=5,
        cache_only=False,
        progress=lambda done, total, cur: progress_events.append((done, total, len(cur))),
    )

    assert len(findings) == 5
    assert progress_events[0] == (0, 5, 0)
    assert progress_events[-1] == (5, 5, 5)

    for finding in findings:
        assert 1 <= len(finding.steps) <= MAX_RESEARCH_STEPS
        assert finding.steps[-1].action == "conclude"
        assert len(finding.steps) >= 2
        verified_quotes = [e.evidence_quote for e in finding.new_edges] + [
            e.evidence_quote for e in result.edges
        ]
        scrubbed = finding.explanation
        for vq in verified_quotes:
            scrubbed = scrubbed.replace(f'"{vq}"', "")
        assert not re.search(r"\d", scrubbed), f"Unquoted digit in explanation: {finding.explanation}"

    confirmed_edge = next(e for e in merged.edges if e.edge_id == "edge_flagged_1")
    assert confirmed_edge.interpretation is not None
    assert confirmed_edge.interpretation.status == "confirmed"
    assert confirmed_edge.importance is not None
    assert confirmed_edge.importance.tier == "critical"

    c3_edges = [e for e in merged.edges if e.source_company_key == "CIK:0009990003"]
    assert len(c3_edges) >= 1
    assert all("Hallucinated" not in e.target_name for e in c3_edges)
    c3_status = next(c for c in merged.companies if c.company_key == "CIK:0009990003")
    assert c3_status.verified_edges == len(c3_edges)
    assert merged.coverage is not None


def test_research_loop_rejects_contradicted_flagged_edge_and_handles_failure() -> None:
    analysis, result = _sample_analysis_and_result()
    negated_quote = "We do not rely on ZZCOMP for any critical manufacturing capacity."
    f1 = _sample_filing(
        cik="0009990001",
        text=f"ITEM 1. BUSINESS\n{negated_quote}\n",
    )
    flagged_neg = _make_edge(
        edge_id="edge_neg_flagged",
        source_key="CIK:0009990001",
        source_name="ZZ Alpha Corp",
        target_name="ZZCOMP",
        quote=negated_quote,
        interp_status="flagged",
        interp_flags=["negated"],
        score=0.50,
        tier="medium",
    )
    custom_result = result.model_copy(update={"edges": [flagged_neg], "companies": result.companies[:1]})

    fake_client = FakeGeminiClient()
    runner = ResearchLoop(
        client=fake_client,
        filings_by_key={"CIK:0009990001": f1},
    )
    findings, merged = runner.run(custom_result, analysis, max_items=2, cache_only=False)
    assert findings[0].outcome == "rejected"
    assert "edge_neg_flagged" in findings[0].rejected_edge_ids
    assert all(e.edge_id != "edge_neg_flagged" for e in merged.edges)
    assert merged.counts.interpretation_rejected == custom_result.counts.interpretation_rejected + 1


def _one_edge(edge: VerifiedEdge) -> tuple[AnalysisResponse, DependencyResult]:
    analysis, result = _sample_analysis_and_result()
    company = result.companies[0].model_copy(update={"verified_edges": 1})
    return analysis, result.model_copy(update={"edges": [edge], "companies": [company]})


def test_hypothetical_cannot_be_promoted() -> None:
    from hoc.ai.interpretation import verify_edge_interpretation

    for force_unresolved in (False, True):
        quote = "If demand increases, we could consider ZZFAB as a potential foundry."
        edge = _make_edge(
            edge_id="hypothetical",
            quote=quote,
            interp_status="flagged",
            interp_flags=["hypothetical"],
        )
        analysis, result = _one_edge(edge)
        filing = _sample_filing(text="ITEM 1. BUSINESS\n" + quote)
        verdict = verify_edge_interpretation(edge, filing.text, cache_only=True)
        assert verdict.status == "flagged"
        assert "hypothetical" in verdict.flags
        client = FakeGeminiClient()
        if force_unresolved:
            client.add_response(
                "",
                {
                    "action": "conclude",
                    "query": "",
                    "cik": filing.cik,
                    "section": "",
                    "outcome": "unresolved",
                    "explanation": "Evidence is hypothetical.",
                    "candidate_edges": [],
                },
            )
        findings, merged = ResearchLoop(
            client=client,
            filings_by_key={edge.source_company_key: filing},
        ).run(result, analysis, max_items=1, cache_only=False)
        assert len(findings) == 1
        assert findings[0].outcome == "unresolved"
        assert edge.edge_id not in findings[0].confirmed_edge_ids
        kept = next(e for e in merged.edges if e.edge_id == edge.edge_id)
        assert kept.interpretation is not None
        assert kept.interpretation.status == "flagged"


def test_cache_only_competitor_cannot_become_dependency() -> None:
    analysis, result = _sample_analysis_and_result()
    company = result.companies[0].model_copy(update={"verified_edges": 0})
    result = result.model_copy(update={"edges": [], "companies": [company]})
    filing = _sample_filing(
        text="ITEM 1. BUSINESS\nOur primary competitors include TSMC and other semiconductor manufacturers."
    )
    client = FakeGeminiClient(has_api_key=False)
    findings, merged = ResearchLoop(
        client=client,
        filings_by_key={company.company_key: filing},
    ).run(result, analysis, max_items=1, cache_only=True)
    assert client.calls == []
    assert len(findings) == 1
    assert findings[0].outcome == "unresolved"
    assert findings[0].new_edges == []
    assert merged.edges == []


def test_verified_quote_cannot_launder_adjacent_invented_digits() -> None:
    quote = "We rely exclusively on ZZFAB for advanced wafer fabrication of our core processor line."
    cleaned = strip_unquoted_numbers(f'Claim: "{quote} 99% invented"', [quote])
    assert not re.search(r"\d", cleaned)
    numeric = "Sales to Customer A accounted for 22% of our consolidated revenue."
    assert f'"{numeric}"' in strip_unquoted_numbers(f'Claim 99: "{numeric}"', [numeric])


def test_unnamed_customer_below_ten_percent_is_not_selected() -> None:
    quote = "Sales to Customer A accounted for 5% of our consolidated revenue."
    edge = _make_edge(
        edge_id="small_customer",
        target_name="Customer A",
        target_key=None,
        target_kind="unnamed_customer",
        edge_type="customer",
        sole_source=False,
        quote=quote,
        tier="low",
        score=0.1,
    ).model_copy(update={"qualifier": "5% of consolidated revenue"})
    analysis, result = _one_edge(edge)
    items = select_research_items(result, analysis, max_items=6)
    assert not any(i.item_kind == "undisclosed_customer" for i in items)


def test_selection_uses_raw_importance_times_exposure() -> None:
    low = _make_edge(edge_id="low_flagged", interp_status="flagged", score=0.55, tier="medium")
    high = _make_edge(
        edge_id="high_flagged",
        source_key="CIK:0009990002",
        target_name="ZZSUP",
        interp_status="flagged",
        score=0.8,
        tier="high",
    )
    analysis, result = _sample_analysis_and_result()
    companies = [
        result.companies[0].model_copy(update={"exposure": 0.40}),
        result.companies[1].model_copy(update={"exposure": 0.40}),
    ]
    result = result.model_copy(update={"edges": [low, high], "companies": companies})
    items = select_research_items(result, analysis, max_items=1)
    assert len(items) == 1
    assert items[0].edge is not None
    assert items[0].edge.edge_id == high.edge_id


def test_slow_gemini_call_obeys_wall_clock_budget() -> None:
    import time

    class SlowClient(FakeGeminiClient):
        def generate_json(self, *args, **kwargs):
            time.sleep(0.5)
            return super().generate_json(*args, **kwargs)

    edge = _make_edge(edge_id="slow_flagged", interp_status="flagged")
    analysis, result = _one_edge(edge)
    runner = ResearchLoop(client=SlowClient(), filings_by_key={edge.source_company_key: _sample_filing()})
    runner.item_timeout_s, runner.total_timeout_s = 0.05, 0.1
    started = time.monotonic()
    findings, _ = runner.run(result, analysis, max_items=1, cache_only=False)
    elapsed = time.monotonic() - started
    assert elapsed < 0.3, f"A blocking Gemini call escaped the budget: {elapsed:.3f}s"
    assert len(findings) == 1
    assert findings[0].outcome == "unresolved"


def test_research_replays_across_runner_instances_and_invalidates_prompt(tmp_path) -> None:
    from hoc.ai.cache import ExtractionCache
    from hoc.core.cache import DiskCache

    edge = _make_edge(edge_id="valid_flagged", interp_status="flagged")
    analysis, result = _one_edge(edge)
    client = FakeGeminiClient()
    online = ResearchLoop(
        client=client,
        cache=ExtractionCache(DiskCache(tmp_path)),
        filings_by_key={edge.source_company_key: _sample_filing()},
    )
    findings, merged = online.run(result, analysis, max_items=1, cache_only=False)
    assert client.calls
    assert any(f.outcome != "unresolved" for f in findings)
    offline_client = FakeGeminiClient(has_api_key=False)
    replay = ResearchLoop(client=offline_client, cache=ExtractionCache(DiskCache(tmp_path)))
    replayed, replayed_result = replay.run(result, analysis, max_items=1, cache_only=True)
    assert offline_client.calls == []
    assert [f.model_dump() for f in replayed] == [f.model_dump() for f in findings]
    assert replayed_result.model_dump() == merged.model_dump()
    replay.prompt_version += "-changed"
    missed, _ = replay.run(result, analysis, max_items=1, cache_only=True)
    assert len(missed) == 1
    assert missed[0].outcome == "unresolved"
    assert offline_client.calls == []


def test_from_settings_wires_etf_service_and_research_runner_offline(tmp_path) -> None:
    """EtfService.from_settings and AgenticResearchRunner.from_settings construct cleanly with zero network calls."""
    from hoc.config import Settings
    from hoc.core.cache import DiskCache
    from hoc.core.http import CachedHttpClient
    from hoc.graph import DependencyOrchestrator
    from hoc.service import EtfService

    settings = Settings(cache_dir=tmp_path)
    http = CachedHttpClient(settings, DiskCache(settings.cache_dir))

    runner = AgenticResearchRunner.from_settings(http, settings)
    assert isinstance(runner, ResearchLoop)
    assert isinstance(runner.orchestrator, DependencyOrchestrator)
    assert runner.cache is not None
    assert runner.fetcher is not None

    service = EtfService.from_settings(settings)
    assert isinstance(service.research_runner, ResearchLoop)
    assert isinstance(service.research_runner.orchestrator, DependencyOrchestrator)


class _VerdictClient(FakeGeminiClient):
    def __init__(self, outcome: str, edge_id: str, cleared: list[str] | tuple[str, ...] = ()) -> None:
        super().__init__()
        self.outcome = outcome
        self.edge_id = edge_id
        self.cleared = list(cleared)

    def generate_json(self, prompt, schema, **kwargs):
        if "verdicts" in schema.get("properties", {}):
            return {
                "verdicts": [
                    {
                        "edge_id": self.edge_id,
                        "label": "supports",
                        "cleared_flags": list(self.cleared),
                        "reason": "Verified by independent judge.",
                    }
                ]
            }, self.extractor_model
        return {
            "action": "conclude",
            "outcome": self.outcome,
            "explanation": "Review completed.",
            "query": "",
            "candidate_edges": [],
        }, self.extractor_model


def test_research_model_cannot_reject_edge_supported_by_independent_judge() -> None:
    from hoc.ai.interpretation import verify_edge_interpretation

    edge = _make_edge(edge_id="judge_supported", interp_status="flagged")
    analysis, result = _one_edge(edge)
    filing = _sample_filing()
    client = _VerdictClient("rejected", edge.edge_id)
    verdict = verify_edge_interpretation(
        edge.model_copy(update={"interpretation": None}),
        filing.text,
        client=client,
    )
    assert verdict.status == "confirmed"
    findings, merged = ResearchLoop(
        client=client,
        filings_by_key={edge.source_company_key: filing},
    ).run(result, analysis, max_items=1)
    assert edge.edge_id not in findings[0].rejected_edge_ids
    assert any(e.edge_id == edge.edge_id for e in merged.edges)


def test_merge_preserves_independent_judge_that_cleared_rule_flag() -> None:
    from hoc.ai.interpretation import verify_edge_interpretation

    quote = "Our competitor ZZFAB also manufactures our processors under a foundry agreement."
    edge = _make_edge(
        edge_id="judge_cleared",
        quote=quote,
        interp_status="flagged",
        interp_flags=["competitor_mention"],
    )
    analysis, result = _one_edge(edge)
    filing = _sample_filing(text="ITEM 1. BUSINESS\n" + quote)
    client = _VerdictClient("confirmed", edge.edge_id, ["competitor_mention"])
    verdict = verify_edge_interpretation(
        edge.model_copy(update={"interpretation": None}),
        filing.text,
        client=client,
    )
    assert verdict.status == "confirmed"
    findings, merged = ResearchLoop(
        client=client,
        filings_by_key={edge.source_company_key: filing},
    ).run(result, analysis, max_items=1)
    assert findings[0].outcome == "confirmed"
    assert merged.edges[0].interpretation == verdict


def test_initial_filing_fetch_respects_research_deadline() -> None:
    import time

    edge = _make_edge(edge_id="slow_fetch", interp_status="flagged")
    analysis, result = _one_edge(edge)

    class SlowFetcher:
        def latest(self, cik):
            time.sleep(0.5)
            return _sample_filing()

    runner = ResearchLoop(
        client=FakeGeminiClient(),
        fetcher=SlowFetcher(),  # type: ignore[arg-type]
        item_timeout_s=0.05,
        total_timeout_s=0.1,
    )
    started = time.monotonic()
    findings, _ = runner.run(result, analysis, max_items=1)
    elapsed = time.monotonic() - started
    assert elapsed < 0.3, f"Filing fetch escaped the budget: {elapsed:.3f}s"
    assert findings[0].outcome == "unresolved"


def test_final_insights_respect_research_deadline() -> None:
    import time

    edge = _make_edge(edge_id="slow_insights", interp_status="flagged")
    analysis, result = _one_edge(edge)

    class SlowOrchestrator:
        def insights(self, analysis, edges, **kwargs):
            time.sleep(0.5)
            return result.metrics, result.insights

    runner = ResearchLoop(
        client=_VerdictClient("confirmed", edge.edge_id),
        filings_by_key={edge.source_company_key: _sample_filing()},
        orchestrator=SlowOrchestrator(),
        item_timeout_s=0.05,
        total_timeout_s=0.1,
    )
    started = time.monotonic()
    _, merged = runner.run(result, analysis, max_items=1)
    elapsed = time.monotonic() - started
    assert elapsed < 0.3, f"Final insights escaped the budget: {elapsed:.3f}s"
    assert merged.insights.status == "metrics_only"


def test_selection_does_not_floor_small_company_exposures() -> None:
    actual_highest = _make_edge(
        edge_id="actual_highest",
        interp_status="flagged",
        score=0.6,
        tier="high",
    )
    floor_promoted = _make_edge(
        edge_id="floor_promoted",
        source_key="CIK:0009990002",
        interp_status="flagged",
        score=0.95,
    )
    analysis, result = _sample_analysis_and_result()
    companies = [
        result.companies[0].model_copy(update={"exposure": 0.004}),
        result.companies[1].model_copy(update={"exposure": 0.001}),
    ]
    result = result.model_copy(update={"edges": [actual_highest, floor_promoted], "companies": companies})
    items = select_research_items(result, analysis, max_items=1)
    assert items[0].edge is not None
    assert items[0].edge.edge_id == actual_highest.edge_id


def test_f2_selection_kind_priority_and_one_per_company_kind() -> None:
    analysis, result = _sample_analysis_and_result()
    extra_single_1 = _make_edge(
        edge_id="edge_single_2",
        source_key="CIK:0009990002",
        source_name="ZZ Beta Corp",
        target_name="Taiwan",
        target_key=None,
        target_kind="country",
        edge_type="contract_manufacturer",
        sole_source=True,
        quote="Substantially all hardware products are manufactured in Asia, including Taiwan and Japan.",
        score=0.99,
        tier="critical",
    )
    extra_single_2 = _make_edge(
        edge_id="edge_single_3",
        source_key="CIK:0009990002",
        source_name="ZZ Beta Corp",
        target_name="Japan",
        target_key=None,
        target_kind="country",
        edge_type="contract_manufacturer",
        sole_source=True,
        quote="Substantially all hardware products are manufactured in Asia, including Taiwan and Japan.",
        score=0.98,
        tier="critical",
    )
    result = result.model_copy(update={"edges": [*result.edges, extra_single_1, extra_single_2]})
    items = select_research_items(result, analysis, max_items=6)
    assert [i.item_kind for i in items] == [
        "flagged_edge",
        "undisclosed_customer",
        "no_disclosures",
        "unresolved_counterparty",
        "single_source",
    ]
    seen_pairs = [(i.subject_key, i.item_kind) for i in items]
    assert len(seen_pairs) == len(set(seen_pairs))


def test_f3_find_in_filing_returns_queried_sentence_with_context_not_opening() -> None:
    analysis, _result = _sample_analysis_and_result()
    filing_text = (
        "ITEM 1. BUSINESS\n"
        "Company Background The Company designs, manufactures and markets smartphones, personal computers and tablets.\n"
        "The Company's global supply chain spans multiple continents.\n"
        "Substantially all of the Company's hardware products are manufactured by outsourcing partners in Asia, including Japan and Taiwan.\n"
        "Any severe disruption in these regions could materially impact shipments.\n"
    )
    filing = _sample_filing(cik="0009990001", text=filing_text)
    edge = _make_edge(
        edge_id="apple_japan",
        target_name="Japan",
        target_key=None,
        target_kind="country",
        edge_type="contract_manufacturer",
        quote="Substantially all of the Company's hardware products are manufactured by outsourcing partners in Asia, including Japan and Taiwan.",
        interp_status="flagged",
    )
    _, one_res = _one_edge(edge)
    items = select_research_items(one_res, analysis, max_items=1)
    runner = ResearchLoop(client=FakeGeminiClient(), filings_by_key={"CIK:0009990001": filing})
    spans = runner._find_spans_in_filing(filing, "Japan", item=items[0], result=one_res)
    assert spans
    assert "Japan" in spans[0]
    assert "Company Background" not in spans[0]


def test_f4_refound_existing_edge_counts_as_confirmed_not_new_evidence() -> None:
    edge = _make_edge(edge_id="existing_single", interp_status="confirmed", score=0.95, tier="critical")
    analysis, result = _one_edge(edge)
    filing = _sample_filing()

    class RefindClient(FakeGeminiClient):
        def generate_json(self, prompt, schema, **kwargs):
            if "verdicts" in schema.get("properties", {}):
                return super().generate_json(prompt, schema, **kwargs)
            return {
                "action": "conclude",
                "query": "ZZFAB",
                "outcome": "new_evidence",
                "explanation": f'Verified passage "{edge.evidence_quote}".',
                "candidate_edges": [
                    {
                        "target_name": edge.target_name,
                        "target_kind": edge.target_kind,
                        "edge_type": edge.edge_type,
                        "sole_source": edge.sole_source,
                        "qualifier": edge.qualifier or "",
                        "evidence_quote": edge.evidence_quote,
                        "section": edge.section,
                    }
                ],
            }, self.extractor_model

    findings, merged = ResearchLoop(
        client=RefindClient(),
        filings_by_key={edge.source_company_key: filing},
    ).run(result, analysis, max_items=1)
    assert len(findings) == 1
    assert findings[0].outcome == "confirmed"
    assert findings[0].new_edges == []
    assert edge.edge_id in findings[0].confirmed_edge_ids
    assert len(merged.edges) == 1
