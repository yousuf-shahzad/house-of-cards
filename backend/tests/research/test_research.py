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
        "Any disruption at ZZFAB or ZZSUP facilities could materially delay shipments of our core products.\n"
        "ITEM 1A. RISK FACTORS\n"
        "Supply chain interruptions at ZZFAB or ZZSUP could adversely affect our operating results.\n"
        "Global semiconductor demand fluctuates across enterprise and consumer markets.\n"
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
    filing = _sample_filing(
        text="ITEM 1. BUSINESS\n"
        + quote
        + "\nAny disruption at ZZFAB foundry sites could delay processor deliveries.\n"
    )
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
    assert merged.insights == result.insights


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


def test_s2_merge_preserves_fresh_flagged_judge_unclear_verdict() -> None:
    from hoc.ai.interpretation import verify_edge_interpretation

    quote = "If demand increases, we could consider ZZFAB as a potential foundry."
    edge = _make_edge(
        edge_id="unclear_flagged",
        quote=quote,
        interp_status="flagged",
        interp_flags=["hypothetical"],
    )
    analysis, result = _one_edge(edge)
    filing = _sample_filing(text="ITEM 1. BUSINESS\n" + quote)
    client = FakeGeminiClient()
    verdict = verify_edge_interpretation(
        edge.model_copy(update={"interpretation": None}),
        filing.text,
        client=client,
    )
    assert verdict.status == "flagged"
    assert "judge_unclear" in verdict.flags
    _, merged = ResearchLoop(
        client=client,
        filings_by_key={edge.source_company_key: filing},
    ).run(result, analysis, max_items=1)
    assert merged.edges[0].interpretation == verdict


def test_f3_multiword_phrase_and_miss_behavior() -> None:
    analysis, _result = _sample_analysis_and_result()
    filing_text = (
        "ITEM 1. BUSINESS\n"
        "We offer advanced software tools and cloud services to enterprise customers.\n"
        "Our semiconductor division designs custom accelerators.\n"
        "We rely exclusively on ZZFAB for advanced wafer fabrication of our core processor line.\n"
        "Any disruption at ZZFAB would delay shipments.\n"
    )
    filing = _sample_filing(cik="0009990001", text=filing_text)
    edge = _make_edge(edge_id="multiword_edge", interp_status="flagged")
    _, one_res = _one_edge(edge)
    items = select_research_items(one_res, analysis, max_items=1)
    runner = ResearchLoop(client=FakeGeminiClient(), filings_by_key={"CIK:0009990001": filing})

    spans = runner._find_spans_in_filing(filing, "advanced wafer fabrication", item=items[0], result=one_res)
    assert spans
    assert "advanced wafer fabrication" in spans[0]
    assert "custom accelerators" in spans[0] or "delay shipments" in spans[0]
    assert "advanced software tools" not in spans[0]

    missed = runner._find_spans_in_filing(filing, "ZXNONEXISTENT", item=items[0], result=one_res)
    assert missed == []

    only_advanced_filing = _sample_filing(
        cik="0009990001",
        text="ITEM 1. BUSINESS\nWe offer advanced software tools and cloud services to enterprise customers.\n",
    )
    assert (
        runner._find_spans_in_filing(
            only_advanced_filing, "advanced wafer fabrication", item=items[0], result=one_res
        )
        == []
    )


def test_q1_final_insights_has_separate_budget_and_keeps_previous_insights_on_failure() -> None:
    edge = _make_edge(edge_id="q1_flagged", interp_status="flagged")
    analysis, result = _one_edge(edge)

    class FailingOrchestrator:
        def insights(self, analysis, edges, **kwargs):
            raise RuntimeError("synthesis timeout")

    runner = ResearchLoop(
        client=_VerdictClient("confirmed", edge.edge_id),
        filings_by_key={edge.source_company_key: _sample_filing()},
        orchestrator=FailingOrchestrator(),
    )
    assert runner.insights_timeout_s == 75.0
    _, merged = runner.run(result, analysis, max_items=1)
    assert merged.insights == result.insights
    assert merged.insights.status == "ok"


