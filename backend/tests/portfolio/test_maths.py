"""Maths tests use only the labelled SYNTHETIC ZZ fixtures.

The local projection builds contract inputs without depending on package d's
normaliser, so failures here isolate portfolio arithmetic.
"""

from datetime import UTC, datetime
from itertools import combinations

import pytest

from hoc.contract import (
    EtfFailure,
    EtfHoldings,
    ExcludedLine,
    NormalisedHolding,
    PortfolioRequest,
    PortfolioValidationError,
    Sector,
    wsum,
)
from hoc.portfolio.analyse import analyse
from hoc.portfolio.sectors import etf_sectors
from hoc.portfolio.validation import validate_request

NOW = datetime(2026, 11, 7, 12, tzinfo=UTC)
TODAY = NOW.date()


@pytest.fixture
def funds(fake_source, fake_reference):
    result = {}
    for ticker in ("ZZAAA", "ZZBBB", "ZZCCC"):
        raw = fake_source.fetch(ticker)
        reference = fake_reference.lookup_symbols(
            [line.source_symbol for line in raw.holdings if line.source_symbol]
        )
        lines, excluded = [], []
        for line in raw.holdings:
            if line.asset_class in ("cash", "derivative", "fx"):
                excluded.append(
                    ExcludedLine(name=line.name, weight=line.weight, asset_class=line.asset_class)
                )
                continue
            info = reference.get(line.source_symbol)
            symbol = line.source_symbol
            key = f"SYM:{symbol}" if symbol else f"NAME:{line.name}"
            company = f"CIK:{info.cik}" if info and info.cik else key
            if symbol in ("ZZEPS", "9999.TW"):
                company = "ALIAS:ZZEPSILON"
            label = line.sector_label or (info.sector_label if info else None)
            sector = {
                "Information Technology": Sector.information_technology,
                "Financials": Sector.financials,
                "Health Care": Sector.health_care,
                "Energy": Sector.energy,
                "Materials": Sector.materials,
            }.get(label, Sector.unknown)
            lines.append(
                NormalisedHolding(
                    etf_ticker=ticker,
                    security_key=key,
                    security_id=symbol or line.name,
                    security_id_type="symbol" if symbol else "name",
                    symbol=symbol,
                    name=line.name,
                    company_key=company,
                    company_name=info.name if info else line.name,
                    company_key_basis="cik"
                    if company.startswith("CIK:")
                    else ("alias" if company.startswith("ALIAS:") else "name"),
                    identity_status="resolved" if info else "unmatched",
                    weight=line.weight,
                    sector=sector,
                    asset_class=line.asset_class,
                    source="fake",
                    as_of=raw.as_of,
                )
            )
        result[ticker] = EtfHoldings(
            etf_ticker=ticker,
            etf_name=raw.etf_name,
            source="fake",
            as_of=raw.as_of,
            retrieved_at=raw.retrieved_at,
            source_url=raw.source_url,
            attribution=raw.attribution,
            holdings=lines,
            excluded=excluded,
            reported_weight=wsum(line.weight for line in raw.holdings),
            holdings_weight=wsum(line.weight for line in lines),
            excluded_weight=wsum(line.weight for line in excluded),
            unmatched_weight=wsum(line.weight for line in lines if line.identity_status == "unmatched"),
            raw_line_count=len(raw.holdings),
            normaliser_version="synthetic-test",
        )
    return result


def request(weights=None, **kwargs):
    weights = weights or {"ZZAAA": 0.5, "ZZBBB": 0.5}
    return PortfolioRequest(holdings=[{"ticker": t, "allocation": a} for t, a in weights.items()], **kwargs)


def run(funds, req=None, failures=None):
    return analyse(req or request(), funds, failures or {}, today=TODAY, generated_at=NOW)


@pytest.mark.parametrize(
    "weights,code",
    [
        ({"ZZAAA": 0.8}, "ALLOCATION_SUM_INVALID"),
        ({"ZZAAA": 0.5, "zzaaa": 0.5}, "DUPLICATE_TICKER"),
        ({f"ZZ{i}": 1 / 11 for i in range(11)}, "TOO_MANY_ETFS"),
    ],
)
def test_validation_errors(weights, code):
    with pytest.raises(PortfolioValidationError) as error:
        validate_request(request(weights))
    assert error.value.code == code


