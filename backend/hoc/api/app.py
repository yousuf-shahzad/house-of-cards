"""FastAPI app. Routes and error shapes are part of the frozen contract (OpenAPI snapshot in
tests/snapshots/openapi.json). Owner after W0-B: package f (Bekarys's Claude).

Run: uv run uvicorn hoc.api.app:app --reload --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Path, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from hoc import __version__
from hoc.config import Settings
from hoc.contract import (
    AnalysisResponse,
    ErrorBody,
    ErrorResponse,
    EtfSummary,
    ExamplesResponse,
    HealthResponse,
    HocError,
    PortfolioRequest,
    SourceName,
)
from hoc.contract.api import TICKER_PATTERN
from hoc.service import EtfService

ERRORS = {
    404: {"model": ErrorResponse, "description": "ETF_NOT_FOUND"},
    422: {"model": ErrorResponse, "description": "VALIDATION_ERROR, ALLOCATION_SUM_INVALID, DUPLICATE_TICKER, "
                                                 "TOO_MANY_ETFS, UNKNOWN_TICKER"},
    503: {"model": ErrorResponse, "description": "SOURCES_UNAVAILABLE"},
}

router = APIRouter(prefix="/api")


def get_service(request: Request) -> EtfService:
    state = request.app.state
    if state.service is None:
        state.service = state.service_factory()
    return state.service


Service = Annotated[EtfService, Depends(get_service)]


@router.get("/health", response_model=HealthResponse)
def health(service: Service) -> HealthResponse:
    return service.health()


@router.get("/etfs/{ticker}", response_model=EtfSummary, responses={k: ERRORS[k] for k in (404, 503)})
def get_etf(
    service: Service,
    ticker: Annotated[str, Path(pattern=TICKER_PATTERN)],
    holdings: Annotated[bool, Query(description="include normalised holdings")] = False,
    source: Annotated[SourceName | None, Query(description="use only this source")] = None,
) -> EtfSummary:
    return service.etf_summary(ticker.upper(), include_holdings=holdings, source=source)


@router.post("/analysis", response_model=AnalysisResponse, responses={k: ERRORS[k] for k in (422, 503)})
def analysis(service: Service, request: PortfolioRequest) -> AnalysisResponse:
    return service.analyse(request)


@router.get("/examples", response_model=ExamplesResponse)
def examples(service: Service) -> ExamplesResponse:
    return service.examples()


def _error(status: int, body: ErrorResponse) -> JSONResponse:
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def create_app(service_factory: Callable[[], EtfService] | None = None,
               settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="House of Cards API", version=__version__,
                  description="ETF look-through analysis on real holdings. Weights are fractions of 1.")
    app.state.service = None
    app.state.service_factory = service_factory or (lambda: EtfService.from_settings(settings))
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.exception_handler(HocError)
    def _hoc_error(_: Request, exc: HocError) -> JSONResponse:
        return _error(exc.status, exc.to_response())

    @app.exception_handler(RequestValidationError)
    def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        body = ErrorBody(code="VALIDATION_ERROR", message="Request did not match the schema",
                         details={"errors": jsonable_encoder(exc.errors())})
        return _error(422, ErrorResponse(error=body))

    @app.exception_handler(Exception)
    def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        body = ErrorBody(code="INTERNAL_ERROR", message="Unexpected server error",
                         details={"type": type(exc).__name__})
        return _error(500, ErrorResponse(error=body))

    app.include_router(router)
    return app


app = create_app()