def test_q2_anonymised_customer_labels_become_unnamed_customer_never_company() -> None:
    analysis, result = _sample_analysis_and_result()
    company = result.companies[0].model_copy(update={"verified_edges": 0})
    result = result.model_copy(update={"edges": [], "companies": [company]})
    filing_text = (
        "ITEM 1. BUSINESS\n"
        "Sales to Customer A accounted for 16% of our total net revenue in 2025.\n"
        "In addition, one customer in North America represented 11% of consolidated revenue.\n"
        "Shipments through a distributor accounted for 12% of net sales.\n"
    )
    filing = _sample_filing(cik="0009990001", text=filing_text)

    class AnonCustomerClient(FakeGeminiClient):
        def generate_json(self, prompt, schema, **kwargs):
            if "verdicts" in schema.get("properties", {}):
                return super().generate_json(prompt, schema, **kwargs)
            return {
                "action": "conclude",
                "query": "Customer A",
                "outcome": "new_evidence",
                "explanation": 'Verified customer concentration "Sales to Customer A accounted for 16% of our total net revenue in 2025."',
                "candidate_edges": [
                    {
                        "target_name": "Customer A",
                        "target_kind": "company",
                        "edge_type": "customer",
                        "sole_source": False,
                        "qualifier": "16% of net revenue",
                        "evidence_quote": "Sales to Customer A accounted for 16% of our total net revenue in 2025.",
                        "section": "Item 1",
                    },
                    {
                        "target_name": "one customer",
                        "target_kind": "company",
                        "edge_type": "customer",
                        "sole_source": False,
                        "qualifier": "11% of consolidated revenue",
                        "evidence_quote": "In addition, one customer in North America represented 11% of consolidated revenue.",
                        "section": "Item 1",
                    },
                    {
                        "target_name": "a distributor",
                        "target_kind": "company",
                        "edge_type": "customer",
                        "sole_source": False,
                        "qualifier": "12% of net sales",
                        "evidence_quote": "Shipments through a distributor accounted for 12% of net sales.",
                        "section": "Item 1",
                    },
                ],
            }, self.extractor_model

    findings, merged = ResearchLoop(
        client=AnonCustomerClient(),
        filings_by_key={company.company_key: filing},
    ).run(result, analysis, max_items=1)
    assert len(findings) == 1
    assert len(findings[0].new_edges) == 3
    by_name = {e.target_name: e for e in merged.edges}
    assert set(by_name.keys()) == {
        "Unnamed customer (Customer A)",
        "Unnamed customer (one customer)",
        "Unnamed customer (a distributor)",
    }
    for e in merged.edges:
        assert e.target_kind == "unnamed_customer"
        assert e.edge_type == "customer"
        assert e.target_key is None
        assert e.target_in_portfolio is False


