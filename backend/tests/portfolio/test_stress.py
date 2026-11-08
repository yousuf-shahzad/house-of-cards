"""Failure simulation arithmetic on invented companies, with all network access blocked."""

from datetime import UTC, date, datetime

import pytest

from hoc.contract import (
    AnalysisResponse,
    CompanyExposure,
    Coverage,
    DataGap,
    Overlap,
    PortfolioRequest,
    PortfolioValidationError,
    SectorExposure,
    ShockBasis,
    StressRequest,
    StressResponse,
    wsum,
)
from hoc.portfolio.concentration import concentration
from hoc.portfolio.stress import simulate_failure


def company(key, weight, sector="information_technology", country="US"):
    return CompanyExposure(
        rank=1, company_key=key, company_name=f"ZZ Company {key}",
        identity_status="resolved", symbols=[], sector=sector, country=country,
        exposure=weight, etf_count=1, contributions=[], securities=[],
    )


def analysis(companies, ticker="ZZBASE", **coverage):
    total = wsum(c.exposure for c in companies)
    fields = {
        "total_allocation": 1, "loaded_allocation": 1, "missing_allocation": 0,
        "covered_weight": total, "excluded_weight": 0, "unexplained_weight": 1-total,
        "unmatched_weight": 0,
        "sector_known_weight": wsum(c.exposure for c in companies if c.sector != "unknown"),
    }
    fields.update(coverage)
    return AnalysisResponse(
        generated_at=datetime(2026, 11, 8, tzinfo=UTC), as_of_date=date(2026, 11, 8),
        request=PortfolioRequest(holdings=[{"ticker": ticker, "allocation": 1}]),
        etfs=[], coverage=Coverage(**fields), exposures=companies,
        exposures_truncated=False, other_exposure=0, overlap=Overlap(etfs=[], matrix=[], pairs=[]),
        concentration=concentration(companies), sectors=[], gaps=[], warnings=[], attributions=[],
    )


def basis(drop=.1):
    return ShockBasis(source="simulated", drop=drop, description=f"Simulated {drop:.0%} fall")


def request(before, after=None, *, kind="sector", key="information_technology", **kwargs):
    return StressRequest(
        baseline=before.request.holdings, candidate=after.request.holdings if after is not None else None,
        shock={"kind": kind, "key": key, "label": "An echoed display label"}, **kwargs,
    )


def test_sector_shock_hand_calculated_before_after_and_money():
    before = analysis([company("ZZ-A", .4), company("ZZ-B", .2), company("ZZ-C", .4, "health_care")])
    after = analysis([company("ZZ-A", .1), company("ZZ-D", .2), company("ZZ-C", .7, "health_care")], "ZZNEW")
    shock = ShockBasis(
        source="historical", drop=.25, proxy="XLK", window_start=date(2022, 8, 16),
        window_end=date(2022, 9, 15), description="Synthetic historical fixture",
    )
    req = request(before, after)
    snapshots = [obj.model_dump_json() for obj in (req, before, after, shock)]
    # Fund-reported sector aggregates deliberately disagree: match CompanyExposure.sector.
    before.sectors = [SectorExposure(sector="information_technology", weight=.99, by_etf=[])]
    snapshots[1] = before.model_dump_json()
    result = simulate_failure(req, before, after, shock)
    assert result.status == "ok" and result.notes == []
    assert result.baseline.affected_weight == pytest.approx(.6)
    assert result.baseline.loss_fraction == pytest.approx(.15)
    assert result.candidate.affected_weight == pytest.approx(.3)
    assert result.candidate.loss_fraction == pytest.approx(.075)
    assert 10000 * (1-result.baseline.loss_fraction) == pytest.approx(8500)
    assert 10000 * (1-result.candidate.loss_fraction) == pytest.approx(9250)
    assert result.shock == req.shock and result.basis == shock
    assert [(c.company_key, c.exposure, c.loss) for c in result.baseline.affected] == [
        ("ZZ-A", .4, .1), ("ZZ-B", .2, .05),
    ]
    assert [obj.model_dump_json() for obj in (req, before, after, shock)] == snapshots
    assert StressResponse.model_validate_json(result.model_dump_json()).model_dump_json() == result.model_dump_json()


