"""FastAPI app. Routes and error shapes are part of the frozen contract (OpenAPI snapshot in
tests/snapshots/openapi.json). Owner after W0-B: package f (Bekarys's Claude).

Run: uv run uvicorn hoc.api.app:app --reload --host 127.0.0.1 --port 8000
The served app warms up in a background thread at startup (example ETFs, reference files, sector data,
then a cache-only replay of their dependency results), so the first analysis is fast; startup itself never
waits for it and never spends Gemini credit. Progress goes to the log.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Path, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from hoc import __version__
from hoc.config import Settings
from hoc.contract import (
    AnalysisResponse,
    ChangeIdeasRequest,
    ChangeIdeasResponse,
    CompareRequest,
    CompareResponse,
    DependencyJob,
    DependencyRequest,
    ErrorBody,
    ErrorResponse,
    EtfSummary,
    ExamplesResponse,
    HealthResponse,
    HocError,
    PortfolioItem,
    PortfolioRequest,
    ResearchJob,
    ResearchRequest,
    SourceName,
    ValuationRequest,
    ValuationResponse,
)
from hoc.contract.api import TICKER_PATTERN
from hoc.jobs import NotWiredPipeline
from hoc.service import EtfService

ERRORS = {
    404: {"model": ErrorResponse, "description": "ETF_NOT_FOUND"},
    422: {"model": ErrorResponse, "description": "VALIDATION_ERROR, ALLOCATION_SUM_INVALID, DUPLICATE_TICKER, "
                                                 "TOO_MANY_ETFS, UNKNOWN_TICKER"},
    503: {"model": ErrorResponse, "description": "SOURCES_UNAVAILABLE"},
}
WARM_DEPENDENCIES_WAIT_SECONDS = 300.0

router = APIRouter(prefix="/api")
log = logging.getLogger("hoc.warmup")


def _service(state) -> EtfService:
    with state.service_lock:  # the warm-up thread and the first request may both ask for it
        if state.service is None:
            state.service = state.service_factory()
        return state.service


def get_service(request: Request) -> EtfService:
    return _service(request.app.state)


def warm_up(state) -> None:
    """Load every example ETF (holdings, reference files, sector data) into the service memo and disk cache.
    Never raises: on failure the first request simply loads the data itself."""
    started = time.monotonic()
    log.info("loading example ETFs, reference files and sector data")
    try:
        service = _service(state)
        examples = service.examples().examples
        for example in examples:
            missing = [e.ticker for e in example.holdings if not e.verified]
            log.info("example %s: %s", example.id,
                     "ready" if not missing else f"NOT verified, missing {', '.join(missing)}")
        verified = [e for e in examples if e.verified]
        _replay_dependencies(service, verified)
        _warm_change_ideas(service, verified)
    except Exception:
        log.exception("warm-up failed; the first request will load the data instead")
        return
    log.info("done in %.1f s", time.monotonic() - started)


def _replay_dependencies(service: EtfService, examples) -> None:
    """Cache-only: serves stored extractions and insights, never calls Gemini and never needs a key."""
    if isinstance(service.dependency_pipeline, NotWiredPipeline):
        log.info("dependency analysis not wired in yet; skipping its replay")
        return
    top_n = getattr(service.settings, "deps_top_n", 15)
    for example in examples:
        request = DependencyRequest(top_n=top_n, holdings=[
            PortfolioItem(ticker=e.ticker, allocation=e.allocation) for e in example.holdings])
        job = service.submit_dependencies(request, cache_only=True, wait=WARM_DEPENDENCIES_WAIT_SECONDS)
        cached = sum(c.status in ("cached", "done") for c in job.companies)
        log.info("dependencies %s: %d/%d companies from cache (%s)", example.id, cached, len(job.companies),
                 job.status)


def _warm_change_ideas(service: EtfService, examples) -> None:
    """FIX-17: load the shortlisted ETFs (and each example's ideas) so the first "Ideas" click is fast.
    Cache-only like /api/change-ideas: no filing fetch and no model call."""
    for example in examples:
        response = service.change_ideas(ChangeIdeasRequest(holdings=[
            PortfolioItem(ticker=e.ticker, allocation=e.allocation) for e in example.holdings]))
        log.info("change ideas %s: %d ready (%s)", example.id, len(response.ideas), response.status)


def _start_warm_up(state) -> threading.Thread:
    if not log.handlers:  # uvicorn only configures its own loggers
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("INFO:     hoc warm-up: %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        log.propagate = False
    thread = threading.Thread(target=warm_up, args=(state,), name="hoc-warm-up", daemon=True)
    thread.start()
    return thread


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


@router.post("/valuation", response_model=ValuationResponse, responses={422: ERRORS[422]})
def valuation(service: Service, request: ValuationRequest) -> ValuationResponse:
    """Shares -> allocations. A blocked valuation is still 200, with status 'blocked' and its issues."""
    return service.valuation(request)


@router.post("/compare", response_model=CompareResponse, responses={k: ERRORS[k] for k in (422, 503)})
def compare(service: Service, request: CompareRequest) -> CompareResponse:
    """Before/after comparison of two portfolios. Cache-only: never fetches a filing or calls Gemini; status
    is 'partial' when some of the candidate's top companies have no cached extraction yet."""
    return service.compare(request)


@router.post("/change-ideas", response_model=ChangeIdeasResponse,
             responses={k: ERRORS[k] for k in (422, 503)})
def change_ideas(service: Service, request: ChangeIdeasRequest) -> ChangeIdeasResponse:
    """Test a fixed ETF shortlist at ten and twenty percent, using cached dependencies only."""
    return service.change_ideas(request)


@router.post("/dependencies", response_model=DependencyJob, responses={
    202: {"model": DependencyJob, "description": "Queued or running: poll GET /api/dependencies/{job_id}"},
    **{k: ERRORS[k] for k in (422, 503)}})
def start_dependencies(service: Service, request: DependencyRequest, response: Response) -> DependencyJob:
    """Same DependencyJob body either way: 200 when already finished (e.g. all cached), else 202."""
    job = service.submit_dependencies(request)
    response.status_code = 200 if job.status in ("done", "error") else 202
    return job


@router.get("/dependencies/{job_id}", response_model=DependencyJob,
            responses={404: {"model": ErrorResponse, "description": "JOB_NOT_FOUND"}})
def get_dependencies(service: Service, job_id: Annotated[str, Path(max_length=128)]) -> DependencyJob:
    return service.dependency_job(job_id)


@router.post("/dependencies/{job_id}/research", response_model=ResearchJob, responses={
    202: {"model": ResearchJob, "description": "Queued or running: poll GET /api/research/{research_id}"},
    404: {"model": ErrorResponse, "description": "JOB_NOT_FOUND"},
    422: ERRORS[422]})
def start_research(service: Service, job_id: Annotated[str, Path(max_length=128)], response: Response,
                   request: ResearchRequest | None = None) -> ResearchJob:
    """Investigate the uncertain findings of a finished dependency job (A-RES). Same ResearchJob body either way:
    200 when already finished (e.g. cached), else 202. 422 while the dependency job is still running."""
    job = service.submit_research(job_id, request or ResearchRequest())
    response.status_code = 200 if job.status in ("done", "error") else 202
    return job


@router.get("/research/{research_id}", response_model=ResearchJob,
            responses={404: {"model": ErrorResponse, "description": "RESEARCH_NOT_FOUND"}})
def get_research(service: Service, research_id: Annotated[str, Path(max_length=128)]) -> ResearchJob:
    return service.research_job(research_id)


def _error(status: int, body: ErrorResponse) -> JSONResponse:
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def create_app(service_factory: Callable[[], EtfService] | None = None,
               settings: Settings | None = None, *, warm: bool = False) -> FastAPI:
    """warm=True starts warm_up() in a background thread when the app starts (the served app does this)."""
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.warm_up_thread = _start_warm_up(app.state) if warm else None
        yield

    app = FastAPI(title="House of Cards API", version=__version__, lifespan=lifespan,
                  description="ETF look-through analysis on real holdings. Weights are fractions of 1.")
    app.state.service = None
    app.state.service_lock = threading.Lock()
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

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        """FIX-57: an unknown route (404) or a wrong method (405) gets the one error envelope, not FastAPI's
        {"detail": ...}. Other HTTP exceptions keep FastAPI's default handling."""
        codes = {404: ("NOT_FOUND", "There is no such API route."),
                 405: ("METHOD_NOT_ALLOWED", "This API route doesn't accept that method.")}
        if exc.status_code not in codes:
            return await http_exception_handler(request, exc)
        code, message = codes[exc.status_code]
        body = ErrorBody(code=code, message=message, details={"path": request.url.path, "method": request.method})
        response = _error(exc.status_code, ErrorResponse(error=body))
        response.headers.update(exc.headers or {})  # keeps Allow on 405
        return response

    @app.exception_handler(Exception)
    def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        body = ErrorBody(code="INTERNAL_ERROR", message="Unexpected server error",
                         details={"type": type(exc).__name__})
        return _error(500, ErrorResponse(error=body))

    app.include_router(router)
    return app


app = create_app(warm=True)
