"""Offline and live tests for hoc.sources.sec_nport (package b).

All offline tests use FakeHttpClient and synthetic ZZ tickers / 999 CIKs (never real holdings).
"""

from __future__ import annotations

import json
import math
from datetime import date

import pytest

from hoc.config import Settings
from hoc.contract import (
    SourceParseError,
    SourceUnavailable,
    TickerNotFound,
    wsum,
)
from hoc.core.http import FakeHttpClient
from hoc.sources.base import ReferenceProvider, SourceAdapter
from hoc.sources.sec_nport import OpenFigiReference, SecNportAdapter
from hoc.sources.sec_nport.adapter import (
    MF_TICKERS_URL,
    OPENFIGI_MAPPING_URL,
    SERIES_ATOM_URL_TPL,
    SUBMISSIONS_URL_TPL,
)

SYNTHETIC_MF_JSON = json.dumps(
    {
        "fields": ["cik", "seriesId", "classId", "symbol"],
        "data": [
            [999000010, "S000999001", "C000999001", "ZZAAA"],
            [999000010, "S000999002", "C000999002", "ZZBBB"],
        ],
    }
)

SYNTHETIC_SUBMISSIONS_JSON = json.dumps(
    {
        "cik": "999000010",
        "name": "ZZ Synthetic Trust",
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0009990010-26-000001",
                    "0009990010-26-000002",
                    "0009990010-26-000000",
                ],
                "filingDate": [
                    "2026-05-28",
                    "2026-08-28",
                    "2026-08-29",
                ],
                "reportDate": [
                    "2026-03-31",
                    "2026-06-30",
                    "2026-06-30",
                ],
                "form": [
                    "NPORT-P",
                    "NPORT-P",
                    "N-CSR",
                ],
                "primaryDocument": [
                    "xslFormNPORT-P_X01/primary_doc.xml",
                    "xslFormNPORT-P_X01/primary_doc.xml",
                    "ncsr.htm",
                ],
            }
        },
    }
)

SYNTHETIC_NPORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nport">
  <headerData>
    <submissionType>NPORT-P</submissionType>
    <filerInfo>
      <seriesClassInfo>
        <seriesId>S000999001</seriesId>
        <classId>C000999001</classId>
      </seriesClassInfo>
    </filerInfo>
  </headerData>
  <formData>
    <genInfo>
      <regName>ZZ Synthetic Trust</regName>
      <seriesName>ZZ Synthetic Alpha ETF</seriesName>
      <seriesId>S000999001</seriesId>
      <repPdEnd>2026-12-31</repPdEnd>
      <repPdDate>2026-06-30</repPdDate>
    </genInfo>
    <fundInfo>
      <totAssets>101500000.00</totAssets>
      <totLiabs>1500000.00</totLiabs>
      <netAssets>100000000.00</netAssets>
    </fundInfo>
    <invstOrSecs>
      <invstOrSec>
        <name>ZZ Alpha Corp</name>
        <lei>549300ZZALPHA0000001</lei>
        <title>ZZ Alpha Common</title>
        <cusip>999000AA1</cusip>
        <identifiers>
          <isin value="US999000AA12"/>
        </identifiers>
        <balance>100000.00</balance>
        <units>NS</units>
        <curCd>USD</curCd>
        <valUSD>55000000.00</valUSD>
        <pctVal>55.000000000000</pctVal>
        <payoffProfile>Long</payoffProfile>
        <assetCat>EC</assetCat>
        <issuerCat>CORP</issuerCat>
        <invCountry>US</invCountry>
        <securityLending>
          <isCashCollateral>N</isCashCollateral>
        </securityLending>
      </invstOrSec>
      <invstOrSec>
        <name>ZZ Taiwan Semi Fake ADR</name>
        <lei>549300ZZTAIWAN000002</lei>
        <title>ZZ Taiwan Semi ADR</title>
        <cusip>999000BB9</cusip>
        <identifiers>
          <isin value="TW0009990005"/>
        </identifiers>
        <balance>50000.00</balance>
        <units>NS</units>
        <currencyConditional curCd="TWD" exchangeRt="32.10000000"/>
        <valUSD>40000000.00</valUSD>
        <pctVal>40.000000000000</pctVal>
        <payoffProfile>Long</payoffProfile>
        <assetConditional assetCat="OTHER" desc="ADR"/>
        <issuerCat>CORP</issuerCat>
        <invCountry>TW</invCountry>
        <securityLending>
          <isCashCollateral>N</isCashCollateral>
        </securityLending>
      </invstOrSec>
      <invstOrSec>
        <name>ZZ Cash Sweep Money Market</name>
        <lei>N/A</lei>
        <title>ZZ Cash Sweep</title>
        <cusip>N/A</cusip>
        <identifiers>
          <isin value="N/A"/>
        </identifiers>
        <valUSD>4000000.00</valUSD>
        <pctVal>4.000000000000</pctVal>
        <payoffProfile>Long</payoffProfile>
        <assetCat>STIV</assetCat>
        <issuerCat>RF</issuerCat>
        <invCountry>US</invCountry>
      </invstOrSec>
      <invstOrSec>
        <name>ZZ Index Future Sep26</name>
        <lei>N/A</lei>
        <title>ZZ Future</title>
        <cusip>N/A</cusip>
        <valUSD>-500000.00</valUSD>
        <pctVal>0.500000000000</pctVal>
        <payoffProfile>Short</payoffProfile>
        <assetCat>DE</assetCat>
        <invCountry>US</invCountry>
      </invstOrSec>
      <invstOrSec>
        <name>ZZ Securities Lending Cash Collateral Pool</name>
        <lei>N/A</lei>
        <title>ZZ SL Cash Collateral</title>
        <cusip>999000SL1</cusip>
        <valUSD>1500000.00</valUSD>
        <pctVal>1.500000000000</pctVal>
        <payoffProfile>Long</payoffProfile>
        <assetCat>STIV</assetCat>
        <securityLending>
          <cashCollateralCondition cashCollateralVal="1500000.00" isCashCollateral="Y"/>
        </securityLending>
      </invstOrSec>
    </invstOrSecs>
  </formData>
