"""X-API arithmetic/cache regressions; invented ZZ companies only, no network or model calls."""
from datetime import UTC, date, datetime

import pytest

from hoc.ai.cache import ExtractionCache
from hoc.contract import (
    AnalysisResponse,
    CompanyExposure,
    CompareRequest,
    CompareResponse,
    Coverage,
    EdgeInterpretation,
    FilingRef,
    Overlap,
    PortfolioRequest,
    PortfolioValidationError,
    SectorExposure,
    VerifiedEdge,
)
from hoc.core.cache import DiskCache
from hoc.identity.resolver import Aliases, aliases_from_entries
from hoc.portfolio.compare import compare_portfolios, read_cached_extractions
from hoc.portfolio.concentration import concentration

NOW = datetime(2026, 11, 8, tzinfo=UTC)
MODEL = "test-extractor"
VERSION = "synthetic-test-1"
A, B, C = "CIK:9990000001", "CIK:9990000002", "CIK:9990000003"


def company(key, weight, rank):
    return CompanyExposure(
        rank=rank, company_key=key, company_name=f"ZZ Company {key[-1]}",
        identity_status="resolved", symbols=[f"ZZ{key[-1]}"], sector="information_technology",
        exposure=weight, etf_count=1, contributions=[], securities=[],
    )


def analysis(weights, ticker="ZZBASE"):
    companies = [company(key, weight, rank) for rank, (key, weight) in enumerate(weights, 1)]
    companies.sort(key=lambda c: (-c.exposure, c.company_key))
    total = sum(weight for _, weight in weights)
    return AnalysisResponse(
        generated_at=NOW, as_of_date=NOW.date(),
        request=PortfolioRequest(holdings=[{"ticker": ticker, "allocation": 1}]), etfs=[],
        coverage=Coverage(total_allocation=1, loaded_allocation=1, missing_allocation=0,
                          covered_weight=total, excluded_weight=1-total, unexplained_weight=0,
                          unmatched_weight=0, sector_known_weight=total),
        exposures=companies, exposures_truncated=False, other_exposure=0,
        overlap=Overlap(etfs=[], matrix=[], pairs=[]), concentration=concentration(companies),
        sectors=[], gaps=[], warnings=[], attributions=[],
    )


def request(before, after, top_n=2):
    return CompareRequest(baseline=before.request.holdings, candidate=after.request.holdings, top_n=top_n)


def edge(source=A, target="ZZ Foundry", *, edge_id="zz-edge", kind="foundry", **updates):
    result = VerifiedEdge(
        edge_id=edge_id, source_company_key=source, source_company_name=f"ZZ Company {source[-1]}",
        source_in_portfolio=False, edge_type=kind, target_name=target, target_kind="company",
        target_key="ALIAS:STALE_PORTFOLIO", target_in_portfolio=True,
        evidence_quote="We use ZZ Foundry to manufacture our chips.", section="Item 1",
        filing=FilingRef(company_key=source, form="10-K", accession="9990000001-26-000001",
                         filed=date(2026, 10, 30), url="https://example.test/zz-10k.htm"),
    )
    return result.model_copy(update=updates)


def compare(before, after, cache, *, top_n=2, aliases=None, company_statuses=None):
    return compare_portfolios(request(before, after, top_n), before, after, cache,
                              aliases=aliases if aliases is not None else Aliases(),
                              company_statuses=company_statuses)


def test_reweighting_uses_each_portfolio_exposure_and_unions_duplicate_edges():
    before = analysis([(A, .6), (B, .4)])
    after = analysis([(A, .2), (B, .8)], "ZZSCEN")
    cached = {A: [edge(), edge(edge_id="zz-second")], B: []}
    original = [e.model_dump() for e in cached[A]]
    result = compare(before, after, cached)
    delta = next(d for d in result.dependency_deltas if d.metric_id.startswith("dep.") and d.unit == "fraction")
    assert (delta.baseline, delta.candidate, delta.delta) == pytest.approx((.6, .2, -.4))
    assert result.status == "ok" and result.candidate_unanalysed == []
    assert result.baseline_top_n_weight == result.candidate_top_n_weight == 1
    assert [e.model_dump() for e in cached[A]] == original
    CompareResponse.model_validate_json(result.model_dump_json())


