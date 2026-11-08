"""Company and security aggregation without renormalising exposure."""

from collections import defaultdict

from hoc.contract import CompanyExposure, Contribution, SecurityExposure, wsum


def group_weights(holdings, key):
    groups = defaultdict(list)
    for line in holdings:
        groups[getattr(line, key)].append(line.weight)
    return {name: wsum(weights) for name, weights in sorted(groups.items())}


def exposures(items, loaded):
    companies = defaultdict(list)
    for item in items:
        if item.allocation > 0 and item.ticker in loaded:
            for line in loaded[item.ticker].holdings:
                companies[line.company_key].append((item, line))
    result = []
    for key, rows in sorted(companies.items()):
        # Stable representative metadata even if a source changes line order.
        rows.sort(key=lambda row: (row[1].security_key, row[0].ticker, row[1].name))
        representative = rows[0][1]
        # Issuer-reported countries outrank TickerInside's listing-country fallback;
        # within that fallback, an overseas listing outranks an inferred US listing.
        # Keep the existing stable row ordering to break ties without changing weights.
        known_countries = [line for _, line in rows if line.country]
        country = min(known_countries, key=lambda line: (
            line.source == "tickerinside", line.source == "tickerinside" and line.country == "US"
        )).country if known_countries else None
        by_etf, securities = defaultdict(list), defaultdict(list)
        for item, line in rows:
            by_etf[item.ticker].append((item, line))
            securities[line.security_key].append((item, line))
        contributions = [
            Contribution(
                etf_ticker=ticker,
                weight_in_etf=wsum(line.weight for _, line in lines),
                contribution=wsum(item.allocation * line.weight for item, line in lines),
                security_keys=sorted({line.security_key for _, line in lines}),
            )
            for ticker, lines in sorted(by_etf.items())
        ]
        contributions.sort(key=lambda value: (-value.contribution, value.etf_ticker))
        security_exposures = [
            SecurityExposure(
                security_key=security_key,
                security_id=lines[0][1].security_id,
                security_id_type=lines[0][1].security_id_type,
                symbol=lines[0][1].symbol,
                name=lines[0][1].name,
                exposure=wsum(item.allocation * line.weight for item, line in lines),
            )
            for security_key, lines in sorted(securities.items())
        ]
        security_exposures.sort(key=lambda value: (-value.exposure, value.security_key))
        result.append(
            CompanyExposure(
                rank=0,
                company_key=key,
                company_name=representative.company_name,
                identity_status=max(
                    (line.identity_status for _, line in rows),
                    key={"resolved": 0, "partial": 1, "unmatched": 2}.__getitem__,
                ),
                symbols=sorted({line.symbol for _, line in rows if line.symbol}),
                sector=representative.sector,
                country=country,
                exposure=wsum(value.contribution for value in contributions),
                etf_count=sum(value.contribution > 0 for value in contributions),
                contributions=contributions,
                securities=security_exposures,
            )
        )
    result.sort(key=lambda value: (-value.exposure, value.company_key))
    for rank, value in enumerate(result, 1):
        value.rank = rank
    return result
