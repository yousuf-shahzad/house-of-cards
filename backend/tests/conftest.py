"""Shared test setup. Every test runs OFFLINE: socket connections raise, and the cache goes to a tmp dir.

Live tests (real sources) are marked @pytest.mark.live and run only with HOC_LIVE=1.
Synthetic data for tests lives in tests/fixtures/synthetic/ (see its README). Never use real holdings here.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from hoc.sources.fake import FakeReference, FakeSourceAdapter

SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic"
LIVE = os.environ.get("HOC_LIVE") == "1"


def pytest_collection_modifyitems(config, items):
    if LIVE:
        return
    skip = pytest.mark.skip(reason="live test: set HOC_LIVE=1 to hit real sources")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _offline(request, monkeypatch, tmp_path):
    monkeypatch.setenv("HOC_CACHE_DIR", str(tmp_path / "cache"))
    if LIVE and "live" in request.keywords:
        return

    def blocked(*args, **kwargs):
        raise RuntimeError(
            "Network access in an offline test. Use FakeHttpClient / FakeSourceAdapter, "
            "or mark the test @pytest.mark.live."
        )

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture
def synthetic_dir() -> Path:
    return SYNTHETIC


@pytest.fixture
def fake_source() -> FakeSourceAdapter:
    return FakeSourceAdapter(SYNTHETIC / "raw")


@pytest.fixture
def fake_reference() -> FakeReference:
    return FakeReference(SYNTHETIC / "reference.json")