</edgarSubmission>
"""


def _setup_fake_http() -> FakeHttpClient:
    http = FakeHttpClient()
    http.add(MF_TICKERS_URL, SYNTHETIC_MF_JSON, content_type="application/json")
    http.add(
        SUBMISSIONS_URL_TPL.format(cik=999000010),
        SYNTHETIC_SUBMISSIONS_JSON,
        content_type="application/json",
    )
    http.add(
        "https://www.sec.gov/Archives/edgar/data/999000010/000999001026000002/primary_doc.xml",
        SYNTHETIC_NPORT_XML,
        content_type="application/xml",
    )
    return http


def test_sec_nport_adapter_implements_protocols():
    http = FakeHttpClient()
    settings = Settings()
    adapter = SecNportAdapter(http, settings)
    ref = OpenFigiReference(http, settings)
    assert isinstance(adapter, SourceAdapter)
    assert isinstance(ref, ReferenceProvider)
    assert adapter.supports("ZZAAA") is True
    assert adapter.supports("") is False


def test_fetch_parses_newest_nport_by_report_date_and_converts_weights():
    http = _setup_fake_http()
    settings = Settings(sec_contact="test@agentverse-hackathon.org")
    adapter = SecNportAdapter(http, settings)

    raw = adapter.fetch("zzaaa")
    assert raw.etf_ticker == "ZZAAA"
    assert raw.etf_name == "ZZ Synthetic Alpha ETF"
    assert raw.source == "sec_nport"
    assert raw.source_layer == "sec_nport"
    assert raw.as_of == date(2026, 6, 30)
    assert raw.source_url == "https://www.sec.gov/Archives/edgar/data/999000010/000999001026000002/primary_doc.xml"
    assert raw.filing_url == (
        "https://www.sec.gov/Archives/edgar/data/999000010/000999001026000002/0009990010-26-000002-index.htm"
    )
    assert raw.licence == "Public domain (SEC EDGAR)"

    # Securities-lending cash collateral line (1.5%) must be skipped with a warning
    assert len(raw.holdings) == 4
    assert any("cash collateral" in w for w in raw.warnings)

    h0, h1, h2, h3 = raw.holdings
    assert h0.name == "ZZ Alpha Corp"
    assert math.isclose(h0.weight, 0.55, abs_tol=1e-12)
    assert h0.isin == "US999000AA12"
    assert h0.cusip == "999000AA1"
    assert h0.lei == "549300ZZALPHA0000001"
    assert h0.asset_class == "equity"
    assert h0.country == "US"
    assert h0.currency == "USD"
    assert h0.market_value_usd == 55_000_000.0

    # assetConditional ADR + currencyConditional TWD
    assert h1.name == "ZZ Taiwan Semi Fake ADR"
    assert math.isclose(h1.weight, 0.40, abs_tol=1e-12)
    assert h1.isin == "TW0009990005"
    assert h1.asset_class == "equity"
    assert h1.currency == "TWD"
    assert h1.country == "TW"

    # STIV -> cash, N/A identifiers cleaned to None
    assert h2.name == "ZZ Cash Sweep Money Market"
    assert math.isclose(h2.weight, 0.04, abs_tol=1e-12)
    assert h2.asset_class == "cash"
    assert h2.isin is None
    assert h2.cusip is None
    assert h2.lei is None

    # DE + Short payoffProfile -> derivative with negative weight
    assert h3.name == "ZZ Index Future Sep26"
    assert math.isclose(h3.weight, -0.005, abs_tol=1e-12)
    assert h3.asset_class == "derivative"

    assert math.isclose(wsum(h.weight for h in raw.holdings), 0.985, abs_tol=1e-12)


def test_multi_series_trust_resolves_via_series_atom_feed():
    http = _setup_fake_http()
    # ZZBBB shares CIK 999000010 with ZZAAA, but has seriesId S000999002.
    # Top submission 0009990010-26-000002 is for S000999001, so adapter uses the series Atom feed.
    atom_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <accession-number>0009990010-26-000099</accession-number>
        <filing-date>2026-08-29</filing-date>
      </entry>
    </feed>
    """
    zzbbb_xml = SYNTHETIC_NPORT_XML.replace("S000999001", "S000999002").replace(
        "ZZ Synthetic Alpha ETF", "ZZ Synthetic Beta ETF"
    )
    http.add(SERIES_ATOM_URL_TPL.format(series_id="S000999002"), atom_xml, content_type="application/atom+xml")
    http.add(
        "https://www.sec.gov/Archives/edgar/data/999000010/000999001026000099/primary_doc.xml",
        zzbbb_xml,
        content_type="application/xml",
    )

    raw = SecNportAdapter(http, Settings()).fetch("ZZBBB")
    assert raw.etf_ticker == "ZZBBB"
    assert raw.etf_name == "ZZ Synthetic Beta ETF"
    assert "0009990010-26-000099" in (raw.attribution or "")


