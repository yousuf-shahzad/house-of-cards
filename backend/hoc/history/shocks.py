"""How big a fall to simulate (FIX-63, CONTRACT.md section 11).

Historical when we can: the proxy fund's worst one-month fall (SHOCK_WINDOW_DAYS trading days) in the
last HISTORY_YEARS years of daily closes. Otherwise a simulated DEFAULT_SHOCK_DROP fall, with a plain
reason. A user-chosen drop (ShockSpec.drop) always wins.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from hoc.contract import DEFAULT_SHOCK_DROP, HISTORY_YEARS, SHOCK_WINDOW_DAYS, ShockBasis, ShockSpec

from .prices import DailyCloses, HistoryProvider
from .proxies import label_for, proxy_for

log = logging.getLogger(__name__)

MIN_HISTORY_DAYS = 120
"""Fewer closes than this (about six months) is too little history to call a worst month."""


def worst_window_drop(
    dates: tuple[date, ...] | list[date], closes: tuple[float, ...] | list[float], window: int = SHOCK_WINDOW_DAYS
) -> tuple[float, date, date] | None:
    """The largest fall from one close to the close `window` trading days later, as a positive fraction,
    with the window's first and last dates. None if there are not enough closes or it never fell."""
    if len(closes) != len(dates) or len(closes) <= window:
        return None
    worst = 0.0
    at = -1
    for i in range(len(closes) - window):
        change = closes[i + window] / closes[i] - 1.0
        if change < worst:
            worst, at = change, i
    if at < 0:
        return None
    return -worst, dates[at], dates[at + window]


def _last_years(history: DailyCloses, years: int) -> tuple[list[date], list[float]]:
    if not history.dates:
        return [], []
    cutoff = history.dates[-1] - timedelta(days=round(365.25 * years))
    kept = [(d, c) for d, c in zip(history.dates, history.closes) if d >= cutoff]
    return [d for d, _ in kept], [c for _, c in kept]


def simulated_basis(reason: str, drop: float = DEFAULT_SHOCK_DROP) -> ShockBasis:
    return ShockBasis(source="simulated", drop=drop, description=reason)


def historical_shock(kind: str, key: str, provider: HistoryProvider | None, *, label: str | None = None) -> ShockBasis:
    """The drop for one shock, from history if possible, else a simulated DEFAULT_SHOCK_DROP (20%) fall (never raises)."""
    name = label or label_for(kind, key)
    pct = f"{DEFAULT_SHOCK_DROP:.0%}"
    if kind == "supplier":
        return simulated_basis(
            f"A supplier failure has no price history to replay, so we simulated a {pct} fall for every company "
            "that relies on it."
        )
    proxy = proxy_for(kind, key)
    if proxy is None:
        return simulated_basis(f"No fund tracks {name} on its own, so we simulated a {pct} fall.")
    if provider is None:
        return simulated_basis(f"Price history isn't available right now, so we simulated a {pct} fall.")
    try:
        history = provider.daily_closes(proxy)
    except Exception:  # SourceUnavailable, a parse error or a bug: fall back, never fail the request
        log.warning("price history for %s failed", proxy, exc_info=True)
        history = None
    if history is None:
        return simulated_basis(f"We couldn't load {proxy}'s price history, so we simulated a {pct} fall.")
    dates, closes = _last_years(history, HISTORY_YEARS)
    if len(closes) < MIN_HISTORY_DAYS:
        return simulated_basis(f"{proxy} doesn't have enough price history, so we simulated a {pct} fall.")
    found = worst_window_drop(dates, closes)
    if found is None:
        return simulated_basis(f"{proxy} never fell over a month in the last {HISTORY_YEARS} years, "
                               f"so we simulated a {pct} fall.")
    drop, start, end = found
    drop = round(min(drop, 1.0), 4)
    return ShockBasis(
        source="historical",
        drop=drop,
        proxy=proxy,
        window_start=start,
        window_end=end,
        description=(
            f"{name}: {proxy}'s worst month in the last {HISTORY_YEARS} years was a {drop:.1%} fall "
            f"({start:%d %b %Y} to {end:%d %b %Y})."
        ),
    )


def basis_for(shock: ShockSpec, provider: HistoryProvider | None) -> ShockBasis:
    """The service's entry point: a user-chosen drop wins; otherwise historical_shock."""
    if shock.drop is not None:
        return simulated_basis(f"You chose a {shock.drop:.0%} fall.", drop=shock.drop)
    return historical_shock(shock.kind, shock.key, provider, label=shock.label)


class HistoricalShocks:
    """What Service.history holds (Bekarys's Claude, #259): historical_shock(kind, key) -> ShockBasis.
    Production: HistoricalShocks(YahooHistory(http)). Never raises; falls back to a simulated DEFAULT_SHOCK_DROP (20%)."""

    def __init__(self, provider: HistoryProvider | None) -> None:
        self.provider = provider

    def historical_shock(self, kind: str, key: str, label: str | None = None) -> ShockBasis:
        return historical_shock(kind, key, self.provider, label=label)
