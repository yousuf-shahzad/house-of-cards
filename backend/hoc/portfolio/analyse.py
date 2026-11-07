"""Pure portfolio analysis; dates and loaded data are supplied by the caller."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime

from hoc.contract import (
    AnalysisResponse,
    Attribution,
    Coverage,
    DataGap,
    EtfFailure,
    EtfHoldings,
    EtfReport,
    PortfolioRequest,
    Sector,
    wsum,
)
from hoc.contract.units import (
    GAP_MIN_PORTFOLIO_WEIGHT,
    LOW_COVERAGE_THRESHOLD,
    STALE_INFO_DAYS,
    STALE_WARNING_DAYS,
)

from .concentration import concentration
from .exposure import exposures
from .overlap import overlap
from .sectors import etf_sectors, portfolio_sectors
from .validation import validate_request


def analyse(
    request: PortfolioRequest,
    loaded: Mapping[str, EtfHoldings],
    failures: Mapping[str, EtfFailure],
    *,
    today: date,
    generated_at: datetime,
) -> AnalysisResponse:
    """Analyse requested ETFs; loaded/failures must cover each requested ticker."""
    warnings = validate_request(request)
    items = request.holdings
    tickers = [item.ticker for item in items if item.ticker in loaded]
    sector_data = {ticker: etf_sectors(loaded[ticker]) for ticker in tickers}
    companies = exposures(items, loaded)
    sectors = portfolio_sectors(items, sector_data)
    total = wsum(item.allocation for item in items)
    covered = wsum(
        item.allocation * loaded[item.ticker].holdings_weight for item in items if item.ticker in loaded
    )
    excluded = wsum(
        item.allocation * loaded[item.ticker].excluded_weight for item in items if item.ticker in loaded
    )
    missing = wsum(item.allocation for item in items if item.ticker not in loaded)
    coverage = Coverage(
        total_allocation=total,
        loaded_allocation=wsum(item.allocation for item in items if item.ticker in loaded),
        missing_allocation=missing,
        covered_weight=covered,
        excluded_weight=excluded,
        unexplained_weight=wsum([total, -covered, -excluded, -missing]),
        unmatched_weight=wsum(
            item.allocation * loaded[item.ticker].unmatched_weight for item in items if item.ticker in loaded
        ),
        sector_known_weight=wsum(value.weight for value in sectors if value.sector != Sector.unknown),
    )
    reports, gaps, attributions = [], [], []
    for item in items:
        ticker = item.ticker
        if ticker not in loaded:
            failure = failures[ticker]
            reports.append(
                EtfReport(
                    ticker=ticker, allocation=item.allocation, status="unavailable", attempts=failure.attempts
                )
            )
            gaps.append(
                DataGap(
                    kind="missing_etf",
                    severity="critical",
                    etf_ticker=ticker,
                    portfolio_weight=item.allocation,
                    message=failure.message,
                )
            )
            continue
        etf = loaded[ticker]
        local_gaps = []
        age = (today - etf.as_of).days
        if age > STALE_INFO_DAYS:
            local_gaps.append(
                DataGap(
                    kind="stale_disclosure",
                    severity="warning" if age > STALE_WARNING_DAYS else "info",
                    etf_ticker=ticker,
                    message=f"Holdings disclosure is {age} days old.",
                )
            )
        if etf.excluded:
            local_gaps.append(
                DataGap(
                    kind="excluded_lines",
                    severity="info",
                    etf_ticker=ticker,
                    portfolio_weight=item.allocation * etf.excluded_weight,
                    message=f"{len(etf.excluded)} cash, derivative or FX lines excluded.",
                )
            )
        if sector_data[ticker][0] == "none":
            local_gaps.append(
                DataGap(
                    kind="no_sector_data",
                    severity="info",
                    etf_ticker=ticker,
                    portfolio_weight=item.allocation * etf.holdings_weight,
                    message="No usable sector breakdown is available.",
                )
            )
        for kind, predicate in (
            ("unmatched_identity", lambda line: line.identity_status == "unmatched"),
            ("nested_fund", lambda line: line.asset_class == "fund"),
        ):
            small = []
            for line in sorted(etf.holdings, key=lambda line: line.security_key):
                weight = item.allocation * line.weight
                if not predicate(line) or weight <= 0:
                    continue
                if weight < GAP_MIN_PORTFOLIO_WEIGHT:
                    small.append(weight)
                else:
                    local_gaps.append(
                        DataGap(
                            kind=kind,
                            severity="warning",
                            etf_ticker=ticker,
                            subject=line.security_key,
                            portfolio_weight=weight,
                            message=f"{line.name}: {kind.replace('_', ' ')}.",
                        )
                    )
            if small:
                local_gaps.append(
                    DataGap(
                        kind=kind,
                        severity="warning",
                        etf_ticker=ticker,
                        portfolio_weight=wsum(small),
                        message=f"{len(small)} smaller lines: {kind.replace('_', ' ')}.",
                    )
                )
        gaps.extend(local_gaps)
        reports.append(
            EtfReport(
                ticker=ticker,
                name=etf.etf_name,
                allocation=item.allocation,
                status="warning" if any(g.severity in ("warning", "critical") for g in local_gaps) else "ok",
                source=etf.source,
                source_layer=etf.source_layer,
                source_url=etf.source_url,
                filing_url=etf.filing_url,
                attribution=etf.attribution,
                licence=etf.licence,
                as_of=etf.as_of,
                age_days=age,
                retrieved_at=etf.retrieved_at,
                holdings_count=len(etf.holdings),
                company_count=len({h.company_key for h in etf.holdings}),
                reported_weight=etf.reported_weight,
                holdings_weight=etf.holdings_weight,
                excluded_weight=etf.excluded_weight,
                unmatched_weight=etf.unmatched_weight,
                portfolio_covered_weight=item.allocation * etf.holdings_weight,
                sector_basis=sector_data[ticker][0],
                warnings=etf.warnings,
                attempts=etf.attempts,
            )
        )
        if etf.attribution:
            attribution = Attribution(
                source=etf.source, text=etf.attribution, url=etf.source_url, licence=etf.licence
            )
            if attribution not in attributions:
                attributions.append(attribution)
    if covered < LOW_COVERAGE_THRESHOLD * total:
        gaps.append(
            DataGap(
                kind="low_coverage",
                severity="warning",
                portfolio_weight=wsum([total, -covered]),
                message="Look-through coverage is below 95% of allocated weight.",
            )
        )
    return AnalysisResponse(
        generated_at=generated_at,
        as_of_date=today,
        request=request,
        etfs=reports,
        coverage=coverage,
        exposures=companies[: request.max_companies],
        exposures_truncated=len(companies) > request.max_companies,
        other_exposure=wsum(value.exposure for value in companies[request.max_companies :]),
        overlap=overlap(tickers, loaded),
        concentration=concentration(companies),
        sectors=sectors,
        gaps=gaps,
        warnings=warnings,
        attributions=attributions,
    )
