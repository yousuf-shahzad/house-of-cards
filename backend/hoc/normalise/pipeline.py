"""RawEtfHoldings -> EtfHoldings. Owner: package d (Kendrick's Claude). Signature fixed by W0-B.

Responsibilities (docs/hoc/CONTRACT.md): reject percent-unit inputs (raw sum > RAW_WEIGHT_SUM_MAX);
move cash/derivative/fx lines to `excluded`; resolve security_key and company_key via hoc.identity;
merge duplicate lines per security_key; map sector labels onto Sector; compute reported/holdings/
excluded/unmatched weights and the sector basis; sort holdings by weight desc, then security_key.
Pure and deterministic: no network (reference data is passed in), no clock.
"""

from __future__ import annotations

import re
from collections import defaultdict

from hoc.contract import (
    EXCLUDED_ASSET_CLASSES,
    EtfHoldings,
    ExcludedLine,
    NormalisedHolding,
    Notice,
    RawEtfHoldings,
    Sector,
    SecurityInfo,
    wsum,
)
from hoc.contract.units import RAW_WEIGHT_SUM_MAX, SECTOR_COVERAGE_THRESHOLD
from hoc.identity.resolver import Aliases, best_company_name, listing_symbol, resolve
from hoc.sources.base import ReferenceProvider

NORMALISER_VERSION = "norm-1"

_S = Sector
# Keys are labels lower-cased with everything but letters removed.
SECTOR_LABELS: dict[str, Sector] = {
    "informationtechnology": _S.information_technology, "technology": _S.information_technology,
    "it": _S.information_technology, "tech": _S.information_technology, "infotech": _S.information_technology,
    "financials": _S.financials, "financial": _S.financials, "financialservices": _S.financials,
    "healthcare": _S.health_care,
    "consumerdiscretionary": _S.consumer_discretionary, "consumercyclical": _S.consumer_discretionary,
    "communicationservices": _S.communication_services, "communication": _S.communication_services,
    "communications": _S.communication_services, "telecommunications": _S.communication_services,
    "telecommunicationservices": _S.communication_services, "telecom": _S.communication_services,
    "industrials": _S.industrials, "industrial": _S.industrials,
    "consumerstaples": _S.consumer_staples, "consumerdefensive": _S.consumer_staples,
    "energy": _S.energy,
    "utilities": _S.utilities, "utility": _S.utilities,
    "realestate": _S.real_estate,
    "materials": _S.materials, "basicmaterials": _S.materials,
}


def map_sector(label: str | None) -> Sector:
    if not label:
        return Sector.unknown
    key = re.sub(r"[^a-z]", "", label.lower())
    return SECTOR_LABELS.get(key) or (Sector(key) if key in Sector.__members__ else Sector.unknown)


