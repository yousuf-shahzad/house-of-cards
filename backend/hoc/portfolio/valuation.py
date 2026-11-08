"""Pure share valuation. Quotes and the valuation date are supplied by the service."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Collection, Mapping
from datetime import date

from hoc.contract import (
    MAX_ETFS,
    PRICE_STALE_DAYS,
    Attribution,
    PriceQuote,
    ValuationIssue,
    ValuationRequest,
    ValuationResponse,
    ValuationRowResult,
    wsum,
)


def value_portfolio(
    request: ValuationRequest,
    quotes: Mapping[str, PriceQuote | None],
    unavailable: Collection[str],
    *,
    today: date,
) -> ValuationResponse:
    """Reserve pinned fractions and distribute the remainder by USD share value.

    A missing mapping entry, like None, means no published price. ``unavailable``
    distinguishes source failures. Pinned rows require neither shares nor prices.
    Blocked responses retain pinned allocations but withhold unpinned allocations;
    total_value includes only computable unpinned USD values.
    """
    quotes = {ticker.upper(): quote for ticker, quote in quotes.items()}
    unavailable = {ticker.upper() for ticker in unavailable}
    rows: list[ValuationRowResult] = []
    issues: list[ValuationIssue] = []
    attribution_pairs: set[tuple[str, str]] = set()

    def issue(code, message, row=None, *, severity="blocking"):
        item = ValuationIssue(
            code=code, severity=severity, ticker=row.ticker if row else None, message=message
        )
        issues.append(item)
        if row is not None:
            row.issues.append(item)

    if len(request.rows) > MAX_ETFS:
        issue("too_many_etfs", f"At most {MAX_ETFS} ETFs are allowed.")
    counts = Counter(item.ticker.upper() for item in request.rows)
    duplicates = sorted(ticker for ticker, count in counts.items() if count > 1)
    if duplicates:
        issue("duplicate_ticker", f"Each ETF may appear only once: {', '.join(duplicates)}.")

    for item in request.rows:
        ticker = item.ticker.upper()
        quote = None if ticker in unavailable else quotes.get(ticker)
        pinned = item.allocation_override is not None
        row = ValuationRowResult(
            ticker=ticker,
            pinned=pinned,
            shares=item.shares,
            price=quote,
            allocation=item.allocation_override,
        )
        rows.append(row)
        if quote is not None:
            if quote.attribution:
                attribution_pairs.add((quote.source, quote.attribution))
            row.price_age_days = (today - quote.as_of).days
            row.price_stale = row.price_age_days > PRICE_STALE_DAYS
            if row.price_stale:
                issue(
                    "stale_price",
                    f"Price is from {quote.as_of} ({row.price_age_days} days old).",
                    row,
                    severity="warning",
                )
        if pinned:
            continue
        if item.shares is None:
            issue("missing_shares", "Enter a share count or pin this row to a percentage.", row)
        if ticker in unavailable:
            issue("price_unavailable", "Price could not be loaded; pin this row to a percentage.", row)
        elif quote is None:
            issue("no_price", "No price is published; pin this row to a percentage.", row)
        elif not math.isfinite(quote.price) or quote.price <= 0:
            issue("invalid_price", "Price is invalid; pin this row to a percentage.", row)
        elif quote.currency != "USD":
            issue("non_usd_price", "Price is not in USD; pin this row to a percentage.", row)
        elif item.shares is not None:
            value = item.shares * quote.price
            if not math.isfinite(value) or (item.shares > 0 and value == 0):
                issue("invalid_price", "Share value is outside the supported numeric range.", row)
            else:
                row.value = value

    pinned_total = wsum(row.allocation for row in rows if row.pinned)
    unpinned = [row for row in rows if not row.pinned]
    try:
        total_value = math.fsum(row.value for row in unpinned if row.value is not None)
    except OverflowError:
        total_value = 0.0
        issue("invalid_price", "Total share value is outside the supported numeric range.")

    if pinned_total > 1:
        issue("pinned_over_100", "Pinned allocations exceed 100%.")
    elif not unpinned and pinned_total != 1:
        issue("allocation_sum_invalid", "When every row is pinned, allocations must total 100%.")
    elif unpinned and pinned_total < 1 and total_value == 0:
        issue(
            "nothing_to_rescale",
            "Unpinned rows need a positive share value to fill the remaining allocation.",
        )

    blocked = any(item.severity == "blocking" for item in issues)
    if not blocked:
        for row in unpinned:
            row.allocation = (1 - pinned_total) * (row.value / total_value) if total_value else 0.0

    return ValuationResponse(
        status="blocked" if blocked else "usable",
        as_of_date=today,
        rows=rows,
        total_value=total_value,
        pinned_total=pinned_total,
        issues=sorted(issues, key=lambda item: item.severity != "blocking"),
        attributions=[Attribution(source=source, text=text) for source, text in sorted(attribution_pairs)],
    )
