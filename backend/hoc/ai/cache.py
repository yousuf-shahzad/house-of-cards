"""Per-company extraction disk cache keyed by (company_key, accession, model, prompt_version).

Owner: package G-AI (Kendrick's Gemini).
Uses `DiskCache` under namespace `ai/extractions` so warm runs and offline demos
replay verified company extractions in < 50 ms without a Gemini API key.
"""

from __future__ import annotations

import json
from typing import Any

from hoc.core.cache import DiskCache

EXTRACTION_CACHE_NAMESPACE = "ai/extractions"


def make_extraction_cache_key(
    company_key: str,
    accession: str,
    model: str,
    prompt_version: str,
) -> str:
    """Build a canonical cache key for a company's filing extraction."""
    return f"{company_key.strip()}|{accession.strip()}|{model.strip()}|{prompt_version.strip()}"


class ExtractionCache:
    """Disk-backed cache for verified per-company dependency extraction results."""

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