def test_a1_research_company_light_vs_thorough_depth_presets() -> None:
    from hoc.research import (
        RESEARCH_DEPTH_PRESETS,
        CompanyResearch,
        research_company,
    )

    assert RESEARCH_DEPTH_PRESETS["none"] == (0, 0)
    assert RESEARCH_DEPTH_PRESETS["light"] == (2, 3)
    assert RESEARCH_DEPTH_PRESETS["thorough"] == (4, 4)

    analysis, _ = _sample_analysis_and_result()
    comp = analysis.exposures[0]
    filing = _sample_filing(cik="0009990001", accession="0009990001-25-000001")

    e1 = _make_edge(
        edge_id="e_flag_1",
        source_key=comp.company_key,
        source_name=comp.company_name,
        target_name="TSMC",
        quote="We rely on TSMC as our primary wafer foundry for advanced logic products.",
        interp_status="flagged",
        interp_flags=["judge_unclear"],
    )
    e2 = _make_edge(
        edge_id="e_undisc_1",
        source_key=comp.company_key,
        source_name=comp.company_name,
        target_name="Customer A",
        target_key=None,
        target_kind="unnamed_customer",
        edge_type="customer",
        sole_source=False,
        quote="Sales to Customer A accounted for 22% of our consolidated revenue.",
    )
    e3 = _make_edge(
        edge_id="e_unres_1",
        source_key=comp.company_key,
        source_name=comp.company_name,
        target_name="ZZSUP",
        target_key=None,
        target_kind="company",
        edge_type="supplier",
        sole_source=True,
        quote="We also purchase memory components from ZZSUP under multi-year supply agreements.",
    )
    e4 = _make_edge(
        edge_id="e_single_1",
        source_key=comp.company_key,
        source_name=comp.company_name,
        target_name="ZZFAB",
        target_key="CIK:0009990009",
        target_kind="company",
        edge_type="foundry",
        sole_source=True,
        quote="We rely exclusively on ZZFAB for advanced wafer fabrication of our core processor line.",
    )
    edges = [e1, e2, e3, e4]

    client_light = FakeGeminiClient()
    runner_light = ResearchLoop(client=client_light, filings_by_key={comp.company_key: filing})
    light_progress: list[tuple[int, int]] = []
    res_light = runner_light.research_company(
        comp,
        filing,
        edges,
        depth="light",
        progress=lambda done, total: light_progress.append((done, total)),
    )
    assert isinstance(res_light, CompanyResearch)
    assert len(res_light.findings) == 2
    assert all(1 <= len(f.steps) <= 3 for f in res_light.findings)
    assert light_progress[0][0] == 0
    assert light_progress[-1][0] == light_progress[-1][1] == res_light.steps_done == res_light.steps_total
    assert res_light.steps_done == sum(len(f.steps) for f in res_light.findings)

    client_thorough = FakeGeminiClient()
    res_thorough = research_company(
        comp,
        filing,
        edges,
        depth="thorough",
        client=client_thorough,
        filings_by_key={comp.company_key: filing},
    )
    assert len(res_thorough.findings) == 4
    assert all(1 <= len(f.steps) <= 4 for f in res_thorough.findings)
    assert res_thorough.steps_done == res_thorough.steps_total == sum(len(f.steps) for f in res_thorough.findings)


def test_a1_research_company_rejects_negated_edge_and_caches_across_depths(tmp_path) -> None:
    import pytest

    from hoc.contract import CompanyUnavailable
    from hoc.core.cache import DiskCache

    analysis, _ = _sample_analysis_and_result()
    comp = analysis.exposures[0]
    neg_quote = "We do not rely on ZZCOMP for any critical manufacturing capacity."
    valid_quote = "We rely on TSMC as our primary wafer foundry for advanced logic products."
    filing = _sample_filing(
        cik="0009990001",
        text=f"ITEM 1. BUSINESS\n{neg_quote}\n{valid_quote}\n",
    )
    e_neg = _make_edge(
        edge_id="e_neg",
        source_key=comp.company_key,
        source_name=comp.company_name,
        target_name="ZZCOMP",
        quote=neg_quote,
        interp_status="flagged",
        interp_flags=["negated"],
    )
    e_valid = _make_edge(
        edge_id="e_valid",
        source_key=comp.company_key,
        source_name=comp.company_name,
        target_name="TSMC",
        quote=valid_quote,
        interp_status="confirmed",
    )

    disk = DiskCache(tmp_path)
    runner1 = ResearchLoop(
        client=FakeGeminiClient(),
        disk_cache=disk,
        filings_by_key={comp.company_key: filing},
    )
    res1 = runner1.research_company(comp, filing, [e_neg, e_valid], depth="light")
    assert res1.cached is False
    assert "e_neg" in res1.rejected_edge_ids
    assert res1.interpretation_rejected == 1
    assert [e.edge_id for e in res1.edges] == ["e_valid"]

    # Replay from DiskCache in cache_only mode with no API key
    offline_client = FakeGeminiClient(has_api_key=False)
    runner2 = ResearchLoop(
        client=offline_client,
        disk_cache=disk,
        filings_by_key={comp.company_key: filing},
    )
    replay_progress: list[tuple[int, int]] = []
    res_cached = runner2.research_company(
        comp,
        filing,
        [e_neg, e_valid],
        depth="light",
        cache_only=True,
        progress=lambda done, total: replay_progress.append((done, total)),
    )
    assert res_cached.cached is True
    assert offline_client.calls == []
    assert res_cached.rejected_edge_ids == ["e_neg"]
    assert [e.edge_id for e in res_cached.edges] == ["e_valid"]
    assert replay_progress[-1][0] == replay_progress[-1][1] == res_cached.steps_total

    # Uncached thorough depth in cache_only mode raises CompanyUnavailable('missing_api_key')
    with pytest.raises(CompanyUnavailable) as exc_info:
        runner2.research_company(comp, filing, [e_neg, e_valid], depth="thorough", cache_only=True)
    assert exc_info.value.status == "missing_api_key"