def test_validation_tolerance_and_zero():
    assert validate_request(request({"ZZAAA": 0.99995})) == []
    with pytest.raises(PortfolioValidationError) as error:
        validate_request(request({"ZZAAA": 0.9998}))
    assert error.value.details == {"total": 0.9998, "tolerance": 1e-4}
    assert validate_request(request({"ZZAAA": 1, "ZZBBB": 0}))[0].code == "ZERO_ALLOCATION"


def test_golden_company_exposure_overlap_and_coverage(funds):
    result = run(funds)
    by_key = {value.company_key: value for value in result.exposures}
    alpha = by_key["CIK:9990000001"]
    beta = by_key["CIK:9990000002"]
    assert alpha.exposure == pytest.approx(0.35)
    assert beta.exposure == pytest.approx(0.25)
    assert len(beta.securities) == 2
    assert [v.contribution for v in beta.contributions] == pytest.approx([0.15, 0.10])
    pair = result.overlap.pairs[0]
    assert pair.weighted_overlap == pytest.approx(0.50)
    assert pair.weighted_overlap_securities == pytest.approx(0.40)
    assert (pair.shared_companies, pair.shared_securities) == (2, 2)
    assert result.overlap.matrix == [[0.95, 0.5], [0.5, 0.98]]
    assert result.coverage.covered_weight == pytest.approx(0.965)
    assert result.coverage.excluded_weight == pytest.approx(0.035)
    assert result.coverage.unexplained_weight == pytest.approx(0)
    assert wsum(v.exposure for v in result.exposures) == pytest.approx(0.965)
    expected = [0.35, 0.25, 0.125, 0.10, 0.11, 0.03]
    assert result.concentration.hhi == pytest.approx(wsum((v / 0.965) ** 2 for v in expected))
    assert result.concentration.effective_companies == pytest.approx(1 / result.concentration.hhi)
    assert result.concentration.distinct_securities == 7
    assert result.concentration.distinct_companies == 6


def test_alias_overlap_and_duplicate_security_lines(funds):
    result = run(funds, request({"ZZBBB": 0.5, "ZZCCC": 0.5}))
    pair = result.overlap.pairs[0]
    assert pair.weighted_overlap == pytest.approx(0.22)
    assert pair.weighted_overlap_securities == 0
    assert pair.shared_companies == 1
    assert pair.shared_securities == 0
    gamma = next(v for v in result.exposures if v.company_key == "CIK:9990000003")
    assert len(gamma.securities) == 1
    assert gamma.exposure == pytest.approx(0.125)


def test_truncation_preserves_full_metrics(funds):
    full = run(funds)
    short = run(funds, request(max_companies=1))
    assert short.exposures_truncated
    assert short.concentration == full.concentration
    assert wsum([short.exposures[0].exposure, short.other_exposure]) == pytest.approx(
        short.coverage.covered_weight
    )


def test_missing_etf_and_zero_allocation_overlap(funds):
    failure = EtfFailure(etf_ticker="ZZBBB", status="unavailable", message="Synthetic unavailable")
    result = run({"ZZAAA": funds["ZZAAA"]}, failures={"ZZBBB": failure})
    assert result.coverage.missing_allocation == 0.5
    assert result.coverage.covered_weight == pytest.approx(0.475)
    assert result.etfs[1].status == "unavailable"
    assert any(g.kind == "missing_etf" and g.severity == "critical" for g in result.gaps)
    zero = run(funds, request({"ZZAAA": 1, "ZZBBB": 0}))
    assert zero.overlap.etfs == ["ZZAAA", "ZZBBB"]
    assert zero.overlap.pairs[0].weighted_overlap == pytest.approx(0.5)
    assert zero.coverage.covered_weight == pytest.approx(0.95)


