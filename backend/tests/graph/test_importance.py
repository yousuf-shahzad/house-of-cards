"""Tests for v3 package R-IMP: deterministic relationship importance & critical.* metrics."""

from __future__ import annotations

from datetime import date

import pytest

from hoc.contract.api import CompanyExposure, Contribution, SecurityExposure
from hoc.contract.dependencies import EdgeInterpretation, FilingRef, VerifiedEdge
from hoc.contract.units import Sector
from hoc.graph import (
    attach_edge_importance,
    compute_dependency_metrics,
    score_edge_importance,
    tier_for_score,
)


def _make_filing(company_key: str = "CIK:9990000001") -> FilingRef:
    return FilingRef(
        company_key=company_key,
        form="10-K",
        accession=f"{company_key.split(':')[-1]}-26-000001",
        filed=date(2026, 10, 30),
        url=f"https://www.sec.gov/Archives/edgar/data/{company_key}/10k.htm",
    )


def _make_edge(
    edge_id: str,
    edge_type: str,
    *,
    source_company_key: str = "CIK:9990000001",
    target_name: str = "ZZ Counterparty",
    target_kind: str = "company",
    target_key: str | None = "ALIAS:ZZTARGET",
    sole_source: bool = False,
    qualifier: str | None = None,
    evidence_quote: str = "We work with ZZ Counterparty.",
    interpretation: EdgeInterpretation | None = None,
) -> VerifiedEdge:
    return VerifiedEdge(
        edge_id=edge_id,
        source_company_key=source_company_key,
        source_company_name="ZZ Alpha Corp",
        source_in_portfolio=True,
        edge_type=edge_type,  # type: ignore[arg-type]
        target_name=target_name,
        target_kind=target_kind,  # type: ignore[arg-type]
        target_key=target_key,
        target_in_portfolio=False,
        sole_source=sole_source,
        qualifier=qualifier,
        evidence_quote=evidence_quote,
        section="Item 1A",
        filing=_make_filing(source_company_key),
        interpretation=interpretation,
    )


def _make_exposure(company_key: str, name: str, exposure: float) -> CompanyExposure:
    return CompanyExposure(
        rank=1,
        company_key=company_key,
        company_name=name,
        identity_status="resolved",
        symbols=["ZZALP"],
        sector=Sector.information_technology,
        country="US",
        exposure=exposure,
        etf_count=1,
        contributions=[
            Contribution(
                etf_ticker="ZZAAA",
                weight_in_etf=exposure,
                contribution=exposure,
                security_keys=["SEC:ZZALP"],
            )
        ],
        securities=[
            SecurityExposure(
                security_key="SEC:ZZALP",
                security_id="ZZALP",
                security_id_type="symbol",
                symbol="ZZALP",
                name=name,
                exposure=exposure,
            )
        ],
    )


def test_tier_for_score_thresholds() -> None:
    assert tier_for_score(0.95) == "critical"
    assert tier_for_score(0.80) == "critical"
    assert tier_for_score(0.79) == "high"
    assert tier_for_score(0.60) == "high"
    assert tier_for_score(0.59) == "medium"
    assert tier_for_score(0.40) == "medium"
    assert tier_for_score(0.39) == "low"
    assert tier_for_score(0.0) == "low"


