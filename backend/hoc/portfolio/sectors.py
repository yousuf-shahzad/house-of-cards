"""Sector allocation, accepting normalisation's mapped fund breakdown."""

from collections import defaultdict

from hoc.contract import Sector, SectorContribution, SectorExposure, wsum
from hoc.contract.units import SECTOR_COVERAGE_THRESHOLD


def etf_sectors(etf):
    groups = defaultdict(list)
    for line in etf.holdings:
        groups[line.sector].append(line.weight)
    known = wsum(line.weight for line in etf.holdings if line.sector != Sector.unknown)
    if etf.holdings_weight > 0 and known >= SECTOR_COVERAGE_THRESHOLD * etf.holdings_weight:
        weights = {sector: wsum(values) for sector, values in sorted(groups.items())}
        return "holdings", weights
    if etf.sector_basis == "fund_reported" and etf.sector_weights:
        total = wsum(etf.sector_weights.values())
        scale = etf.holdings_weight / total if total > etf.holdings_weight and total > 0 else 1.0
        weights = {sector: weight * scale for sector, weight in sorted(etf.sector_weights.items())}
        weights[Sector.unknown] = wsum(
            [weights.get(Sector.unknown, 0), etf.holdings_weight, -wsum(weights.values())]
        )
        return "fund_reported", weights
    return "none", {Sector.unknown: etf.holdings_weight}


def portfolio_sectors(items, sector_data):
    groups = defaultdict(list)
    for item in items:
        if item.ticker in sector_data:
            for sector, weight in sector_data[item.ticker][1].items():
                groups[sector].append(
                    SectorContribution(etf_ticker=item.ticker, contribution=item.allocation * weight)
                )
    result = []
    for sector, contributions in sorted(groups.items()):
        contributions.sort(key=lambda value: (-value.contribution, value.etf_ticker))
        result.append(
            SectorExposure(
                sector=sector, weight=wsum(v.contribution for v in contributions), by_etf=contributions
            )
        )
    return sorted(result, key=lambda value: (-value.weight, value.sector))
