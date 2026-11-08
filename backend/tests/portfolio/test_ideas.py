"""Invented portfolios verify objective selection, arithmetic and unknown dependency handling."""

from datetime import UTC, date, datetime

import pytest

from hoc.contract import (
    ChangeIdeasRequest,
    ChangeIdeasResponse,
    EtfHoldings,
    FilingRef,
    NormalisedHolding,
    PortfolioRequest,
    Sector,
    VerifiedEdge,
)
from hoc.identity.resolver import Aliases
from hoc.portfolio.analyse import analyse
from hoc.portfolio.ideas import build_idea_scenarios, rank_change_ideas

NOW = datetime(2026, 11, 8, tzinfo=UTC)


def fund(ticker, weights, sectors=None, *, prefix=None):
    sectors = sectors or [s for s in Sector if s != Sector.unknown]
    return EtfHoldings(
        etf_ticker=ticker, etf_name=f"SYNTHETIC {ticker} Fund", source="fake", as_of=date(2026, 11, 1),
        retrieved_at=NOW, source_url="https://example.invalid/synthetic", attribution="SYNTHETIC",
        holdings=[NormalisedHolding(
            etf_ticker=ticker, security_key=f"{prefix or ticker}:{i}", security_id=f"ZZ{i}",
            security_id_type="symbol", name=f"ZZ Company {i}", company_key=f"{prefix or ticker}:{i}",
            company_key_basis="symbol", company_name=f"ZZ Company {i}", identity_status="resolved",
            weight=weight, source="fake", as_of=date(2026, 11, 1), sector=sectors[i % len(sectors)],
        ) for i, weight in enumerate(weights)],
        reported_weight=sum(weights), holdings_weight=sum(weights), excluded_weight=0,
        unmatched_weight=0, raw_line_count=len(weights), normaliser_version="synthetic",
    )


def setup(base=None, candidates=None):
    base = base or fund("ZZBASE", [.51, .49], [Sector.information_technology, Sector.health_care])
    candidates = candidates or [fund(t, [.01] * 100) for t in ("ZZADD", "ZZBROAD", "ZZDIVER", "ZZOTHER")]
    loaded = {f.etf_ticker: f for f in [base, *candidates]}
    request = ChangeIdeasRequest(holdings=[{"ticker": "ZZBASE", "allocation": 1}], top_n=30)
    baseline = analyse(PortfolioRequest(holdings=request.holdings), loaded, {}, today=NOW.date(), generated_at=NOW)
    scenarios = build_idea_scenarios(request, baseline, loaded, [f.etf_ticker for f in candidates])
    return request, baseline, loaded, scenarios


def ranked(request, baseline, scenarios, cache=None):
    return rank_change_ideas(request, baseline, scenarios, cache or {}, aliases=Aliases())


def test_industry_first_best_fraction_three_distinct_etfs_and_exact_allocations():
    request, baseline, _, scenarios = setup()
    assert len(scenarios) == 8
    result = ranked(request, baseline, scenarios)
    assert len(result.ideas) == 3 and len({i.ticker for i in result.ideas}) == 3
    for idea in result.ideas:
        assert idea.addresses == "top_sector" and idea.metric_id is None
        assert idea.add_fraction == .2
        assert {h.ticker: h.allocation for h in idea.holdings} == {"ZZBASE": .8, idea.ticker: .2}
        delta = next(d for d in idea.concentration_deltas if d.name == "top_sector")
        assert delta.delta < 0
        assert "51.0%" in idea.reason and f"{delta.candidate:.1%}" in idea.reason
        assert "Information Technology" in idea.reason
        assert idea.biggest_dependency_delta is None
        assert idea.status == "partial" and idea.candidate_unanalysed
    # Input iteration order cannot change the shortlist or its stable identifiers.
    assert result == ranked(request, baseline, list(reversed(scenarios)))
    ChangeIdeasResponse.model_validate_json(result.model_dump_json())