def test_a1_dependency_extractor_reuses_cached_extraction_from_light_to_thorough(tmp_path) -> None:
    from hoc.ai.cache import ExtractionCache
    from hoc.ai.extractor import DependencyExtractor
    from hoc.core.cache import DiskCache

    analysis, _ = _sample_analysis_and_result()
    comp = analysis.exposures[0]
    filing = _sample_filing(cik="0009990001", accession="0009990001-25-000099")

    disk = DiskCache(tmp_path)
    ext_cache = ExtractionCache(disk)
    client = FakeGeminiClient()
    extractor = DependencyExtractor(client, cache=ext_cache)

    light_ext = extractor.extract(comp, filing, depth="light")
    assert light_ext.cached is False
    assert len(light_ext.edges) >= 1
    assert len(light_ext.findings) >= 1
    assert light_ext.steps_done == light_ext.steps_total > 0

    calls_after_light = len(client.calls)
    # Upgrading to thorough reuses the cached initial extraction (0 new extraction calls; only research steps run)
    thorough_ext = extractor.extract_agentic(comp, filing, depth="thorough")
    new_calls = client.calls[calls_after_light:]
    assert all("FILING TEXT:" not in c["prompt"] for c in new_calls)
    assert len(thorough_ext.findings) >= len(light_ext.findings)


def test_fix1_non_circular_confirmation_requires_different_passage_or_other_filing() -> None:
    analysis, _ = _sample_analysis_and_result()
    comp = analysis.exposures[0]
    quote = "We rely exclusively on ZZFAB for advanced wafer fabrication of our core processor line."

    # 1. Filing containing ONLY the edge's own initial quote -> re-finding it is circular -> unresolved
    single_passage_filing = _sample_filing(
        cik="0009990001",
        accession="0009990001-25-000101",
        text=f"ITEM 1. BUSINESS\n{quote}\nThe Company operates globally across several regions.\n",
    )
    edge = _make_edge(
        edge_id="e_circular",
        source_key=comp.company_key,
        source_name=comp.company_name,
        target_name="ZZFAB",
        target_key="CIK:0009990009",
        quote=quote,
        interp_status="flagged",
        interp_flags=["judge_unclear"],
    )
    res_circular = ResearchLoop(
        client=FakeGeminiClient(),
        filings_by_key={comp.company_key: single_passage_filing},
    ).research_company(comp, single_passage_filing, [edge], depth="light")
    assert len(res_circular.findings) == 1
    assert res_circular.findings[0].outcome == "unresolved"
    assert res_circular.findings[0].confirmed_edge_ids == []

    # 2. Counterparty filing in search_filings corroborates the edge even when own filing has only the 1 quote
    counterparty_filing = _sample_filing(
        cik="0009990009",
        accession="0009990009-25-000001",
        text=(
            "ITEM 1. BUSINESS\n"
            "ZZFAB provides dedicated wafer foundry services to ZZ Alpha Corp under long-term agreements.\n"
        ),
    )
    res_cross_filing = ResearchLoop(
        client=FakeGeminiClient(),
        filings_by_key={
            comp.company_key: single_passage_filing,
            "CIK:0009990009": counterparty_filing,
        },
    ).research_company(comp, single_passage_filing, [edge], depth="thorough")
    assert len(res_cross_filing.findings) == 1
    assert res_cross_filing.findings[0].outcome == "confirmed"
    assert res_cross_filing.findings[0].confirmed_edge_ids == ["e_circular"]
    assert any(s.action == "search_filings" for s in res_cross_filing.findings[0].steps)


