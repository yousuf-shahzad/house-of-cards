"""Fake source and reference over SYNTHETIC fixtures, for tests and offline development only.

Everything it serves is invented test data (tickers and companies prefixed ZZ, CIKs starting 999),
lives in backend/tests/fixtures/synthetic/, and is labelled source="fake". Never wire it into the
production registry.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from hoc.contract import RawEtfHoldings, SecurityInfo, SourceName, SourceUnavailable, TickerNotFound

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "synthetic"


class FakeSourceAdapter:
    name: ClassVar[SourceName] = "fake"

    def __init__(
        self,
        raw_dir: Path = FIXTURES / "raw",
        unavailable: Sequence[str] = (),
    ) -> None:
        self.raw_dir = raw_dir
        self.unavailable = {ticker.upper() for ticker in unavailable}
        self.calls: list[str] = []

    def supports(self, ticker: str) -> bool:
        return True

    def fetch(self, ticker: str) -> RawEtfHoldings:
        ticker = ticker.upper()
        self.calls.append(ticker)
        if ticker in self.unavailable:
            raise SourceUnavailable(f"fake source configured as unavailable for {ticker}")
        path = self.raw_dir / f"{ticker}.json"
        if not path.is_file():
            raise TickerNotFound(f"no synthetic fixture for {ticker}")
        return RawEtfHoldings.model_validate_json(path.read_text(encoding="utf-8"))


class FakeReference:
    """ReferenceProvider over tests/fixtures/synthetic/reference.json."""

    def __init__(self, path: Path = FIXTURES / "reference.json") -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        self._symbols = {k: SecurityInfo.model_validate(v) for k, v in data.get("symbols", {}).items()}
        self._isins = {k: SecurityInfo.model_validate(v) for k, v in data.get("isins", {}).items()}

    def lookup_symbols(self, symbols: Sequence[str]) -> dict[str, SecurityInfo]:
        return {s: self._symbols[s] for s in symbols if s in self._symbols}

    def lookup_isins(self, isins: Sequence[str]) -> dict[str, SecurityInfo]:
        return {i: self._isins[i] for i in isins if i in self._isins}