def test_largest_known_dependency_wins_when_no_industry_is_concentrated():
    base = fund("ZZBASE", [.3] + [.7 / 19] * 19)
    request, baseline, _, scenarios = setup(base)
    edge = VerifiedEdge(
        edge_id="zz-edge", source_company_key="ZZBASE:0", source_company_name="ZZ Company 0",
        source_in_portfolio=True,
        edge_type="foundry", target_kind="company", target_name="ZZ External Foundry",
        evidence_quote="SYNTHETIC: we rely on ZZ External Foundry.", section="Item 1",
        filing=FilingRef(company_key="ZZBASE:0", form="10-K", accession="9999999999-26-000001",
                         filed=NOW.date(), url="https://example.invalid/10k"),
    )
    result = ranked(request, baseline, scenarios, {"ZZBASE:0": [edge]})
    assert result.ideas
    for idea in result.ideas:
        assert idea.addresses == "dependency" and idea.metric_id.startswith("dep.")
        assert "ZZ External Foundry" in idea.reason
        delta = idea.biggest_dependency_delta
        assert (delta.baseline, delta.candidate, delta.delta) == pytest.approx((.3, .24, -.06))


def test_missing_dependency_on_candidate_side_is_unknown_never_a_reduction():
    from unittest.mock import patch

    from hoc.contract import CompareResponse, ConcentrationDelta, MetricDelta

    request, baseline, _, scenarios = setup()
    baseline.coverage.sector_known_weight = 0
    concentration = [ConcentrationDelta(name=name, baseline=1, candidate=1, delta=0)
                     for name in ("top5", "top10", "top20", "effective_n", "largest_company", "top_sector")]
    old = CompareResponse(status="ok", baseline_top_n_weight=1, candidate_top_n_weight=1,
                          concentration_deltas=concentration, dependency_deltas=[MetricDelta(
                              metric_id="dep.zz", label="ZZ dependency", unit="fraction",
                              baseline=.4, candidate=.4, delta=0)])
    missing = old.model_copy(deep=True)
    missing.dependency_deltas[0].candidate = None
    missing.dependency_deltas[0].delta = None
    with patch("hoc.portfolio.ideas.compare_portfolios", side_effect=[old, *[missing] * len(scenarios)]):
        assert ranked(request, baseline, scenarios).ideas == []


def test_concentration_fallback_and_effective_count_for_small_portfolios():
    request, baseline, _, scenarios = setup(fund("ZZBASE", [.05] * 20))
    assert all(i.addresses == "top10" for i in ranked(request, baseline, scenarios).ideas)
    base = fund("ZZBASE", [.6, .4], [Sector.unknown])
    added = fund("ZZADD", [.5, .5], [Sector.unknown])
    request, baseline, _, scenarios = setup(base, [added])
    ideas = ranked(request, baseline, scenarios).ideas
    assert len(ideas) == 1 and ideas[0].addresses == "effective_n"
    assert "would rise" in ideas[0].reason


def test_already_held_unavailable_and_cash_heavy_funds_are_omitted():
    request, baseline, loaded, _ = setup()
    loaded["ZZCASH"] = fund("ZZCASH", [.1])
    scenarios = build_idea_scenarios(request, baseline, loaded, ["ZZBASE", "ZZCASH", "ZZMISSING"])
    assert scenarios == []


def test_missing_sector_data_cannot_appear_to_improve_largest_industry():
    request, baseline, _, scenarios = setup(candidates=[fund("ZZADD", [.01] * 100, [Sector.unknown])])
    assert ranked(request, baseline, scenarios).ideas == []


def test_non_improving_identical_exposures_are_not_ideas():
    base = fund("ZZBASE", [.51, .49], [Sector.information_technology, Sector.health_care], prefix="ZZ")
    candidate = base.model_copy(update={"etf_ticker": "ZZADD", "etf_name": "SYNTHETIC same exposures"})
    request, baseline, _, scenarios = setup(base, [candidate])
    assert ranked(request, baseline, scenarios).ideas == []


def test_reason_names_both_industries_if_the_largest_changes():
    candidate = fund("ZZADD", [.2, .4, .4], [Sector.information_technology, Sector.health_care, Sector.financials])
    request, baseline, _, scenarios = setup(candidates=[candidate])
    ideas = ranked(request, baseline, scenarios).ideas
    assert len(ideas) == 1
    assert "Information Technology at 51.0% to Health Care at 47.2%" in ideas[0].reason