def test_top_n_selection_is_independent_and_concentration_uses_full_analysis():
    before = analysis([(A, .6), (B, .3), (C, .1)])
    after = analysis([(B, .7), (A, .2), (C, .1)], "ZZSCEN")
    result = compare(before, after, {A: [edge()], B: [], C: [edge(C)]}, top_n=1)
    assert result.baseline_top_n_weight == .6
    assert result.candidate_top_n_weight == .7
    dep = next(d for d in result.dependency_deltas if d.metric_id.startswith("dep.") and d.unit == "fraction")
    assert dep.baseline == .6 and dep.candidate is None and dep.delta is None
    conc = {d.name: d for d in result.concentration_deltas}
    assert list(conc) == ["top5", "top10", "top20", "effective_n", "largest_company", "top_sector"]
    assert conc["top5"].baseline == conc["top5"].candidate == 1
    assert conc["effective_n"].baseline == pytest.approx(1/(.6**2+.3**2+.1**2))
    assert conc["effective_n"].candidate == pytest.approx(1/(.7**2+.2**2+.1**2))
    assert conc["largest_company"].delta == pytest.approx(.1)


@pytest.mark.parametrize(("baseline_sectors", "candidate_sectors", "expected"), [
    # Unsorted sectors, a different leading industry, and no renormalisation to known weight.
    ([("health_care", .1), ("information_technology", .5), ("unknown", .4)],
     [("information_technology", .1), ("unknown", .6), ("health_care", .3)], (.5, .3, -.2)),
    ([], [], (0, 0, 0)),
    ([("unknown", 1)], [("health_care", .25), ("unknown", .75)], (0, .25, .25)),
    ([("information_technology", .4), ("unknown", .6)], [], (.4, 0, -.4)),
])
def test_top_sector_uses_full_analysis_known_sectors(baseline_sectors, candidate_sectors, expected):
    before = analysis([(A, .6), (B, .4)])
    after = analysis([(B, .7), (A, .3)], "ZZSCEN")
    for side, sectors in ((before, baseline_sectors), (after, candidate_sectors)):
        side.sectors = [SectorExposure(sector=sector, weight=weight, by_etf=[]) for sector, weight in sectors]
    # Both company-level sectors are technology; the analysis sector breakdown is authoritative.
    result = compare(before, after, {}, top_n=1)
    delta = next(d for d in result.concentration_deltas if d.name == "top_sector")
    assert (delta.baseline, delta.candidate, delta.delta) == pytest.approx(expected)
    CompareResponse.model_validate_json(result.model_dump_json())


def test_cache_miss_is_partial_but_cached_empty_is_analysed():
    before = analysis([(A, .6), (B, .4)])
    after = analysis([(C, .5), (B, .3), (A, .2)], "ZZSCEN")
    result = compare(before, after, {A: [edge()], B: []}, top_n=3)
    assert result.status == "partial"
    assert [(c.company_key, c.exposure) for c in result.candidate_unanalysed] == [(C, .5)]
    assert any("Find dependencies" in note for note in result.notes)
    assert any("current portfolio" in note for note in compare(before, after, {B: []}).notes)
    complete = compare(before, after, {A: [], B: [], C: []}, top_n=3)
    assert complete.status == "ok" and complete.candidate_unanalysed == []


def test_one_sided_metrics_keep_null_and_sort_by_value():
    before = analysis([(A, .7), (B, .3)])
    after = analysis([(C, .8), (B, .2)], "ZZSCEN")
    result = compare(before, after, {A: [edge(target="ZZ Old Supply")], B: [],
                                      C: [edge(C, "ZZ New Supply", edge_id="zz-new")]})
    fractions = [d for d in result.dependency_deltas if d.metric_id.startswith("dep.") and d.unit == "fraction"]
    assert len(fractions) == 2
    assert fractions[0].candidate == .8 and fractions[0].baseline is None
    assert fractions[1].baseline == .7 and fractions[1].candidate is None
    assert all(d.delta is None for d in fractions)
    assert any("not treated as zero" in n for n in result.notes)


