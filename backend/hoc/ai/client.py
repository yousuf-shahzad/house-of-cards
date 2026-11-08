"""Gemini Interactions REST client and deterministic FakeGeminiClient.

Owner: package G-AI (Kendrick's Gemini).
Rules (docs/hoc/PLAN-v2.md & R5-gemini-and-prices.md):
- No Gemini SDK dependency: calls `POST https://generativelanguage.googleapis.com/v1beta/interactions`
  through `hoc.core.http.HttpClient` with `"store": False`.
- API key (`GEMINI_API_KEY` or `GOOGLE_API_KEY`) is sent ONLY in the `x-goog-api-key` header,
  never in a URL, cache key, request body, or exception/log message.
- Models: `HOC_GEMINI_EXTRACTOR_MODEL=gemini-3.8-flash` and
  `HOC_GEMINI_ORCHESTRATOR_MODEL=gemini-4-argon` (both env-overridable).
- Argon (`gemini-4-argon`) automatically falls back to Flash (`gemini-3.8-flash`) on HTTP 429 / quota errors.
- Never sends `temperature`, `top_p`, or `top_k` (unsupported on Argon); uses
  `generation_config={"thinking_level": ..., "max_output_tokens": 32768}`.
- Enforces a bounded concurrency cap (default 4 in-flight requests).
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Mapping
from typing import Any

from hoc.contract import SourceUnavailable
from hoc.core.http import HttpClient

GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
API_REVISION = "2026-05-20"
DEFAULT_EXTRACTOR_MODEL = "gemini-3.8-flash"
DEFAULT_ORCHESTRATOR_MODEL = "gemini-4-argon"
DEFAULT_MAX_CONCURRENCY = 4
DEFAULT_MAX_OUTPUT_TOKENS = 32768


class GeminiError(Exception):
    """Base error for Gemini API interactions."""


class GeminiMissingKeyError(GeminiError):
    """Raised when `GEMINI_API_KEY` / `GOOGLE_API_KEY` is not configured."""


class GeminiQuotaError(GeminiError):
    """Raised when Gemini returns HTTP 429 / quota exhaustion after retries and fallback."""


class GeminiParseError(GeminiError):
    """Raised when Gemini returns non-JSON or schema-incompatible output."""


def resolve_api_key(settings: Any = None, env: Mapping[str, str] | None = None) -> str | None:
    """Resolve the Gemini API key from settings or environment (`GOOGLE_API_KEY` wins over `GEMINI_API_KEY`)."""
    if settings is not None:
        for attr in ("gemini_api_key", "google_api_key"):
            val = getattr(settings, attr, None)
            if isinstance(val, str) and val.strip():
                return val.strip()
    environ = os.environ if env is None else env
    for var in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "HOC_GEMINI_API_KEY"):
        val = environ.get(var, "").strip()
        if val:
            return val
    return None


def resolve_models(settings: Any = None, env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """Return `(extractor_model, orchestrator_model)` from settings or environment."""
    environ = os.environ if env is None else env
    ext = (
        getattr(settings, "gemini_extractor_model", None)
        or environ.get("HOC_GEMINI_EXTRACTOR_MODEL", "").strip()
        or DEFAULT_EXTRACTOR_MODEL
    )
    orch = (
        getattr(settings, "gemini_orchestrator_model", None)
        or environ.get("HOC_GEMINI_ORCHESTRATOR_MODEL", "").strip()
        or DEFAULT_ORCHESTRATOR_MODEL
    )
    return str(ext), str(orch)


def extract_interaction_text(payload: Any) -> str:
    """Extract the trailing model text output from an Interactions API JSON response."""
    if not isinstance(payload, Mapping):
        raise GeminiParseError("Interaction response is not a JSON object")

    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    steps = payload.get("steps")
    if isinstance(steps, list) and steps:
        collected: list[str] = []
        for step in reversed(steps):
            if not isinstance(step, Mapping):
                continue
            if step.get("type") == "model_output":
                content = step.get("content")
                if isinstance(content, list):
                    step_texts = [
                        part["text"]
                        for part in content
                        if isinstance(part, Mapping)
                        and part.get("type") in (None, "text")
                        and isinstance(part.get("text"), str)
                    ]
                    if step_texts:
                        collected.insert(0, "".join(step_texts))
            elif collected:
                break
        if collected:
            return "".join(collected).strip()

    outputs = payload.get("outputs")
    if isinstance(outputs, list) and outputs:
        last = outputs[-1]
        if isinstance(last, Mapping) and isinstance(last.get("text"), str):
            return last["text"].strip()

    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates:
        first = candidates[0]
        if isinstance(first, Mapping):
            content = first.get("content")
            if isinstance(content, Mapping) and isinstance(content.get("parts"), list):
                parts = [
                    p["text"]
                    for p in content["parts"]
                    if isinstance(p, Mapping) and isinstance(p.get("text"), str)
                ]
                if parts:
                    return "".join(parts).strip()

    raise GeminiParseError("Interaction response contained no model_output text")


def _strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


class GeminiClient:
    """Production Gemini Interactions REST client over `HttpClient` (`store=False`)."""

    def __init__(
        self,
        http: HttpClient,
        settings: Any = None,
        *,
        api_key: str | None = None,
        extractor_model: str | None = None,
        orchestrator_model: str | None = None,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    ) -> None:
        self.http = http
        self.settings = settings
        self._explicit_api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        ext_default, orch_default = resolve_models(settings)
        self.extractor_model = extractor_model or ext_default
        self.orchestrator_model = orchestrator_model or orch_default
        self.max_concurrency = max(1, int(max_concurrency))
        self._semaphore = threading.BoundedSemaphore(self.max_concurrency)

    @property
    def api_key(self) -> str | None:
        return self._explicit_api_key or resolve_api_key(self.settings)

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def generate_json(
        self,
        prompt: str,
        schema: Mapping[str, Any],
        *,
        model: str | None = None,
        system_instruction: str | None = None,
        thinking_level: str | None = "low",
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        fallback_model: str | None = None,
    ) -> tuple[Any, str]:
        """Run a stateless Interactions API call (`store=False`) with a flat JSON schema.

        Returns `(parsed_json, model_used)`. If `model` is `gemini-4-argon` (or `fallback_model`
        is specified) and the primary model fails with HTTP 429 / quota exhaustion, automatically
        retries once with the fallback model (`gemini-3.8-flash`).
        """
        key = self.api_key
        if not key:
            raise GeminiMissingKeyError("GEMINI_API_KEY is not configured")

        primary_model = model or self.extractor_model
        effective_fallback = fallback_model
        if effective_fallback is None and primary_model == DEFAULT_ORCHESTRATOR_MODEL:
            effective_fallback = self.extractor_model

        try:
            return self._call_once(
                key=key,
                model=primary_model,
                prompt=prompt,
                schema=schema,
                system_instruction=system_instruction,
                thinking_level=thinking_level,
                max_output_tokens=max_output_tokens,
            ), primary_model
        except GeminiQuotaError:
            if effective_fallback and effective_fallback != primary_model:
                return self._call_once(
                    key=key,
                    model=effective_fallback,
                    prompt=prompt,
                    schema=schema,
                    system_instruction=system_instruction,
                    thinking_level="low",
                    max_output_tokens=max_output_tokens,
                ), effective_fallback
            raise

    def complete_json(
        self,
        prompt: str,
        schema: Mapping[str, Any],
        *,
        model: str | None = None,
        system_instruction: str | None = None,
        thinking_level: str | None = "low",
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        fallback_model: str | None = None,
    ) -> Any:
        """Convenience wrapper returning only the parsed JSON object."""
        parsed, _ = self.generate_json(
            prompt,
            schema,
            model=model,
            system_instruction=system_instruction,
            thinking_level=thinking_level,
            max_output_tokens=max_output_tokens,
            fallback_model=fallback_model,
        )
        return parsed

    def _call_once(
        self,
        *,
        key: str,
        model: str,
        prompt: str,
        schema: Mapping[str, Any],
        system_instruction: str | None,
        thinking_level: str | None,
        max_output_tokens: int,
    ) -> Any:
        gen_config: dict[str, Any] = {"max_output_tokens": max_output_tokens}
        if thinking_level:
            gen_config["thinking_level"] = thinking_level

        payload: dict[str, Any] = {
            "model": model,
            "input": prompt,
            "store": False,
            "response_format": {
                "type": "text",
                "mime_type": "application/json",
                "schema": dict(schema),
            },
            "generation_config": gen_config,
        }
        if system_instruction:
            payload["system_instruction"] = system_instruction

        headers = {
            "x-goog-api-key": key,
            "Api-Revision": API_REVISION,
            "Content-Type": "application/json",
        }

        with self._semaphore:
            try:
                response = self.http.post_json(
                    GEMINI_INTERACTIONS_URL,
                    payload,
                    source="gemini",
                    ttl=None,
                    headers=headers,
                )
            except SourceUnavailable as exc:
                msg = str(exc)
                if "429" in msg:
                    raise GeminiQuotaError(f"Gemini quota exhausted on model {model}") from exc
                raise GeminiError(f"Gemini request failed on model {model}: {msg}") from exc

        if response.status == 429:
            raise GeminiQuotaError(f"Gemini returned HTTP 429 on model {model}")
        if response.status >= 400:
            raise GeminiError(f"Gemini returned HTTP {response.status} on model {model}")

        try:
            body_json = response.json()
        except ValueError as exc:
            raise GeminiParseError("Gemini response was not valid JSON") from exc

        raw_text = extract_interaction_text(body_json)
        clean_text = _strip_markdown_fences(raw_text)
        try:
            return json.loads(clean_text)
        except ValueError as exc:
            raise GeminiParseError("Gemini model_output text was not valid JSON") from exc


RestGeminiClient = GeminiClient


class FakeGeminiClient:
    """Deterministic offline test double for `GeminiClient`.

    - Supports canned responses keyed by `company_key` or prompt substring.
    - By default, emits both valid verbatim quotes (matching the passed filing text)
      AND mutated/hallucinated quotes so offline unit tests and Tier B E2E tests
      verify that Python quote verification rejects unverified edges (`rejected > 0`).
    - Also handles V-INT judge prompts (`JUDGE_SCHEMA` with `"verdicts"`).
    """

    def __init__(
        self,
        responses: Mapping[str, Any] | None = None,
        *,
        has_api_key: bool = True,
        extractor_model: str = DEFAULT_EXTRACTOR_MODEL,
        orchestrator_model: str = DEFAULT_ORCHESTRATOR_MODEL,
        include_mutated_quotes: bool = True,
        fail_keys: set[str] | None = None,
    ) -> None:
        self.responses: dict[str, Any] = dict(responses or {})
        self.has_api_key = has_api_key
        self.extractor_model = extractor_model
        self.orchestrator_model = orchestrator_model
        self.include_mutated_quotes = include_mutated_quotes
        self.fail_keys: set[str] = set(fail_keys or set())
        self.calls: list[dict[str, Any]] = []

    def add_response(self, match_key: str, payload: Any) -> None:
        """Register a canned JSON response when `match_key` appears in the prompt."""
        self.responses[match_key] = payload

    def generate_json(
        self,
        prompt: str,
        schema: Mapping[str, Any],
        *,
        model: str | None = None,
        system_instruction: str | None = None,
        thinking_level: str | None = "low",
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        fallback_model: str | None = None,
    ) -> tuple[Any, str]:
        used_model = model or self.extractor_model
        self.calls.append({
            "model": used_model,
            "prompt": prompt,
            "schema": dict(schema),
            "system_instruction": system_instruction,
            "thinking_level": thinking_level,
        })
        if not self.has_api_key:
            raise GeminiMissingKeyError("FakeGeminiClient configured with has_api_key=False")

        for fail_token in self.fail_keys:
            if fail_token in prompt:
                raise GeminiError(f"Simulated Gemini failure for {fail_token}")

        for key, canned in self.responses.items():
            if key in prompt:
                return canned, used_model

        props = schema.get("properties", {}) if isinstance(schema, Mapping) else {}
        if "verdicts" in props:
            return self._default_judge_response(prompt), used_model
        if "suggestions" in props or "flaws" in props:
            return self._default_orchestrator_response(), used_model
        return self._default_extraction_response(prompt), used_model

    def complete_json(
        self,
        prompt: str,
        schema: Mapping[str, Any],
        *,
        model: str | None = None,
        system_instruction: str | None = None,
        thinking_level: str | None = "low",
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        fallback_model: str | None = None,
    ) -> Any:
        parsed, _ = self.generate_json(
            prompt,
            schema,
            model=model,
            system_instruction=system_instruction,
            thinking_level=thinking_level,
            max_output_tokens=max_output_tokens,
            fallback_model=fallback_model,
        )
        return parsed

    def _default_extraction_response(self, prompt: str) -> dict[str, Any]:
        edges: list[dict[str, Any]] = []
        # Extract real sentences from the filing section of the prompt if present
        doc_part = prompt.split("FILING TEXT:", 1)[-1] if "FILING TEXT:" in prompt else prompt

        # Look for common patterns or sentences in synthetic/real test filings
        known_candidates = [
            ("Taiwan Semiconductor Manufacturing", "foundry", "company", True, "Item 1"),
            ("TSMC", "foundry", "company", True, "Item 1"),
            ("Samsung Electronics", "supplier", "company", False, "Item 1"),
            ("SK Hynix", "supplier", "company", False, "Item 1"),
            ("Micron Technology", "supplier", "company", False, "Item 1"),
            ("Hon Hai", "contract_manufacturer", "company", False, "Item 1"),
            ("Foxconn", "contract_manufacturer", "company", False, "Item 1"),
            ("Carl Zeiss SMT", "supplier", "company", True, "Item 4"),
            ("ZZSUP", "supplier", "company", True, "Item 1"),
            ("ZZFAB", "foundry", "company", True, "Item 1"),
            ("Taiwan", "facility", "country", False, "Item 2"),
            ("Arizona", "facility", "region", False, "Item 2"),
        ]
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", doc_part) if len(s.strip()) >= 25]
        for target, edge_type, kind, sole, section in known_candidates:
            for sent in sentences:
                if target.lower() in sent.lower() and len(sent) <= 320:
                    edges.append({
                        "edge_type": edge_type,
                        "target_name": target,
                        "target_kind": kind,
                        "sole_source": sole,
                        "qualifier": "primary wafer foundry" if sole else "",
                        "section": section,
                        "evidence_quote": sent[:300],
                    })
                    break

        if not edges and sentences:
            # Take the first sentence >= 25 chars and ground a generic facility/supplier token from it
            first_sent = sentences[0][:280]
            words = [w.strip(".,;:()\"'") for w in first_sent.split() if len(w.strip(".,;:()\"'")) >= 4]
            target_word = words[0] if words else "Operations"
            edges.append({
                "edge_type": "supplier",
                "target_name": target_word,
                "target_kind": "company",
                "sole_source": False,
                "qualifier": "",
                "section": "Item 1",
                "evidence_quote": first_sent,
            })

        if self.include_mutated_quotes:
            edges.append({
                "edge_type": "supplier",
                "target_name": "Hallucinated Quantum Foundry Corp.",
                "target_kind": "company",
                "sole_source": True,
                "qualifier": "100% exclusive supplier",
                "section": "Item 1",
                "evidence_quote": (
                    "We rely exclusively on Hallucinated Quantum Foundry Corp. for 100% of our "
                    "sub-angstrom wafer fabrication capacity."
                ),
            })
            if sentences:
                edges.append({
                    "edge_type": "supplier",
                    "target_name": "TSMC",
                    "target_kind": "company",
                    "sole_source": True,
                    "qualifier": "mutated quote wording",
                    "section": "Item 1A",
                    "evidence_quote": sentences[0][:80] + " [MUTATED BY LLM DO NOT TRUST] " + sentences[0][-40:],
                })

        return {"edges": edges}

    @staticmethod
    def _default_judge_response(prompt: str) -> dict[str, Any]:
        """Deterministic judge response for `hoc-v3-judge-1` prompts."""
        verdicts: list[dict[str, Any]] = []
        blocks = re.split(r"\[ITEM\s+\d+\]", prompt)
        for block in blocks[1:]:
            id_match = re.search(r"edge_id:\s*([^\r\n]+)", block)
            flags_match = re.search(r"rule_flags:\s*([^\r\n]+)", block)
            if not id_match:
                continue
            edge_id = id_match.group(1).strip()
            flags_raw = flags_match.group(1).strip() if flags_match else "none"
            flags = [f.strip() for f in flags_raw.split(",") if f.strip() and f.strip() != "none"]

            if "competitor_mention" in flags:
                label = "competitor"
                reason = "Target is mentioned as a competitor in the filing context."
            elif any(f in flags for f in ("negated", "direction_mismatch", "generic_reference")):
                label = "contradicts"
                reason = "Quote negates or reverses the claimed relationship."
            elif "subject_mismatch" in flags:
                label = "unrelated"
                reason = "Filer is not the subject of the dependency in this context."
            elif "hypothetical" in flags:
                label = "unclear"
                reason = "Quote uses conditional/hypothetical wording without a confirmed active dependency."
            else:
                label = "supports"
                reason = "Quote directly supports the claimed dependency."

            verdicts.append({
                "edge_id": edge_id,
                "label": label,
                "cleared_flags": [],
                "reason": reason,
            })
        return {"verdicts": verdicts}

    @staticmethod
    def _default_orchestrator_response() -> dict[str, Any]:
        return {
            "suggestions": [
                {
                    "title": "Reduce single-foundry wafer concentration",
                    "detail": (
                        "Top holdings rely on shared foundry capacity ({{metric:supplier_dep_1}}). "
                        "Adding non-semiconductor value exposure reduces single-point foundry risk."
                    ),
                    "cited_metric_ids": ["supplier_dep_1"],
                    "cited_edge_ids": ["edge_1"],
                },
                {
                    "title": "Hallucinated numeric claim that Python must reject",
                    "detail": "Exactly 99.99% of your portfolio is exposed to unverified lunar mining.",
                    "cited_metric_ids": ["supplier_dep_1"],
                    "cited_edge_ids": ["edge_1"],
                },
            ],
            "flaws": [
                {
                    "title": "Shared semiconductor fabrication bottleneck",
                    "detail": (
                        "Multiple top holdings depend on the same wafer foundry ({{metric:supplier_dep_1}}), "
                        "creating correlated supply-chain tail risk."
                    ),
                    "severity": "warning",
                    "cited_metric_ids": ["supplier_dep_1"],
                    "cited_edge_ids": ["edge_1"],
                }
            ],
        }
