"""Package d: normalisation and identity, on SYNTHETIC fixtures only."""

from __future__ import annotations

import json

import pytest

from hoc.contract import RawEtfHoldings, Sector, wsum
from hoc.identity.resolver import Aliases, aliases_from_entries, clean_company_name, load_aliases
from hoc.normalise.pipeline import map_sector, normalise_etf


@pytest.fixture
def aliases(synthetic_dir):
    data = json.loads((synthetic_dir / "reference.json").read_text(encoding="utf-8"))
    return aliases_from_entries(data["aliases_for_tests"])


def norm(fake_source, fake_reference, aliases, ticker):
    return normalise_etf(fake_source.fetch(ticker), fake_reference, aliases)


def by_symbol(etf):
    return {h.symbol or h.name: h for h in etf.holdings}


def test_share_classes_merge_by_cik_and_cash_is_excluded(fake_source, fake_reference, aliases):
    etf = norm(fake_source, fake_reference, aliases, "ZZAAA")
    h = by_symbol(etf)
    assert h["ZZBET.A"].company_key == h["ZZBET.B"].company_key == "CIK:9990000002"
    assert h["ZZBET.A"].security_key != h["ZZBET.B"].security_key
    assert h["ZZBET.A"].company_name == h["ZZBET.B"].company_name
    assert [e.asset_class for e in etf.excluded] == ["cash"]
    assert etf.excluded_weight == pytest.approx(0.05)
    assert etf.holdings_weight == pytest.approx(0.95)
    assert etf.reported_weight == pytest.approx(1.0)
    assert etf.sector_basis == "holdings"
    assert wsum(etf.sector_weights.values()) == pytest.approx(etf.holdings_weight)
    assert [x.weight for x in etf.holdings] == sorted((x.weight for x in etf.holdings), reverse=True)


def test_alias_merges_adr_with_local_listing(fake_source, fake_reference, aliases):
    adr = by_symbol(norm(fake_source, fake_reference, aliases, "ZZCCC"))["ZZEPS"]
    local = by_symbol(norm(fake_source, fake_reference, aliases, "ZZBBB"))["9999.TW"]
    assert adr.company_key == local.company_key == "ALIAS:ZZEPSILON"
    assert adr.company_name == local.company_name == "ZZ Epsilon Semiconductor"
    assert adr.identity_status == "resolved"


def test_unmatched_line_kept_and_fund_sectors_used(fake_source, fake_reference, aliases):
    etf = norm(fake_source, fake_reference, aliases, "ZZBBB")
    unnamed = by_symbol(etf)["ZZ Unnamed Private Co"]
    assert (unnamed.company_key, unnamed.identity_status) == ("NAME:ZZ UNNAMED PRIVATE CO", "unmatched")
    assert etf.unmatched_weight == pytest.approx(0.06)
    assert etf.excluded_weight == pytest.approx(0.02)
    # 9999.TW (0.22) and the unnamed line have no line sector; reference covers 9999.TW only -> < 95%
    assert etf.sector_basis == "fund_reported"
    assert etf.sector_weights[Sector.information_technology] == pytest.approx(0.62)
    assert wsum(etf.sector_weights.values()) == pytest.approx(etf.holdings_weight)


def test_duplicates_merge_and_isin_lei_identity(fake_source, fake_reference, aliases):
    etf = norm(fake_source, fake_reference, aliases, "ZZCCC")
    gam = [h for h in etf.holdings if h.symbol == "ZZGAM"]
    assert len(gam) == 1 and gam[0].weight == pytest.approx(0.25)
    zeta = by_symbol(etf)["ZZ Zeta Mining"]
    assert (zeta.security_key, zeta.security_id_type) == ("ISIN:ZZ0000000ZT1", "isin")
    assert zeta.company_key == "LEI:9999000000000000ZETA"
    assert etf.raw_line_count == 5 and len(etf.holdings) == 3


def test_percent_inputs_are_rejected(fake_source, fake_reference, aliases):
    raw = fake_source.fetch("ZZAAA")
    pct = RawEtfHoldings.model_validate(
        raw.model_dump() | {"holdings": [h.model_dump() | {"weight": h.weight * 100} for h in raw.holdings]})
    with pytest.raises(ValueError, match="percent"):
        normalise_etf(pct, fake_reference, aliases)


def test_us_isin_falls_back_to_issuer_prefix(fake_source, fake_reference):
    raw = fake_source.fetch("ZZAAA")
    line = raw.holdings[0].model_copy(update={"source_symbol": None, "isin": "US9999990001"})
    etf = normalise_etf(raw.model_copy(update={"holdings": [line]}), fake_reference, Aliases())
    assert etf.holdings[0].company_key == "ISSUER:US999999"


def test_deterministic(fake_source, fake_reference, aliases):
    a = norm(fake_source, fake_reference, aliases, "ZZCCC").model_dump_json()
    assert a == norm(fake_source, fake_reference, aliases, "ZZCCC").model_dump_json()


def test_sector_labels():
    assert map_sector("Information Technology") is Sector.information_technology
    assert map_sector("Consumer Cyclical") is Sector.consumer_discretionary
    assert map_sector("health_care") is Sector.health_care
    assert map_sector("tech") is Sector.information_technology  # R3 tokens
    assert map_sector("Telecom") is Sector.communication_services
    assert map_sector("Communication") is Sector.communication_services
    assert map_sector("Cash and/or Derivatives") is Sector.unknown


def test_aliases_file_loads_and_validates():
    load_aliases()
    with pytest.raises(ValueError, match="note"):
        aliases_from_entries([{"id": "X", "company_name": "X", "identifiers": ["A"]}])
    with pytest.raises(ValueError, match="two aliases"):
        aliases_from_entries([{"id": "X", "company_name": "X", "identifiers": ["A"], "note": "n"},
                              {"id": "Y", "company_name": "Y", "identifiers": ["A"], "note": "n"}])


@pytest.mark.parametrize(("raw", "clean"), [
    ("Alphabet Inc. (Class A)", "Alphabet Inc."), ("Berkshire Hathaway Class B", "Berkshire Hathaway"),
    ("Fox Corp Cl A", "Fox Corp"), ("News Corp - A", "News Corp"), ("Baidu Inc ADR", "Baidu Inc"),
    ("Shell PLC - Sponsored ADR", "Shell PLC"), ("Samsung Electronics Pref", "Samsung Electronics"),
    ("Acme Ordinary Shares", "Acme"), ("Crossroads", "Crossroads"), ("Subclass A", "Subclass A"), ("ADR", "ADR"),
])
def test_clean_company_name(raw, clean):
    assert clean_company_name(raw) == clean


def test_company_name_prefers_longest_clean_name(fake_source, fake_reference, aliases):
    raw = fake_source.fetch("ZZAAA")
    lines = [h.model_copy(update={"name": n}) if h.source_symbol in ("ZZBET.A", "ZZBET.B") else h
             for h, n in zip(raw.holdings, ["", "ZZ Beta Hold (Class A)", "ZZ Beta Holdings Class B", "", "", ""],
                             strict=True)]
    etf = normalise_etf(raw.model_copy(update={"holdings": lines}), fake_reference, aliases)
    assert {h.company_name for h in etf.holdings if h.company_key == "CIK:9990000002"} == {"ZZ Beta Holdings"}
