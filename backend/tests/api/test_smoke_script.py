"""scripts/smoke_api.py run against the real app (TestClient) on SYNTHETIC sources: every check passes."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from hoc.api.app import create_app
from hoc.config import Settings
from hoc.examples import ExampleDefinition

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "smoke_api.py"


def _load():
    spec = importlib.util.spec_from_file_location("smoke_api", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_checks_pass_against_the_app(make_service, monkeypatch):
    monkeypatch.setattr("hoc.service.EXAMPLES", (
        ExampleDefinition("zz", "ZZ", "synthetic", (("ZZAAA", 0.6), ("ZZBBB", 0.4))),))
    monkeypatch.setattr("hoc.service.IDEA_TICKERS", ())
    service, _ = make_service()
    client = TestClient(create_app(lambda: service, Settings()))

    def fetch(method, path, body=None):
        response = client.request(method, path, json=body)
        return response.status_code, response.json()

    results = _load().run_checks(fetch)
    assert [name for name, ok, _ in results if not ok] == []
    assert {"stress sector", "stress country", "stress supplier", "error envelope"} <= {n for n, _, _ in results}