def normalise_etf(raw: RawEtfHoldings, reference: ReferenceProvider, aliases: Aliases) -> EtfHoldings:
    reported = wsum(h.weight for h in raw.holdings)
    if reported > RAW_WEIGHT_SUM_MAX:
        raise ValueError(f"raw weights of {raw.etf_ticker} sum to {reported:.2f}: they look like percent")

    kept = [h for h in raw.holdings if h.asset_class not in EXCLUDED_ASSET_CLASSES]
    excluded = [
        ExcludedLine(name=h.name or h.source_symbol or "Unnamed line", asset_class=h.asset_class, weight=h.weight)
        for h in raw.holdings if h.asset_class in EXCLUDED_ASSET_CLASSES
    ]

    symbols = [listing_symbol(h, raw.source) for h in kept]
    # Heaviest first: providers may bound per-symbol work (TickerInside sector files) to the first N.
    heaviest: dict[str, float] = defaultdict(float)
    for line, symbol in zip(kept, symbols, strict=True):
        if symbol:
            heaviest[symbol] += line.weight
    by_symbol = reference.lookup_symbols(sorted(heaviest, key=lambda s: (-heaviest[s], s)))
    no_symbol_isins = sorted({h.isin.upper() for h, s in zip(kept, symbols, strict=True) if h.isin and not s})
    by_isin = reference.lookup_isins(no_symbol_isins) if no_symbol_isins else {}

    merged: dict[str, dict] = {}
    for line, symbol in zip(kept, symbols, strict=True):
        info = by_symbol.get(symbol) if symbol else by_isin.get((line.isin or "").upper())
        if not symbol and info and info.symbol:
            symbol = info.symbol.upper()
        info = info or SecurityInfo()
        name = line.name or info.name or symbol or line.isin or line.cusip or "Unnamed holding"
        ident = resolve(line, symbol, info, aliases, name)
        if line.sector_label and map_sector(line.sector_label) is not Sector.unknown:
            sector, sector_source = map_sector(line.sector_label), "source"
        elif map_sector(info.sector_label) is not Sector.unknown:
            sector, sector_source = map_sector(info.sector_label), "reference"
        else:
            sector, sector_source = Sector.unknown, "none"
        entry = merged.get(ident.security_key)
        if entry:  # duplicate source line for one security: sum, keep the first line's metadata
            entry["weights"].append(line.weight)
            continue
        merged[ident.security_key] = {
            "weights": [line.weight], "alias_name": ident.alias_name,
            "fields": {
                "etf_ticker": raw.etf_ticker, "security_key": ident.security_key, "security_id": ident.security_id,
                "security_id_type": ident.security_id_type, "symbol": ident.symbol, "name": name,
                "company_key": ident.company_key, "company_key_basis": ident.company_key_basis,
                "identity_status": ident.identity_status, "sector": sector, "sector_source": sector_source,
                "asset_class": line.asset_class, "country": (line.country or info.country or None),
                "source": raw.source, "as_of": raw.as_of,
            },
        }

    # One display name per company in this ETF: the alias name, else the best clean line name.
    company_lines: dict[str, list[dict]] = defaultdict(list)
    for entry in merged.values():
        entry["weight"] = wsum(entry["weights"])
        company_lines[entry["fields"]["company_key"]].append(entry)
    holdings = []
    for lines in company_lines.values():
        alias_name = next((e["alias_name"] for e in lines if e["alias_name"]), None)
        company_name = alias_name or best_company_name(e["fields"]["name"] for e in lines)
        holdings += [NormalisedHolding(**e["fields"], weight=e["weight"], company_name=company_name) for e in lines]
    holdings.sort(key=lambda h: (-h.weight, h.security_key))

    holdings_weight = wsum(h.weight for h in holdings)
    sector_weights, sector_basis = _sectors(raw, holdings, holdings_weight)
    return EtfHoldings(
        etf_ticker=raw.etf_ticker, etf_name=raw.etf_name, source=raw.source, source_layer=raw.source_layer,
        as_of=raw.as_of, retrieved_at=raw.retrieved_at, source_url=raw.source_url, filing_url=raw.filing_url,
        attribution=raw.attribution, licence=raw.licence, holdings=holdings, excluded=excluded,
        reported_weight=reported, holdings_weight=holdings_weight,
        excluded_weight=wsum(e.weight for e in excluded),
        unmatched_weight=wsum(h.weight for h in holdings if h.identity_status == "unmatched"),
        sector_weights=sector_weights, sector_basis=sector_basis, raw_line_count=len(raw.holdings),
        warnings=[Notice(code="source_warning", message=w) for w in raw.warnings], price=raw.price,
        normaliser_version=NORMALISER_VERSION,
    )


def _sectors(raw: RawEtfHoldings, holdings: list[NormalisedHolding], holdings_weight: float):
    known = wsum(h.weight for h in holdings if h.sector is not Sector.unknown)
    if holdings and known >= SECTOR_COVERAGE_THRESHOLD * holdings_weight:
        parts: dict[Sector, list[float]] = defaultdict(list)
        for h in holdings:
            parts[h.sector].append(h.weight)
        return {s: wsum(w) for s, w in sorted(parts.items())}, "holdings"
    if raw.reported_sector_weights:
        parts = defaultdict(list)
        for label, weight in raw.reported_sector_weights.items():
            parts[map_sector(label)].append(weight)
        weights = {s: wsum(w) for s, w in parts.items()}
        total = wsum(weights.values())
        if total > holdings_weight and total > 0:  # scale down to the look-through part
            weights = {s: w * holdings_weight / total for s, w in weights.items()}
            total = wsum(weights.values())
        weights[Sector.unknown] = weights.get(Sector.unknown, 0.0) + (holdings_weight - total)
        return dict(sorted(weights.items())), "fund_reported"
    return {}, "none"
