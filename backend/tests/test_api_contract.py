"""The HTTP contract: OpenAPI snapshot, error shapes and CORS. Uses a stub service (no sources).

If you intentionally change the API (lead approval required), regenerate the snapshot with
HOC_UPDATE_SNAPSHOT=1 uv run pytest tests/test_api_contract.py and update frontend/api/types.ts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from hoc.api.app import create_app
from hoc.config import Settings
from hoc.contract import PortfolioValidationError, SourcesUnavailableError
from hoc.service import EtfService

SNAPSHOT = Path(__file__).parent / "snapshots" / "openapi.json"


class StubRegistry:
    names = ("fake",)


class StubService(EtfService):
    def __init__(self, error: Exception | None = None) -> None:
        super().__init__(StubRegistry(), None, None, Settings())
        self.error = error

    def analyse(self, request):
        raise self.error

    def examples(self):
        raise SourcesUnavailableError("all sources down", {"attempts": []})


def client(error: Exception | None = None) -> TestClient:
    return TestClient(create_app(lambda: StubService(error), Settings()))


def test_openapi_matches_snapshot():
    schema = create_app(lambda: StubService(), Settings()).openapi()
    if os.environ.get("HOC_UPDATE_SNAPSHOT") == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert schema == json.loads(SNAPSHOT.read_text(encoding="utf-8")), (
        "API contract changed. If intended (lead approval), regenerate with HOC_UPDATE_SNAPSHOT=1 and "
        "update frontend/api/types.ts in the same PR."
    )


def test_health():
    response = client().get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok" and response.json()["sources"] == ["fake"]


def test_schema_errors_use_the_error_shape():
    response = client().post("/api/analysis", json={"holdings": [{"ticker": "IVV QQQ", "allocation": 2}]})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR" and body["error"]["details"]["errors"]


def test_business_errors_keep_their_code():
    err = PortfolioValidationError("ALLOCATION_SUM_INVALID", "Allocations total 90%", {"total": 0.9})
    response = client(err).post("/api/analysis", json={"holdings": [{"ticker": "IVV", "allocation": 0.9}]})
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "ALLOCATION_SUM_INVALID", "message": "Allocations total 90%",
                                         "details": {"total": 0.9}}}


def test_unavailable_is_503():
    response = client().get("/api/examples")
    assert response.status_code == 503 and response.json()["error"]["code"] == "SOURCES_UNAVAILABLE"


def test_cors_allows_the_vite_dev_origin():
    response = client().get("/api/health", headers={"Origin": "http://127.0.0.1:5173"})
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:5173"
