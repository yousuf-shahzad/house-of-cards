"""Example portfolios: tickers and allocations ONLY (user choices, not financial data). Owner: package f.

Holdings and weights are always fetched live (or from cache) through the service; an example is
offered by the UI only when every ETF in it verified.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExampleDefinition:
    id: str
    name: str
    description: str
    holdings: tuple[tuple[str, float], ...]
    """(ticker, allocation as a fraction of 1)."""


EXAMPLES: tuple[ExampleDefinition, ...] = (
    ExampleDefinition(
        id="us-core-tilt",
        name="US core with a tech tilt",
        description="S&P 500, Nasdaq-100, US tech and emerging markets: heavy mega-cap overlap.",
        holdings=(("IVV", 0.40), ("QQQ", 0.25), ("XLK", 0.15), ("EEM", 0.20)),
    ),
)