def test_country_matches_country_only_and_ignores_supplier_keys_and_label():
    before = analysis([company("ZZ-US", .3), company("ZZ-TW", .2, country="TW"),
                       company("ZZ-JP", .5, country="JP")])
    result = simulate_failure(request(before, kind="country", key="TW", company_keys=["ZZ-US"]),
                              before, None, basis(.2))
    assert result.baseline.affected_weight == .2
    assert result.baseline.loss_fraction == pytest.approx(.04)
    assert [c.company_key for c in result.baseline.affected] == ["ZZ-TW"]
    assert result.candidate is None and result.status == "ok"


def test_supplier_uses_explicit_keys_once_with_supplier_and_candidate_entrant():
    before = analysis([company("ZZ-DEPENDENT", .4), company("ZZ-SUPPLIER", .1), company("ZZ-OTHER", .5)])
    after = analysis([company("ZZ-DEPENDENT", .1), company("ZZ-ENTRANT", .7), company("ZZ-OTHER", .2)], "ZZNEW")
    req = request(before, after, kind="supplier", key="ZZ-SUPPLIER", company_keys=[
        "ZZ-DEPENDENT", "ZZ-DEPENDENT", "ZZ-SUPPLIER", "ZZ-ENTRANT", "ZZ-NOT-HELD",
    ])
    result = simulate_failure(req, before, after, basis())
    assert result.baseline.affected_count == result.candidate.affected_count == 2
    assert result.baseline.loss_fraction == pytest.approx(.05)
    assert result.candidate.loss_fraction == pytest.approx(.08)
    assert result.status == "ok"


def test_supplier_key_is_not_implicitly_added_to_explicit_affected_set():
    before = analysis([company("ZZ-SUPPLIER", .3), company("ZZ-OTHER", .7)])
    result = simulate_failure(request(before, kind="supplier", key="ZZ-SUPPLIER"), before, None, basis())
    assert result.baseline.affected_count == 0
    assert result.baseline.affected == []
    assert result.baseline.affected_weight == result.baseline.loss_fraction == 0
    assert result.status == "ok"


def test_full_totals_include_more_than_ten_and_ties_break_by_key_deterministically():
    companies = [company(f"ZZ-{i:02}", .05) for i in range(12)] + [company("ZZ-LARGEST", .4)]
    before = analysis(list(reversed(companies)))
    req = request(before)
    result = simulate_failure(req, before, None, basis())
    assert result.baseline.affected_count == 13
    assert len(result.baseline.affected) == 10
    assert [c.company_key for c in result.baseline.affected] == ["ZZ-LARGEST"] + [f"ZZ-{i:02}" for i in range(9)]
    assert result.baseline.affected_weight == 1
    assert result.baseline.loss_fraction == .1
    before.exposures.reverse()
    assert simulate_failure(req, before, None, basis()).model_dump_json() == result.model_dump_json()


@pytest.mark.parametrize("drop", [.1, .2739, 1.0])
def test_supplied_basis_drop_is_applied_exactly_to_positive_exposure(drop):
    before = analysis([company("ZZ-A", 1), company("ZZ-ZERO", 0)])
    result = simulate_failure(request(before), before, None, basis(drop))
    assert result.baseline.loss_fraction == drop
    assert result.baseline.affected_count == 1
    assert result.baseline.affected[0].loss == drop


@pytest.mark.parametrize(("changes", "phrase"), [
    ({"missing_allocation": .2, "loaded_allocation": .8, "unexplained_weight": 0}, "unavailable"),
    ({"excluded_weight": .2, "unexplained_weight": 0}, "excluded"),
    ({"unexplained_weight": .2}, "unexplained"),
])
def test_incomplete_coverage_is_partial_and_never_renormalised(changes, phrase):
    before = analysis([company("ZZ-A", .3), company("ZZ-B", .5, "health_care")], **changes)
    result = simulate_failure(request(before), before, None, basis(.2))
    assert result.status == "partial"
    assert result.baseline.affected_weight == .3
    assert result.baseline.loss_fraction == .06
    assert any(phrase in note for note in result.notes)
    assert any("understated" in note for note in result.notes)


