"""Package G-AI: Gemini Interactions REST client, fake client, quote verifier, cache, and extractor.

Owner: Kendrick's Gemini (`@kendricklow2008 (Gemini)`).
"""

from __future__ import annotations

from hoc.ai.cache import EXTRACTION_CACHE_NAMESPACE, ExtractionCache, make_extraction_cache_key
from hoc.ai.client import (
    API_REVISION,
    DEFAULT_EXTRACTOR_MODEL,
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_ORCHESTRATOR_MODEL,
    GEMINI_INTERACTIONS_URL,
    FakeGeminiClient,
    GeminiClient,
    GeminiError,
    GeminiMissingKeyError,
    GeminiParseError,
    GeminiQuotaError,
    RestGeminiClient,
    extract_interaction_text,
    resolve_api_key,
    resolve_models,
)
from hoc.ai.extractor import (
    EDGE_TYPES,
    EXTRACTION_SCHEMA,
    EXTRACTOR_SYSTEM_INSTRUCTION,
    MAX_PACKED_CHARS,
    MAX_REVERSE_HITS,
    TARGET_KINDS,
    CompanyExtractionOutcome,
    CompanyUnavailable,
    DependencyExtractor,
    Extraction,
    build_extraction_prompt,
    dedupe_edges,
    make_edge_id,
    pack_filing_sections,
    verify_and_build_edges,
)
from hoc.ai.verifier import PROMPT_VERSION, normalise_for_verify, verify_quote

prompt_version = PROMPT_VERSION

__all__ = [
    "API_REVISION",
    "DEFAULT_EXTRACTOR_MODEL",
    "DEFAULT_MAX_CONCURRENCY",
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "DEFAULT_ORCHESTRATOR_MODEL",
    "EDGE_TYPES",
    "EXTRACTION_CACHE_NAMESPACE",
    "EXTRACTION_SCHEMA",
    "EXTRACTOR_SYSTEM_INSTRUCTION",
    "GEMINI_INTERACTIONS_URL",
    "MAX_PACKED_CHARS",
    "MAX_REVERSE_HITS",
    "PROMPT_VERSION",
    "TARGET_KINDS",
    "CompanyExtractionOutcome",
    "CompanyUnavailable",
    "DependencyExtractor",
    "Extraction",
    "ExtractionCache",
    "FakeGeminiClient",
    "GeminiClient",
    "GeminiError",
    "GeminiMissingKeyError",
    "GeminiParseError",
    "GeminiQuotaError",
    "RestGeminiClient",
    "build_extraction_prompt",
    "dedupe_edges",
    "extract_interaction_text",
    "make_edge_id",
    "make_extraction_cache_key",
    "normalise_for_verify",
    "pack_filing_sections",
    "prompt_version",
    "resolve_api_key",
    "resolve_models",
    "verify_and_build_edges",
    "verify_quote",
]