def test_fix1_enforces_minimum_tool_calls_and_thorough_search_filings() -> None:
    analysis, _ = _sample_analysis_and_result()
    comp = analysis.exposures[0]
    filing = _sample_filing(cik="0009990001", accession="0009990001-25-000102")
    edge = _make_edge(
        edge_id="e_early",
        source_key=comp.company_key,
        source_name=comp.company_name,
        target_name="ZZFAB",
        interp_status="flagged",
        interp_flags=["judge_unclear"],
    )

    class AlwaysEarlyConcludeClient(FakeGeminiClient):
        def generate_json(self, prompt, schema, **kwargs):
            if "verdicts" in schema.get("properties", {}):
                return super().generate_json(prompt, schema, **kwargs)
            return {
                "action": "conclude",
                "query": "ZZFAB",
                "outcome": "confirmed",
                "explanation": 'Corroborated "Any disruption at ZZFAB or ZZSUP facilities could materially delay shipments of our core products."',
                "candidate_edges": [],
            }, self.extractor_model

    # Light mode enforces >= 2 tool calls before conclude (so 3 steps total)
    res_light = ResearchLoop(
        client=AlwaysEarlyConcludeClient(),
        filings_by_key={comp.company_key: filing},
    ).research_company(comp, filing, [edge], depth="light")
    f_light = res_light.findings[0]
    tool_steps_light = [s for s in f_light.steps if s.action != "conclude"]
    assert len(tool_steps_light) >= 2
    assert f_light.steps[-1].action == "conclude"

    # Thorough mode enforces >= 3 tool calls including >= 1 search_filings before conclude (4 steps total)
    res_thorough = ResearchLoop(
        client=AlwaysEarlyConcludeClient(),
        filings_by_key={comp.company_key: filing},
    ).research_company(comp, filing, [edge], depth="thorough")
    f_thorough = res_thorough.findings[0]
    tool_steps_thorough = [s for s in f_thorough.steps if s.action != "conclude"]
    assert len(tool_steps_thorough) >= 3
    assert any(s.action == "search_filings" for s in tool_steps_thorough)
    assert f_thorough.steps[-1].action == "conclude"


