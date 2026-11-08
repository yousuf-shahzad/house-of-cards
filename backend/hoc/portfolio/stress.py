"""Pure failure simulation on supplied look-through analyses; no prices or network calls."""

from __future__ import annotations

from hoc.contract import (
    MAX_AFFECTED_LISTED,
    AffectedCompany,
    AnalysisResponse,
    PortfolioRequest,
    Sector,
    ShockBasis,
    StressRequest,
    StressResponse,
    StressSide,
    wsum,
)

from .validation import validate_request


def _side(
    request: StressRequest, analysis: AnalysisResponse, basis: ShockBasis, label: str,
) -> tuple[StressSide, list[str]]:
    companies = [company for company in analysis.exposures if company.exposure > 0]
    keys = set(request.company_keys)
    affected = []
    for company in companies:
        if request.shock.kind == "sector":
            matches = company.sector == request.shock.key
        elif request.shock.kind == "country":
            matches = company.country == request.shock.key
        else:
            matches = company.company_key in keys
        if matches:
            affected.append(AffectedCompany(
                company_key=company.company_key, company_name=company.company_name,
                exposure=company.exposure, loss=company.exposure * basis.drop,
            ))
    affected.sort(key=lambda company: (-company.loss, company.company_key))
    weight = wsum(company.exposure for company in affected)

    notes = []
    # Coverage reconciliation can leave floating-point dust. Ignore amounts that would
    # round to zero at the contract's ten-decimal serialization precision.
    for amount, reason in (
        (analysis.coverage.missing_allocation, "ETF holdings were unavailable"),
        (analysis.coverage.excluded_weight, "cash, derivative or FX holdings were excluded"),
        (analysis.coverage.unexplained_weight, "holdings weight was unexplained"),
    ):
        if round(amount, 10) > 0:
            notes.append(f"{label}: {amount:.2%} of the portfolio was not shocked because {reason}.")
    if analysis.exposures_truncated or analysis.other_exposure > 0:
        notes.append(f"{label}: the company list was truncated; omitted companies were not shocked.")
    if any(gap.kind == "nested_fund" and (gap.portfolio_weight is None or gap.portfolio_weight > 0)
           for gap in analysis.gaps):
        notes.append(f"{label}: holdings inside nested funds could not be looked through.")
    if request.shock.kind == "sector":
        unknown = wsum(company.exposure for company in companies if company.sector == Sector.unknown)
        if unknown > 0:
            notes.append(f"{label}: {unknown:.2%} of the portfolio has an unknown industry.")
    elif request.shock.kind == "country":
        unknown = wsum(company.exposure for company in companies if not (company.country or "").strip())
        if unknown > 0:
            notes.append(f"{label}: {unknown:.2%} of the portfolio has an unknown country.")
    if notes:
        notes.append(f"{label}: coverage is incomplete, so the loss may be understated.")

    return StressSide(
        affected_weight=weight, loss_fraction=weight * basis.drop, affected_count=len(affected),
        affected=affected[:MAX_AFFECTED_LISTED],
    ), notes


def simulate_failure(
    request: StressRequest,
    baseline_analysis: AnalysisResponse,
    candidate_analysis: AnalysisResponse | None,
    basis: ShockBasis,
) -> StressResponse:
    """Apply one supplied drop to each side's affected company exposure without renormalising.

    The caller obtains the historical/simulated basis (including any explicit override)
    and analyses. Only the top ten affected companies are listed; totals use every match.
    Supplier keys identify the supplied affected set, including the supplier if held.
    """
    if (request.candidate is None) != (candidate_analysis is None):
        raise ValueError("Candidate analysis must be supplied exactly when a candidate is requested.")
    for holdings, analysis in ((request.baseline, baseline_analysis), (request.candidate, candidate_analysis)):
        if analysis is None:
            continue
        validate_request(PortfolioRequest(holdings=holdings))
        if sorted((item.ticker, item.allocation) for item in holdings) != sorted(
            (item.ticker, item.allocation) for item in analysis.request.holdings
        ):
            raise ValueError("Stress analyses must correspond to the requested portfolios.")

    baseline, notes = _side(request, baseline_analysis, basis, "Your portfolio")
    candidate = None
    if candidate_analysis is not None:
        candidate, candidate_notes = _side(request, candidate_analysis, basis, "Your new mix")
        notes.extend(candidate_notes)
    return StressResponse(
        status="partial" if notes else "ok", shock=request.shock, basis=basis,
        baseline=baseline, candidate=candidate, notes=notes,
    )
