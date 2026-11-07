"""Synthetic issuer replicas only; ZZ tickers are not downloaded fund data."""
import csv
import io
import json
from dataclasses import replace
from datetime import date

import pytest

from hoc.config import Settings
from hoc.contract import SourceParseError, SourceUnavailable, TickerNotFound
from hoc.core.http import FakeHttpClient
from hoc.sources.ishares.adapter import CATALOGUE_URL, TTL, ISharesAdapter

PAGE = "https://www.ishares.com/us/products/999999/synthetic-zz-fund"
CSV_URL = PAGE + "/latest-holdings.csv"
HEADER = ["Ticker", "Name", "Sector", "Asset Class", "Weight (%)", "Location", "Exchange", "Currency"]


def csv_body(rows=None, header=None, disclosure="Nov 05, 2026"):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["SYNTHETIC ZZ Fund"])
    writer.writerow(["Fund Holdings as of", disclosure])
    writer.writerow([])
    writer.writerow(header or HEADER)
    writer.writerows(rows if rows is not None else [
        ["ZZAL", "ZZ Alpha", "Information Technology", "Equity", "92.5", "US", "NASDAQ", "USD"],
        ["ZZCASH", "ZZ Cash", "Cash and/or Derivatives", "Cash", "7.5", "US", "-", "USD"],
    ])
    writer.writerow(["\xa0"])
    writer.writerow(["Synthetic legal footer; no issuer data."])
    return out.getvalue()


def setup(body=None, page=None):
    http = FakeHttpClient()
    http.add(CATALOGUE_URL, json.dumps({"999999": {
        "localExchangeTicker": "ZZF", "productPageUrl": PAGE, "fundName": "Synthetic ZZ Fund",
    }}), content_type="application/json")
    http.add(PAGE, page if page is not None else (
        '<html><script type="application/ld+json">' + json.dumps({"@graph": [{
            "distribution": [{"contentUrl": CSV_URL}],
        }]}) + '</script></html>'
    ), content_type="text/html")
    http.add(CSV_URL, csv_body() if body is None else body, content_type="text/csv")
    return http, ISharesAdapter(http, Settings())


def test_discovery_metadata_and_fraction_units():
    http, adapter = setup()
    assert adapter.supports("ZZF") and http.requests == []
    result = adapter.fetch("zzf")
    assert http.requests == [("GET", CATALOGUE_URL), ("GET", PAGE), ("GET", CSV_URL)]
    assert result.etf_ticker == "ZZF"
    assert result.etf_name == "Synthetic ZZ Fund"
    assert result.source == "ishares" and result.source_layer == "issuer"
    assert result.source_url == CSV_URL
    assert result.as_of == date(2026, 11, 5)
    assert result.retrieved_at.tzinfo is not None
    assert result.holdings[0].weight == .925
    assert result.holdings[0].country == "US"
    assert result.holdings[0].sector_label == "Information Technology"
    assert result.holdings[1].asset_class == "cash"


def test_uk_date_reordered_headers_and_market_weight():
    header = ["Name", "Market Weight", "Ticker", "Asset Class", "Exchange", "Location", "Market Currency"]
    _, adapter = setup(csv_body([
        ["ZZ Foreign", "12.34", "009999", "Equity", "ZZ Exchange", "United Kingdom", "GBP"],
    ], header, "05/Nov/2026"))
    result = adapter.fetch("ZZF")
    line = result.holdings[0]
    assert result.as_of == date(2026, 11, 5)
    assert line.source_symbol == "009999" and line.weight == .1234
    assert line.exchange == "ZZ Exchange" and line.currency == "GBP"
    assert line.country is None  # never pass a country name as an ISO code
    assert line.isin is None and line.cusip is None


@pytest.mark.parametrize(("asset", "kind", "expected"), [
    ("Equity", "EQUITY", "equity"), ("Equity", "CASH", "cash"),
    ("Money Market", "STIF", "cash"), ("Cash Collateral and Margins", "COLLATERAL", "cash"),
    ("Equity", "FUTURE", "derivative"), ("Futures", "", "derivative"),
    ("Equity", "INDEX", "derivative"), ("Equity", "WARRANT", "derivative"),
    ("FX", "", "fx"), ("Equity", "FX", "fx"), ("Fund", "FUND", "fund"),
    ("Fixed Income", "", "fixed_income"), ("Preferred Stock", "", "preferred"),
    ("Unrecognised", "", "other"),
])
def test_classification_with_type_override(asset, kind, expected):
    _, adapter = setup(csv_body([["ZZ", "ZZ Instrument", asset, kind, "-0.25"]],
                               ["Ticker", "Name", "Asset Class", "Type", "Weight (%)"]))
    line = adapter.fetch("ZZF").holdings[0]
    assert line.asset_class == expected and line.weight == -.0025