def test_openfigi_enrichment_maps_isin_to_symbol_and_figi():
    http = _setup_fake_http()
    openfigi_resp = json.dumps(
        [
            {
                "data": [
                    {
                        "figi": "BBG999000AA1",
                        "shareClassFIGI": "BBG999000AA2",
                        "ticker": "ZZALP/A",
                        "name": "ZZ ALPHA CORP",
                        "exchCode": "US",
                        "marketSector": "Equity",
                    }
                ]
            },
            {
                "data": [
                    {
                        "figi": "BBG999000TW1",
                        "shareClassFIGI": "BBG999000TW2",
                        "ticker": "9990",
                        "name": "ZZ TAIWAN SEMI",
                        "exchCode": "TT",
                        "marketSector": "Equity",
                    }
                ]
            },
        ]
    )
    http.add(OPENFIGI_MAPPING_URL, openfigi_resp, content_type="application/json")

    adapter = SecNportAdapter(http, Settings(openfigi_key="fake-key-for-test"))
    raw = adapter.fetch("ZZAAA")
    assert raw.holdings[0].source_symbol == "ZZALP.A"
    assert raw.holdings[0].figi == "BBG999000AA2"
    assert raw.holdings[1].source_symbol == "9990.TW"
    assert raw.holdings[1].figi == "BBG999000TW2"


def test_unknown_ticker_and_malformed_xml_errors():
    http = _setup_fake_http()
    adapter = SecNportAdapter(http, Settings())

    with pytest.raises(TickerNotFound):
        adapter.fetch("ZZNOPE")

    # Malformed / HTML payload instead of XML raises SourceParseError
    http.add(
        "https://www.sec.gov/Archives/edgar/data/999000010/000999001026000002/primary_doc.xml",
        "<html><body>Error</body></html>",
        content_type="text/html",
    )
    with pytest.raises(SourceParseError):
        adapter.fetch("ZZAAA")


def test_missing_http_routes_raise_source_unavailable():
    adapter = SecNportAdapter(FakeHttpClient(), Settings())
    with pytest.raises(SourceUnavailable):
        adapter.fetch("ZZAAA")


@pytest.mark.live
def test_live_sec_nport_fetch_qqq():
    """Live smoke test (runs only when HOC_LIVE=1)."""
    import urllib.request
    from datetime import UTC, datetime

    from hoc.core.http import CachedResponse

    class LiveStdlibHttp:
        def get(self, url, *, source, ttl, headers=None, params=None):
            req = urllib.request.Request(url, headers=dict(headers or {}))
            with urllib.request.urlopen(req, timeout=25) as r:
                return CachedResponse(
                    url=url,
                    status=r.status,
                    content_type=r.headers.get("Content-Type"),
                    body=r.read(),
                    fetched_at=datetime.now(UTC),
                )

        def post_json(self, url, payload, *, source, ttl, headers=None):
            raise SourceUnavailable("OpenFIGI disabled in smoke test")

    raw = SecNportAdapter(LiveStdlibHttp(), Settings(sec_contact="smoke@agentverse-hackathon.org")).fetch("QQQ")
    assert raw.etf_ticker == "QQQ"
    assert raw.source == "sec_nport"
    assert len(raw.holdings) >= 90
    assert 0.90 < wsum(h.weight for h in raw.holdings) <= 1.05
