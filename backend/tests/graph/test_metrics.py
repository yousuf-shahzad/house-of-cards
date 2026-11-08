"""Tests for deterministic dependency graph metrics (backend/hoc/graph/metrics.py)."""

from __future__ import annotations

from datetime import date

import pytest

from hoc.contract.api import CompanyExposure, Contribution, SecurityExposure
from hoc.contract.dependencies import FilingRef, VerifiedEdge
from hoc.contract.units import Sector
from hoc.graph.metrics import (
    canonical_country_info,
    compute_dependency_metrics,
    compute_dependency_summary,
    format_metric_value,
)


def _make_company(
    rank: int,
    company_key: str,
    company_name: str,
    exposure: float,
    symbol: str,
    etfs: list[tuple[str, float]],
) -> CompanyExposure:
    return CompanyExposure(
        rank=rank,
        company_key=company_key,
        company_name=company_name,
        identity_status="resolved",
        symbols=[symbol],
        sector=Sector.information_technology,
        country="US",
        exposure=exposure,
        etf_count=len(etfs),
        contributions=[
            Contribution(
                etf_ticker=ticker,
                weight_in_etf=contrib * 2,
                contribution=contrib,
                security_keys=[f"SEC:{symbol}"],
            )
            for ticker, contrib in etfs
        ],
        securities=[
            SecurityExposure(
                security_key=f"SEC:{symbol}",
                security_id=symbol,
                security_id_type="symbol",
                symbol=symbol,
                name=company_name,
                exposure=exposure,
            )
        ],
    )


def _make_filing(company_key: str, form: str = "10-K") -> FilingRef:
    return FilingRef(
        company_key=company_key,
        form=form,  # type: ignore[arg-type]
        accession=f"{company_key.split(':')[-1]}-26-000001",
        filed=date(2026, 10, 30),
        url=f"https://www.sec.gov/Archives/edgar/data/{company_key}/10k.htm",
    )


def test_union_by_dependent_company_and_target_prevents_double_counting() -> None:
    """Multiple edges from ZZ Alpha (34%) to ZZ Epsilon must count ZZ Alpha's 34% only once."""
    exposures = [
        _make_company(
            1,
            "CIK:9990000001",
            "ZZ Alpha Corp",
            0.34,
            "ZZALP",
            [("ZZAAA", 0.24), ("ZZBBB", 0.10)],
        ),
        _make_company(
            2,
            "CIK:9990000002",
            "ZZ Beta Holdings",
            0.24,
            "ZZBET",
            [("ZZAAA", 0.14), ("ZZBBB", 0.10)],
        ),
        _make_company(
            3,
            "ALIAS:ZZEPSILON",
            "ZZ Epsilon Semiconductor",
            0.088,
            "ZZEPS",
            [("ZZBBB", 0.088)],
        ),
    ]

    edges = [
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
            filing=_make_filing("CIK:9990000001"),
        ),
        # Second edge from the SAME company (ZZ Alpha) to the SAME supplier (ZZ Epsilon)
        VerifiedEdge(
            edge_id="e-alp-cm-eps",
            source_company_key="CIK:9990000001",
            source_company_name="ZZ Alpha Corp",
            source_in_portfolio=True,
            edge_type="contract_manufacturer",
            target_name="ZZ Epsilon Semiconductor",
            target_kind="company",
            target_key="ALIAS:ZZEPSILON",
            target_in_portfolio=True,
            sole_source=False,
            evidence_quote="ZZ Epsilon Semiconductor also provides advanced wafer packaging.",
            section="Item 1",
            filing=_make_filing("CIK:9990000001"),
        ),
        # Edge from ZZ Beta (24%) to ZZ Epsilon
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
            filing=_make_filing("CIK:9990000002"),
        ),
    ]

    summary = compute_dependency_summary(exposures, edges)

    # Combined dependent weight must be 0.34 + 0.24 == 0.58 (NOT 0.34*2 + 0.24 = 0.92)
    dep_metric = summary.metrics_by_id["dep.ALIAS:ZZEPSILON"]
    assert dep_metric.value == pytest.approx(0.58)
    assert dep_metric.unit == "fraction"
    assert dep_metric.subject_key == "ALIAS:ZZEPSILON"
    assert dep_metric.supporting_edge_ids == [
        "e-alp-cm-eps",
        "e-alp-foundry-eps",
        "e-bet-foundry-eps",
    ]
    assert format_metric_value(dep_metric) == "58.00%"

    comp_metric = summary.metrics_by_id["dep.ALIAS:ZZEPSILON.companies"]
    assert comp_metric.value == 2.0
    assert comp_metric.unit == "count"
    assert format_metric_value(comp_metric) == "2"

    # Single point of failure detected (shared by 2 companies AND sole_source)
    assert summary.metrics_by_id["spof.count"].value == 1.0
    assert summary.metrics_by_id["spof.ALIAS:ZZEPSILON"].value == pytest.approx(0.58)