def test_zero_weight_fallback_column_and_numeric_formats():
    header = ["Ticker", "Name", "Asset Class", "Weight (%)", "Market Weight", "Market Value", "Currency"]
    _, adapter = setup(csv_body([
        ["ZZ0", "ZZ Zero", "Equity", "0.00", "75", "1,234.56", "USD"],
        ["ZZ1", "ZZ One", "FX", "-", "(1.25)", "50", "GBP"],
    ], header))
    lines = adapter.fetch("ZZF").holdings
    assert lines[0].weight == 0 and lines[0].market_value_usd == 1234.56
    assert lines[1].weight == -.0125 and lines[1].market_value_usd is None


@pytest.mark.parametrize("body", [
    '<!DOCTYPE html><html><body>Challenge</body></html>',
    csv_body(disclosure="invalid"), csv_body(disclosure=""),
    'Ticker,Name,Asset Class,Weight (%)\nZZ,ZZ Alpha,Equity,100',
    csv_body().replace("Weight (%)", "Notional Weight"),
    csv_body().replace("92.5", "NaN"), csv_body().replace("92.5", "inf"),
    csv_body().replace("92.5", "bad"), csv_body().replace("92.5", ""),
    csv_body().replace("ZZ Alpha", ""), csv_body(rows=[]),
    csv_body().replace("ZZAL,ZZ Alpha", "ZZAL,EXTRA,ZZ Alpha"),
    csv_body().replace("Currency", "Ticker"),
    csv_body().replace('ZZAL,ZZ Alpha', 'ZZAL,"unterminated'),
    b'\xff\xfe\xff',
])
def test_rejects_malformed_or_mislabelled_csv(body):
    _, adapter = setup(body)
    with pytest.raises(SourceParseError):
        adapter.fetch("ZZF")


@pytest.mark.parametrize("page", [
    '<html>No dataset</html>', '<script type="application/ld+json">broken</script>',
    '<script type="application/ld+json">{"contentUrl":"https://other.example/latest-holdings.csv"}</script>',
])
def test_bad_jsonld_or_external_url(page):
    http, adapter = setup(page=page)
    with pytest.raises(SourceParseError):
        adapter.fetch("ZZF")
    assert len(http.requests) == 2


def test_relative_link_and_unrelated_jsonld():
    _, adapter = setup(page='<script type="application/ld+json">invalid</script>'
                       '<script type="application/ld+json">'
                       '{"contentUrl":"' + PAGE.removeprefix("https://www.ishares.com") +
                       '/latest-holdings.csv"}</script>')
    assert adapter.fetch("ZZF").source_url == CSV_URL


def test_unknown_ticker_and_offline_failure():
    http, adapter = setup()
    with pytest.raises(TickerNotFound):
        adapter.fetch("ZZUNKNOWN")
    assert len(http.requests) == 1
    with pytest.raises(SourceUnavailable):
        ISharesAdapter(FakeHttpClient(), Settings()).fetch("ZZF")


@pytest.mark.parametrize("url", [CATALOGUE_URL, PAGE, CSV_URL])
@pytest.mark.parametrize(("status", "error"), [(404, TickerNotFound), (403, SourceUnavailable),
                                             (429, SourceUnavailable), (503, SourceUnavailable)])
def test_statuses(url, status, error):
    http, adapter = setup()
    http.add(url, "Synthetic failure", status=status)
    with pytest.raises(error):
        adapter.fetch("ZZF")


@pytest.mark.parametrize("body", ['{}', '[]', '<html>blocked</html>', '{"bad":{}}'])
def test_malformed_catalogue(body):
    http, adapter = setup()
    http.add(CATALOGUE_URL, body)
    with pytest.raises(SourceParseError):
        adapter.fetch("ZZF")


def test_cache_policy_and_stale_provenance():
    http, _ = setup()
    original = http.get
    calls = []

    def get(url, **kwargs):
        calls.append(kwargs)
        return replace(original(url, **kwargs), stale=url == CSV_URL, from_cache=True)

    http.get = get
    result = ISharesAdapter(http, Settings(user_agent="ZZ test contact")).fetch("ZZF")
    assert result.warnings == ["iShares holdings served from stale cache"]
    assert all(c["ttl"] == TTL and c["source"] == "ishares" for c in calls)
    assert all(c["headers"]["User-Agent"] == "ZZ test contact" for c in calls)
