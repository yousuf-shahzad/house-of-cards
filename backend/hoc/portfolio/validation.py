"""Portfolio request business rules. Owner: package e (Yousuf's Codex). Signature fixed by W0-B.

Raise hoc.contract.PortfolioValidationError with the specific code:
  ALLOCATION_SUM_INVALID  |sum - 1| > ALLOCATION_TOLERANCE   details {"total": <sum>, "tolerance": 1e-4}
  DUPLICATE_TICKER        same ticker twice (case-insensitive)  details {"tickers": [...]}
  TOO_MANY_ETFS           more than MAX_ETFS                    details {"count": n, "max": 10}
Return non-fatal notices (e.g. a 0% allocation) as Notice objects.
"""

from __future__ import annotations

from hoc.contract import Notice, PortfolioRequest


def validate_request(request: PortfolioRequest) -> list[Notice]:
    raise NotImplementedError("package e: validate_request")
