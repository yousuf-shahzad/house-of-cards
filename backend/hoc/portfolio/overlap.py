"""Company and listing overlap on unadjusted ETF NAV weights."""

from hoc.contract import Overlap, OverlapPair, TopShared, wsum

from .exposure import group_weights


def overlap(tickers, loaded):
    companies = {t: group_weights(loaded[t].holdings, "company_key") for t in tickers}
    securities = {t: group_weights(loaded[t].holdings, "security_key") for t in tickers}
    matrix = [[0.0 for _ in tickers] for _ in tickers]
    pairs = []
    for i, a in enumerate(tickers):
        matrix[i][i] = loaded[a].holdings_weight
        for j in range(i + 1, len(tickers)):
            b = tickers[j]
            shared = sorted(
                k
                for k in companies[a].keys() & companies[b].keys()
                if companies[a][k] > 0 and companies[b][k] > 0
            )
            shared_securities = sorted(
                k
                for k in securities[a].keys() & securities[b].keys()
                if securities[a][k] > 0 and securities[b][k] > 0
            )
            names = {}
            for line in sorted(loaded[a].holdings, key=lambda line: line.security_key):
                names.setdefault(line.company_key, line.company_name)
            top = [
                TopShared(
                    company_key=k,
                    company_name=names[k],
                    weight_a=companies[a][k],
                    weight_b=companies[b][k],
                    min_weight=min(companies[a][k], companies[b][k]),
                )
                for k in shared
            ]
            top.sort(key=lambda value: (-value.min_weight, value.company_key))
            weight = wsum(value.min_weight for value in top)
            matrix[i][j] = matrix[j][i] = weight
            pairs.append(
                OverlapPair(
                    etf_a=a,
                    etf_b=b,
                    shared_securities=len(shared_securities),
                    shared_companies=len(shared),
                    weighted_overlap=weight,
                    weighted_overlap_securities=wsum(
                        min(securities[a][k], securities[b][k]) for k in shared_securities
                    ),
                    top_shared=top[:10],
                )
            )
    return Overlap(etfs=tickers, matrix=matrix, pairs=pairs)