def test_empty_and_negative_holdings(funds):
    empty = funds["ZZAAA"].model_copy(update={"holdings": [], "holdings_weight": 0})
    result = run({"ZZAAA": empty}, request({"ZZAAA": 1}))
    assert result.concentration.hhi == result.concentration.effective_companies == 0
    assert result.concentration.distinct_companies == 0
    assert result.exposures == []
    negative = funds["ZZAAA"].holdings[0].model_copy(update={"weight": -0.3})
    altered = funds["ZZAAA"].model_copy(update={"holdings": [negative], "holdings_weight": -0.3})
    result = run({**funds, "ZZAAA": altered})
    assert result.overlap.pairs[0].weighted_overlap == 0
    assert result.concentration.distinct_securities == result.concentration.distinct_companies


@pytest.mark.parametrize("days,severity", [(35, None), (36, "info"), (100, "info"), (101, "warning")])
def test_staleness_boundaries(funds, days, severity):
    from datetime import timedelta

    etf = funds["ZZAAA"].model_copy(update={"as_of": TODAY - timedelta(days=days)})
    result = run({"ZZAAA": etf}, request({"ZZAAA": 1}))
    stale = [g for g in result.gaps if g.kind == "stale_disclosure"]
    assert ([g.severity for g in stale] or [None]) == [severity]
    assert result.etfs[0].status == ("warning" if severity == "warning" else "ok")


def test_sector_holdings_fallback_scaling_and_none(funds):
    etf = funds["ZZAAA"]
    basis, weights = etf_sectors(etf)
    assert basis == "holdings"
    assert wsum(weights.values()) == pytest.approx(0.95)
    unknown = [line.model_copy(update={"sector": Sector.unknown}) for line in etf.holdings]
    fallback = etf.model_copy(
        update={
            "holdings": unknown,
            "sector_basis": "fund_reported",
            "sector_weights": {Sector.energy: 0.8, Sector.financials: 0.4},
        }
    )
    basis, weights = etf_sectors(fallback)
    assert basis == "fund_reported"
    assert weights[Sector.energy] == pytest.approx(0.95 * 2 / 3)
    assert wsum(weights.values()) == pytest.approx(0.95)
    remainder = fallback.model_copy(update={"sector_weights": {Sector.energy: 0.5}})
    assert etf_sectors(remainder)[1][Sector.unknown] == pytest.approx(0.45)
    assert etf_sectors(etf.model_copy(update={"holdings": unknown}))[0] == "none"
    result = run(funds)
    assert wsum(s.weight for s in result.sectors) == pytest.approx(result.coverage.covered_weight)


def test_gap_aggregation_and_nested_fund(funds):
    etf = funds["ZZAAA"]
    lines = [
        line.model_copy(
            update={
                "identity_status": "unmatched",
                "asset_class": "fund",
                "weight": 0.0001,
            }
        )
        for line in etf.holdings
    ]
    lines[0] = lines[0].model_copy(update={"weight": 0.0005})
    etf = etf.model_copy(update={"holdings": lines})
    result = run({"ZZAAA": etf}, request({"ZZAAA": 1}))
    for kind in ("nested_fund", "unmatched_identity"):
        gaps = [g for g in result.gaps if g.kind == kind]
        assert len(gaps) == 2
        assert gaps[0].subject is not None
        assert gaps[0].portfolio_weight == 0.0005
        assert gaps[1].subject is None
        assert gaps[1].portfolio_weight == pytest.approx(0.0004)


def test_reordering_is_deterministic_and_reconciles(funds):
    original = run(funds)
    reversed_funds = {
        ticker: etf.model_copy(update={"holdings": list(reversed(etf.holdings))})
        for ticker, etf in reversed(list(funds.items()))
    }
    assert run(reversed_funds).model_dump_json() == original.model_dump_json()
    for pair in combinations(funds, 2):
        result = run(funds, request({ticker: 0.5 for ticker in pair}))
        coverage = result.coverage
        assert wsum(
            [
                coverage.covered_weight,
                coverage.excluded_weight,
                coverage.missing_allocation,
                coverage.unexplained_weight,
            ]
        ) == pytest.approx(1)
        assert result.concentration.distinct_securities >= result.concentration.distinct_companies
