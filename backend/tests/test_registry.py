"""Source fallback order and attempt recording (hoc.sources.registry) plus the fake adapter."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from hoc.contract import RawEtfHoldings, SourceParseError, SourceUnavailable, TickerNotFound
from hoc.sources.base import ReferenceProvider, SourceAdapter
from hoc.sources.registry import SourceRegistry


def _raw(ticker: str, source: str) -> RawEtfHoldings:
    return RawEtfHoldings(etf_ticker=ticker, source=source, as_of=date(2026, 1, 1),
                          retrieved_at=datetime(2026, 1, 2, tzinfo=UTC), source_url="https://example.invalid",
                          holdings=[])


class Scripted:
    """An adapter that raises or returns per a script. name is set per instance via a subclass."""

    def __init__(self, outcome: str, supports: bool = True) -> None:
        self.outcome, self._supports, self.calls = outcome, supports, 0

    def supports(self, ticker: str) -> bool:
        return self._supports

    def fetch(self, ticker: str) -> RawEtfHoldings:
        self.calls += 1
        errors = {"not_found": TickerNotFound, "unavailable": SourceUnavailable, "parse_error": SourceParseError}
        if self.outcome in errors:
            raise errors[self.outcome](f"{self.name} {self.outcome}")
        return _raw(ticker, self.name)


def adapter(name: str, outcome: str, supports: bool = True) -> Scripted:
    cls = type(f"Scripted_{name}", (Scripted,), {"name": name})
    return cls(outcome, supports)


def test_fake_adapter_implements_protocols(fake_source, fake_reference):
    assert isinstance(fake_source, SourceAdapter)
    assert isinstance(fake_reference, ReferenceProvider)


def test_first_success_wins_and_later_sources_are_not_called():
    a, b = adapter("tickerinside", "ok"), adapter("sec_nport", "ok")
    result = SourceRegistry([a, b]).fetch_with_fallback("ivv")
    assert result.status == "ok" and result.raw.source == "tickerinside" and result.ticker == "IVV"
    assert b.calls == 0
    assert [x.outcome for x in result.attempts] == ["ok"]


def test_falls_back_on_unavailable_and_parse_error():
    reg = SourceRegistry([adapter("tickerinside", "unavailable"), adapter("ishares", "parse_error"),
                          adapter("sec_nport", "ok")])
    result = reg.fetch_with_fallback("QQQ")
    assert result.raw.source == "sec_nport"
    assert [(x.source, x.outcome) for x in result.attempts] == [
        ("tickerinside", "unavailable"), ("ishares", "parse_error"), ("sec_nport", "ok")]


def test_not_found_everywhere_is_not_found():
    reg = SourceRegistry([adapter("tickerinside", "not_found"), adapter("sec_nport", "not_found")])
    assert reg.fetch_with_fallback("NOPE").status == "not_found"


def test_any_unavailable_without_success_is_unavailable():
    reg = SourceRegistry([adapter("tickerinside", "not_found"), adapter("sec_nport", "unavailable")])
    assert reg.fetch_with_fallback("IVV").status == "unavailable"


def test_unsupported_sources_are_skipped():
    reg = SourceRegistry([adapter("ishares", "ok", supports=False), adapter("tickerinside", "ok")])
    result = reg.fetch_with_fallback("VOO")
    assert result.raw.source == "tickerinside"
    assert result.attempts[0].outcome == "skipped"


def test_order_override_and_only():
    a, b = adapter("tickerinside", "ok"), adapter("sec_nport", "ok")
    assert SourceRegistry([a, b], order=["sec_nport", "tickerinside"]).fetch_with_fallback("X").raw.source == "sec_nport"
    assert SourceRegistry([a, b]).fetch_with_fallback("X", only="sec_nport").raw.source == "sec_nport"


def test_bad_configuration_is_rejected():
    with pytest.raises(ValueError):
        SourceRegistry([adapter("tickerinside", "ok")], order=["nope"])
    with pytest.raises(ValueError):
        SourceRegistry([adapter("tickerinside", "ok"), adapter("tickerinside", "ok")])


def test_fake_source_serves_synthetic_fixtures(fake_source):
    raw = fake_source.fetch("zzaaa")
    assert raw.etf_ticker == "ZZAAA" and raw.source == "fake"
    with pytest.raises(TickerNotFound):
        fake_source.fetch("ZZMISSING")


def test_fake_source_can_simulate_outage(synthetic_dir):
    from hoc.sources.fake import FakeSourceAdapter

    with pytest.raises(SourceUnavailable):
        FakeSourceAdapter(synthetic_dir / "raw", unavailable=["ZZAAA"]).fetch("ZZAAA")


def test_fake_reference_lookups(fake_reference):
    found = fake_reference.lookup_symbols(["ZZBET.A", "ZZBET.B", "UNKNOWN"])
    assert set(found) == {"ZZBET.A", "ZZBET.B"}
    assert found["ZZBET.A"].cik == found["ZZBET.B"].cik == "9990000002"
    assert fake_reference.lookup_isins(["ZZ0000000ZT1"]) == {}


class Malformed:
    """An adapter whose upstream data slips past its own checks."""

    name = "tickerinside"

    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def supports(self, ticker: str) -> bool:
        return True

    def fetch(self, ticker: str) -> RawEtfHoldings:
        raise self.exc


@pytest.mark.parametrize("exc", [ValueError("bad sector value"), AttributeError(), KeyError("holdings"), TypeError("x")])
def test_malformed_upstream_data_is_a_parse_error_not_a_crash(exc):
    reg = SourceRegistry([Malformed(exc), adapter("sec_nport", "ok")])
    result = reg.fetch_with_fallback("ZZBAD")
    assert result.raw.source == "sec_nport"
    assert result.attempts[0].outcome == "parse_error" and "malformed data" in result.attempts[0].message


def test_nan_weight_is_rejected_by_the_contract_and_becomes_a_parse_error():
    import math

    from hoc.contract import RawHolding

    with pytest.raises(ValueError):
        RawHolding(source_symbol="ZZALP", weight=math.nan)

    class NanAdapter(Malformed):
        def fetch(self, ticker: str) -> RawEtfHoldings:
            return RawEtfHoldings(etf_ticker=ticker, source="tickerinside", as_of=date(2026, 1, 1),
                                  retrieved_at=datetime(2026, 1, 2, tzinfo=UTC), source_url="https://example.invalid",
                                  holdings=[RawHolding(source_symbol="ZZALP", weight=float("inf"))])

    result = SourceRegistry([NanAdapter(None)]).fetch_with_fallback("ZZBAD")
    assert result.status == "unavailable" and result.attempts[0].outcome == "parse_error"