def test_base_scores_across_edge_types_and_customer_revenue_shares() -> None:
    # foundry -> 0.90 (critical)
    foundry_imp = score_edge_importance(
        _make_edge("e-foundry", "foundry", evidence_quote="ZZ Counterparty fabricates our wafers.")
    )
    assert foundry_imp.score == pytest.approx(0.90)
    assert foundry_imp.tier == "critical"

    # contract_manufacturer -> 0.85 (critical)
    cm_imp = score_edge_importance(
        _make_edge(
            "e-cm",
            "contract_manufacturer",
            evidence_quote="ZZ Counterparty assembles our enclosures.",
        )
    )
    assert cm_imp.score == pytest.approx(0.85)
    assert cm_imp.tier == "critical"

    # key_input -> 0.60 (high)
    ki_imp = score_edge_importance(
        _make_edge(
            "e-ki",
            "key_input",
            target_kind="material",
            target_key=None,
            evidence_quote="We purchase silicon carbide wafers for our power modules.",
        )
    )
    assert ki_imp.score == pytest.approx(0.60)
    assert ki_imp.tier == "high"

    # supplier -> 0.50 (medium)
    sup_imp = score_edge_importance(
        _make_edge("e-sup", "supplier", evidence_quote="ZZ Counterparty supplies components.")
    )
    assert sup_imp.score == pytest.approx(0.50)
    assert sup_imp.tier == "medium"

    # jv_partner -> 0.40 (medium)
    jv_imp = score_edge_importance(
        _make_edge("e-jv", "jv_partner", evidence_quote="We operate a joint venture with ZZ Counterparty.")
    )
    assert jv_imp.score == pytest.approx(0.40)
    assert jv_imp.tier == "medium"

    # customer >= 20% -> 0.90 (critical)
    cust_22 = score_edge_importance(
        _make_edge(
            "e-c22",
            "customer",
            qualifier="22% of revenue",
            evidence_quote="One customer accounted for 22% of our total net revenue.",
        )
    )
    assert cust_22.score == pytest.approx(0.90)
    assert cust_22.tier == "critical"

    # customer 10-20% -> 0.70 (high)
    cust_14 = score_edge_importance(
        _make_edge(
            "e-c14",
            "customer",
            qualifier="14% of revenue",
            evidence_quote="ZZ Counterparty accounted for 14% of our revenue in fiscal 2025.",
        )
    )
    assert cust_14.score == pytest.approx(0.70)
    assert cust_14.tier == "high"

    # customer < 10% -> 0.50 (medium)
    cust_8 = score_edge_importance(
        _make_edge(
            "e-c8",
            "customer",
            qualifier="8% of revenue",
            evidence_quote="ZZ Counterparty represented 8% of revenue.",
        )
    )
    assert cust_8.score == pytest.approx(0.50)
    assert cust_8.tier == "medium"

    # facility production/assembly -> 0.70 (high) vs HQ/office/R&D -> 0.30 (low)
    fac_prod = score_edge_importance(
        _make_edge(
            "e-fac-prod",
            "facility",
            target_kind="country",
            target_name="Taiwan",
            target_key=None,
            qualifier="final assembly and testing",
            evidence_quote="Final assembly and wafer testing are performed in Taiwan.",
        )
    )
    assert fac_prod.score == pytest.approx(0.70)
    assert fac_prod.tier == "high"

    fac_hq = score_edge_importance(
        _make_edge(
            "e-fac-hq",
            "facility",
            target_kind="facility",
            target_name="Cupertino headquarters",
            target_key=None,
            qualifier="corporate headquarters and R&D center",
            evidence_quote="Our corporate headquarters and R&D center are in Cupertino, California.",
        )
    )
    assert fac_hq.score == pytest.approx(0.30)
    assert fac_hq.tier == "low"


def test_sole_source_and_quote_cue_adjustments() -> None:
    # sole_source forces >= 0.95 (critical)
    sole_sup = score_edge_importance(
        _make_edge(
            "e-sole",
            "supplier",
            sole_source=True,
            evidence_quote="ZZ Counterparty is our sole supplier of specialty lenses.",
        )
    )
    assert sole_sup.score >= 0.95
    assert sole_sup.tier == "critical"

    # Upward cues ("substantially all", "critical", "limited number of", "rely on") lift supplier to critical
    upward_sup = score_edge_importance(
        _make_edge(
            "e-up",
            "supplier",
            evidence_quote=(
                "We rely on a limited number of critical suppliers and purchase substantially all "
                "of our substrates from ZZ Counterparty."
            ),
        )
    )
    assert upward_sup.score >= 0.80
    assert upward_sup.tier == "critical"

    # Downward cues ("one of several", "readily available") lower supplier to low
    downward_sup = score_edge_importance(
        _make_edge(
            "e-down",
            "supplier",
            evidence_quote=(
                "ZZ Counterparty is one of several suppliers of standard memory, which is "
                "readily available from multiple sources."
            ),
        )
    )
    assert downward_sup.score < 0.40
    assert downward_sup.tier == "low"


def test_flagged_interpretation_caps_importance_at_medium() -> None:
    """When V-INT flags an edge (status='flagged'), tier is capped at 'medium' and score matches tier."""
    flagged_edge = _make_edge(
        "e-flagged-sole-foundry",
        "foundry",
        sole_source=True,
        evidence_quote="We do not rely on ZZ Counterparty as our sole foundry.",
        interpretation=EdgeInterpretation(
            status="flagged",
            method="rules",
            flags=["negated"],
            reason="Quote negates the relationship.",
        ),
    )
    imp = score_edge_importance(flagged_edge)
    assert imp.tier in ("medium", "low")
    assert imp.tier == tier_for_score(imp.score)
    assert imp.score <= 0.55
    assert any("Capped at medium" in r for r in imp.reasons)


