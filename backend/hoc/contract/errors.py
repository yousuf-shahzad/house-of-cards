"""Exceptions shared across layers. FROZEN.

Source adapters raise SourceError subclasses; the registry turns them into SourceAttempts.
Everything the API can report is a HocError carrying its ErrorCode and HTTP status.
"""

from __future__ import annotations

from typing import Any

from .api import ErrorBody, ErrorCode, ErrorResponse

# ---------- source adapters ----------


class SourceError(Exception):
    """Base for adapter failures. The message must be safe to show users (no secrets, no raw bodies)."""


class TickerNotFound(SourceError):
    """This source does not have this ETF (HTTP 404, not in the index...)."""


class SourceUnavailable(SourceError):
    """Network error, rate limit, offline with no cache, blocked endpoint..."""


class SourceParseError(SourceError):
    """The source answered but the content was not in the expected format (e.g. HTML instead of CSV)."""


# ---------- errors reported by the API ----------


class HocError(Exception):
    code: ErrorCode = "INTERNAL_ERROR"
    status: int = 500

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_response(self) -> ErrorResponse:
        return ErrorResponse(error=ErrorBody(code=self.code, message=self.message, details=self.details))


class PortfolioValidationError(HocError):
    """Business-rule failure in a PortfolioRequest. Raise with the specific code."""

    status = 422

    def __init__(self, code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details)
        self.code = code


class UnknownTickerError(HocError):
    """Every source said not_found for at least one requested ticker. details: {tickers, attempts}."""

    code = "UNKNOWN_TICKER"
    status = 422


class EtfNotFoundError(HocError):
    """GET /api/etfs/{ticker} for an ETF no source has."""

    code = "ETF_NOT_FOUND"
    status = 404


class JobNotFoundError(HocError):
    """GET /api/dependencies/{job_id} for an unknown or expired job (v2)."""

    code = "JOB_NOT_FOUND"
    status = 404


class ResearchNotFoundError(HocError):
    """GET /api/research/{research_id} for an unknown or expired research job (v3)."""

    code = "RESEARCH_NOT_FOUND"
    status = 404


class SourcesUnavailableError(HocError):
    """No requested ETF could be loaded because sources were unavailable."""

    code = "SOURCES_UNAVAILABLE"
    status = 503


# ---------- v2 dependency pipeline ----------


class CompanyUnavailable(Exception):
    """One company can't be analysed (v2). Raised by hoc.filings / hoc.ai, caught by the job runner, which records
    `status` on that company's CompanyRunStatus and carries on with the others. Never becomes an HTTP error."""

    def __init__(self, status: str, message: str) -> None:
        # status is one of: no_sec_filing, unsupported_form, sec_contact_missing, missing_api_key, error
        super().__init__(message)
        self.status = status
        self.message = message
