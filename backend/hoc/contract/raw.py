"""What source adapters return: one ETF's holdings exactly as the source reported them. FROZEN."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from .units import AssetClass, SourceName, Weight


class PriceQuote(BaseModel):
    """One ETF's latest market price, as published by a source (v2). Used to value share counts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    price: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    """Price per share in `currency`."""
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    as_of: date
    """The trading date of the price (e.g. TickerInside last_close_date), not the download date."""
    kind: Literal["close", "nav"] = "close"
    """'close' = exchange closing price (TickerInside last_close); 'nav' = net asset value per share."""
    source: SourceName
    attribution: str | None = None


class RawHolding(BaseModel):
    """One line from a source file. Identifiers are whatever that source provides (often partial)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_symbol: str | None = None
    """The source's own symbol, e.g. TickerInside 'BRK.B' / '2330.TW', iShares 'BRKB' + exchange."""
    name: str | None = None
    weight: Weight
    """Fraction of the ETF's NAV as reported. May be negative (short futures, FX)."""
    asset_class: AssetClass = "equity"
    exchange: str | None = None
    country: str | None = None
    """ISO 3166-1 alpha-2 of the listing or issuer, when known."""
    currency: str | None = None
    isin: str | None = None
    cusip: str | None = None
    sedol: str | None = None
    lei: str | None = None
    cik: str | None = None
    """10-digit zero-padded SEC CIK."""
    figi: str | None = None
    sector_label: str | None = None
    """The source's own sector text, unmapped. Normalisation maps it onto Sector."""
    market_value_usd: float | None = None


class RawEtfHoldings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    etf_ticker: str
    etf_name: str | None = None
    source: SourceName
    source_layer: str | None = None
    """Where the source itself got the data, e.g. TickerInside 'issuer' or 'sec_nport'."""
    as_of: date
    """The DISCLOSURE date of the holdings (not the download date)."""
    retrieved_at: AwareDatetime
    source_url: str
    filing_url: str | None = None
    attribution: str | None = None
    """Text the source requires us to show (TickerInside: its cite_as line). Mandatory where licensed."""
    licence: str | None = None
    reported_sector_weights: dict[str, Weight] | None = None
    """The fund's own sector breakdown, label -> fraction of NAV, if the source publishes one."""
    holdings: list[RawHolding]
    warnings: list[str] = []
    price: PriceQuote | None = None
    """The ETF's own latest price, if this source publishes one (v2). Bad price data -> None + a warning."""


class SecurityInfo(BaseModel):
    """Reference data about one security, from a ReferenceProvider. Every field may be missing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str | None = None
    name: str | None = None
    cik: str | None = None
    lei: str | None = None
    figi: str | None = None
    share_class_figi: str | None = None
    exchange: str | None = None
    country: str | None = None
    sector_label: str | None = None
