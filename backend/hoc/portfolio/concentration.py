"""Concentration on full company exposure, before display truncation."""

from collections import defaultdict

from hoc.contract import Concentration, wsum


def concentration(companies):
    positive = [value.exposure for value in companies if value.exposure > 0]
    total = wsum(positive)
    hhi = wsum((value / total) ** 2 for value in positive) if total else 0.0
    securities = defaultdict(list)
    for company in companies:
        for security in company.securities:
            securities[security.security_key].append(security.exposure)
    return Concentration(
        top5=wsum(value.exposure for value in companies[:5]),
        top10=wsum(value.exposure for value in companies[:10]),
        top20=wsum(value.exposure for value in companies[:20]),
        hhi=hhi,
        effective_companies=1.0 / hhi if hhi else 0.0,
        distinct_securities=sum(wsum(values) > 0 for values in securities.values()),
        distinct_companies=len(positive),
    )
