"""v2: share-based portfolio valuation (POST /api/valuation). FROZEN: mirrored in frontend/api/types.ts.

Rows give shares (unpinned) or a target allocation (pinned). With pinned total P and unpinned values
V_i = shares_i x price_i: allocation_i = (1 - P) * V_i / sum(V). All arithmetic is Python's
(hoc.portfolio.valuation); the UI only displays it. A `usable` response's allocations sum to 1 and can
be sent to POST /api/analysis unchanged.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .api import TICKER_PATTERN, Attribution
from .raw import PriceQuote
from .units import Weight

PRICE_STALE_DAYS = 4
"""A price is stale when its date is more than 4 calendar days before the valuation date (weekends +
one holiday; no exchange calendar). Stale prices warn but don't block."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ValuationRow(_Model):
    ticker: Annotated[str, Field(pattern=TICKER_PATTERN)]
    shares: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    """Number of shares held (fractional allowed). Ignored when allocation_override is set."""
    allocation_override: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    """A pinned target allocation as a FRACTION (0.25 = 25%). None = unpinned (valued from shares)."""

    @field_validator("ticker")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()


class ValuationRequest(_Model):
    rows: Annotated[list[ValuationRow], Field(min_length=1, max_length=50)]


ValuationIssueCode = Literal[
    "no_price",            # the ETF's source publishes no price: pin this row to a %
    "invalid_price",       # price present but unusable
    "non_usd_price",       # not USD: no FX conversion, so pin this row to a %
    "price_unavailable",   # the ETF couldn't be loaded at all
    "stale_price",         # warning only: price older than PRICE_STALE_DAYS
    "missing_shares",      # unpinned row with no shares entered
    "pinned_over_100",     # pinned allocations sum above 100%
    "nothing_to_rescale",  # pinned < 100% but the unpinned rows have no value
    "allocation_sum_invalid",  # every row pinned and they don't total 100%
    "duplicate_ticker",
    "too_many_etfs",
]


class ValuationIssue(_Model):
    code: ValuationIssueCode
    severity: Literal["warning", "blocking"]
    ticker: str | None = None
    """None for portfolio-level issues."""
    message: str


class ValuationRowResult(_Model):
    ticker: str
    pinned: bool
    shares: float | None = None
    price: PriceQuote | None = None
    price_age_days: int | None = None
    """(as_of_date - price.as_of) in days."""
    price_stale: bool = False
    value: float | None = None
    """shares x price in price.currency, for unpinned rows with a usable price."""
    allocation: Weight | None = None
    """The row's resulting allocation (fraction). None when the response is blocked for this row."""
    issues: list[ValuationIssue] = []


class ValuationResponse(_Model):
    status: Literal["usable", "blocked"]
    """usable: every row has an allocation and they total 1. blocked: fix the blocking issues first."""
    as_of_date: date
    rows: list[ValuationRowResult]
    """Same order as the request."""
    total_value: float
    """Sum of unpinned rows' values (USD)."""
    pinned_total: Weight
    issues: list[ValuationIssue] = []
    """All issues (row-level ones repeated here with their ticker), blocking first."""
    attributions: list[Attribution] = []
