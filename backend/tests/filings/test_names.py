"""G-DOC: deterministic counterparty name -> company_key. Synthetic portfolio, real-style names."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hoc.filings.names import NameResolver, name_key
from hoc.identity.resolver import aliases_from_entries, load_aliases


def company(key, name, *symbols):
    return SimpleNamespace(company_key=key, company_name=name, symbols=list(symbols))


PORTFOLIO = [
    company("ALIAS:TSMC", "Taiwan Semiconductor Manufacturing Co., Ltd.", "2330.TW"),
    company("ALIAS:SAMSUNG_ELEC", "Samsung Electronics Co., Ltd.", "005930.KR", "005935.KR"),
    company("CIK:0000723125", "Micron Technology", "MU"),
    company("CIK:0000789019", "Microsoft", "MSFT"),
    company("SYM:2303.TW", "United Microelectronics Corp", "2303.TW"),
]


@pytest.mark.parametrize(("name", "key"), [
    ("Taiwan Semiconductor Manufacturing Company Limited", "ALIAS:TSMC"),
    ("TSMC", "ALIAS:TSMC"),
    ("Taiwan Semiconductor Manufacturing Co., Ltd.", "ALIAS:TSMC"),
    ("Samsung Electronics Co., Ltd.", "ALIAS:SAMSUNG_ELEC"),
    ("Samsung", "ALIAS:SAMSUNG_ELEC"),
    ("Micron Technology, Inc.", "CIK:0000723125"),
    ("MICROSOFT CORPORATION", "CIK:0000789019"),
    ("United Microelectronics Corporation", "SYM:2303.TW"),
    ("UMC", "SYM:2303.TW"),
    ("contract manufacturers", None),
    ("Micron", None),  # no fuzzy/prefix matching
])
def test_portfolio_names_resolve_exactly(name, key):
    assert NameResolver(PORTFOLIO).resolve(name) == key


def test_aliases_then_sec_titles_for_companies_outside_the_portfolio():
    aliases = aliases_from_entries([{"id": "ZZFOX", "company_name": "Hon Hai Precision Industry Co., Ltd.",
                                     "identifiers": ["2317.TW"], "note": "synthetic"}])
    resolver = NameResolver(PORTFOLIO, aliases, sec_titles={"ZZ OPTICS AG": "9990000042"})
    assert resolver.resolve("Foxconn") == resolver.resolve("Hon Hai Precision Industry") == "ALIAS:ZZFOX"
    assert resolver.resolve("ZZ Optics") == "CIK:9990000042"


def test_portfolio_wins_over_sec_titles_and_ambiguity_stays_unresolved():
    resolver = NameResolver(PORTFOLIO, sec_titles={"MICRON TECHNOLOGY INC": "0000000001"})
    assert resolver.resolve("Micron Technology Inc") == "CIK:0000723125"
    twins = [company("SYM:ZZA", "ZZ Twin Holdings"), company("SYM:ZZB", "ZZ Twin Holdings Inc")]
    assert NameResolver(twins).resolve("ZZ Twin Holdings") is None


def test_name_key_and_real_aliases_file():
    assert name_key("The Coca-Cola Company") == "coca cola"
    assert name_key("Alphabet Inc. (Class A)") == "alphabet"
    assert NameResolver([], load_aliases()).resolve("Taiwan Semiconductor Manufacturing Company Limited") == "ALIAS:TSMC"