def test_critical_metrics_only_count_critical_and_high_edges_and_have_dep_twins() -> None:
    """critical.<key> includes only critical/high edges while dep.<key> includes all supply edges."""
    exposures = [
        _make_exposure("CIK:9990000001", "ZZ Alpha Corp", 0.30),
        _make_exposure("CIK:9990000002", "ZZ Beta Holdings", 0.20),
    ]
    edges = attach_edge_importance(
        [
            # Alpha -> Epsilon is critical (foundry, sole_source)
            _make_edge(
                "e-alp-eps-crit",
                "foundry",
                source_company_key="CIK:9990000001",
                target_name="ZZ Epsilon Semiconductor",
                target_key="ALIAS:ZZEPSILON",
                sole_source=True,
                evidence_quote="We rely on ZZ Epsilon Semiconductor as the sole foundry.",
            ),
            # Beta -> Epsilon is low (supplier with downward cues)
            _make_edge(
                "e-bet-eps-low",
                "supplier",
                source_company_key="CIK:9990000002",
                target_name="ZZ Epsilon Semiconductor",
                target_key="ALIAS:ZZEPSILON",
                sole_source=False,
                evidence_quote="ZZ Epsilon Semiconductor is one of several suppliers among multiple suppliers.",
            ),
            # Beta -> Minor Commodity Co is low (no critical/high edges at all)
            _make_edge(
                "e-bet-minor-low",
                "supplier",
                source_company_key="CIK:9990000002",
                target_name="ZZ Minor Commodity Co",
                target_key="CIK:0000999009",
                sole_source=False,
                evidence_quote="ZZ Minor Commodity Co is one of several secondary suppliers.",
            ),
        ]
    )

    metrics = compute_dependency_metrics(exposures, edges)
    by_id = {m.metric_id: m for m in metrics}

    # dep.ALIAS:ZZEPSILON includes both Alpha (0.30) and Beta (0.20) = 0.50
    assert by_id["dep.ALIAS:ZZEPSILON"].value == pytest.approx(0.50)
    assert by_id["dep.ALIAS:ZZEPSILON.companies"].value == 2.0

    # critical.ALIAS:ZZEPSILON includes ONLY Alpha (0.30) because Beta's edge is low tier
    assert by_id["critical.ALIAS:ZZEPSILON"].value == pytest.approx(0.30)
    assert by_id["critical.ALIAS:ZZEPSILON"].supporting_edge_ids == ["e-alp-eps-crit"]
    assert by_id["critical.ALIAS:ZZEPSILON.companies"].value == 1.0

    # ZZ Minor Commodity Co has only a low-tier edge -> dep.* emitted, critical.* NOT emitted
    assert "dep.CIK:0000999009" in by_id
    assert "critical.CIK:0000999009" not in by_id

    # Contract invariant: every critical.<key> metric has a dep.<key> twin
    for m in metrics:
        if m.metric_id.startswith("critical.") and not m.metric_id.endswith(".companies"):
            assert m.metric_id.replace("critical.", "dep.", 1) in by_id

    # Lead invariant (#6716240487): compute_dependency_metrics scores edges with importance=None
    # automatically without mutating the input edges.
    unscored_edge = _make_edge(
        "e-unscored-foundry",
        "foundry",
        source_company_key="CIK:9990000001",
        target_name="ZZ Epsilon Semiconductor",
        target_key="ALIAS:ZZEPSILON",
        sole_source=True,
        evidence_quote="We rely on ZZ Epsilon Semiconductor as the sole foundry.",
    )
    assert unscored_edge.importance is None
    unscored_metrics = {
        m.metric_id: m for m in compute_dependency_metrics(exposures, [unscored_edge])
    }
    assert unscored_edge.importance is None
    assert "critical.ALIAS:ZZEPSILON" in unscored_metrics
    assert unscored_metrics["critical.ALIAS:ZZEPSILON"].value == pytest.approx(0.30)


