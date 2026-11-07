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
LOOPBACK = {"127.0.0.1", "::1", "localhost"}


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

    real_connect = socket.socket.connect
    real_create_connection = socket.create_connection

    def refuse(address):
        raise RuntimeError(
            f"Network access in an offline test ({address!r}). Use FakeHttpClient / FakeSourceAdapter, "
            "or mark the test @pytest.mark.live."
        )

    def is_local(address) -> bool:
        # Loopback stays allowed: asyncio's self-pipe on Windows is a socketpair over 127.0.0.1,
        # which TestClient needs. Unix-domain sockets (str/bytes paths) are local too.
        if not isinstance(address, tuple):
            return True
        return str(address[0]).lower() in LOOPBACK

    def guarded_connect(self, address):
        if not is_local(address):
            refuse(address)
        return real_connect(self, address)

    def guarded_create_connection(address, *args, **kwargs):
        if not is_local(address):
            refuse(address)
        return real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)


@pytest.fixture
def synthetic_dir() -> Path:
    return SYNTHETIC


@pytest.fixture
def fake_source() -> FakeSourceAdapter:
    return FakeSourceAdapter(SYNTHETIC / "raw")


@pytest.fixture
def fake_reference() -> FakeReference:
    return FakeReference(SYNTHETIC / "reference.json")
