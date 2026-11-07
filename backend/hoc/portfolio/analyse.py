"""The whole analysis, as one pure function. Owner: package e (Yousuf's Codex). Signature fixed by W0-B.

No I/O and no clock: `today` drives age_days and staleness, `generated_at` is stamped as given.
Every definition is in docs/hoc/CONTRACT.md. Split the work across exposure.py, overlap.py,
concentration.py, sectors.py and coverage.py in this package as you see fit.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime

from hoc.contract import AnalysisResponse, EtfFailure, EtfHoldings, PortfolioRequest


def analyse(
    request: PortfolioRequest,
    loaded: Mapping[str, EtfHoldings],
    failures: Mapping[str, EtfFailure],
    *,
    today: date,
    generated_at: datetime,
) -> AnalysisResponse:
    """`loaded` and `failures` are keyed by upper-case ticker and together cover every request ticker."""
    raise NotImplementedError("package e: analyse")
