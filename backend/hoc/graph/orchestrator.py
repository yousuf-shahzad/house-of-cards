"""Orchestrator Gemini agent + deterministic claim verifier (package G-ORCH).

Rules (docs/hoc/PLAN-v2.md, docs/hoc/CONTRACT.md & docs/hoc/research/R5-gemini-and-prices.md):
- The orchestrator receives only verified edges and deterministic Python MetricFacts.
- It writes numbers ONLY as ``{{metric:<id>}}`` placeholders, which Python fills in.
- Any other literal number in its text, an unknown metric_id or edge_id, or a
  company/ticker outside the portfolio or verified edges causes that claim to be
  dropped and increments ``rejected_claims_count``.
- Cached on disk by ``(allocations_hash, verified_edge_ids, prompt_version)`` so
  warm demos replay offline without needing ``GEMINI_API_KEY``.
- Never raises for ``metrics_only``, ``no_verified_edges``, ``missing_api_key``, or ``error``;
  always returns ``(list[MetricFact], Insights)``.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

from hoc.ai.client import GeminiClient, GeminiError, GeminiQuotaError
from hoc.config import DEFAULT_EXTRACTOR_MODEL, DEFAULT_ORCHESTRATOR_MODEL, Settings
from hoc.contract import SourceUnavailable
from hoc.contract.api import AnalysisResponse, CompanyExposure, EtfReport, PortfolioItem
from hoc.contract.dependencies import (
    InsightClaim,
    Insights,
    InsightsStatus,
    MetricFact,
    VerifiedEdge,
)
from hoc.graph.importance import attach_edge_importance, score_edge_importance
from hoc.graph.metrics import (
    DependencyGraphSummary,
    compute_dependency_summary,
    format_metric_value,
)

log = logging.getLogger("hoc.graph.orchestrator")

ORCHESTRATOR_PROMPT_VERSION = "hoc-orch-v3.1"
prompt_version: str = ORCHESTRATOR_PROMPT_VERSION

GEMINI_INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_API_REVISION = "2026-05-20"

ClaimSeverity = Literal["info", "warning", "critical"]

# Flat JSON schema for Gemini Interactions API structured output (no $ref / anyOf).
ORCHESTRATOR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "flaws": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                    "plain_text": {"type": "string"},
                    "plain_title": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "warning", "info"],
                    },
                    "cited_metric_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "cited_edge_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "entities": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "title",
                    "text",
                    "plain_text",
                    "plain_title",
                    "severity",
                    "cited_metric_ids",
                    "cited_edge_ids",
                ],
            },
        },
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                    "plain_text": {"type": "string"},
                    "plain_title": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["critical", "warning", "info"],
                    },
                    "cited_metric_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "cited_edge_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "entities": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "title",
                    "text",
                    "plain_text",
                    "plain_title",
                    "cited_metric_ids",
                    "cited_edge_ids",
                ],
            },
        },
    },
    "required": ["flaws", "suggestions"],
}

ORCHESTRATOR_SYSTEM_INSTRUCTION = """You are the House of Cards dependency risk orchestrator.
You evaluate a portfolio's verified SEC 10-K/20-F supply-chain, facility, and customer dependency graph.

STRICT GROUNDING RULES (claims violating any rule are automatically rejected by Python):
1. ZERO INVENTED NUMBERS: Never write any literal number, percentage, or count in `title`, `text`, `plain_title`, or `plain_text`.
   Every number MUST be written as a `{{metric:<metric_id>}}` placeholder using an exact `metric_id` from the provided `metrics` list (for example: `{{metric:dep.ALIAS:ZZEPSILON}}` or `{{metric:facility.TW}}`).
2. REQUIRED CITATIONS: Every flaw and suggestion MUST list the `cited_metric_ids` it uses and the supporting `cited_edge_ids` from the provided `verified_edges` list.
3. ENTITY LOCK: Mention ONLY company names, ETF tickers, countries, and inputs that appear in the provided portfolio holdings or verified edges. Never name outside tickers or companies.
4. ADVISORY ONLY: Focus on structural diversification dimensions (foundry concentration, single-source bottlenecks, geographic facility clustering across ETFs). Never recommend buying, selling, or shorting specific securities.
5. BEGINNER PLAIN FIELDS (`plain_text` and `plain_title`):
   - Write `plain_text` first: <= 25 words, simple everyday English, at most 1 number and ONLY via a cited `{{metric:<metric_id>}}` placeholder (e.g. "{{metric:dep.ALIAS:TSMC}} of your money relies on TSMC to make chips for your companies.").
   - Then write `plain_title` to summarise `plain_text` ONLY (never `title` or `text`): <= 8 words, simple everyday English, zero numbers (no digits, no placeholders, and no count words like "two", "three", "four", or "both"), zero financial jargon (never write HHI, GICS, look-through, 10-K, 20-F, CIK, edges, tier names, or orchestrator), and NEVER name any company, country, or plural count that is not in `plain_text` (e.g. if `plain_text` names only TSMC, write "Heavy reliance on one chip maker", never "two chip makers").
