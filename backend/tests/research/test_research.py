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
    scores = [item.priority_score for item in items]
    assert scores == sorted(scores, reverse=True)


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
