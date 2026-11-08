"""Failure simulator for the Compare screen (Gawyn, 2026-11-08). Lead-owned additive contract.

"What happens to my money if one industry, country or supplier fails?" Every affected company loses
`basis.drop` of its value:
- the drop comes from history when we can get it: the proxy ETF's worst one-month fall
  (SHOCK_WINDOW_DAYS trading days) in the last HISTORY_YEARS years of daily adjusted closes;
- otherwise it is a simulated DEFAULT_SHOCK_DROP (10%) fall, and `basis.source` says so.

The API returns fractions of the portfolio. The UI turns them into money: before = the portfolio's
value (shares mode) or a notional $10,000 (percent mode), after = before * (1 - loss_fraction).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .api import PortfolioItem
from .units import Weight

ShockKind = Literal["sector", "country", "supplier"]
"""sector: every company in one Sector. country: every company whose `country` matches.
supplier: the companies in `StressRequest.company_keys` (the supplier, if held, and the companies
that rely on it in the dependencies result)."""

ShockSource = Literal["historical", "simulated"]

DEFAULT_SHOCK_DROP = 0.10
HISTORY_YEARS = 5
SHOCK_WINDOW_DAYS = 21
MAX_AFFECTED_LISTED = 10


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ShockSpec(_Model):
    kind: ShockKind
    key: Annotated[str, Field(min_length=1, max_length=120)]
    """sector: a Sector value (e.g. "information_technology"). country: ISO 3166-1 alpha-2, upper case
    (e.g. "TW"). supplier: the dependency target's key from the dependencies result."""
    label: Annotated[str, Field(max_length=200)] | None = None
    """Display name (e.g. "Taiwan Semiconductor Manufacturing"); echoed back, never used for matching."""
    drop: Annotated[float, Field(gt=0, le=1)] | None = None
    """Override the fall (0.10 = 10%). None: historical if possible, else DEFAULT_SHOCK_DROP."""


class StressRequest(_Model):
    baseline: Annotated[list[PortfolioItem], Field(min_length=1, max_length=50)]
    candidate: Annotated[list[PortfolioItem], Field(min_length=1, max_length=50)] | None = None
    """The changed portfolio from Try a change; None when only the current portfolio is shocked."""
    shock: ShockSpec
    company_keys: Annotated[list[Annotated[str, Field(min_length=1, max_length=200)]], Field(max_length=300)] = []
    """supplier only (ignored otherwise): the company_keys the failure hits."""


class ShockBasis(_Model):
    source: ShockSource
    drop: Annotated[float, Field(gt=0, le=1)]
    """The fraction of value each affected company loses (0.193 = 19.3%)."""
    proxy: str | None = None
    """The ETF whose history set the drop (e.g. "XLK"); None when simulated."""
    window_start: date | None = None
    window_end: date | None = None
    """The worst window's first and last close (historical only)."""
    description: str
    """One plain-English line, e.g. "XLK's worst month in the last 5 years: -19.3% (2022-08-16 to
    2022-09-15)" or "No price history for this group, so we simulated a 10% fall"."""


class AffectedCompany(_Model):
    company_key: str
    company_name: str
    exposure: Weight
    loss: Weight
    """exposure * basis.drop: the share of the whole portfolio's value this company loses."""


class StressSide(_Model):
    affected_weight: Weight
    """Share of the portfolio held in affected companies (look-through)."""
    loss_fraction: Weight
    """Share of the portfolio's value lost: affected_weight * basis.drop."""
    affected_count: int
    affected: list[AffectedCompany] = []
    """Largest loss first, then company_key; at most MAX_AFFECTED_LISTED."""


class StressResponse(_Model):
    status: Literal["ok", "partial"]
    """partial: part of a portfolio couldn't be looked through, so its loss may be understated (see notes)."""
    shock: ShockSpec
    basis: ShockBasis
    baseline: StressSide
    candidate: StressSide | None = None
    notes: list[str] = []