def test_fraction_changes_precede_counts_with_magnitude_and_deterministic_ties(monkeypatch):
    import hoc.portfolio.compare as module
    from hoc.contract import MetricFact

    before = analysis([(A, .6), (B, .4)])
    after = analysis([(B, .7), (A, .3)], "ZZSCEN")
    facts = [
        ("dep.ZZOLD", "fraction", .8, None),
        ("dep.ZZNEW", "fraction", None, .9),
        ("dep.ZZFALL", "fraction", .6, .2),
        ("facility.ZZRISE", "fraction", .1, .4),
        ("critical.ZZSTILL", "fraction", .5, .5),
        ("dep.ZZSTILL", "fraction", .5, .5),
        ("dep.ZZFALL.companies", "count", 5, 2),
        ("dep.ZZNEW.companies", "count", None, 2),
        ("spof.count", "count", 1, 1),
    ]

    def metrics(companies, edges):
        side = 2 if companies[0].company_key == A else 3
        return [MetricFact(metric_id=row[0], label=row[0], unit=row[1], value=row[side])
                for row in reversed(facts) if row[side] is not None]

    monkeypatch.setattr(module, "compute_dependency_metrics", metrics)
    result = compare(before, after, {A: [], B: []})
    assert [d.metric_id for d in result.dependency_deltas] == [
        "dep.ZZNEW", "dep.ZZOLD", "dep.ZZFALL", "facility.ZZRISE",
        "critical.ZZSTILL", "dep.ZZSTILL", "dep.ZZFALL.companies",
        "dep.ZZNEW.companies", "spof.count",
    ]
    assert result.dependency_deltas[0].baseline is None
    assert result.dependency_deltas[0].delta is None
    assert result.dependency_deltas[2].delta == pytest.approx(-.4)
    assert result.dependency_deltas[6].delta == -3


def test_known_no_sec_filing_is_named_separately_from_unknown_cache_misses():
    before = analysis([(A, .6), (C, .4)])
    after = analysis([(C, .5), (B, .3), (A, .2)], "ZZSCEN")
    result = compare(before, after, {A: []}, top_n=3, company_statuses={C: "no_sec_filing"})
    assert result.status == "partial"
    assert [c.company_key for c in result.candidate_unanalysed] == [C, B]
    assert any("ZZ Company 3 in the scenario has no SEC filing" in n for n in result.notes)
    assert any("ZZ Company 3 in the current portfolio has no SEC filing" in n for n in result.notes)
    assert any("1 scenario company" in n and "available SEC filings" in n for n in result.notes)
    assert not any("current portfolio also has" in n for n in result.notes)


def test_only_no_sec_filing_missing_does_not_promise_find_dependencies_will_fill_it():
    before = analysis([(A, 1)])
    after = analysis([(C, 1)], "ZZSCEN")
    result = compare(before, after, {A: []}, company_statuses={C: "no_sec_filing"})
    assert result.status == "partial" and result.candidate_unanalysed[0].company_key == C
    assert any("has no SEC filing" in n for n in result.notes)
    assert not any("Find dependencies" in n or "without a cached extraction" in n for n in result.notes)


def test_unknown_filing_availability_is_not_inferred_from_company_key():
    key = "ALIAS:ZZNONUS"
    before = analysis([(A, 1)])
    after = analysis([(key, 1)], "ZZSCEN")
    result = compare(before, after, {A: []})
    assert result.status == "partial"
    assert not any("has no SEC filing" in n for n in result.notes)
    assert any("available SEC filings" in n for n in result.notes)


def test_alias_resolution_replaces_stale_cached_keys_and_respects_portfolio_priority():
    before = analysis([(A, .6), (B, .4)])
    after = analysis([(A, .6), (C, .4)], "ZZSCEN")
    aliases = aliases_from_entries([{"id": "ZZTARGET", "company_name": "ZZ Company 2",
                                    "identifiers": ["ZZTARGET"], "note": "Synthetic test alias"}])
    result = compare(before, after, {A: [edge(target="ZZ Company 2")], B: [], C: []}, aliases=aliases)
    ids = {d.metric_id for d in result.dependency_deltas}
    assert f"dep.{B}" in ids and "dep.ALIAS:ZZTARGET" in ids
    assert not any("STALE_PORTFOLIO" in i for i in ids)


def test_facility_countries_union_and_rejected_or_foreign_source_edges_do_not_count():
    before = analysis([(A, .6), (B, .4)])
    after = analysis([(A, .3), (B, .7)], "ZZSCEN")
    facility = edge(target="Taiwan", kind="facility", target_kind="country", target_key=None)
    rejected = edge(edge_id="zz-rejected", interpretation=EdgeInterpretation(
        status="rejected", method="rules", flags=["competitor_mention"]))
    result = compare(before, after, {A: [facility, facility.model_copy(update={"edge_id": "zz-site-2"}),
                                       rejected, edge(B)], B: []})
    country = next(d for d in result.dependency_deltas if d.metric_id == "facility.TW")
    assert (country.baseline, country.candidate, country.delta) == pytest.approx((.6, .3, -.3))
    assert not any(d.metric_id.startswith("dep.") for d in result.dependency_deltas)