def test_fix2_thorough_preserves_light_findings_and_edges(tmp_path) -> None:
    from hoc.core.cache import DiskCache

    analysis, _ = _sample_analysis_and_result()
    comp = analysis.exposures[0]
    new_quote = "We depend on ZZPACK as our sole provider of advanced substrate packaging."
    filing = _sample_filing(
        cik="0009990001",
        accession="0009990001-25-000103",
        text=(
            "ITEM 1. BUSINESS\n"
            "We rely exclusively on ZZFAB for advanced wafer fabrication of our core processor line.\n"
            f"{new_quote}\n"
            "Sales to Customer A accounted for 18% of our revenue in fiscal 2025.\n"
            "ITEM 1A. RISK FACTORS\n"
            "Any disruption at ZZFAB or ZZPACK facilities could materially delay shipments of our core products.\n"
        ),
    )
    e_flag = _make_edge(
        edge_id="e_flag_keep",
        source_key=comp.company_key,
        source_name=comp.company_name,
        target_name="ZZFAB",
        interp_status="flagged",
        interp_flags=["judge_unclear"],
    )
    e_undisc = _make_edge(
        edge_id="e_undisc_keep",
        source_key=comp.company_key,
        source_name=comp.company_name,
        target_name="Unnamed customer (Customer A)",
        target_key=None,
        target_kind="unnamed_customer",
        edge_type="customer",
        sole_source=False,
        quote="Sales to Customer A accounted for 18% of our revenue in fiscal 2025.",
    )
    e_single = _make_edge(
        edge_id="e_single_extra",
        source_key=comp.company_key,
        source_name=comp.company_name,
        target_name="ZZFAB",
        sole_source=True,
    )

    class LightFindsNewEdgeButThoroughMissesItClient(FakeGeminiClient):
        def __init__(self) -> None:
            super().__init__()
            self.mode = "light"

        def generate_json(self, prompt, schema, **kwargs):
            if "verdicts" in schema.get("properties", {}):
                return super().generate_json(prompt, schema, **kwargs)
            resp, model = super().generate_json(prompt, schema, **kwargs)
            if self.mode == "light" and resp.get("action") == "conclude" and "undisclosed_customer" in prompt:
                return {
                    "action": "conclude",
                    "query": "ZZPACK",
                    "outcome": "new_evidence",
                    "explanation": f'Discovered substrate supplier "{new_quote}".',
                    "candidate_edges": [
                        {
                            "target_name": "ZZPACK",
                            "target_kind": "company",
                            "edge_type": "supplier",
                            "sole_source": True,
                            "qualifier": "sole substrate packaging provider",
                            "evidence_quote": new_quote,
                            "section": "Item 1",
                        }
                    ],
                }, model
            return resp, model

    disk = DiskCache(tmp_path)
    client = LightFindsNewEdgeButThoroughMissesItClient()
    runner = ResearchLoop(
        client=client,
        disk_cache=disk,
        filings_by_key={comp.company_key: filing},
    )
    light_res = runner.research_company(comp, filing, [e_flag, e_undisc, e_single], depth="light")
    light_edge_ids = {e.edge_id for e in light_res.edges}
    assert any(e.target_name == "ZZPACK" for e in light_res.edges)

    client.mode = "thorough"
    thorough_res = runner.research_company(comp, filing, [e_flag, e_undisc, e_single], depth="thorough")
    thorough_edge_ids = {e.edge_id for e in thorough_res.edges}
    expected_subset = light_edge_ids - set(thorough_res.rejected_edge_ids)
    assert expected_subset.issubset(thorough_edge_ids)
    assert any(e.target_name == "ZZPACK" for e in thorough_res.edges)
    assert len(thorough_res.findings) >= len(light_res.findings)