@pytest.mark.parametrize(("kind", "unknown", "phrase"), [
    ("sector", company("ZZ-UNKNOWN", .3, "unknown"), "unknown industry"),
    ("country", company("ZZ-UNKNOWN", .3, country=None), "unknown country"),
    ("country", company("ZZ-UNKNOWN", .3, country=""), "unknown country"),
])
def test_missing_matching_metadata_is_partial(kind, unknown, phrase):
    before = analysis([company("ZZ-A", .7), unknown])
    key = "information_technology" if kind == "sector" else "US"
    result = simulate_failure(request(before, kind=kind, key=key), before, None, basis())
    assert result.status == "partial"
    assert result.baseline.affected_weight == .7
    assert any(phrase in note for note in result.notes)


def test_irrelevant_unknown_metadata_does_not_make_supplier_result_partial():
    before = analysis([company("ZZ-A", 1, "unknown", country=None)])
    result = simulate_failure(request(before, kind="supplier", key="ZZ-A", company_keys=["ZZ-A"]),
                              before, None, basis())
    assert result.status == "ok" and result.baseline.affected_weight == 1


def test_candidate_only_truncation_marks_response_partial_with_side_specific_notes():
    before = analysis([company("ZZ-A", 1)])
    after = analysis([company("ZZ-A", .4)], "ZZNEW", covered_weight=1, unexplained_weight=0)
    after.exposures_truncated = True
    after.other_exposure = .6
    result = simulate_failure(request(before, after), before, after, basis())
    assert result.status == "partial"
    assert result.baseline.loss_fraction == .1
    assert result.candidate.loss_fraction == pytest.approx(.04)
    assert all(note.startswith("Your new mix:") for note in result.notes)
    assert any("truncated" in note for note in result.notes)


def test_nested_funds_are_partial_even_if_reported_weight_is_complete():
    before = analysis([company("ZZ-FUND", 1)])
    before.gaps = [DataGap(kind="nested_fund", severity="warning", portfolio_weight=1,
                           message="Synthetic fund holding without look-through")]
    result = simulate_failure(request(before), before, None, basis())
    assert result.status == "partial" and any("nested funds" in note for note in result.notes)


def test_empty_coverage_is_partial_and_zero_matching_exposure_is_safe():
    before = analysis([], missing_allocation=1, loaded_allocation=0, unexplained_weight=0)
    result = simulate_failure(request(before), before, None, basis())
    assert result.status == "partial"
    assert result.baseline.affected_weight == result.baseline.loss_fraction == 0
    assert result.baseline.affected_count == 0 and result.baseline.affected == []


def test_floating_point_coverage_dust_is_not_partial():
    before = analysis([company("ZZ-A", .7), company("ZZ-B", .2), company("ZZ-C", .1)])
    before.coverage.unexplained_weight = 1e-16
    result = simulate_failure(request(before), before, None, basis())
    assert result.status == "ok" and result.notes == []


def test_supplied_analyses_must_match_requested_holdings():
    before = analysis([company("ZZ-A", 1)])
    other = analysis([company("ZZ-A", 1)], "ZZOTHER")
    with pytest.raises(ValueError, match="correspond"):
        simulate_failure(request(before), other, None, basis())
    with pytest.raises(ValueError, match="correspond"):
        simulate_failure(request(before, other), before, before, basis())


def test_candidate_analysis_presence_must_match_request():
    before = analysis([company("ZZ-A", 1)])
    with pytest.raises(ValueError, match="Candidate analysis"):
        simulate_failure(request(before, before), before, None, basis())
    with pytest.raises(ValueError, match="Candidate analysis"):
        simulate_failure(request(before), before, before, basis())


def test_portfolio_business_rules_are_validated():
    before = analysis([company("ZZ-A", 1)])
    before.request.holdings[0].allocation = .5
    with pytest.raises(PortfolioValidationError) as error:
        simulate_failure(request(before), before, None, basis())
    assert error.value.code == "ALLOCATION_SUM_INVALID"
