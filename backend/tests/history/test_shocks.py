"""FIX-63 failure simulator: proxy funds, Yahoo chart parsing and the size of the fall. No network."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from hoc.contract import DEFAULT_SHOCK_DROP, Sector, ShockSpec
from hoc.contract.errors import SourceUnavailable
from hoc.core.http import CachedResponse
from hoc.history import (
    COUNTRY_PROXIES,
    GENERIC_USER_AGENT,
    SECTOR_PROXIES,
    DailyCloses,
    HistoricalShocks,
    YahooHistory,
    basis_for,
    historical_shock,
    parse_chart,
    proxy_for,
    worst_window_drop,
)


def _days(n: int, start: date = date(2021, 11, 8)) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _series_with_dip(n: int = 1300, dip_at: int = 600, dip: float = 0.25) -> DailyCloses:
    """Flat at 100, then a straight-line fall of `dip` over 21 days starting at dip_at, then flat."""
    closes = []
    for i in range(n):
        if i <= dip_at:
            closes.append(100.0)
        elif i <= dip_at + 21:
            closes.append(100.0 * (1 - dip * (i - dip_at) / 21))
        else:
            closes.append(100.0 * (1 - dip))
    days = _days(n)
    return DailyCloses(symbol="XLK", dates=tuple(days), closes=tuple(closes))


class _Provider:
    def __init__(self, history: DailyCloses | None = None, error: Exception | None = None) -> None:
        self.history, self.error, self.calls = history, error, []

    def daily_closes(self, symbol: str) -> DailyCloses | None:
        self.calls.append(symbol)
        if self.error:
            raise self.error
        return self.history


def test_every_sector_but_unknown_has_a_proxy():
    assert set(SECTOR_PROXIES) == {s.value for s in Sector} - {"unknown"}
    assert proxy_for("sector", "information_technology") == "XLK"
    assert proxy_for("country", "tw") == "EWT"
    assert proxy_for("country", "US") == "SPY"
    assert proxy_for("supplier", "TSMC") is None
    assert all(code == code.upper() and len(code) == 2 for code in COUNTRY_PROXIES)


def test_worst_window_drop_finds_the_full_21_day_fall():
    history = _series_with_dip(dip=0.25)
    drop, start, end = worst_window_drop(history.dates, history.closes)
    assert drop == pytest.approx(0.25)
    assert start == history.dates[600] and end == history.dates[621]


def test_worst_window_drop_none_when_short_or_never_falls():
    assert worst_window_drop(_days(10), [1.0] * 10) is None
    assert worst_window_drop(_days(50), [float(i + 1) for i in range(50)]) is None


def test_historical_sector_shock_uses_the_proxy_and_dates():
    provider = _Provider(_series_with_dip(dip=0.193))
    basis = historical_shock("sector", "information_technology", provider)
    assert provider.calls == ["XLK"]
    assert basis.source == "historical" and basis.proxy == "XLK"
    assert basis.drop == pytest.approx(0.193)
    assert basis.window_start is not None and basis.window_end is not None
    assert "XLK" in basis.description and "19.3%" in basis.description and basis.description.startswith("Technology")


def test_only_the_last_five_years_count():
    """A crash more than 5 years before the last close is ignored."""
    days = _days(1700)
    closes = [100.0] * 1700
    for i in range(10, 31):  # a 50% fall in the first weeks, ~6.5 years before the end
        closes[i] = 100.0 * (1 - 0.5 * (i - 9) / 21)
    for i in range(31, 1700):
        closes[i] = 50.0
    closes[1500:1521] = [50.0 * (1 - 0.1 * (k + 1) / 21) for k in range(21)]  # a recent 10% fall
    closes[1521:] = [45.0] * (1700 - 1521)
    basis = historical_shock("sector", "energy", _Provider(DailyCloses("XLE", tuple(days), tuple(closes))))
    assert basis.source == "historical"
    assert basis.drop == pytest.approx(0.10, abs=1e-3)


@pytest.mark.parametrize(
    ("kind", "key", "provider", "needle"),
    [
        ("supplier", "TSMC", _Provider(), "supplier failure"),
        ("sector", "unknown", _Provider(), "No fund tracks"),
        ("country", "ZZ", _Provider(), "No fund tracks"),
        ("sector", "energy", None, "isn't available"),
        ("sector", "energy", _Provider(error=SourceUnavailable("down")), "couldn't load XLE"),
        ("sector", "energy", _Provider(history=None), "couldn't load XLE"),
        ("sector", "energy", _Provider(DailyCloses("XLE", tuple(_days(60)), tuple([1.0] * 60))), "enough price history"),
    ],
)
def test_falls_back_to_a_simulated_ten_percent(kind, key, provider, needle):
    basis = historical_shock(kind, key, provider)
    assert basis.source == "simulated"
    assert basis.drop == DEFAULT_SHOCK_DROP
    assert basis.proxy is None
    assert needle in basis.description
    assert DEFAULT_SHOCK_DROP == 0.20 and "20%" in basis.description


def test_user_chosen_drop_wins():
    provider = _Provider(_series_with_dip())
    basis = basis_for(ShockSpec(kind="sector", key="information_technology", drop=0.3), provider)
    assert basis.source == "simulated" and basis.drop == 0.3 and "30%" in basis.description
    assert provider.calls == []


def _chart(stamps, closes, adj=None) -> dict:
    indicators = {"quote": [{"close": closes}]}
    if adj is not None:
        indicators["adjclose"] = [{"adjclose": adj}]
    return {"chart": {"result": [{"timestamp": stamps, "indicators": indicators}], "error": None}}


def _stamp(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, 14, 30, tzinfo=UTC).timestamp())


def test_parse_chart_prefers_adjusted_and_skips_gaps():
    days = _days(4)
    payload = _chart([_stamp(d) for d in days], [10.0, None, 12.0, 13.0], adj=[9.0, None, 11.0, 12.0])
    parsed = parse_chart("XLK", payload)
    assert parsed.dates == (days[0], days[2], days[3])
    assert parsed.closes == (9.0, 11.0, 12.0)
    assert parse_chart("XLK", {"chart": {"result": None, "error": {"code": "Not Found"}}}) is None
    assert parse_chart("XLK", {}) is None


class _FakeHttp:
    def __init__(self, status: int, payload: dict) -> None:
        self.status, self.payload, self.calls = status, payload, []

    def get(self, url, *, source, ttl, headers=None, params=None):
        self.calls.append({"url": url, "source": source, "ttl": ttl, "headers": headers, "params": params})
        return CachedResponse(url=url, status=self.status, content_type="application/json",
                              body=json.dumps(self.payload).encode(), fetched_at=datetime.now(UTC))


def test_yahoo_history_request_shape_and_generic_user_agent():
    days = _days(3)
    http = _FakeHttp(200, _chart([_stamp(d) for d in days], [1.0, 2.0, 3.0]))
    closes = YahooHistory(http).daily_closes("xlk")
    assert closes.symbol == "XLK" and closes.closes == (1.0, 2.0, 3.0)
    call = http.calls[0]
    assert call["url"].endswith("/v8/finance/chart/XLK")
    assert call["params"] == {"range": "5y", "interval": "1d", "events": "div,split"}
    assert call["headers"]["User-Agent"] == GENERIC_USER_AGENT
    assert call["ttl"] == timedelta(hours=24) and call["source"] == "yahoo_chart"


def test_yahoo_history_non_200_is_none():
    assert YahooHistory(_FakeHttp(404, {})).daily_closes("NOPE") is None


def test_historical_shocks_object_for_the_service():
    shocks = HistoricalShocks(_Provider(_series_with_dip(dip=0.2)))
    assert shocks.historical_shock("sector", "information_technology").drop == pytest.approx(0.2)
    assert HistoricalShocks(None).historical_shock("country", "TW").source == "simulated"
