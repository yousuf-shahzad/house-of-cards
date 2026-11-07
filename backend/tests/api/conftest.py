"""Package f test helpers: a fake-backed EtfService."""

from __future__ import annotations

import pytest

from hoc.config import Settings
from hoc.contract import EXCLUDED_ASSET_CLASSES, EtfHoldings, NormalisedHolding, wsum
from hoc.service import EtfService
from hoc.sources.registry import SourceRegistry


def stand_in_normalise(raw, reference, aliases) -> EtfHoldings:
    """A minimal normaliser (one company per symbol) so service wiring is testable before package d lands."""
    kept = [h for h in raw.holdings if h.asset_class not in EXCLUDED_ASSET_CLASSES]
    holdings = [
        NormalisedHolding(
            etf_ticker=raw.etf_ticker, security_key=f"SYM:{h.source_symbol or h.name}",
            security_id=h.source_symbol or h.name, security_id_type="symbol", symbol=h.source_symbol,
            name=h.name, company_key=f"SYM:{h.source_symbol or h.name}", company_key_basis="symbol",
            company_name=h.name, identity_status="partial", weight=h.weight, source=raw.source, as_of=raw.as_of,
        )
        for h in kept
    ]
    reported, covered = wsum(h.weight for h in raw.holdings), wsum(h.weight for h in kept)
    return EtfHoldings(
        etf_ticker=raw.etf_ticker, etf_name=raw.etf_name, source=raw.source, as_of=raw.as_of,
        retrieved_at=raw.retrieved_at, source_url=raw.source_url, attribution=raw.attribution,
        holdings=holdings, reported_weight=reported, holdings_weight=covered,
        excluded_weight=reported - covered, unmatched_weight=0.0, raw_line_count=len(raw.holdings),
        normaliser_version="test-stand-in",
    )


@pytest.fixture
def make_service(fake_source, fake_reference, monkeypatch):
    """make_service(unavailable=[...]) -> (service, fake adapter). Uses the stand-in normaliser."""
    monkeypatch.setattr("hoc.service.normalise_etf", stand_in_normalise)

    def make(unavailable=()):
        source = type(fake_source)(fake_source.raw_dir, unavailable=unavailable)
        return EtfService(SourceRegistry([source]), fake_reference, None, Settings()), source

    return make