def test_fix14_skips_duplicate_unnamed_customers_and_plural_customer_groups() -> None:
    analysis, _ = _sample_analysis_and_result()
    comp = analysis.exposures[0]
    quote_anon = "Sales to our largest customer accounted for 14% of total revenue in fiscal 2025."
    quote_group = "Our three largest customers outside of the United States accounted for 29% of revenue."
    quote_group_2 = "Sales through five distributors represented 21% of consolidated net revenue."
    filing = _sample_filing(
        cik="0009990001",
        accession="0009990001-25-000104",
        text=(
            "ITEM 1. BUSINESS\n"
            f"{quote_anon}\n"
            f"{quote_group}\n"
            f"{quote_group_2}\n"
            "ITEM 1A. RISK FACTORS\n"
            "Loss of our largest customer could materially reduce revenue.\n"
        ),
    )
    existing_unnamed = _make_edge(
        edge_id="e_unnamed_existing",
        source_key=comp.company_key,
        source_name=comp.company_name,
        target_name="Unnamed customer (largest customer)",
        target_key=None,
        target_kind="unnamed_customer",
        edge_type="customer",
        sole_source=False,
        quote=quote_anon,
    )

    class DuplicateAndGroupCustomerClient(FakeGeminiClient):
        def generate_json(self, prompt, schema, **kwargs):
            if "verdicts" in schema.get("properties", {}):
                return super().generate_json(prompt, schema, **kwargs)
            resp, model = super().generate_json(prompt, schema, **kwargs)
            if resp.get("action") == "conclude":
                return {
                    "action": "conclude",
                    "query": "largest customer",
                    "outcome": "new_evidence",
                    "explanation": f'Found "{quote_anon}" and "{quote_group}".',
                    "candidate_edges": [
                        {
                            "target_name": "Unnamed customer (our largest customer)",
                            "target_kind": "unnamed_customer",
                            "edge_type": "customer",
                            "sole_source": False,
                            "qualifier": "14% of total revenue",
                            "evidence_quote": quote_anon,
                            "section": "Item 1",
                        },
                        {
                            "target_name": "Three largest customers outside of the United States",
                            "target_kind": "unnamed_customer",
                            "edge_type": "customer",
                            "sole_source": False,
                            "qualifier": "29% of revenue",
                            "evidence_quote": quote_group,
                            "section": "Item 1",
                        },
                        {
                            "target_name": "five distributors",
                            "target_kind": "company",
                            "edge_type": "customer",
                            "sole_source": False,
                            "qualifier": "21% of consolidated net revenue",
                            "evidence_quote": quote_group_2,
                            "section": "Item 1",
                        },
                    ],
                }, model
            return resp, model

    res = ResearchLoop(
        client=DuplicateAndGroupCustomerClient(),
        filings_by_key={comp.company_key: filing},
    ).research_company(comp, filing, [existing_unnamed], depth="light")

    # Neither the duplicate unnamed customer on the same quote nor the plural customer groups may be added
    assert [e.edge_id for e in res.edges] == ["e_unnamed_existing"]
    assert all(f.new_edges == [] for f in res.findings)


def test_fix22_budgets_and_budget_stops_labelled_not_finished_in_time(tmp_path) -> None:
    import time as _time

    from hoc.core.cache import DiskCache
    from hoc.research.loop import (
        DEFAULT_ITEM_TIMEOUT_SECONDS,
        RESEARCH_DEPTH_TIMEOUT_SECONDS,
    )

    assert DEFAULT_ITEM_TIMEOUT_SECONDS == 40.0
    assert RESEARCH_DEPTH_TIMEOUT_SECONDS == {"none": 0.0, "light": 40.0, "thorough": 85.0}

    analysis, _ = _sample_analysis_and_result()
    comp = analysis.exposures[0]
    filing = _sample_filing(cik="0009990001", accession="0009990001-25-000221")
    e_single = _make_edge(
        edge_id="e_budget_1",
        source_key=comp.company_key,
        source_name=comp.company_name,
        target_name="ZZFAB",
        sole_source=True,
    )
    e_flag = _make_edge(
        edge_id="e_budget_2",
        source_key=comp.company_key,
        source_name=comp.company_name,
        target_name="ZZSUP",
        quote="We depend on ZZSUP for specialized substrate packaging.",
        interp_status="flagged",
        interp_flags=["judge_unclear"],
    )

    class SlowStepClient(FakeGeminiClient):
        def generate_json(self, prompt, schema, **kwargs):
            if "verdicts" in schema.get("properties", {}):
                return super().generate_json(prompt, schema, **kwargs)
            _time.sleep(0.08)
            return super().generate_json(prompt, schema, **kwargs)

    disk = DiskCache(tmp_path)
    # Tight budget so the step times out during investigation
    timed_out_runner = ResearchLoop(
        client=SlowStepClient(),
        disk_cache=disk,
        filings_by_key={comp.company_key: filing},
        call_timeout_s=0.01,
        item_timeout_s=0.02,
        total_timeout_s=0.02,
    )
    res_timeout = timed_out_runner.research_company(comp, filing, [e_single, e_flag], depth="light")
    assert len(res_timeout.findings) == 2
    for finding in res_timeout.findings:
        assert finding.outcome == "unresolved"
        assert finding.explanation.startswith("Not finished in time:")
        assert finding.steps[-1].summary.startswith("Not finished in time:")

    # Re-running with normal budget and cache_only=False re-investigates budget-stopped findings
    normal_runner = ResearchLoop(
        client=FakeGeminiClient(),
        disk_cache=disk,
        filings_by_key={comp.company_key: filing},
    )
    res_recovered = normal_runner.research_company(comp, filing, [e_single, e_flag], depth="light")
    assert all(not f.explanation.startswith("Not finished in time:") for f in res_recovered.findings)