def test_invalid_allocations_and_mismatched_analysis_are_rejected():
    before = analysis([(A, 1)])
    after = analysis([(B, 1)], "ZZSCEN")
    req = request(before, after)
    req.baseline[0].allocation = .5
    with pytest.raises(PortfolioValidationError):
        compare_portfolios(req, before, after, {})
    req = request(analysis([(A, 1)]), after)
    req.baseline[0].ticker = "ZZOTHER"
    with pytest.raises(ValueError, match="correspond"):
        compare_portfolios(req, analysis([(A, 1)]), after, {})


def put(cache, source=A, *, edges=None, filed="2026-10-30", accession="9990000001-26-000001",
        model=MODEL, version=VERSION):
    cache.put(source, accession, model=model, prompt_version=version, payload={
        "company_key": source, "accession": accession, "filed": filed,
        "model": model, "prompt_version": version,
        "edges": [e.model_dump(mode="json") for e in (edges or [])],
        "raw_edges": [{"target_name": "ZZ Unverified Prediction"}],
    })


def read(tmp_path, keys=(A, B), models=(MODEL, "fallback")):
    return read_cached_extractions(tmp_path, keys, models=models, prompt_version=VERSION)


def test_disk_reader_uses_verified_edges_including_keyless_empty_cache(tmp_path):
    cache = ExtractionCache(DiskCache(tmp_path))
    put(cache, edges=[edge()])
    put(cache, B)
    result = read(tmp_path)
    assert set(result) == {A, B} and result[B] == []
    assert result[A] == [edge()]
    assert "Unverified" not in result[A][0].target_name
    assert read(tmp_path, (C,)) == {}


def test_disk_reader_chooses_latest_filing_then_model_preference(tmp_path):
    cache = ExtractionCache(DiskCache(tmp_path))
    old = edge()
    new_filing = old.filing.model_copy(update={"accession": "9990000001-26-000002", "filed": date(2026, 11, 1)})
    new = old.model_copy(update={"edge_id": "zz-latest", "filing": new_filing})
    put(cache, edges=[old])
    put(cache, edges=[new], filed="2026-11-01", accession=new_filing.accession, model="fallback")
    assert read(tmp_path)[A] == [new]
    put(cache, filed="2026-11-01", accession=new_filing.accession)
    assert read(tmp_path)[A] == []  # preferred model's explicit no-disclosure result
    put(cache, C, version="other-prompt")
    assert C not in read(tmp_path, (A, B, C))


def test_disk_reader_ignores_corruption_wrong_sources_and_raw_only_payloads(tmp_path):
    cache = ExtractionCache(DiskCache(tmp_path))
    put(cache, edges=[edge(B)])  # cannot attribute a different filer's relationships to A
    assert read(tmp_path) == {}
    cache.put(A, "raw-only", model=MODEL, prompt_version=VERSION, payload={
        "company_key": A, "accession": "raw-only", "filed": "2026-11-01", "model": MODEL,
        "prompt_version": VERSION, "raw_edges": [{"target_name": "ZZ Made Up"}],
    })
    folder = tmp_path / "ai/extractions"
    (folder / "broken.json").write_text("not JSON")
    (folder / "bad-shape.json").write_text("[]")
    assert read(tmp_path) == {}


def test_disk_reader_removes_rejected_interpretations(tmp_path):
    cache = ExtractionCache(DiskCache(tmp_path))
    rejected = edge(interpretation=EdgeInterpretation(status="rejected", method="rules", flags=[]))
    put(cache, edges=[rejected])
    assert read(tmp_path) == {A: []}


def test_critical_metrics_are_forwarded_when_graph_emits_them(monkeypatch):
    # X-API must compare new metric namespaces without a model call or hand-written scoring.
    import hoc.portfolio.compare as module
    from hoc.contract import MetricFact
    monkeypatch.setattr(module, "compute_dependency_metrics", lambda companies, edges: [
        MetricFact(metric_id="critical.ZZSUPPLY", label="ZZ critical exposure",
                   value=companies[0].exposure, unit="fraction"),
        MetricFact(metric_id="summary.verified_edges", label="ZZ summary", value=1, unit="count"),
    ])
    result = compare(analysis([(A, .6), (B, .4)]), analysis([(B, .7), (A, .3)], "ZZSCEN"), {A: [], B: []})
    assert len(result.dependency_deltas) == 1
    assert result.dependency_deltas[0].metric_id == "critical.ZZSUPPLY"
    assert result.dependency_deltas[0].delta == pytest.approx(.1)
