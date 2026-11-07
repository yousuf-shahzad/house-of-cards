"""Shared production wiring for explicitly opted-in live smoke tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from hoc.config import BACKEND_DIR, Settings
from hoc.core.cache import DiskCache
from hoc.core.http import CachedHttpClient

pytestmark = pytest.mark.live


@pytest.fixture
def live_settings(monkeypatch):
    # The parent offline fixture installs a temporary cache. Override it here so
    # rerunning smoke tests respects the sources' daily-fetch/cache policy.
    root = Path(os.environ.get("HOC_LIVE_CACHE_DIR", BACKEND_DIR / ".cache"))
    monkeypatch.setenv("HOC_CACHE_DIR", str(root.resolve()))
    monkeypatch.setenv("HOC_OFFLINE", "0")
    return Settings.from_env()


@pytest.fixture
def live_http(live_settings):
    return CachedHttpClient(live_settings, DiskCache(live_settings.cache_dir))