def test_facility_country_concentration_deduplicates_multiple_sites_per_company() -> None:
    """A company listing multiple fabs in Taiwan (Hsinchu + Tainan) is counted once in facility.TW."""
    exposures = [
        _make_company(1, "CIK:9990000001", "ZZ Alpha Corp", 0.34, "ZZALP", [("ZZAAA", 0.34)]),
        _make_company(2, "CIK:9990000002", "ZZ Beta Holdings", 0.24, "ZZBET", [("ZZBBB", 0.24)]),
    ]
    edges = [
        VerifiedEdge(
            edge_id="e-alp-tw-1",
            source_company_key="CIK:9990000001",
            source_company_name="ZZ Alpha Corp",
            source_in_portfolio=True,
            edge_type="facility",
            target_name="Taiwan",
            target_kind="country",
            target_key=None,
            evidence_quote="Final assembly is performed in Taiwan.",
            section="Item 1",
            filing=_make_filing("CIK:9990000001"),
        ),
        VerifiedEdge(
            edge_id="e-alp-tw-2",
            source_company_key="CIK:9990000001",
            source_company_name="ZZ Alpha Corp",
            source_in_portfolio=True,
            edge_type="facility",
            target_name="Hsinchu, Taiwan",
            target_kind="facility",
            target_key=None,
            evidence_quote="Our primary testing facility is in Hsinchu, Taiwan.",
            section="Item 2",
            filing=_make_filing("CIK:9990000001"),
        ),
        VerifiedEdge(
            edge_id="e-bet-us-1",
            source_company_key="CIK:9990000002",
            source_company_name="ZZ Beta Holdings",
            source_in_portfolio=True,
            edge_type="facility",
            target_name="Arizona, United States",
            target_kind="facility",
            target_key=None,
            evidence_quote="We operate a wafer facility in Arizona, United States.",
            section="Item 2",
            filing=_make_filing("CIK:9990000002"),
        ),
    ]

    metrics = {m.metric_id: m for m in compute_dependency_metrics(exposures, edges)}
    assert metrics["facility.TW"].value == pytest.approx(0.34)
    assert metrics["facility.TW"].supporting_edge_ids == ["e-alp-tw-1", "e-alp-tw-2"]
    assert metrics["facility.TW.companies"].value == 1.0
    assert metrics["facility.US"].value == pytest.approx(0.24)
    assert canonical_country_info("Kumamoto, Japan") == ("JP", "Japan")
    assert canonical_country_info("Dresden, Germany") == ("DE", "Germany")


