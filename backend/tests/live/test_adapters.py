"""Real issuer/EDGAR -> production HTTP cache -> adapter smoke tests.

No downloaded bytes or financial observations are stored in the test tree.
"""
from __future__ import annotations

import math
import socket
from datetime import UTC, datetime

import pytest

from hoc.config import Settings
from hoc.contract import EXCLUDED_ASSET_CLASSES
from hoc.core.cache import DiskCache
from hoc.core.http import CachedHttpClient
from hoc.identity.resolver import load_aliases
from hoc.normalise.pipeline import normalise_etf
from hoc.sources.ishares.adapter import ISharesAdapter
from hoc.sources.sec_nport.adapter import SecNportAdapter
from hoc.sources.tickerinside.adapter import TickerInsideAdapter

pytestmark = pytest.mark.live


class NoEnrichment:
    """Cash exclusion must work even when optional reference identifiers are absent."""

    def lookup_symbols(self, symbols):
        return {}

    def lookup_isins(self, isins):
        return {}


def assert_disclosure(raw, *, source, ticker, max_age_days, min_lines):
    today = datetime.now(UTC).date()
    assert raw.source == source
    assert raw.etf_ticker == ticker
    assert 0 <= (today - raw.as_of).days <= max_age_days, raw.as_of
    assert len(raw.holdings) >= min_lines
    total = math.fsum(line.weight for line in raw.holdings)
    assert total == pytest.approx(1.0, abs=0.05), total
    assert raw.source_url.startswith("https://")
    assert raw.retrieved_at.tzinfo is not None
    return raw


@pytest.mark.parametrize("ticker", ["IVV", "EEM"])
def test_ishares_disclosure(live_http, live_settings, ticker):
    # A week permits weekends/issuer holidays without accepting monthly data.
    raw = ISharesAdapter(live_http, live_settings).fetch(ticker)
    assert_disclosure(raw, source="ishares", ticker=ticker, max_age_days=7, min_lines=101)
    assert sum(line.asset_class in {"equity", "preferred"} for line in raw.holdings) > 100
    excluded = [line for line in raw.holdings if line.asset_class in EXCLUDED_ASSET_CLASSES]
    # These issuer funds report cash/collateral; require actual exclusion evidence.
    assert any(line.asset_class == "cash" for line in excluded)
    normalised = normalise_etf(raw, NoEnrichment(), load_aliases())
    assert all(line.asset_class not in EXCLUDED_ASSET_CLASSES for line in normalised.holdings)
    assert len(normalised.excluded) == len(excluded)
    assert normalised.excluded_weight == pytest.approx(math.fsum(line.weight for line in excluded))
    assert normalised.holdings_weight == pytest.approx(
        normalised.reported_weight - normalised.excluded_weight
    )


def test_nport_production_cache(live_http, live_settings):
    # SEC requires the operator's real contact; do not invent one in a test.
    if not live_settings.sec_contact:
        pytest.skip("set HOC_SEC_CONTACT to your real SEC contact for the EDGAR smoke")
    raw = SecNportAdapter(live_http, live_settings).fetch("QQQ")
    assert_disclosure(raw, source="sec_nport", ticker="QQQ", max_age_days=180, min_lines=90)
    assert raw.filing_url and raw.filing_url.startswith("https://")
    assert any(line.isin or line.cusip for line in raw.holdings)


def test_offline_replays_ishares_disk_cache(live_http, live_settings, monkeypatch):
    warm = ISharesAdapter(live_http, live_settings).fetch("IVV")
    monkeypatch.setenv("HOC_OFFLINE", "1")
    offline = Settings.from_env()
    assert offline.offline
    assert offline.cache_dir == live_settings.cache_dir

    def refuse_network(*args, **kwargs):
        pytest.fail("HOC_OFFLINE=1 attempted a network connection instead of reading disk cache")

    monkeypatch.setattr(socket.socket, "connect", refuse_network)
    monkeypatch.setattr(socket, "create_connection", refuse_network)
    # Rebuild both client and adapter: an in-memory memo must not satisfy this.
    http = CachedHttpClient(offline, DiskCache(offline.cache_dir))
    replay = ISharesAdapter(http, offline).fetch("IVV")
    assert replay.etf_ticker == warm.etf_ticker
    assert replay.source == warm.source
    assert replay.as_of == warm.as_of
    assert replay.retrieved_at == warm.retrieved_at
    assert replay.holdings == warm.holdings



def test_tickerinside_disclosure(live_http, live_settings):
    raw = TickerInsideAdapter(live_http, live_settings).fetch("XLK")
    assert_disclosure(raw, source="tickerinside", ticker="XLK", max_age_days=7, min_lines=50)
    assert raw.attribution and raw.licence == "CC BY 4.0"
    assert raw.source_layer in {"issuer", "sec_nport"}
    assert raw.reported_sector_weights
    assert any(line.cik or line.figi for line in raw.holdings)
    assert any(line.asset_class == "derivative" for line in raw.holdings)
    normalised = normalise_etf(raw, NoEnrichment(), load_aliases())
    assert all(line.asset_class not in EXCLUDED_ASSET_CLASSES for line in normalised.holdings)
    assert normalised.excluded
    assert normalised.reported_weight == pytest.approx(
        normalised.holdings_weight + normalised.excluded_weight
    )
