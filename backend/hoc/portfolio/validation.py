"""Business validation for portfolio requests."""

from hoc.contract import (
    ALLOCATION_TOLERANCE,
    MAX_ETFS,
    Notice,
    PortfolioRequest,
    PortfolioValidationError,
    wsum,
)


def validate_request(request: PortfolioRequest) -> list[Notice]:
    if len(request.holdings) > MAX_ETFS:
        raise PortfolioValidationError(
            "TOO_MANY_ETFS",
            f"At most {MAX_ETFS} ETFs are allowed.",
            {"count": len(request.holdings), "max": MAX_ETFS},
        )
    tickers = [item.ticker.upper() for item in request.holdings]
    duplicates = sorted({ticker for ticker in tickers if tickers.count(ticker) > 1})
    if duplicates:
        raise PortfolioValidationError(
            "DUPLICATE_TICKER",
            "Each ETF may appear only once.",
            {"tickers": duplicates},
        )
    total = wsum(item.allocation for item in request.holdings)
    if abs(total - 1.0) > ALLOCATION_TOLERANCE:
        raise PortfolioValidationError(
            "ALLOCATION_SUM_INVALID",
            "Allocations must total 100%.",
            {"total": total, "tolerance": ALLOCATION_TOLERANCE},
        )
    return [
        Notice(code="ZERO_ALLOCATION", message=f"{item.ticker} has a 0% allocation.")
        for item in request.holdings
        if item.allocation == 0
    ]
