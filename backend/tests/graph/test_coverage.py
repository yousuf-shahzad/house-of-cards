"""Tests for v3 package C-COV: deterministic dependency coverage report (backend/hoc/graph/coverage.py)."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime

import pytest

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
from hoc.contract.dependencies import CompanyRunStatus, FilingRef, VerifiedEdge
from hoc.contract.units import Sector
from hoc.graph import compute_coverage_report


def _make_filing(company_key: str, filed: date = date(2026, 2, 15)) -> FilingRef:
    return FilingRef(
        company_key=company_key,
        form="10-K",
        accession=f"{company_key.split(':')[-1]}-26-000001",
        filed=filed,
        url=f"https://www.sec.gov/Archives/edgar/data/{company_key}/10k.htm",
    )


def _make_exposure(
    rank: int,
    company_key: str,
    company_name: str,
    exposure: float,
    contributions: list[tuple[str, float, float]],
) -> CompanyExposure:
    sym = f"SYM{rank}"
    return CompanyExposure(
        rank=rank,
        company_key=company_key,
        company_name=company_name,
        identity_status="resolved",
        symbols=[sym],
        sector=Sector.information_technology,
        country="US",
        exposure=exposure,
        etf_count=len(contributions),
        contributions=[
            Contribution(
                etf_ticker=ticker,
                weight_in_etf=w_in_etf,
                contribution=contrib,
                security_keys=[f"SEC:{sym}"],
            )
            for ticker, w_in_etf, contrib in contributions
        ],
        securities=[
            SecurityExposure(
                security_key=f"SEC:{sym}",
                security_id=sym,
                security_id_type="symbol",
                symbol=sym,
                name=company_name,
                exposure=exposure,
            )
        ],
    )


def test_coverage_buckets_sum_to_one_and_match_synthetic_fixture_invariants() -> None:
    """5 mutually-exclusive buckets sum to 1.0 within ±1e-6; by_etf, largest_unanalysed, and gaps populate."""
    exposures = [
        _make_exposure(
            1, "CIK:9990000001", "ZZ Alpha Corp", 0.22, [("AAA", 0.25, 0.10), ("BBB", 0.20, 0.12)]
        ),
        _make_exposure(
            2, "CIK:9990000002", "ZZ Beta Holdings", 0.19, [("AAA", 0.20, 0.08), ("BBB", 0.1833333333, 0.11)]
        ),
        _make_exposure(
            3, "CIK:9990000003", "ZZ Gamma Inc", 0.17, [("AAA", 0.175, 0.07), ("BBB", 0.1666666667, 0.10)]
        ),
        _make_exposure(
            4, "CIK:9990000004", "ZZ Delta Ltd", 0.14, [("AAA", 0.20, 0.08), ("BBB", 0.10, 0.06)]
        ),
        _make_exposure(
            5, "ISIN:TW0009999995", "ZZ Eta Foreign Holdings", 0.10, [("BBB", 0.1666666667, 0.10)]
        ),
        _make_exposure(
            6, "CIK:9990000006", "ZZ Zeta Systems", 0.10, [("AAA", 0.175, 0.07), ("BBB", 0.05, 0.03)]
        ),
        _make_exposure(
            7, "CIK:9990000007", "ZZ Theta Devices", 0.08, [("BBB", 0.1333333333, 0.08)]
        ),
    ]
    req = PortfolioRequest(
        holdings=[
            PortfolioItem(ticker="AAA", allocation=0.40),
            PortfolioItem(ticker="BBB", allocation=0.60),
        ]
    )
    analysis = AnalysisResponse(
        generated_at=datetime(2026, 11, 8, 0, 0, tzinfo=UTC),
        as_of_date=date(2026, 11, 8),
        request=req,
        etfs=[
            EtfReport(ticker="AAA", name="Synthetic Core ETF", allocation=0.40, status="ok"),
            EtfReport(ticker="BBB", name="Synthetic Tech ETF", allocation=0.60, status="ok"),
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
        overlap=Overlap(etfs=["AAA", "BBB"], matrix=[[1.0, 0.5], [0.5, 1.0]], pairs=[]),
        concentration=Concentration(
            top5=0.82,
            top10=1.0,
            top20=1.0,
            hhi=0.16,
            effective_companies=6.25,
            distinct_securities=7,
            distinct_companies=7,
        ),
        sectors=[],
        gaps=[],
        warnings=[],
        attributions=[],
    )

    companies = [
        CompanyRunStatus(
            company_key="CIK:9990000001",
            company_name="ZZ Alpha Corp",
            exposure=0.22,
            status="done",
            filing=_make_filing("CIK:9990000001"),
            verified_edges=2,
        ),
        CompanyRunStatus(
            company_key="CIK:9990000002",
            company_name="ZZ Beta Holdings",
            exposure=0.19,
            status="done",
            filing=_make_filing("CIK:9990000002"),
            verified_edges=2,
        ),
        CompanyRunStatus(
            company_key="CIK:9990000003",
            company_name="ZZ Gamma Inc",
            exposure=0.17,
            status="cached",
            filing=_make_filing("CIK:9990000003"),
            verified_edges=1,
        ),
        CompanyRunStatus(
            company_key="CIK:9990000004",
            company_name="ZZ Delta Ltd",
            exposure=0.14,
            status="done",
            filing=_make_filing("CIK:9990000004"),
            verified_edges=0,
        ),
        CompanyRunStatus(
            company_key="ISIN:TW0009999995",
            company_name="ZZ Eta Foreign Holdings",
            exposure=0.10,
            status="no_sec_filing",
            filing=None,
            verified_edges=0,
        ),
    ]

    edges = [
        VerifiedEdge(
            edge_id="e-syn-0001",
            source_company_key="CIK:9990000001",
            source_company_name="ZZ Alpha Corp",
            source_in_portfolio=True,
            edge_type="foundry",
            target_name="ZZ Epsilon Foundry",
            target_kind="company",
            target_key="ALIAS:ZZEPSILON",
            target_in_portfolio=False,
            sole_source=True,
            evidence_quote="We rely on ZZ Epsilon Foundry as the sole foundry.",
            section="Item 1A",
            filing=_make_filing("CIK:9990000001"),
        ),
        VerifiedEdge(
            edge_id="e-syn-0002",
            source_company_key="CIK:9990000002",
            source_company_name="ZZ Beta Holdings",
            source_in_portfolio=True,
            edge_type="foundry",
            target_name="ZZ Epsilon Foundry",
            target_kind="company",
            target_key="ALIAS:ZZEPSILON",
            target_in_portfolio=False,
            sole_source=False,
            evidence_quote="ZZ Epsilon Foundry manufactures our custom chips.",
            section="Item 1",
            filing=_make_filing("CIK:9990000002"),
        ),
        VerifiedEdge(
            edge_id="e-syn-0005",
            source_company_key="CIK:9990000002",
            source_company_name="ZZ Beta Holdings",
            source_in_portfolio=True,
            edge_type="customer",
            target_name="Unnamed Cloud Customer A",
            target_kind="unnamed_customer",
            target_key=None,
            target_in_portfolio=False,
            sole_source=False,
            qualifier="14% of revenue",
            evidence_quote="One customer accounted for 14% of our total revenue.",
            section="Item 1",
            filing=_make_filing("CIK:9990000002"),
        ),
        VerifiedEdge(
            edge_id="e-syn-0004",
            source_company_key="CIK:9990000003",
            source_company_name="ZZ Gamma Inc",
            source_in_portfolio=True,
            edge_type="facility",
            target_name="Taiwan",
            target_kind="country",
            target_key=None,
            target_in_portfolio=False,
            sole_source=False,
            evidence_quote="Final assembly is in Taiwan.",
            section="Item 2",
            filing=_make_filing("CIK:9990000003"),
        ),
    ]

    report = compute_coverage_report(analysis, companies, edges)

    # 1. Buckets sum to 1.0 within ±1e-6 and have distinct kinds
    assert abs(math.fsum(b.weight for b in report.buckets) - 1.0) <= 1e-6
    assert len({b.kind for b in report.buckets}) == 5
    by_kind = {b.kind: b for b in report.buckets}
    assert by_kind["verified"].weight == pytest.approx(0.58)
    assert by_kind["verified"].companies == 3
    assert by_kind["no_disclosures"].weight == pytest.approx(0.14)
    assert by_kind["no_disclosures"].companies == 1
    assert by_kind["no_sec_filing"].weight == pytest.approx(0.10)
    assert by_kind["no_sec_filing"].companies == 1
    assert by_kind["not_analysed"].weight == pytest.approx(0.0)
    assert by_kind["not_analysed"].companies == 0
    assert by_kind["outside_top_n"].weight == pytest.approx(0.18)
    assert by_kind["outside_top_n"].companies == 2

    # 2. by_etf verified_weight in [0, 1] matching AAA=0.625 (0.25/0.40) and BBB=0.55 (0.33/0.60)
    etf_map = {e.ticker: e.verified_weight for e in report.by_etf}
    assert etf_map["AAA"] == pytest.approx(0.625)
    assert etf_map["BBB"] == pytest.approx(0.55)

    # 3. largest_unanalysed contains the 2 outside_top_n holdings sorted by exposure desc
    assert len(report.largest_unanalysed) == 2
    assert report.largest_unanalysed[0].company_key == "CIK:9990000006"
    assert report.largest_unanalysed[0].exposure == pytest.approx(0.10)
    assert report.largest_unanalysed[1].company_key == "CIK:9990000007"
    assert report.largest_unanalysed[1].exposure == pytest.approx(0.08)

    # 4. gaps use exact plural CoverageGapKind literals
    gap_by_kind = {g.kind: g for g in report.gaps}
    assert "outside_top_n" in gap_by_kind
    assert gap_by_kind["outside_top_n"].weight == pytest.approx(0.18)
    assert "raise the number analysed to 30 to cover more" in gap_by_kind["outside_top_n"].message
    assert "unnamed_customers" in gap_by_kind
    assert gap_by_kind["unnamed_customers"].weight == pytest.approx(0.19)
    assert "non_sec_counterparties" in gap_by_kind
    assert gap_by_kind["non_sec_counterparties"].weight == pytest.approx(0.41)


def test_coverage_gaps_for_old_filings_and_region_only_facilities_and_top10_cap() -> None:
    """Verify old_filings (>15 months), region_only_facilities, not_analysed bucket, and <=10 unanalysed cap."""
    # 1 top-N company with an old filing + region-only facility, 1 skipped_budget, and 12 unanalysed holdings
    exposures = [
        _make_exposure(1, "CIK:9990000001", "ZZ Alpha Corp", 0.30, [("AAA", 0.30, 0.30)]),
        _make_exposure(2, "CIK:9990000002", "ZZ Beta Holdings", 0.10, [("AAA", 0.10, 0.10)]),
    ] + [
        _make_exposure(i + 3, f"CIK:99900000{i + 10:02d}", f"ZZ Tail Co {i + 1}", 0.05, [("AAA", 0.05, 0.05)])
        for i in range(12)
    ]

    old_filing = _make_filing("CIK:9990000001", filed=date(2025, 1, 10))
    companies = [
        CompanyRunStatus(
            company_key="CIK:9990000001",
            company_name="ZZ Alpha Corp",
            exposure=0.30,
            status="done",
            filing=old_filing,
            verified_edges=1,
        ),
        CompanyRunStatus(
            company_key="CIK:9990000002",
            company_name="ZZ Beta Holdings",
            exposure=0.10,
            status="missing_api_key",
            filing=None,
            verified_edges=0,
        ),
    ]
    edges = [
        VerifiedEdge(
            edge_id="e-region-asia",
            source_company_key="CIK:9990000001",
            source_company_name="ZZ Alpha Corp",
            source_in_portfolio=True,
            edge_type="facility",
            target_name="Asia",
            target_kind="region",
            target_key=None,
            qualifier="regional contract manufacturing",
            evidence_quote="We use regional contract manufacturers across Asia.",
            section="Item 1",
            filing=old_filing,
        )
    ]

    report = compute_coverage_report(
        exposures,
        companies,
        edges,
        as_of_date=date(2026, 11, 8),
    )

    assert abs(math.fsum(b.weight for b in report.buckets) - 1.0) <= 1e-6
    by_kind = {b.kind: b for b in report.buckets}
    assert by_kind["verified"].weight == pytest.approx(0.30)
    assert by_kind["not_analysed"].weight == pytest.approx(0.10)
    assert by_kind["outside_top_n"].weight == pytest.approx(0.60)
    assert by_kind["outside_top_n"].companies == 12

    # largest_unanalysed is capped at 10
    assert len(report.largest_unanalysed) == 10

    gap_by_kind = {g.kind: g for g in report.gaps}
    assert "old_filings" in gap_by_kind
    assert gap_by_kind["old_filings"].weight == pytest.approx(0.30)
    assert "region_only_facilities" in gap_by_kind
    assert gap_by_kind["region_only_facilities"].weight == pytest.approx(0.30)