def test_fix_33_customer_share_grounding_office_facilities_and_reverse_customer_cap() -> None:
    """FIX-33 (#216 / #215):
    - (A) Customer importance uses only a share grounded to this target (never another customer's 22%
      or an ungrounded qualifier share).
    - (C) 'office facilities' / headquarters scores 0.30 unless there is actual production evidence.
    - Reverse customer links are capped at medium and never raise the buyer's critical.* metric.
    """
    # (A.1) Issue #216 repro: target has 8% qualifier, another company in same quote has 22%
    other_cust_imp = score_edge_importance(
        _make_edge(
            "e-fix33-a1",
            "customer",
            target_name="ZZ Counterparty",
            qualifier="8% of revenue",
            evidence_quote="ZZ Counterparty represented 8% of revenue; Another Company represented 22% of revenue.",
        )
    )
    assert other_cust_imp.score == pytest.approx(0.50)
    assert other_cust_imp.tier == "medium"
    assert not any("22%" in r for r in other_cust_imp.reasons)

    # (A.2) Issue #215 B.1 repro: invented 90% qualifier not present in evidence_quote
    ungrounded_qual_imp = score_edge_importance(
        _make_edge(
            "e-fix33-b1",
            "customer",
            target_name="Acme",
            qualifier="90% of revenue",
            evidence_quote="Acme is one of our customers.",
        )
    )
    assert ungrounded_qual_imp.score == pytest.approx(0.50)
    assert ungrounded_qual_imp.tier == "medium"

    # (A.3) Issue #215 B.2 repro: target has 2% while exports have 80%
    exports_imp = score_edge_importance(
        _make_edge(
            "e-fix33-b2",
            "customer",
            target_name="Acme",
            qualifier=None,
            evidence_quote="Acme accounted for 2% of revenue, while exports accounted for 80% of revenue.",
        )
    )
    assert exports_imp.score == pytest.approx(0.50)
    assert exports_imp.tier == "medium"

    # (A.4) Issue #215 B.3 repro: another supplier's 'sole supplier' cue in a separate clause
    other_sole_imp = score_edge_importance(
        _make_edge(
            "e-fix33-b3",
            "supplier",
            target_name="Acme",
            sole_source=False,
            evidence_quote="We buy components from Acme and our sole supplier of packaging is Beta.",
        )
    )
    assert other_sole_imp.score == pytest.approx(0.50)
    assert other_sole_imp.tier == "medium"

    # (C) Issue #216 repro: 'office facilities' / corporate headquarters scores 0.30 (low), not 0.70 (high)
    office_fac_imp = score_edge_importance(
        _make_edge(
            "e-fix33-c",
            "facility",
            target_kind="country",
            target_name="United States",
            target_key="US",
            qualifier="corporate headquarters",
            evidence_quote="Our corporate headquarters and office facilities are in the United States.",
        )
    )
    assert office_fac_imp.score == pytest.approx(0.30)
    assert office_fac_imp.tier == "low"
    assert not any("Production facility" in r for r in office_fac_imp.reasons)

    # Reverse customer link: external supplier says portfolio buyer is 30% of supplier's sales ->
    # capped at medium (<= 0.55) and does NOT emit critical.<supplier> for the buyer
    exposures = [
        _make_exposure("CIK:9990000001", "ZZ Alpha Corp", 0.10),
    ]
    rev_cust_edge = VerifiedEdge(
        edge_id="e-fix33-rev",
        source_company_key="CIK:8880000009",
        source_company_name="ZZ Optics Supplier",
        source_in_portfolio=False,
        edge_type="customer",
        target_name="ZZ Alpha Corp",
        target_kind="company",
        target_key="CIK:9990000001",
        target_in_portfolio=True,
        sole_source=False,
        qualifier="30% of revenue",
        evidence_quote="ZZ Alpha Corp accounted for 30% of our revenue.",
        section="Item 1",
        filing=_make_filing("CIK:8880000009"),
    )
    rev_imp = score_edge_importance(rev_cust_edge)
    assert rev_imp.tier == "medium"
    assert rev_imp.score <= 0.55

    rev_metrics = {m.metric_id: m for m in compute_dependency_metrics(exposures, [rev_cust_edge])}
    assert "dep.CIK:8880000009" in rev_metrics
    assert rev_metrics["dep.CIK:8880000009"].value == pytest.approx(0.10)
    assert "critical.CIK:8880000009" not in rev_metrics

