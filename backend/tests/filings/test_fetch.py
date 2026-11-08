"""G-DOC: finding and reading the latest 10-K/20-F, over SYNTHETIC SEC answers (FakeHttpClient, no network)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from hoc.config import Settings
from hoc.contract import CompanyUnavailable
from hoc.core.http import FakeHttpClient
from hoc.filings.fetch import ARCHIVE_URL, SUBMISSIONS_URL, TICKERS_URL, FilingFetcher, FilingUnavailable

CIK = "9990000001"
FILLER = "We design widgets for industrial customers. " * 60
DOC = (f"<html><body><p>Item 1. Business</p><p>We buy wafers from ZZ Foundry Ltd. {FILLER}</p>"
       f"<p>Item 1A. Risk Factors</p><p>ZZ Optics is our sole source of lenses. {FILLER}</p>"
       f"<p>Item 2. Properties</p><p>Our plants are in Arizona. {FILLER}</p><p>Item 3. Legal</p></body></html>")


def submissions(*rows):
    forms, accs, dates, docs = zip(*rows, strict=True)
    return json.dumps({"filings": {"recent": {"form": list(forms), "accessionNumber": list(accs),
                                              "filingDate": list(dates), "primaryDocument": list(docs)}}})


def http_with(rows=(("10-K", "0000999-26-000002", "2026-02-01", "zz-10k.htm"),
                    ("8-K", "0000999-26-000003", "2026-03-01", "zz-8k.htm"),
                    ("10-K", "0000999-25-000001", "2025-02-01", "zz-old.htm"))):
    http = FakeHttpClient()
    http.add(SUBMISSIONS_URL.format(cik=CIK), submissions(*rows))
    http.add(ARCHIVE_URL.format(cik=int(CIK), accession="000099926000002", document="zz-10k.htm"), DOC)
    http.add(TICKERS_URL, json.dumps({"0": {"cik_str": int(CIK), "ticker": "ZZALP", "title": "ZZ Alpha Corp"}}))
    return http


SETTINGS = replace(Settings(), sec_contact="tests@example.invalid")


def test_latest_10k_with_sections_and_hash():
    http = http_with()
    filing = FilingFetcher(http, SETTINGS).latest(CIK)
    assert (filing.form, filing.accession, filing.filed) == ("10-K", "0000999-26-000002", date(2026, 2, 1))
    assert filing.quality == "sections" and {"1", "1A", "2"} <= set(filing.sections)
    texts = filing.section_texts()
    assert "We buy wafers from ZZ Foundry Ltd." in texts["1"] and "sole source of lenses" in texts["1A"]
    assert len(filing.sha256) == 64 and "ZZ Optics is our sole source" in filing.text


def test_memoised_per_accession():
    http = http_with()
    fetcher = FilingFetcher(http, SETTINGS)
    assert fetcher.latest(CIK) is fetcher.latest(CIK)
    assert sum("zz-10k.htm" in url for _, url in http.requests) == 1


def test_for_company_by_cik_key_and_by_us_symbol():
    fetcher = FilingFetcher(http_with(), SETTINGS)
    by_key = fetcher.for_company(SimpleNamespace(company_key=f"CIK:{CIK}", symbols=["ZZALP"]))
    by_symbol = fetcher.for_company(SimpleNamespace(company_key="SYM:ZZALP", symbols=["ZZALP"]))
    assert by_key.accession == by_symbol.accession


@pytest.mark.parametrize(("key", "symbols", "status"), [
    ("ALIAS:SAMSUNG_ELEC", ["005930.KR"], "no_sec_filing"),
    ("SYM:ZZNOPE", ["ZZNOPE"], "no_sec_filing"),
])
def test_companies_without_a_sec_filer(key, symbols, status):
    with pytest.raises(FilingUnavailable) as exc:
        FilingFetcher(http_with(), SETTINGS).for_company(SimpleNamespace(company_key=key, symbols=symbols))
    assert exc.value.status == status


def test_unsupported_form_and_no_annual_report():
    with pytest.raises(FilingUnavailable) as exc:
        FilingFetcher(http_with([("40-F", "0000999-26-000009", "2026-03-01", "zz-40f.htm")]), SETTINGS).latest(CIK)
    assert exc.value.status == "unsupported_form"
    with pytest.raises(FilingUnavailable) as exc:
        FilingFetcher(http_with([("6-K", "0000999-26-000009", "2026-03-01", "zz-6k.htm")]), SETTINGS).latest(CIK)
    assert exc.value.status == "no_sec_filing"


def test_no_sec_contact_means_no_request():
    http = http_with()
    with pytest.raises(FilingUnavailable) as exc:
        FilingFetcher(http, Settings()).latest(CIK)
    assert exc.value.status == "sec_contact_missing" and http.requests == []
    assert isinstance(exc.value, CompanyUnavailable) and exc.value.message.startswith("Set HOC_SEC_CONTACT")


def test_sec_errors_become_error_status():
    http = FakeHttpClient()
    http.add(SUBMISSIONS_URL.format(cik=CIK), "busy", status=503)
    with pytest.raises(FilingUnavailable) as exc:
        FilingFetcher(http, SETTINGS).latest(CIK)
    assert exc.value.status == "error"
    http = FakeHttpClient()
    http.add(SUBMISSIONS_URL.format(cik=CIK), json.dumps({"filings": {}}))
    with pytest.raises(FilingUnavailable) as exc:
        FilingFetcher(http, SETTINGS).latest(CIK)
    assert exc.value.status == "error"


@pytest.mark.live
def test_live_nvidia_10k_names_its_foundry(tmp_path):
    import os

    from hoc.core.cache import DiskCache
    from hoc.core.http import CachedHttpClient

    if not os.environ.get("HOC_SEC_CONTACT"):
        pytest.skip("set HOC_SEC_CONTACT to fetch real SEC filings")
    settings = replace(Settings.from_env(), cache_dir=tmp_path)
    fetcher = FilingFetcher(CachedHttpClient(settings, DiskCache(tmp_path)), settings)
    filing = fetcher.for_company(SimpleNamespace(company_key="CIK:0001045810", symbols=["NVDA"]))
    assert filing.form == "10-K" and filing.quality == "sections"
    assert "foundr" in filing.section_texts()["1"].lower()


def efts_route(name):
    from hoc.filings.fetch import EFTS_URL
    return f'{EFTS_URL}?forms=10-K,20-F&q="{name}"'


def hit(cik, form, accession, filed, document):
    return {"_id": f"{accession}:{document}", "_source": {"ciks": [cik], "form": form, "file_date": filed}}


def test_names_in_other_filings_one_per_filer_newest_excluding_self():
    http = http_with()
    other = "9990000077"
    hits = [hit(CIK, "10-K", "0000999-26-000002", "2026-02-01", "zz-10k.htm"),  # the company itself
            hit(other, "10-K", "0000777-26-000001", "2026-01-15", "other-10k.htm"),
            hit(other, "10-K", "0000777-25-000001", "2025-01-15", "other-old.htm"),  # older year, same filer
            hit("9990000088", "8-K", "0000888-26-000001", "2026-03-01", "x-8k.htm")]  # not an annual report
    http.add(efts_route("ZZ Foundry Ltd"), json.dumps({"hits": {"hits": hits}}))
    http.add(ARCHIVE_URL.format(cik=int(other), accession="000077726000001", document="other-10k.htm"),
             "<p>Item 1. Business</p><p>We buy wafers from ZZ Foundry Ltd.</p>")
    filings = FilingFetcher(http, SETTINGS).names_in_other_filings("ZZ Foundry Ltd", exclude_cik=CIK)
    assert [(f.cik, f.accession) for f in filings] == [(other, "0000777-26-000001")]
    assert "We buy wafers from ZZ Foundry Ltd." in filings[0].text and filings[0].quality == "fallback"


def test_names_in_other_filings_caps_hits_and_skips_unreadable_ones():
    http = http_with()
    hits = [hit(f"99900001{i:02d}", "10-K", f"0001{i:02d}-26-000001", f"2026-01-{i + 1:02d}", "d.htm") for i in range(15)]
    http.add(efts_route("ZZ Optics"), json.dumps({"hits": {"hits": hits}}))
    for i in range(1, 15):  # the newest hit (i=14) and one more (i=0) have no document route
        if i != 14:
            http.add(ARCHIVE_URL.format(cik=int(f"99900001{i:02d}"), accession=f"0001{i:02d}26000001", document="d.htm"),
                     "<p>ZZ Optics supplies lenses.</p>")
    filings = FilingFetcher(http, SETTINGS).names_in_other_filings("ZZ Optics", limit=10)
    assert len(filings) == 10 and filings[0].cik == "9990000113"


def test_efts_failures_and_sec_titles():
    http = http_with()
    http.add(efts_route("ZZ Bad"), json.dumps({"hits": {"hits": [{"_id": "no-colon"}]}}))
    with pytest.raises(FilingUnavailable) as exc:
        FilingFetcher(http, SETTINGS).names_in_other_filings("ZZ Bad")
    assert exc.value.status == "error"
    assert FilingFetcher(http, SETTINGS).sec_titles() == {"ZZ Alpha Corp": CIK}