"""

_PLACEHOLDER_RE = re.compile(r"\{\{metric:([A-Za-z0-9_:.\-]+)\}\}")

# Whitelisted SEC / standard nomenclature tokens whose digits are not quantitative claims.
_WHITELISTED_DIGIT_TOKENS_RE = re.compile(
    r"\b(?:"
    r"10-K|20-F|40-F|6-K|8-K|N-PORT|"
    r"Item\s+1A|Item\s+1B|Item\s+1|Item\s+2|Item\s+3\.D|Item\s+3|Item\s+4|Item\s+5|Item\s+7|"
    r"Exhibit\s+21|Exhibit\s+8\.1|Exhibit\s+8|"
    r"S&P\s*500|Nasdaq[- ]100|Russell\s*1000|Russell\s*2000|"
    r"CC\s+BY\s+4\.0|Tier\s+1|Level\s+1|Level\s+2"
    r")\b",
    re.IGNORECASE,
)

# Common uppercase English / finance abbreviations that are NOT stock tickers.
_COMMON_UPPER_ACRONYMS: frozenset[str] = frozenset(
    {
        "ETF",
        "ETFS",
        "SEC",
        "USA",
        "USD",
        "NAV",
        "GICS",
        "HHI",
        "ADR",
        "ADRS",
        "SPOF",
        "SPOFS",
        "EU",
        "UK",
        "US",
        "TW",
        "KR",
        "JP",
        "CN",
        "DE",
        "NL",
        "VN",
        "IN",
        "SG",
        "IE",
        "IL",
        "MY",
        "GB",
        "AI",
        "IT",
        "JV",
        "CPU",
        "GPU",
        "DRAM",
        "NAND",
        "HBM",
        "EUV",
        "DUV",
        "SOI",
        "PCB",
        "OSAT",
        "API",
        "LLM",
        "EDGAR",
        "CIK",
        "ISIN",
        "LEI",
        "FIGI",
        "CUSIP",
        "ROC",
        "PRC",
        "OEM",
        "ODM",
    }
)

_FORBIDDEN_TRADE_VERBS_RE = re.compile(
    r"\b(?:buy|sell|short|liquidate)\s+(?:shares|units|stock|position)\b",
    re.IGNORECASE,
)

_FORBIDDEN_PLAIN_JARGON_RE = re.compile(
    r"\b(?:HHI|GICS|look[- ]through|10-K|20-F|40-F|6-K|8-K|N-PORT|CIK|edges?|orchestrator|critical)\b",
    re.IGNORECASE,
)

_UNSUPPORTED_PLAIN_TITLE_COUNTS_RE = re.compile(
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|both|couple|dozen)\b",
    re.IGNORECASE,
)

_GENERIC_ENTITY_PREFIXES: frozenset[str] = frozenset(
    {
        "united",
        "american",
        "general",
        "advanced",
        "applied",
        "international",
        "national",
        "first",
        "standard",
        "western",
        "eastern",
        "northern",
        "southern",
        "pacific",
        "global",
        "taiwan",
    }
)


def _build_claim_entity_alias_groups(
    explicit_entities: Sequence[str],
    cited_edge_ids: Sequence[str],
    edges_by_id: Mapping[str, VerifiedEdge],
) -> list[set[str]]:
    """Group normalised surface forms (and short brand names / aliases) for entities on a claim."""
    by_key: dict[str, set[str]] = {}

    def _add_forms(key: str, raw_name: str, *, is_company: bool) -> None:
        norm = _normalise_entity_token(raw_name)
        if len(norm) < 3:
            return
        forms = by_key.setdefault(key, set())
        forms.add(norm)
        if key.startswith("ALIAS:"):
            alias_tail = key.split(":", 1)[1].lower().replace("_", " ").strip()
            if len(alias_tail) >= 3:
                forms.add(alias_tail)
            if key == "ALIAS:TSMC":
                forms.add("tsmc")
            elif key == "ALIAS:SAMSUNG_ELEC":
                forms.add("samsung")
        if is_company:
            tokens = norm.split()
            if tokens and len(tokens[0]) >= 4 and tokens[0] not in _GENERIC_ENTITY_PREFIXES:
                forms.add(tokens[0])
            if "taiwan semiconductor" in norm:
                forms.add("tsmc")
                forms.add("taiwan semiconductor")

    for eid in cited_edge_ids:
        edge = edges_by_id.get(eid)
        if edge is None:
            continue
        _add_forms(edge.source_company_key, edge.source_company_name, is_company=True)
        tkey = edge.target_key or f"{edge.target_kind}:{_normalise_entity_token(edge.target_name)}"
        _add_forms(tkey, edge.target_name, is_company=(edge.target_kind == "company"))

    for ent in explicit_entities:
        norm = _normalise_entity_token(ent)
        if len(norm) < 3:
            continue
        matched_existing = False
        for forms in by_key.values():
            if norm in forms or any(norm in f or f in norm for f in forms if len(f) >= 4):
                forms.add(norm)
                matched_existing = True
                break
        if not matched_existing:
            by_key.setdefault(f"ENT:{norm}", set()).add(norm)

    return [forms for forms in by_key.values() if forms]


def _contains_entity_form(norm_text: str, form: str) -> bool:
    if len(form) < 3:
        return False
    if form == "taiwan":
        return bool(re.search(r"\btaiwan\b(?!\s+semiconductor)", norm_text))
    return bool(re.search(rf"\b{re.escape(form)}\b", norm_text))


def _is_plain_title_supported_by_text(
    plain_title: str,
    support_text: str,
    entity_groups: Sequence[set[str]],
) -> bool:
    """Ensure `plain_title` does not claim counts or entities absent from `support_text` (FIX-10)."""
    if _UNSUPPORTED_PLAIN_TITLE_COUNTS_RE.search(plain_title):
        return False
    title_norm = _normalise_entity_token(plain_title)
    support_norm = _normalise_entity_token(support_text)
    if not title_norm:
        return False
    for forms in entity_groups:
        if any(_contains_entity_form(title_norm, f) for f in forms) and not any(
            _contains_entity_form(support_norm, f) for f in forms
        ):
            return False
    return True


def _verify_and_render_plain_field(
    raw_value: Any,
    *,
    max_words: int,
    max_numbers: int,
    cited_metric_ids: Sequence[str],
    metrics_by_id: Mapping[str, MetricFact],
    allowed_tickers: set[str],
    allowed_entities: set[str],
    resolve_mid: Any,
    expand_fn: Any,
) -> str | None:
    """Verify and render `plain_title` or `plain_text`; return None if any check fails."""
    if not isinstance(raw_value, str):
        return None
    cleaned = raw_value.strip()
    if not cleaned:
        return None

    # 1. Placeholders must resolve to metrics cited on the claim
    pids = [resolve_mid(m) for m in _PLACEHOLDER_RE.findall(cleaned)]
    if len(pids) > max_numbers:
        return None
    cited_set = set(cited_metric_ids)
    for mid in pids:
        if mid not in metrics_by_id or mid not in cited_set:
            return None

    # 2. No literal numbers outside {{metric:<id>}} placeholders (and no SEC form digits in beginner text)
    stripped = _PLACEHOLDER_RE.sub(" ", cleaned)
    if re.search(r"\d", stripped):
        return None

    # 3. No forbidden beginner jargon or trade instructions
    if _FORBIDDEN_PLAIN_JARGON_RE.search(stripped) or _FORBIDDEN_TRADE_VERBS_RE.search(stripped):
        return None

    # 4. Ticker & entity lock: uppercase 2..5 letter tokens must be in allowed_tickers,
    #    and any proper-noun phrase that looks like an outside company is rejected.
    for token in re.findall(r"\b[A-Z]{2,5}\b", stripped):
        if token not in allowed_tickers:
            return None

    # 5. Expand placeholders and enforce word & rendered-number limits
    rendered = re.sub(r"\s+", " ", _PLACEHOLDER_RE.sub(expand_fn, cleaned)).strip()
    if not rendered or "{{metric:" in rendered:
        return None
    if len(rendered.split()) > max_words:
        return None
    rendered_numbers = re.findall(r"\d+(?:\.\d+)?%?", rendered)
    if len(rendered_numbers) > max_numbers:
        return None

    return rendered


class OrchestratorAiClient(Protocol):
    """Protocol for injecting either the real Gemini client or FakeGeminiClient."""

    def generate_orchestrator_json(
        self,
        *,
        model: str,
        system_instruction: str,
        user_prompt: str,
        response_schema: Mapping[str, Any],
    ) -> dict[str, Any] | str: ...


def _normalise_entity_token(name: str) -> str:
    cleaned = re.sub(
        r"\b(?:inc|incorporated|corp|corporation|co|company|ltd|limited|plc|nv|n\.v\.|ag|se|sa|s\.a\.|llc|lp|the|group|holdings|holding|adr)\b",
        " ",
        name.lower(),
    )
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned).strip()
    return cleaned


def build_allowed_vocabulary(
    exposures: Sequence[CompanyExposure],
    edges: Sequence[VerifiedEdge],
    etfs: Sequence[EtfReport] | Sequence[PortfolioItem] = (),
) -> tuple[set[str], set[str]]:
    """Return (allowed_tickers_upper, allowed_entity_phrases_lower) from portfolio & verified edges."""
    allowed_tickers: set[str] = set(_COMMON_UPPER_ACRONYMS)
    allowed_entities: set[str] = set()

    for etf in etfs:
        ticker = str(getattr(etf, "ticker", "") or "").strip().upper()
        if ticker:
            allowed_tickers.add(ticker)
            allowed_entities.add(ticker.lower())
        etf_name = str(getattr(etf, "name", "") or "").strip()
        if etf_name:
            allowed_entities.add(_normalise_entity_token(etf_name))

    for comp in exposures:
        if comp.company_name:
            norm = _normalise_entity_token(comp.company_name)
            if norm:
                allowed_entities.add(norm)
                first_word = norm.split()[0]
                if len(first_word) >= 3:
                    allowed_entities.add(first_word)
            for tok in re.findall(r"\b[A-Z]{2,6}\b", comp.company_name):
                allowed_tickers.add(tok)
        if comp.company_key:
            allowed_entities.add(comp.company_key.lower())
            key_tail = comp.company_key.split(":", 1)[-1].lower()
            allowed_entities.add(key_tail.replace("_", " ").replace("-", " "))
            allowed_tickers.add(key_tail.upper())
        for sym in comp.symbols:
            clean_sym = sym.strip().upper()
            if clean_sym:
                allowed_tickers.add(clean_sym)
                allowed_tickers.add(clean_sym.split(".")[0])
                allowed_entities.add(clean_sym.lower())
        for contrib in comp.contributions:
            allowed_tickers.add(contrib.etf_ticker.strip().upper())

    for edge in edges:
        for name_field in (edge.target_name, edge.source_company_name):
            raw_name = (name_field or "").strip()
            if raw_name:
                norm_t = _normalise_entity_token(raw_name)
                if norm_t:
                    allowed_entities.add(norm_t)
                    first_word = norm_t.split()[0]
                    if len(first_word) >= 3:
                        allowed_entities.add(first_word)
                for tok in re.findall(r"\b[A-Z]{2,6}\b", raw_name):
                    allowed_tickers.add(tok)
        for key_field in (edge.target_key, edge.source_company_key):
            raw_key = (key_field or "").strip()
            if raw_key:
                allowed_entities.add(raw_key.lower())
                tail = raw_key.split(":", 1)[-1].lower()
                allowed_entities.add(tail.replace("_", " ").replace("-", " "))
                allowed_tickers.add(tail.upper())
        if edge.qualifier:
            allowed_entities.add(_normalise_entity_token(edge.qualifier))

    return allowed_tickers, allowed_entities


def _build_metric_and_edge_aliases(
    summary: DependencyGraphSummary,
    edges: Sequence[VerifiedEdge],
) -> tuple[dict[str, str], dict[str, str]]:
    """Map synthetic FakeGeminiClient IDs (e.g. supplier_dep_1, edge_1) to canonical IDs if present."""
    metric_aliases: dict[str, str] = {}
    edge_aliases: dict[str, str] = {}
    for idx, sup in enumerate(summary.suppliers, start=1):
        canonical_mid = f"dep.{sup.target_id}"
        if canonical_mid in summary.metrics_by_id:
            metric_aliases.setdefault(f"supplier_dep_{idx}", canonical_mid)
        crit_mid = f"critical.{sup.target_id}"
        if crit_mid in summary.metrics_by_id:
            metric_aliases.setdefault(f"critical_dep_{idx}", crit_mid)
    if not metric_aliases and summary.metrics:
        metric_aliases["supplier_dep_1"] = summary.metrics[0].metric_id
    for idx, edge in enumerate(edges, start=1):
        edge_aliases.setdefault(f"edge_{idx}", edge.edge_id)
    return metric_aliases, edge_aliases


def verify_and_render_claim(
    raw_claim: Mapping[str, Any],
    *,
    metrics_by_id: Mapping[str, MetricFact],
    edges_by_id: Mapping[str, VerifiedEdge],
    allowed_tickers: set[str],
    allowed_entities: set[str],
    claim_id: str,
    kind: Literal["suggestion", "flaw"],
    metric_aliases: Mapping[str, str] | None = None,
    edge_aliases: Mapping[str, str] | None = None,
) -> tuple[InsightClaim | None, str | None]:
    """Verify one orchestrator flaw or suggestion and expand {{metric:<id>}} placeholders.

    Returns ``(InsightClaim, None)`` when valid, or ``(None, rejection_reason)`` when rejected.
    """
    raw_title = str(raw_claim.get("title") or "").strip()
    raw_text = str(
        raw_claim.get("text")
        or raw_claim.get("description")
        or raw_claim.get("detail")
        or ""
    ).strip()

    if not raw_title or not raw_text:
        return None, "empty_title_or_text"

    combined_raw = f"{raw_title} {raw_text}"
    m_aliases = metric_aliases or {}
    e_aliases = edge_aliases or {}

    def _resolve_mid(mid: str) -> str:
        return m_aliases.get(mid, mid) if mid not in metrics_by_id else mid

    def _resolve_eid(eid: str) -> str:
        return e_aliases.get(eid, eid) if eid not in edges_by_id else eid

    # 1. Extract {{metric:<id>}} placeholders and validate cited_metric_ids & cited_edge_ids
    placeholder_ids = [_resolve_mid(m) for m in _PLACEHOLDER_RE.findall(combined_raw)]
    raw_metric_ids = [
        _resolve_mid(str(m).strip())
        for m in (raw_claim.get("cited_metric_ids") or raw_claim.get("metric_ids") or [])
        if str(m).strip()
    ]
    all_metric_ids: list[str] = []
    for mid in [*raw_metric_ids, *placeholder_ids]:
        if mid not in all_metric_ids:
            all_metric_ids.append(mid)

    if not all_metric_ids:
        return None, "missing_metric_ids"

    for mid in all_metric_ids:
        if mid not in metrics_by_id:
            return None, f"unknown_metric_id:{mid}"

    raw_edge_ids = [
        _resolve_eid(str(e).strip())
        for e in (raw_claim.get("cited_edge_ids") or raw_claim.get("edge_ids") or [])
        if str(e).strip()
    ]
    if not raw_edge_ids:
        for mid in all_metric_ids:
            for eid in metrics_by_id[mid].supporting_edge_ids:
                if eid not in raw_edge_ids:
                    raw_edge_ids.append(eid)

    if not raw_edge_ids:
        return None, "missing_edge_ids"

    for eid in raw_edge_ids:
        if eid not in edges_by_id:
            return None, f"unknown_edge_id:{eid}"

    # 2. Strict literal number check BEFORE expanding {{metric:<id>}} placeholders.
    #    Every quantitative figure in title/text must come from a {{metric:<id>}} placeholder.
    stripped = _PLACEHOLDER_RE.sub(" ", combined_raw)
    stripped = _WHITELISTED_DIGIT_TOKENS_RE.sub(" ", stripped)
    if re.search(r"\d", stripped):
        return None, "unverified_literal_number"

    # 3. Entity & ticker name lock
    explicit_entities = [
        str(ent).strip()
        for ent in (raw_claim.get("entities") or raw_claim.get("referenced_companies") or [])
        if str(ent).strip()
    ]
    for ent in explicit_entities:
        norm_ent = _normalise_entity_token(ent)
        if not norm_ent:
            continue
        if (
            ent.upper() not in allowed_tickers
            and norm_ent not in allowed_entities
            and not any(
                norm_ent in allowed or allowed in norm_ent
                for allowed in allowed_entities
                if len(allowed) >= 3
            )
        ):
            return None, f"unknown_entity:{ent}"

    for token in re.findall(r"\b[A-Z]{2,5}\b", stripped):
        if token not in allowed_tickers:
            return None, f"unknown_ticker_in_text:{token}"

    # 4. Advisory-only guard
    if _FORBIDDEN_TRADE_VERBS_RE.search(stripped):
        return None, "forbidden_trading_instruction"

    # 5. Expand {{metric:<id>}} placeholders deterministically
    def _expand(match: re.Match[str]) -> str:
        mid = _resolve_mid(match.group(1))
        return format_metric_value(metrics_by_id[mid])

    rendered_title = _PLACEHOLDER_RE.sub(_expand, raw_title)
    rendered_text = _PLACEHOLDER_RE.sub(_expand, raw_text)

    rendered_plain_text = _verify_and_render_plain_field(
        raw_claim.get("plain_text"),
        max_words=25,
        max_numbers=1,
        cited_metric_ids=all_metric_ids,
        metrics_by_id=metrics_by_id,
        allowed_tickers=allowed_tickers,
        allowed_entities=allowed_entities,
        resolve_mid=_resolve_mid,
        expand_fn=_expand,
    )
    rendered_plain_title = _verify_and_render_plain_field(
        raw_claim.get("plain_title"),
        max_words=8,
        max_numbers=0,
        cited_metric_ids=all_metric_ids,
        metrics_by_id=metrics_by_id,
        allowed_tickers=allowed_tickers,
        allowed_entities=allowed_entities,
        resolve_mid=_resolve_mid,
        expand_fn=_expand,
    )
    if rendered_plain_title is not None:
        entity_groups = _build_claim_entity_alias_groups(
            explicit_entities,
            raw_edge_ids,
            edges_by_id,
        )
        support_text = rendered_plain_text if rendered_plain_text is not None else rendered_text
        if not _is_plain_title_supported_by_text(
            rendered_plain_title,
            support_text,
            entity_groups,
        ):
            rendered_plain_title = None

    default_sev = "warning" if kind == "flaw" else "info"
    severity_raw = str(raw_claim.get("severity") or default_sev).lower()
    severity: ClaimSeverity = (
        severity_raw  # type: ignore[assignment]
        if severity_raw in {"critical", "warning", "info"}
        else default_sev
    )

    return (
        InsightClaim(
            claim_id=str(raw_claim.get("claim_id") or raw_claim.get("id") or claim_id),
            kind=kind,
            severity=severity,
            title=rendered_title,
            text=rendered_text,
            cited_metric_ids=all_metric_ids,
            cited_edge_ids=raw_edge_ids,
            plain_title=rendered_plain_title,
            plain_text=rendered_plain_text,
        ),
        None,
    )


def compute_orchestrator_cache_key(
    exposures: Sequence[CompanyExposure],
    edges: Sequence[VerifiedEdge],
    holdings: Sequence[PortfolioItem] = (),
    prompt_ver: str = ORCHESTRATOR_PROMPT_VERSION,
    *,
    model: str | None = None,
    user_prompt: str | None = None,
) -> str:
    """Compute the deterministic sha256 cache key for orchestrator output.

    Edge ids alone are not enough: resolving a target_key (or any metric change) keeps every edge id but
    changes what the model sees, so a stale reply would be re-validated against new metrics and lose
    every claim that cites a renamed metric. `user_prompt` (the exact grounding payload) and `model`
    therefore go into the key too.
    """
    alloc_part = (
        [
            (h.ticker.upper(), f"{h.allocation:.10f}")
            for h in sorted(holdings, key=lambda x: x.ticker.upper())
        ]
        if holdings
        else [
            (c.company_key, f"{c.exposure:.10f}")
            for c in sorted(exposures, key=lambda x: x.company_key)
        ]
    )
    edge_ids = sorted({e.edge_id.strip() for e in edges if e.edge_id.strip()})
    payload = json.dumps(
        {
            "allocations": alloc_part,
            "verified_edge_ids": edge_ids,
            "prompt_version": prompt_ver,
            "model": model,
            "user_prompt_sha256": (
                hashlib.sha256(user_prompt.encode("utf-8")).hexdigest() if user_prompt is not None else None
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_deterministic_raw_claims(
    summary: DependencyGraphSummary,
) -> dict[str, list[dict[str, Any]]]:
    """Generate deterministic template claims using {{metric:<id>}} placeholders."""
    raw_flaws: list[dict[str, Any]] = []
    raw_suggestions: list[dict[str, Any]] = []

    # 1. Single points of failure -> flaws + diversification suggestions
    for spof in summary.single_points_of_failure[:4]:
        weight_mid = f"dep.{spof.target_id}"
        comp_mid = f"dep.{spof.target_id}.companies"
        spof_mid = f"spof.{spof.target_id}"
        metric_ids = [weight_mid, comp_mid]
        if spof_mid in summary.metrics_by_id:
            metric_ids.append(spof_mid)

        holders_str = ", ".join(spof.dependent_company_names[:3])
        etfs_str = ", ".join(spof.etf_tickers) if spof.etf_tickers else "loaded ETFs"
        severity: ClaimSeverity = (
            "critical"
            if spof.dependent_weight >= 0.08
            or (spof.sole_source and len(spof.dependent_company_keys) >= 2)
            else "warning"
        )
        sole_label = "sole-source " if spof.sole_source else "shared "
        direct_note = (
            ", which your portfolio also holds directly"
            if spof.target_in_portfolio
            else ""
        )

        raw_flaws.append(
            {
                "title": f"Critical {sole_label}bottleneck on {spof.target_name}",
                "text": (
                    f"{{{{metric:{weight_mid}}}}} of your portfolio across {{{{metric:{comp_mid}}}}} "
                    f"holdings ({holders_str} in {etfs_str}) depends on {spof.target_name}"
                    f"{direct_note}."
                ),
                "plain_title": "Several holdings rely on one supplier",
                "plain_text": (
                    f"{{{{metric:{weight_mid}}}}} of your money depends on {spof.target_name} "
                    f"across your biggest companies."
                ),
                "severity": severity,
                "cited_metric_ids": metric_ids,
                "cited_edge_ids": list(spof.supporting_edge_ids),
                "entities": [
                    spof.target_name,
                    *spof.dependent_company_names[:3],
                    *spof.etf_tickers,
                ],
            }
        )

        raw_suggestions.append(
            {
                "title": f"Diversify supply-chain reliance on {spof.target_name}",
                "text": (
                    f"Because {spof.target_name} underpins {{{{metric:{weight_mid}}}}} of the portfolio "
                    f"across {{{{metric:{comp_mid}}}}} holdings ({holders_str}), balancing toward sectors "
                    f"or funds with independent suppliers reduces single-counterparty risk."
                ),
                "plain_title": "Add funds with different suppliers",
                "plain_text": (
                    f"{{{{metric:{weight_mid}}}}} of your money depends on {spof.target_name}, "
                    f"so shifting toward other industries can spread that risk."
                ),
                "severity": "warning" if severity == "critical" else "info",
                "cited_metric_ids": [weight_mid, comp_mid],
                "cited_edge_ids": list(spof.supporting_edge_ids),
                "entities": [spof.target_name, *spof.dependent_company_names[:3]],
            }
        )

    # 2. Facility-country concentration -> flaws + suggestions
    for fac in summary.facilities_by_country[:2]:
        weight_mid = f"facility.{fac.country_code}"
        comp_mid = f"facility.{fac.country_code}.companies"
        holders_str = ", ".join(fac.company_names[:3])
        severity = "critical" if fac.dependent_weight >= 0.15 else "warning"

        raw_flaws.append(
            {
                "title": f"Geographic facility concentration in {fac.country_name}",
                "text": (
                    f"{{{{metric:{weight_mid}}}}} of your portfolio across {{{{metric:{comp_mid}}}}} "
                    f"companies ({holders_str}) relies on key facilities or assembly in {fac.country_name}."
                ),
                "plain_title": f"Key factories concentrated in {fac.country_name}",
                "plain_text": (
                    f"{{{{metric:{weight_mid}}}}} of your money is in companies with key factories "
                    f"in {fac.country_name}."
                ),
                "severity": severity,
                "cited_metric_ids": [weight_mid, comp_mid],
                "cited_edge_ids": list(fac.supporting_edge_ids),
                "entities": [fac.country_name, *fac.company_names[:3]],
            }
        )

        raw_suggestions.append(
            {
                "title": f"Balance {fac.country_name} physical facility footprint",
                "text": (
                    f"{{{{metric:{weight_mid}}}}} of your portfolio relies on facilities in "
                    f"{fac.country_name} ({{{{metric:{comp_mid}}}}} holdings: {holders_str}); "
                    f"consider holdings with manufacturing diversified across other regions."
                ),
                "plain_title": "Spread factory locations across more countries",
                "plain_text": (
                    f"{{{{metric:{weight_mid}}}}} of your money relies on factories in "
                    f"{fac.country_name}; broader funds can reduce single-country exposure."
                ),
                "severity": "warning",
                "cited_metric_ids": [weight_mid, comp_mid],
                "cited_edge_ids": list(fac.supporting_edge_ids),
                "entities": [fac.country_name, *fac.company_names[:3]],
            }
        )

    # 3. If no SPOF or facility concentration existed but supplier edges exist, surface top supplier
    if not raw_flaws and summary.suppliers:
        top_sup = summary.suppliers[0]
        weight_mid = f"dep.{top_sup.target_id}"
        comp_mid = f"dep.{top_sup.target_id}.companies"
        holders_str = ", ".join(top_sup.dependent_company_names[:3])
        raw_flaws.append(
            {
                "title": f"Supply-chain dependency on {top_sup.target_name}",
                "text": (
                    f"{holders_str} ({{{{metric:{comp_mid}}}}} holding) discloses a verified supply-chain "
                    f"dependency on {top_sup.target_name} covering {{{{metric:{weight_mid}}}}} of the portfolio."
                ),
                "plain_title": "Key supplier behind your holdings",
                "plain_text": (
                    f"{{{{metric:{weight_mid}}}}} of your money relies on {top_sup.target_name}."
                ),
                "severity": "info",
                "cited_metric_ids": [weight_mid, comp_mid],
                "cited_edge_ids": list(top_sup.supporting_edge_ids),
                "entities": [top_sup.target_name, *top_sup.dependent_company_names[:3]],
            }
        )

    return {"flaws": raw_flaws, "suggestions": raw_suggestions}


def build_user_prompt(
    exposures: Sequence[CompanyExposure],
    edges: Sequence[VerifiedEdge],
    summary: DependencyGraphSummary,
    etfs: Sequence[EtfReport] | Sequence[PortfolioItem] = (),
) -> str:
    """Format the verified edges and MetricFacts into a compact grounding payload for Argon."""
    etf_list = [
        {
            "ticker": getattr(e, "ticker", ""),
            "allocation_pct": f"{float(getattr(e, 'allocation', 0.0)) * 100:.2f}%",
        }
        for e in etfs
    ]
    top_holdings = [
        {
            "company_key": c.company_key,
            "company_name": c.company_name,
            "symbols": c.symbols,
            "exposure_pct": f"{c.exposure * 100:.2f}%",
            "etfs": [contrib.etf_ticker for contrib in c.contributions],
        }
        for c in exposures[:15]
    ]
    metrics_payload = [
        {
            "metric_id": m.metric_id,
            "label": m.label,
            "formatted_value": format_metric_value(m),
            "placeholder": f"{{{{metric:{m.metric_id}}}}}",
            "supporting_edge_ids": list(m.supporting_edge_ids),
        }
        for m in summary.metrics
    ]
    edges_payload = []
    for e in edges:
        imp = e.importance if e.importance is not None else score_edge_importance(e)
        edges_payload.append(
            {
                "edge_id": e.edge_id,
                "source_company_key": e.source_company_key,
                "source_company_name": e.source_company_name,
                "edge_type": e.edge_type,
                "target_name": e.target_name,
                "target_kind": e.target_kind,
                "target_key": e.target_key,
                "sole_source": e.sole_source,
                "importance_tier": imp.tier,
                "importance_score": imp.score,
                "importance_reasons": list(imp.reasons),
                "interpretation_status": (
                    e.interpretation.status if e.interpretation is not None else "ok"
                ),
                "qualifier": e.qualifier,
                "section": e.section,
                "form": e.filing.form,
                "filed": str(e.filing.filed),
                "evidence_quote": e.evidence_quote,
            }
        )
    payload = {
        "etfs": etf_list,
        "top_holdings": top_holdings,
        "metrics": metrics_payload,
        "verified_edges": edges_payload,
    }
    return (
        "Analyse the following verified portfolio dependency graph and metrics.\n"
        "Remember: NEVER write literal digits/numbers/percentages in `title`, `text`, `plain_title`, or `plain_text` — "
        "always write `{{metric:<metric_id>}}` placeholders.\n"
        "For every flaw and suggestion, first write `plain_text` (<= 25 words, at most 1 `{{metric:<metric_id>}}` "
        "placeholder, everyday English, no jargon) and then write `plain_title` (<= 8 words, zero numbers and no "
        "count words like 'two' or 'three', no jargon) summarising ONLY what `plain_text` says.\n\n"
        + json.dumps(payload, indent=2)
    )


def verify_and_build_insights(
    raw_payload: Mapping[str, Any],
    *,
    exposures: Sequence[CompanyExposure],
    edges: Sequence[VerifiedEdge],
    summary: DependencyGraphSummary,
    etfs: Sequence[EtfReport] | Sequence[PortfolioItem] = (),
    status: InsightsStatus = "ok",
    model: str | None = None,
) -> Insights:
    """Verify all raw flaws and suggestions from an LLM or fallback payload."""
    edges_by_id = {e.edge_id.strip(): e for e in edges if e.edge_id.strip()}
    allowed_tickers, allowed_entities = build_allowed_vocabulary(exposures, edges, etfs)
    metric_aliases, edge_aliases = _build_metric_and_edge_aliases(summary, edges)

    verified_flaws: list[InsightClaim] = []
    verified_suggestions: list[InsightClaim] = []
    rejected_count = 0

    for idx, raw_flaw in enumerate(raw_payload.get("flaws") or []):
        if not isinstance(raw_flaw, Mapping):
            rejected_count += 1
            continue
        rendered, err = verify_and_render_claim(
            raw_flaw,
            metrics_by_id=summary.metrics_by_id,
            edges_by_id=edges_by_id,
            allowed_tickers=allowed_tickers,
            allowed_entities=allowed_entities,
            claim_id=f"c-flaw-{idx + 1}",
            kind="flaw",
            metric_aliases=metric_aliases,
            edge_aliases=edge_aliases,
        )
        if rendered is not None and err is None:
            verified_flaws.append(rendered)
        else:
            rejected_count += 1

    for idx, raw_sug in enumerate(raw_payload.get("suggestions") or []):
        if not isinstance(raw_sug, Mapping):
            rejected_count += 1
            continue
        rendered, err = verify_and_render_claim(
            raw_sug,
            metrics_by_id=summary.metrics_by_id,
            edges_by_id=edges_by_id,
            allowed_tickers=allowed_tickers,
            allowed_entities=allowed_entities,
            claim_id=f"c-sugg-{idx + 1}",
            kind="suggestion",
            metric_aliases=metric_aliases,
            edge_aliases=edge_aliases,
        )
        if rendered is not None and err is None:
            verified_suggestions.append(rendered)
        else:
            rejected_count += 1

    return Insights(
        status=status,
        model=model,
        suggestions=verified_suggestions,
        flaws=verified_flaws,
        rejected_claims_count=rejected_count,
    )


class DependencyOrchestrator:
    """Orchestrates deterministic graph metrics + Gemini 4 Argon synthesis with disk caching."""

    prompt_version: str = ORCHESTRATOR_PROMPT_VERSION

    def __init__(
        self,
        http: Any | None = None,
        settings: Settings | None = None,
        *,
        ai_client: OrchestratorAiClient | Any | None = None,
        http_client: Any | None = None,
        cache_dir: Path | str | None = None,
        orchestrator_model: str | None = None,
        fallback_model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._http_client = http if http is not None else http_client
        self._settings = settings
        self._ai_client = ai_client
        resolved_cache = (
            Path(cache_dir)
            if cache_dir is not None
            else (settings.cache_dir if settings is not None else None)
        )
        self._cache_dir = resolved_cache
        self._orchestrator_model = (
            orchestrator_model
            or (settings.gemini_orchestrator_model if settings is not None else None)
            or os.environ.get("HOC_GEMINI_ORCHESTRATOR_MODEL")
            or DEFAULT_ORCHESTRATOR_MODEL
        )
        self._fallback_model = (
            fallback_model
            or (settings.gemini_extractor_model if settings is not None else None)
            or os.environ.get("HOC_GEMINI_EXTRACTOR_MODEL")
            or DEFAULT_EXTRACTOR_MODEL
        )
        self._explicit_api_key = api_key

    def _resolve_api_key(self) -> str | None:
        if self._explicit_api_key is not None:
            return self._explicit_api_key.strip() or None
        if self._settings is not None and self._settings.gemini_api_key:
            return self._settings.gemini_api_key.strip() or None
        if self._ai_client is not None and hasattr(self._ai_client, "has_api_key"):
            return "injected-client-key" if self._ai_client.has_api_key else None
        return (
            os.environ.get("GOOGLE_API_KEY", "").strip()
            or os.environ.get("GEMINI_API_KEY", "").strip()
            or None
        )

    def _cache_path(self, cache_key: str) -> Path | None:
        if self._cache_dir is None:
            return None
        return self._cache_dir / "orchestrator" / f"{cache_key}.json"

    def _read_cache(self, cache_key: str) -> dict[str, Any] | None:
        path = self._cache_path(cache_key)
        if path is None or not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "raw_payload" in data:
                return data
        except (OSError, ValueError, TypeError):
            return None
        return None

    def _write_cache(
        self,
        cache_key: str,
        *,
        model: str,
        raw_payload: Mapping[str, Any],
    ) -> None:
        path = self._cache_path(cache_key)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "cache_key": cache_key,
                        "prompt_version": self.prompt_version,
                        "model": model,
                        "raw_payload": dict(raw_payload),
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError as exc:
            log.debug("Could not write orchestrator cache %s: %s", path, exc)

    def _call_ai_client(self, model: str, user_prompt: str) -> tuple[dict[str, Any], str]:
        """Invoke the injected AI client (or GeminiClient over HttpClient) and return (payload, used_model)."""
        client = self._ai_client
        if client is None and self._http_client is not None:
            client = GeminiClient(
                self._http_client,
                self._settings,
                api_key=self._resolve_api_key(),
                extractor_model=self._fallback_model,
                orchestrator_model=self._orchestrator_model,
            )

        if client is None:
            raise RuntimeError("No AI client or HTTP client configured")

        used_model = model
        if hasattr(client, "generate_orchestrator_json"):
            raw = client.generate_orchestrator_json(
                model=model,
                system_instruction=ORCHESTRATOR_SYSTEM_INSTRUCTION,
                user_prompt=user_prompt,
                response_schema=ORCHESTRATOR_RESPONSE_SCHEMA,
            )
        elif hasattr(client, "generate_json"):
            sig = inspect.signature(client.generate_json)
            if "fallback_model" in sig.parameters:
                raw, used_model = client.generate_json(
                    user_prompt,
                    ORCHESTRATOR_RESPONSE_SCHEMA,
                    model=model,
                    system_instruction=ORCHESTRATOR_SYSTEM_INSTRUCTION,
                    thinking_level="medium",
                    fallback_model=self._fallback_model,
                )
            else:
                raw = client.generate_json(
                    model=model,
                    system_instruction=ORCHESTRATOR_SYSTEM_INSTRUCTION,
                    prompt=user_prompt,
                    schema=ORCHESTRATOR_RESPONSE_SCHEMA,
                )
        elif callable(client):
            raw = client(
                model=model,
                system_instruction=ORCHESTRATOR_SYSTEM_INSTRUCTION,
                user_prompt=user_prompt,
                response_schema=ORCHESTRATOR_RESPONSE_SCHEMA,
            )
        else:
            raise TypeError(f"Unsupported AI client type: {type(client)!r}")

        if isinstance(raw, str):
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise TypeError("Orchestrator response JSON root must be an object")
            return parsed, used_model
        if isinstance(raw, Mapping):
            return dict(raw), used_model
        raise TypeError(f"Unexpected orchestrator response type: {type(raw)!r}")

    def insights(
        self,
        analysis: AnalysisResponse,
        edges: Sequence[VerifiedEdge],
        *,
        cache_only: bool = False,
    ) -> tuple[list[MetricFact], Insights]:
        """Pipeline seam called by hoc.jobs: compute (metrics, Insights) for an AnalysisResponse."""
        return self.run(
            analysis.exposures,
            edges,
            holdings=analysis.request.holdings,
            etfs=analysis.etfs,
            cache_only=cache_only,
        )

    def run(
        self,
        exposures: Sequence[CompanyExposure],
        edges: Sequence[VerifiedEdge],
        *,
        holdings: Sequence[PortfolioItem] = (),
        etfs: Sequence[EtfReport] | Sequence[PortfolioItem] = (),
        cache_only: bool = False,
    ) -> tuple[list[MetricFact], Insights]:
        """Compute deterministic MetricFacts and verified Insights without raising."""
        edges = [
            e if e.importance is not None else attach_edge_importance([e])[0]
            for e in edges
        ]
        summary = compute_dependency_summary(exposures, edges)
        etf_context = etfs if etfs else holdings

        # 1. Empty verified edges -> immediate no_verified_edges status
        if not edges:
            return summary.metrics, Insights(
                status="no_verified_edges",
                model=None,
                suggestions=[],
                flaws=[],
                rejected_claims_count=0,
            )

        # 2. Check disk cache by (allocations, verified_edge_ids, prompt_version, model, exact prompt)
        user_prompt = build_user_prompt(exposures, edges, summary, etfs=etf_context)
        cache_key = compute_orchestrator_cache_key(
            exposures, edges, holdings=holdings, prompt_ver=self.prompt_version,
            model=self._orchestrator_model, user_prompt=user_prompt,
        )
        cached = self._read_cache(cache_key)
        if cached is not None:
            cached_insights = verify_and_build_insights(
                cached["raw_payload"],
                exposures=exposures,
                edges=edges,
                summary=summary,
                etfs=etf_context,
                status="ok",
                model=cached.get("model"),
            )
            return summary.metrics, cached_insights

        # 3. If cache_only or offline or missing API key
        api_key = self._resolve_api_key()
        is_offline = bool(self._settings and self._settings.offline) and self._ai_client is None
        client_missing_key = (
            self._ai_client is not None
            and hasattr(self._ai_client, "has_api_key")
            and not self._ai_client.has_api_key
        )
        has_transport = (
            (self._ai_client is not None and not client_missing_key)
            or (self._http_client is not None and bool(api_key))
        )

        if cache_only or is_offline or not has_transport:
            fallback_raw = build_deterministic_raw_claims(summary)
            fallback_status: InsightsStatus = (
                "missing_api_key"
                if (not api_key and not cache_only and (self._ai_client is None or client_missing_key))
                else "metrics_only"
            )
            fallback_insights = verify_and_build_insights(
                fallback_raw,
                exposures=exposures,
                edges=edges,
                summary=summary,
                etfs=etf_context,
                status=fallback_status,
                model=None,
            )
            return summary.metrics, fallback_insights

        # 4. Call AI client or HTTP client (with 429 fallback from Argon to Flash)
        chosen_model = self._orchestrator_model
        raw_payload: dict[str, Any] | None = None
        call_failed = False

        try:
            raw_payload, chosen_model = self._call_ai_client(chosen_model, user_prompt)
        except (
            GeminiQuotaError,
            GeminiError,
            SourceUnavailable,
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
            OSError,
        ) as exc:
            status_code = getattr(exc, "status_code", None)
            if (
                isinstance(exc, GeminiQuotaError)
                or status_code == 429
                or "429" in str(exc)
            ) and self._fallback_model != chosen_model:
                chosen_model = self._fallback_model
                try:
                    raw_payload, chosen_model = self._call_ai_client(chosen_model, user_prompt)
                except (
                    GeminiError,
                    SourceUnavailable,
                    RuntimeError,
                    ValueError,
                    TypeError,
                    KeyError,
                    OSError,
                ):
                    call_failed = True
            else:
                call_failed = True

        if call_failed or raw_payload is None:
            fallback_raw = build_deterministic_raw_claims(summary)
            err_insights = verify_and_build_insights(
                fallback_raw,
                exposures=exposures,
                edges=edges,
                summary=summary,
                etfs=etf_context,
                status="error",
                model=chosen_model,
            )
            return summary.metrics, err_insights

        # 5. Verify LLM claims
        verified = verify_and_build_insights(
            raw_payload,
            exposures=exposures,
            edges=edges,
            summary=summary,
            etfs=etf_context,
            status="ok",
            model=chosen_model,
        )

        if verified.flaws or verified.suggestions:
            self._write_cache(cache_key, model=chosen_model, raw_payload=raw_payload)
            return summary.metrics, verified

        # If every LLM claim was rejected, preserve rejected_claims_count and return metrics_only fallback
        rejected_from_llm = verified.rejected_claims_count
        fallback_raw = build_deterministic_raw_claims(summary)
        fallback_verified = verify_and_build_insights(
            fallback_raw,
            exposures=exposures,
            edges=edges,
            summary=summary,
            etfs=etf_context,
            status="metrics_only",
            model=chosen_model,
        )
        return summary.metrics, Insights(
            status="metrics_only",
            model=chosen_model,
            suggestions=fallback_verified.suggestions,
            flaws=fallback_verified.flaws,
            rejected_claims_count=rejected_from_llm,
        )


def insights(
    analysis: AnalysisResponse,
    edges: Sequence[VerifiedEdge],
    *,
    cache_only: bool = False,
    http: Any | None = None,
    settings: Settings | None = None,
    ai_client: OrchestratorAiClient | Any | None = None,
    cache_dir: Path | str | None = None,
) -> tuple[list[MetricFact], Insights]:
    """Top-level pipeline seam for G-ORCH (called by hoc.jobs)."""
    orch = DependencyOrchestrator(
        http=http,
        settings=settings,
        ai_client=ai_client,
        cache_dir=cache_dir,
    )
    return orch.insights(analysis, edges, cache_only=cache_only)