def test_reverse_link_customer_edge_maps_to_supplier_dependency() -> None:
    """When supplier S files a customer edge naming portfolio company A, A depends on S."""
    exposures = [
        _make_company(1, "CIK:9990000001", "ZZ Alpha Corp", 0.34, "ZZALP", [("ZZAAA", 0.34)]),
    ]
    edges = [
        VerifiedEdge(
            edge_id="e-rev-1",
            source_company_key="CIK:8880000009",
            source_company_name="ZZ Optics Supplier",
            source_in_portfolio=False,
            edge_type="customer",
            target_name="ZZ Alpha Corp",
            target_kind="company",
            target_key="CIK:9990000001",
            target_in_portfolio=True,
            sole_source=True,
            evidence_quote="ZZ Alpha Corp is our largest customer for lithography optics.",
            section="Item 1",
            filing=_make_filing("CIK:8880000009"),
        ),
    ]

    summary = compute_dependency_summary(exposures, edges)
    assert "dep.CIK:8880000009" in summary.metrics_by_id
    assert summary.metrics_by_id["dep.CIK:8880000009"].value == pytest.approx(0.34)
    assert summary.metrics_by_id["spof.CIK:8880000009"].value == pytest.approx(0.34)


def test_facility_country_resolution_and_unplaced_count() -> None:
    """Named sites, states/provinces, cities, dotted aliases, and single-country quotes resolve to ISO-2;
    multi-country quotes and macro-regions stay unplaced in facility.unplaced.count, never facility.<NAME>.
    """
    # 1. Examples from live SEC filings (#6715782618)
    assert canonical_country_info(
        "Fab 22",
        qualifier="located in Kaohsiung Nanzih Technology Industrial Park",
    ) == ("TW", "Taiwan")
    assert canonical_country_info("Nanjing", qualifier="one fab") == ("CN", "China")
    assert canonical_country_info("Shanghai", qualifier="one fab") == ("CN", "China")
    assert canonical_country_info("Gigafactory Shanghai") == ("CN", "China")
    assert canonical_country_info("Gigafactory Nevada") == ("US", "United States")
    assert canonical_country_info("Boise, Idaho fab") == ("US", "United States")
    assert canonical_country_info("Manassas, Virginia fab") == ("US", "United States")
    assert canonical_country_info("Clay, New York") == ("US", "United States")
    assert canonical_country_info("Hiroshima manufacturing facility") == ("JP", "Japan")
    assert canonical_country_info("Gujarat assembly and test facility") == ("IN", "India")
    assert canonical_country_info("Seattle, Washington area") == ("US", "United States")
    assert canonical_country_info("Fort Collins, Colorado") == ("US", "United States")
    assert canonical_country_info("Breinigsville, Pennsylvania") == ("US", "United States")
    assert canonical_country_info("Silicon Valley") == ("US", "United States")
    assert canonical_country_info("San Jose, CA") == ("US", "United States")
    assert canonical_country_info("Vernon Hills, IL") == ("US", "United States")

    # 2. Dotted abbreviations & additional ISO countries
    assert canonical_country_info("Kaohsiung, R.O.C.") == ("TW", "Taiwan")
    assert canonical_country_info("London, U.K.") == ("GB", "United Kingdom")
    assert canonical_country_info("U.S.") == ("US", "United States")
    assert canonical_country_info("Shenzhen, P.R.C.") == ("CN", "China")
    assert canonical_country_info("Belfast, Northern Ireland") == ("GB", "United Kingdom")
    assert canonical_country_info("Laval, Quebec, Canada") == ("CA", "Canada")
    assert canonical_country_info("Guadalajara and Tonala, Mexico") == ("MX", "Mexico")
    assert canonical_country_info("Philippines") == ("PH", "Philippines")
    assert canonical_country_info("Landriano (Italy)") == ("IT", "Italy")
    assert canonical_country_info("Hong Kong") == ("HK", "Hong Kong")
    assert canonical_country_info("Spain") == ("ES", "Spain")
    assert canonical_country_info("Canada Goose manufacturing facility (Romania)") == (
        "RO",
        "Romania",
    )

    # 3. Single-country evidence_quote fallback vs multi-country quote rejection
    assert canonical_country_info(
        "Poway facility",
        qualifier="assembly and production facility",
        evidence_quote="In February 2025, we expanded into a larger facility in Poway to support increased production.",
    ) == ("US", "United States")
    assert canonical_country_info(
        "Primary assembly plant",
        qualifier="outsourced assembly",
        evidence_quote="Our primary assembly plant is located in Penang, Malaysia.",
    ) == ("MY", "Malaysia")
    assert (
        canonical_country_info(
            "Outsourced manufacturing facilities",
            qualifier="contract manufacturing locations",
            evidence_quote="Much of our manufacturing is performed by outsourcing partners located in China, Malaysia, and Mexico.",
        )
        is None
    )
    assert (
        canonical_country_info(
            "Asia",
            qualifier="outsourced contract manufacturing partners",
            evidence_quote="Our global manufacturing strategy uses contract manufacturers in Asia.",
        )
        is None
    )

    # 4. End-to-end metrics check: no facility.* metric is keyed on a non-country; unplaced go to facility.unplaced.count
    exposures = [
        _make_company(1, "CIK:9990000001", "ZZ Alpha Corp", 0.30, "ZZALP", [("ZZAAA", 0.30)]),
        _make_company(2, "CIK:9990000002", "ZZ Beta Holdings", 0.20, "ZZBET", [("ZZBBB", 0.20)]),
    ]
    edges = [
        VerifiedEdge(
            edge_id="e-fab22",
            source_company_key="CIK:9990000001",
            source_company_name="ZZ Alpha Corp",
            source_in_portfolio=True,
            edge_type="facility",
            target_name="Fab 22",
            target_kind="facility",
            qualifier="located in Kaohsiung Nanzih Technology Industrial Park",
            evidence_quote="We leased land in the Kaohsiung Nanzih Technology Industrial Park for Fab 22.",
            section="2",
            filing=_make_filing("CIK:9990000001", form="20-F"),
        ),
        VerifiedEdge(
            edge_id="e-giga-sh",
            source_company_key="CIK:9990000002",
            source_company_name="ZZ Beta Holdings",
            source_in_portfolio=True,
            edge_type="facility",
            target_name="Gigafactory Shanghai",
            target_kind="facility",
            qualifier="manufacturing facility",
            evidence_quote="We operate Gigafactory Shanghai.",
            section="2",
            filing=_make_filing("CIK:9990000002"),
        ),
        VerifiedEdge(
            edge_id="e-multi-country",
            source_company_key="CIK:9990000001",
            source_company_name="ZZ Alpha Corp",
            source_in_portfolio=True,
            edge_type="facility",
            target_name="Contract partner plants",
            target_kind="facility",
            qualifier="assembly plants",
            evidence_quote="Our contract partner plants are located in China, Malaysia, and Mexico.",
            section="1",
            filing=_make_filing("CIK:9990000001"),
        ),
        VerifiedEdge(
            edge_id="e-region-asia",
            source_company_key="CIK:9990000002",
            source_company_name="ZZ Beta Holdings",
            source_in_portfolio=True,
            edge_type="facility",
            target_name="Asia",
            target_kind="region",
            qualifier="regional hub",
            evidence_quote="We maintain regional hubs across Asia.",
            section="1",
            filing=_make_filing("CIK:9990000002"),
        ),
    ]

    metrics = compute_dependency_metrics(exposures, edges)
    by_id = {m.metric_id: m for m in metrics}

    assert by_id["facility.TW"].value == pytest.approx(0.30)
    assert by_id["facility.TW"].supporting_edge_ids == ["e-fab22"]
    assert by_id["facility.CN"].value == pytest.approx(0.20)
    assert by_id["facility.CN"].supporting_edge_ids == ["e-giga-sh"]

    # Unplaced edges are recorded in facility.unplaced.count and never emit fake country metrics
    assert by_id["facility.unplaced.count"].value == 2.0
    assert by_id["facility.unplaced.count"].unit == "count"
    assert by_id["facility.unplaced.count"].supporting_edge_ids == [
        "e-multi-country",
        "e-region-asia",
    ]
    for m in metrics:
        if m.metric_id.startswith("facility.") and m.unit == "fraction":
            code = m.metric_id.removeprefix("facility.")
            assert len(code) == 2 and code.isalpha() and code.isupper(), m.metric_id