def test_fix22_explanation_outcome_consistency_for_hypothetical_flagged_edge(tmp_path) -> None:
    from hoc.core.cache import DiskCache

    analysis, _ = _sample_analysis_and_result()
    comp = analysis.exposures[0]
    hypo_quote = (
        "We are finalizing an investment and partnership agreement with OpenAI. "
        "There is no assurance that we will enter into an investment and partnership agreement "
        "with OpenAI or that a transaction will be completed."
    )
    second_openai_quote = (
        "Our cloud service customers and AI model developers such as OpenAI deploy our accelerated computing platforms."
    )
    filing = _sample_filing(
        cik="0001045810",
        accession="0001045810-26-000024",
        text=(
            "ITEM 1. BUSINESS\n"
            f"{second_openai_quote}\n"
            "ITEM 1A. RISK FACTORS\n"
            f"{hypo_quote}\n"
        ),
    )
    edge_jv = _make_edge(
        edge_id="e_nvda_openai_jv",
        source_key=comp.company_key,
        source_name="Nvidia",
        target_name="OpenAI",
        target_key="ALIAS:OPENAI",
        edge_type="jv_partner",
        sole_source=False,
        quote=hypo_quote,
        interp_status="flagged",
        interp_flags=["hypothetical"],
    )

    class ContradictoryRejectionProseClient(FakeGeminiClient):
        def generate_json(self, prompt, schema, **kwargs):
            # V-INT keeps the edge flagged as hypothetical (not rejected, not confirmed)
            props = schema.get("properties", {})
            if "verdicts" in props:
                return {
                    "verdicts": [
                        {
                            "index": 0,
                            "status": "flagged",
                            "flags": ["hypothetical"],
                            "rationale": "The partnership agreement is still being finalized with no assurance of completion.",
                        }
                    ]
                }, self.extractor_model
            if "flags" in props and "status" in props:
                return {
                    "status": "flagged",
                    "flags": ["hypothetical"],
                    "rationale": "The partnership agreement is still being finalized with no assurance of completion.",
                }, self.extractor_model
            resp, model = super().generate_json(prompt, schema, **kwargs)
            if resp.get("action") == "conclude":
                return {
                    "action": "conclude",
                    "query": "OpenAI",
                    "outcome": "rejected",
                    "explanation": (
                        f'The jv_partner edge to OpenAI is rejected. The filing states: "{hypo_quote}" '
                        "This does not establish an active joint venture and should not be recorded."
                    ),
                    "candidate_edges": [],
                }, model
            return resp, model

    disk = DiskCache(tmp_path)
    runner = ResearchLoop(
        client=ContradictoryRejectionProseClient(),
        disk_cache=disk,
        filings_by_key={comp.company_key: filing},
    )
    res = runner.research_company(comp, filing, [edge_jv], depth="light")
    assert len(res.findings) == 1
    finding = res.findings[0]
    assert finding.outcome == "unresolved"
    assert finding.rejected_edge_ids == []
    assert "is rejected" not in finding.explanation.lower()
    assert "does not establish" not in finding.explanation.lower()
    assert "should not be recorded" not in finding.explanation.lower()
    assert "unresolved" in finding.explanation.lower() or "prospective" in finding.explanation.lower()


