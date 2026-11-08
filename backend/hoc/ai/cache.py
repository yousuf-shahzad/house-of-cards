"""Per-company extraction and per-edge V-INT judge disk caches.

Owner: package G-AI / V-INT (Kendrick's Gemini).
Uses `DiskCache` under namespaces `ai/extractions` and `ai/judge` so warm runs and offline demos
replay verified company extractions and interpretation judge verdicts in < 50 ms without a Gemini API key.
"""

from __future__ import annotations

import json
from typing import Any

from hoc.core.cache import DiskCache

EXTRACTION_CACHE_NAMESPACE = "ai/extractions"
JUDGE_CACHE_NAMESPACE = "ai/judge"


def make_extraction_cache_key(
    company_key: str,
    accession: str,
    model: str,
    prompt_version: str,
) -> str:
    """Build a canonical cache key for a company's filing extraction."""
    return f"{company_key.strip()}|{accession.strip()}|{model.strip()}|{prompt_version.strip()}"


def make_judge_cache_key(
    edge_id: str,
    model: str,
    prompt_version: str,
) -> str:
    """Build a canonical per-edge cache key for V-INT judge verification."""
    return f"{edge_id.strip()}|{model.strip()}|{prompt_version.strip()}"


class ExtractionCache:
    """Disk-backed cache for verified per-company dependency extraction and per-edge V-INT judge results."""

    def __init__(self, disk_cache: DiskCache) -> None:
        self.disk_cache = disk_cache

    def get(
        self,
        company_key: str,
        accession: str,
        *,
        model: str,
        prompt_version: str,
    ) -> dict[str, Any] | None:
        """Return cached extraction payload if present for the exact key, else None."""
        key = make_extraction_cache_key(company_key, accession, model, prompt_version)
        entry = self.disk_cache.get(EXTRACTION_CACHE_NAMESPACE, key)
        if entry is None:
            return None
        try:
            data = json.loads(entry.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def get_any_model(
        self,
        company_key: str,
        accession: str,
        *,
        models: tuple[str, ...],
        prompt_version: str,
    ) -> dict[str, Any] | None:
        """Check multiple candidate models in order (useful for keyless warm cache replay)."""
        for model in models:
            hit = self.get(company_key, accession, model=model, prompt_version=prompt_version)
            if hit is not None:
                return hit
        return None

    def put(
        self,
        company_key: str,
        accession: str,
        *,
        model: str,
        prompt_version: str,
        payload: dict[str, Any],
    ) -> None:
        """Atomically persist a verified company extraction result to disk."""
        key = make_extraction_cache_key(company_key, accession, model, prompt_version)
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.disk_cache.put(
            EXTRACTION_CACHE_NAMESPACE,
            key,
            body,
            {
                "company_key": company_key,
                "accession": accession,
                "model": model,
                "prompt_version": prompt_version,
                "status": 200,
                "content_type": "application/json",
            },
        )

    def get_judge(
        self,
        edge_id: str,
        *,
        model: str,
        prompt_version: str,
    ) -> dict[str, Any] | None:
        """Return cached per-edge V-INT judge payload if present for `(edge_id, model, prompt_version)`."""
        key = make_judge_cache_key(edge_id, model, prompt_version)
        entry = self.disk_cache.get(JUDGE_CACHE_NAMESPACE, key)
        if entry is None:
            return None
        try:
            data = json.loads(entry.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def get_judge_any_model(
        self,
        edge_id: str,
        *,
        models: tuple[str, ...],
        prompt_version: str,
    ) -> dict[str, Any] | None:
        """Check multiple candidate models in order for a cached per-edge V-INT judge verdict."""
        for model in models:
            hit = self.get_judge(edge_id, model=model, prompt_version=prompt_version)
            if hit is not None:
                return hit
        return None

    def put_judge(
        self,
        edge_id: str,
        *,
        model: str,
        prompt_version: str,
        payload: dict[str, Any],
    ) -> None:
        """Atomically persist a per-edge V-INT judge verdict to disk."""
        key = make_judge_cache_key(edge_id, model, prompt_version)
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.disk_cache.put(
            JUDGE_CACHE_NAMESPACE,
            key,
            body,
            {
                "edge_id": edge_id,
                "model": model,
                "prompt_version": prompt_version,
                "status": 200,
                "content_type": "application/json",
            },
        )
