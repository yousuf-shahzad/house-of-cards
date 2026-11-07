"""Interfaces every data source implements. FROZEN: change only through the lead.

A SourceAdapter turns an ETF ticker into RawEtfHoldings, exactly as that source reports them
(weights already converted to fractions). It never resolves identity or computes anything.
A ReferenceProvider answers "what is this security?" for symbols or ISINs.
Both get an HttpClient (hoc.core.http) injected and must do all network access through it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, Protocol, runtime_checkable

from hoc.contract import RawEtfHoldings, SecurityInfo, SourceName


@runtime_checkable
class SourceAdapter(Protocol):
    name: ClassVar[SourceName]

    def supports(self, ticker: str) -> bool:
        """Cheap, no network: could this source plausibly have this ticker? (True if unsure.)"""
        ...

    def fetch(self, ticker: str) -> RawEtfHoldings:
        """Return the ETF's latest holdings.

        Raises hoc.contract.TickerNotFound, SourceUnavailable or SourceParseError. Never returns partial
        garbage: if the payload is not the expected format, raise SourceParseError.
        """
        ...


@runtime_checkable
class ReferenceProvider(Protocol):
    def lookup_symbols(self, symbols: Sequence[str]) -> dict[str, SecurityInfo]:
        """Symbol (TickerInside convention, e.g. 'BRK.B', '2330.TW') -> info. Unknown symbols are omitted."""
        ...

    def lookup_isins(self, isins: Sequence[str]) -> dict[str, SecurityInfo]:
        """ISIN -> info. Return {} if this provider cannot look up ISINs."""
        ...
