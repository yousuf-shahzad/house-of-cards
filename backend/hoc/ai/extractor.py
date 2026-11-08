"""Per-company Gemini dependency extractor, reverse-link extractor, section packer, and I-API seam.

Owner: package G-AI / V-INT (Kendrick's Gemini).
Rules (docs/hoc/PLAN-v2.md, docs/hoc/PLAN-v3.md §5 & docs/hoc/CONTRACT.md §§7-8):
- One extraction call per company with sections packed up to 160,000 chars (`MAX_PACKED_CHARS`).
- Flat JSON schema (`EXTRACTION_SCHEMA`) with no `$ref` or `anyOf`.
- Every extracted edge is verified against the whole canonical filing text via `verify_quote`
  (using `hoc.filings.text.normalise`).
- Generic common nouns (e.g. 'contract manufacturers') are rejected as `target_kind == 'company'`.
- `edge.section` is set deterministically in Python from the `Filing.sections` span that contains
  the verified quote match (`'document'` when none), never from the model.
- Runs V-INT (`verify_company_interpretations`: 6 deterministic rules on quote ±300 chars + one
  independent Flash judge call `hoc-v3-judge-1` per company on flagged + 20% sampled unflagged edges)
  to set `VerifiedEdge.interpretation`, removing `rejected` interpretations and counting them in
  `Extraction.interpretation_rejected`.
- Produces frozen `hoc.contract.VerifiedEdge` models with `FilingRef` and `EdgeInterpretation`.
- Exposes `DependencyExtractor.extract(company, filing, *, cache_only: bool = False) -> Extraction`
  and `DependencyExtractor.extract_reverse(company, filings, *, cache_only: bool = False) -> Extraction`
  (capped at `MAX_REVERSE_HITS = 10` filings per company, keeping only edges whose target resolves
  deterministically to a top-N company, and deduplicating `edge_id` across forward and reverse).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Collection, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from hoc.ai.cache import ExtractionCache
from hoc.ai.client import (
    DEFAULT_EXTRACTOR_MODEL,
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_ORCHESTRATOR_MODEL,
    GeminiClient,
    GeminiError,
    GeminiMissingKeyError,
)
from hoc.ai.interpretation import verify_company_interpretations
from hoc.ai.verifier import (
    PROMPT_VERSION,
    find_quote_span,
    is_generic_company_target,
    normalise_for_verify,
    resolve_quote_section,
    verify_quote,
)
from hoc.contract import (
    CompanyRunStatus,
    CompanyUnavailable,
    FilingRef,
    VerifiedEdge,
)
from hoc.contract.dependencies import CompanyStatus, EdgeType, FilingForm, TargetKind

MAX_PACKED_CHARS = 160_000
MAX_REVERSE_HITS = 10

EDGE_TYPES: tuple[EdgeType, ...] = (
    "supplier",
    "customer",
    "contract_manufacturer",
    "foundry",
    "key_input",
    "facility",
    "jv_partner",
)

TARGET_KINDS: tuple[TargetKind, ...] = (
    "company",
    "country",
    "region",
    "material",
    "component",
    "facility",
    "unnamed_customer",
)

_EDGE_TYPE_ALIASES: dict[str, EdgeType] = {
    "supplier_of": "supplier",
    "customer_of": "customer",
    "facility_in": "facility",
    "sole_source": "supplier",
}

EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "edge_type": {
                        "type": "string",
                        "enum": list(EDGE_TYPES),
                    },
                    "target_name": {"type": "string"},
                    "target_kind": {
                        "type": "string",
                        "enum": list(TARGET_KINDS),
                    },
                    "sole_source": {"type": "boolean"},
                    "qualifier": {"type": "string"},
                    "section": {"type": "string"},
                    "evidence_quote": {"type": "string"},
                },
                "required": [
                    "edge_type",
                    "target_name",
                    "target_kind",
                    "sole_source",
                    "qualifier",
                    "section",
                    "evidence_quote",
                ],
            },
        }
    },
    "required": ["edges"],
}

EXTRACTOR_SYSTEM_INSTRUCTION = (
    "You are a financial supply-chain and dependency extraction sub-agent analyzing SEC Form 10-K "
    "and Form 20-F filings. Extract only factual supply-chain, customer, foundry, contract-manufacturing, "
    "key-input, joint-venture, and physical facility dependencies explicitly stated in the filing text.\n"
    "CRITICAL RULES:\n"
    "1. Every edge MUST include an `evidence_quote` (30 to 300 characters) copied VERBATIM from the filing text.\n"
    "2. Do NOT paraphrase, summarize, or invent words inside `evidence_quote`. Copy a single contiguous clause "
    "or sentence directly from the text. Never use `...` unless bridging two clauses within 300 characters where "
    "both halves are at least 25 characters long.\n"
    "3. The `target_name` (or customer revenue percentage for `unnamed_customer`) MUST appear inside `evidence_quote`.\n"
    "4. Set `sole_source` to true ONLY when the quote explicitly describes a sole, single, or exclusive source.\n"
    "5. If a major customer is anonymous (e.g. 'one customer accounted for 22% of revenue'), set `target_kind` to "
    "`unnamed_customer`, `target_name` to 'Unnamed Customer', and `qualifier` to the percentage (e.g. '22% of revenue').\n"
    "6. For `target_kind` = `company`, extract ONLY specific named companies or corporate brands (e.g. 'TSMC', "
    "'Foxconn', 'SK Hynix'). NEVER extract generic common nouns or categories like 'contract manufacturers', "
    "'third-party suppliers', or 'wafer foundries' as `company`."
)

_SECTION_PRIORITY: tuple[str, ...] = (
    "1",
    "item 1",
    "4",
    "item 4",
    "2",
    "item 2",
    "5",
    "item 5",
    "concentration",
    "1a",
    "item 1a",
    "3d",
    "item 3.d",
    "3",
    "item 3",
    "reverse_links",
    "document",
)

_CORP_SUFFIX_RE = re.compile(
    r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|llc|plc|nv|n\.v\.|se|ag|sa|holdings|holding|group|the)\b\.?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Extraction:
    """Return value of `DependencyExtractor.extract` and `extract_reverse` for I-API."""

    edges: list[VerifiedEdge]
    rejected: int = 0
    interpretation_rejected: int = 0
    quality: Literal["sections", "fallback"] | None = "sections"
    cached: bool = False
    model: str | None = None


@dataclass(frozen=True)
class CompanyExtractionOutcome:
    """Full outcome of extracting dependencies for a single company."""

    company_key: str
    company_name: str
    status: CompanyStatus
    edges: list[VerifiedEdge] = field(default_factory=list)
    verified_count: int = 0
    rejected_count: int = 0
    interpretation_rejected_count: int = 0
    model: str | None = None
    from_cache: bool = False
    filing: FilingRef | None = None
    extraction_quality: Literal["sections", "fallback"] | None = None
    error_message: str | None = None

    def to_run_status(self, exposure: float = 0.0) -> CompanyRunStatus:
        return CompanyRunStatus(
            company_key=self.company_key,
            company_name=self.company_name,
            exposure=exposure,
            status=self.status,
            extraction_quality=self.extraction_quality,
            filing=self.filing,
            verified_edges=self.verified_count,
            rejected_edges=self.rejected_count,
            message=self.error_message,
        )


def make_edge_id(
    accession: str,
    evidence_quote: str,
    edge_type: str,
    target_name: str,
) -> str:
    """Stable id: hash of filing accession + normalised quote + edge type + target (CONTRACT.md)."""
    norm_quote = normalise_for_verify(evidence_quote).casefold()
    norm_target = normalise_for_verify(target_name).casefold()
    raw = f"{accession.strip()}|{norm_quote}|{edge_type.strip()}|{norm_target}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"edge_{digest}"


def dedupe_edges(*edge_iterables: Iterable[VerifiedEdge]) -> list[VerifiedEdge]:
    """Deduplicate `VerifiedEdge` items across forward and reverse passes by `edge_id`."""
    by_id: dict[str, VerifiedEdge] = {}
    for iterable in edge_iterables:
        for edge in iterable:
            existing = by_id.get(edge.edge_id)
            if existing is None or (edge.sole_source and not existing.sole_source):
                by_id[edge.edge_id] = edge
    return list(by_id.values())


def _section_rank(sec_name: str) -> tuple[int, str]:
    cleaned = sec_name.strip().lower()
    for i, p in enumerate(_SECTION_PRIORITY):
        if cleaned == p:
            return (i, sec_name)
    for i, p in enumerate(_SECTION_PRIORITY):
        if len(p) >= 4 and p in cleaned and not (p == "item 1" and "1a" in cleaned):
            return (i, sec_name)
    return (99, sec_name)


def pack_filing_sections(
    canonical_text: str,
    sections: Mapping[str, tuple[int, int] | str] | None = None,
    *,
    extra_snippets: Iterable[tuple[str, str]] | None = None,
    max_chars: int = MAX_PACKED_CHARS,
) -> str:
    """Pack extracted filing sections into a single prompt string up to `max_chars` (160K chars)."""
    if not canonical_text and not sections and not extra_snippets:
        return ""

    blocks: list[str] = []
    used = 0

    if sections:
        ordered_keys = sorted(sections.keys(), key=_section_rank)
        for sec_name in ordered_keys:
            val = sections[sec_name]
            if isinstance(val, tuple) and len(val) == 2:
                start, end = int(val[0]), int(val[1])
                sec_text = canonical_text[max(0, start) : max(0, end)].strip()
            elif isinstance(val, str):
                sec_text = val.strip()
            else:
                continue
            if not sec_text:
                continue
            header = f"[SECTION: {sec_name}]\n"
            remaining = max_chars - used - len(header) - 2
            if remaining <= 0:
                break
            clipped = sec_text[:remaining]
            block = f"{header}{clipped}\n\n"
            blocks.append(block)
            used += len(block)

    if extra_snippets:
        for label, snippet in extra_snippets:
            snip = snippet.strip()
            if not snip:
                continue
            header = f"[SECTION: {label}]\n"
            remaining = max_chars - used - len(header) - 2
            if remaining <= 0:
                break
            block = f"{header}{snip[:remaining]}\n\n"
            blocks.append(block)
            used += len(block)

    if not blocks and canonical_text:
        header = "[SECTION: Full Filing]\n"
        remaining = max(0, max_chars - len(header))
        return f"{header}{canonical_text[:remaining].strip()}"

    return "".join(blocks).strip()


def build_extraction_prompt(
    *,
    company_key: str,
    company_name: str,
    form: str,
    filed: str,
    packed_sections: str,
) -> str:
    return (
        f"COMPANY: {company_name} ({company_key})\n"
        f"FILING: SEC Form {form} (filed {filed})\n\n"
        "Extract all verifiable suppliers, customers, contract manufacturers, foundries, "
        "key physical inputs/components, joint-venture partners, and manufacturing/facility "
        "locations from the filing sections below. Every edge must include a verbatim "
        "`evidence_quote` copied directly from the text.\n\n"
        f"FILING TEXT:\n{packed_sections}"
    )


def _normalise_edge_type(raw_type: str, sole_source: bool) -> tuple[EdgeType, bool]:
    cleaned = raw_type.strip().lower()
    if cleaned == "sole_source":
        return "supplier", True
    mapped = _EDGE_TYPE_ALIASES.get(cleaned, cleaned)
    if mapped not in EDGE_TYPES:
        return "supplier", bool(sole_source)
    return mapped, bool(sole_source)  # type: ignore[return-value]


def _normalise_target_kind(raw_kind: str, edge_type: EdgeType) -> TargetKind:
    cleaned = raw_kind.strip().lower()
    if cleaned in TARGET_KINDS:
        return cleaned  # type: ignore[return-value]
    if edge_type == "facility":
        return "country"
    if edge_type == "key_input":
        return "component"
    return "company"


def _parse_date(val: date | str | None) -> date:
    if isinstance(val, date):
        return val
    if isinstance(val, str) and val.strip():
        try:
            return date.fromisoformat(val.strip()[:10])
        except ValueError:
            pass
    return date(2026, 1, 1)


def _parse_form(val: str | None) -> FilingForm:
    cleaned = (val or "10-K").strip().upper()
    return "20-F" if "20-F" in cleaned else "10-K"


def _clean_corp_name(name: str) -> str:
    norm = normalise_for_verify(name).casefold()
    stripped = _CORP_SUFFIX_RE.sub(" ", norm)
    cleaned = re.sub(r"[^a-z0-9]+", " ", stripped).strip()
    return re.sub(r"\s+", " ", cleaned)


def verify_and_build_edges(
    raw_edges: Iterable[Mapping[str, Any]],
    *,
    source_company_key: str,
    source_company_name: str,
    source_in_portfolio: bool = True,
    canonical_text: str,
    filing_ref: FilingRef,
    sections: Mapping[str, tuple[int, int] | str] | None = None,
    portfolio_company_keys: Collection[str] | None = None,
    resolve_target_key: Callable[[str], str | None] | None = None,
) -> tuple[list[VerifiedEdge], int]:
    """Verify raw LLM edges against `canonical_text` and deduplicate verified `VerifiedEdge` models.

    - Rejects unverified quotes and generic common-noun targets (`target_kind == 'company'`).
    - Sets `edge.section` deterministically in Python from the `Filing.sections` span that
      contains the quote match (`'document'` when none), never from the model.

    Returns `(verified_edges, rejected_count)`.
    """
    norm_doc = normalise_for_verify(canonical_text)
    portfolio_set = set(portfolio_company_keys) if portfolio_company_keys is not None else None
    verified: list[VerifiedEdge] = []
    seen_keys: dict[tuple[str, str, str], int] = {}
    rejected_count = 0

    for item in raw_edges:
        if not isinstance(item, Mapping):
            rejected_count += 1
            continue
        raw_target = str(item.get("target_name") or item.get("object_name_as_written") or "").strip()
        raw_quote = str(item.get("evidence_quote") or "").strip()
        raw_type = str(item.get("edge_type") or item.get("predicate") or "").strip()
        raw_kind = str(item.get("target_kind") or item.get("object_kind") or "").strip()
        raw_sole = bool(item.get("sole_source", False))
        raw_qualifier = str(item.get("qualifier") or "").strip()

        if not raw_target or not raw_quote or not raw_type:
            rejected_count += 1
            continue

        edge_type, sole_source = _normalise_edge_type(raw_type, raw_sole)
        target_kind = _normalise_target_kind(raw_kind, edge_type)

        if target_kind == "company" and is_generic_company_target(raw_target, raw_quote):
            rejected_count += 1
            continue

        if not verify_quote(
            raw_quote,
            norm_doc,
            target_name=raw_target,
            target_kind=target_kind,
            qualifier=raw_qualifier,
            already_normalised_doc=True,
        ):
            rejected_count += 1
            continue

        match_span = find_quote_span(raw_quote, norm_doc, already_normalised_doc=True)
        resolved_section = resolve_quote_section(
            raw_quote,
            canonical_text,
            sections,
            match_span=match_span,
            already_normalised_doc=(len(norm_doc) == len(canonical_text)),
        )

        target_key: str | None = None
        if target_kind == "company" and resolve_target_key is not None:
            resolved = resolve_target_key(raw_target)
            if isinstance(resolved, str) and resolved.strip():
                candidate_key = resolved.strip()
                if candidate_key == source_company_key:
                    rejected_count += 1
                    continue
                if not candidate_key.startswith("NAME:"):
                    target_key = candidate_key

        target_in_portfolio = bool(
            target_key is not None and portfolio_set is not None and target_key in portfolio_set
        )
        norm_quote_clean = normalise_for_verify(raw_quote)
        edge_id = make_edge_id(filing_ref.accession, norm_quote_clean, edge_type, raw_target)
        record = VerifiedEdge(
            edge_id=edge_id,
            source_company_key=source_company_key,
            source_company_name=source_company_name,
            source_in_portfolio=source_in_portfolio,
            edge_type=edge_type,
            target_name=raw_target,
            target_kind=target_kind,
            target_key=target_key,
            target_in_portfolio=target_in_portfolio,
            sole_source=sole_source,
            qualifier=raw_qualifier or None,
            evidence_quote=norm_quote_clean,
            section=resolved_section,
            filing=filing_ref,
        )

        dedup_key = (
            source_company_key,
            edge_type,
            target_key or normalise_for_verify(raw_target).casefold(),
        )
        if dedup_key in seen_keys:
            idx = seen_keys[dedup_key]
            existing = verified[idx]
            if sole_source and not existing.sole_source:
                verified[idx] = record
            continue

        seen_keys[dedup_key] = len(verified)
        verified.append(record)

    return verified, rejected_count


def _coerce_company(company: Any) -> tuple[str, str]:
    if isinstance(company, tuple) and len(company) >= 2:
        return str(company[0]), str(company[1])
    if isinstance(company, Mapping):
        k = str(company.get("company_key") or company.get("key") or "")
        n = str(company.get("company_name") or company.get("name") or k)
        return k, n
    if isinstance(company, str):
        return company, company
    k = str(getattr(company, "company_key", ""))
    n = str(getattr(company, "company_name", k))
    return k, n


def _coerce_reverse_filer(hit: Any) -> tuple[str, str, Any]:
    """Extract `(source_company_key, source_company_name, filing_obj)` from a reverse-link hit."""
    if isinstance(hit, tuple) and len(hit) >= 2:
        if len(hit) == 2:
            company, filing = hit
            k, n = _coerce_company(company)
            return k, n, filing
        return str(hit[0]), str(hit[1]), hit[2]
    if isinstance(hit, Mapping):
        filing_obj = hit.get("filing", hit)
        cik = str(hit.get("cik") or getattr(filing_obj, "cik", "") or "").strip()
        k = str(hit.get("company_key") or (f"CIK:{cik.zfill(10)}" if cik.isdigit() else cik) or "")
        n = str(
            hit.get("company_name")
            or hit.get("filer_name")
            or hit.get("entity_name")
            or hit.get("name")
            or getattr(filing_obj, "company_name", None)
            or getattr(filing_obj, "filer_name", None)
            or k
        )
        return k, n, filing_obj

    cik = str(getattr(hit, "cik", "") or "").strip()
    k = str(
        getattr(hit, "company_key", None)
        or (f"CIK:{cik.zfill(10)}" if cik.isdigit() else cik)
        or ""
    )
    n = str(
        getattr(hit, "company_name", None)
        or getattr(hit, "filer_name", None)
        or getattr(hit, "entity_name", None)
        or getattr(hit, "name", None)
        or k
    )
    return k, n, hit


class DependencyExtractor:
    """High-level per-company, reverse-link, and multi-company dependency extractor with disk caching."""

    prompt_version: str = PROMPT_VERSION

    def __init__(
        self,
        client: GeminiClient | Any,
        cache: ExtractionCache | None = None,
        *,
        filing_fetcher: Any = None,
        prompt_version: str = PROMPT_VERSION,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        resolve_target_key: Callable[[str], str | None] | None = None,
        portfolio_company_keys: Collection[str] | None = None,
    ) -> None:
        self.client = client
        self.cache = cache
        self.filing_fetcher = filing_fetcher
        self.prompt_version = prompt_version
        self.max_concurrency = max(1, int(max_concurrency))
        self.resolve_target_key = resolve_target_key
        self.portfolio_company_keys = set(portfolio_company_keys) if portfolio_company_keys else None

    def extract(
        self,
        company: Any,
        filing: Any,
        *,
        cache_only: bool = False,
        canonical_text: str | None = None,
        sections: Mapping[str, tuple[int, int] | str] | None = None,
        extraction_quality: Literal["sections", "fallback"] | None = None,
        portfolio_company_keys: Collection[str] | None = None,
        resolve_target_key: Callable[[str], str | None] | None = None,
    ) -> Extraction:
        """I-API pipeline seam: extract verified edges for `(company, filing)`.

        Returns `Extraction(edges, rejected, interpretation_rejected, quality, cached, model)`.
        Raises `hoc.contract.CompanyUnavailable(status, message)` when:
        - `filing` indicates an unavailable status (`no_sec_filing`, `unsupported_form`, `sec_contact_missing`)
        - `cache_only=True` and the filing is not cached (`missing_api_key`)
        - uncached and `not client.has_api_key` (`missing_api_key`)
        - Gemini call fails (`error`)
        """
        company_key, company_name = _coerce_company(company)
        outcome = self.extract_company(
            company_key=company_key,
            company_name=company_name,
            company_obj=company,
            filing=filing,
            canonical_text=canonical_text,
            sections=sections,
            extraction_quality=extraction_quality,
            cache_only=cache_only,
            portfolio_company_keys=portfolio_company_keys,
            resolve_target_key=resolve_target_key,
        )
        if outcome.status not in {"done", "cached"}:
            raise CompanyUnavailable(
                outcome.status,
                outcome.error_message or f"Extraction unavailable for {company_key}: {outcome.status}",
            )
        quality: Literal["sections", "fallback"] = outcome.extraction_quality or "sections"
        return Extraction(
            edges=outcome.edges,
            rejected=outcome.rejected_count,
            interpretation_rejected=outcome.interpretation_rejected_count,
            quality=quality,
            cached=outcome.from_cache,
            model=outcome.model,
        )

    def extract_reverse(
        self,
        company: Any,
        filings: Iterable[Any],
        *,
        cache_only: bool = False,
        top_n_company_keys: Collection[str] | None = None,
        resolve_target_key: Callable[[str], str | None] | None = None,
    ) -> Extraction:
        """Extract reverse-link edges from other filers' sections (`names_in_other_filings` hits).

        - Caps hits per company at `MAX_REVERSE_HITS` (10).
        - Runs the same extractor + quote verifier + V-INT interpretation verifier over each other
          filer's sections (reusing `ExtractionCache` keyed by `(other_company_key, accession, model, prompt_version)`
          so filers already extracted in the forward pass cost 0 extra Gemini calls).
        - Keeps ONLY verified edges whose `target_key` resolves deterministically to a top-N
          portfolio company (`top_n_company_keys` / `portfolio_company_keys` / `company.company_key`).
        - Deduplicates `edge_id` across all hits.
        """
        target_key, target_name = _coerce_company(company)
        target_clean = _clean_corp_name(target_name)
        target_symbols = {
            str(s).strip().upper()
            for s in (getattr(company, "symbols", None) or ())
            if str(s).strip()
        }
        allowed_targets: set[str] = set(
            top_n_company_keys
            if top_n_company_keys is not None
            else (self.portfolio_company_keys or ())
        )
        if target_key:
            allowed_targets.add(target_key)

        base_resolver = resolve_target_key or self.resolve_target_key

        def _reverse_resolver(raw_name: str) -> str | None:
            if base_resolver is not None:
                resolved = base_resolver(raw_name)
                if isinstance(resolved, str) and resolved.strip() and not resolved.strip().startswith("NAME:"):
                    return resolved.strip()
            cleaned = _clean_corp_name(raw_name)
            if cleaned and target_clean and cleaned == target_clean:
                return target_key
            if raw_name.strip().upper() in target_symbols:
                return target_key
            return None

        hits = list(filings)[:MAX_REVERSE_HITS]
        if not hits:
            return Extraction(edges=[], rejected=0, interpretation_rejected=0, quality="sections", cached=True)

        kept_by_id: dict[str, VerifiedEdge] = {}
        total_rejected = 0
        total_interp_rejected = 0
        all_cached = True
        any_fallback = False
        any_processed = False
        missing_key_seen = False
        last_model: str | None = None

        for hit in hits:
            other_key, other_name, filing_obj = _coerce_reverse_filer(hit)
            if not other_key or other_key == target_key:
                continue
            other_in_portfolio = bool(
                self.portfolio_company_keys is not None and other_key in self.portfolio_company_keys
            )
            outcome = self.extract_company(
                company_key=other_key,
                company_name=other_name,
                filing=filing_obj,
                cache_only=cache_only,
                source_in_portfolio=other_in_portfolio,
                portfolio_company_keys=allowed_targets,
                resolve_target_key=_reverse_resolver,
            )
            if outcome.status == "missing_api_key":
                missing_key_seen = True
                continue
            if outcome.status not in {"done", "cached"}:
                continue

            any_processed = True
            if not outcome.from_cache:
                all_cached = False
            if outcome.extraction_quality == "fallback":
                any_fallback = True
            if outcome.model:
                last_model = outcome.model
            total_rejected += outcome.rejected_count
            total_interp_rejected += outcome.interpretation_rejected_count

            for edge in outcome.edges:
                if edge.target_key is not None and edge.target_key in allowed_targets:
                    updated_edge = (
                        edge
                        if edge.target_in_portfolio
                        else edge.model_copy(update={"target_in_portfolio": True})
                    )
                    existing = kept_by_id.get(updated_edge.edge_id)
                    if existing is None or (updated_edge.sole_source and not existing.sole_source):
                        kept_by_id[updated_edge.edge_id] = updated_edge

        if not any_processed and missing_key_seen:
            raise CompanyUnavailable(
                "missing_api_key",
                f"GEMINI_API_KEY is not set and reverse filings for {target_key} are not cached.",
            )

        quality: Literal["sections", "fallback"] = "fallback" if any_fallback else "sections"
        return Extraction(
            edges=list(kept_by_id.values()),
            rejected=total_rejected,
            interpretation_rejected=total_interp_rejected,
            quality=quality,
            cached=all_cached if any_processed else True,
            model=last_model,
        )

    def extract_company(
        self,
        *,
        company_key: str,
        company_name: str,
        company_obj: Any = None,
        filing: Any = None,
        canonical_text: str | None = None,
        sections: Mapping[str, tuple[int, int] | str] | None = None,
        form: str | None = None,
        accession: str | None = None,
        filed: date | str | None = None,
        filing_url: str | None = None,
        extraction_quality: Literal["sections", "fallback"] | None = None,
        filing_status: CompanyStatus | None = None,
        extra_snippets: Iterable[tuple[str, str]] | None = None,
        cache_only: bool = False,
        source_in_portfolio: bool = True,
        portfolio_company_keys: Collection[str] | None = None,
        resolve_target_key: Callable[[str], str | None] | None = None,
    ) -> CompanyExtractionOutcome:
        """Extract and verify dependencies for a single company's filing without raising."""
        if filing is not None:
            filing_status = filing_status or getattr(filing, "status", None)
            canonical_text = (
                canonical_text
                if canonical_text is not None
                else (getattr(filing, "text", None) or getattr(filing, "canonical_text", None))
            )
            sections = sections if sections is not None else getattr(filing, "sections", None)
            ref = getattr(filing, "ref", None) or (filing if isinstance(filing, FilingRef) else None)
            form = form or getattr(filing, "form", None) or (getattr(ref, "form", None) if ref else None)
            accession = (
                accession
                or getattr(filing, "accession", None)
                or (getattr(ref, "accession", None) if ref else None)
            )
            filed = (
                filed
                if filed is not None
                else (getattr(filing, "filed", None) or (getattr(ref, "filed", None) if ref else None))
            )
            filing_url = (
                filing_url
                or getattr(filing, "url", None)
                or getattr(filing, "filing_url", None)
                or (getattr(ref, "url", None) if ref else None)
            )
            extraction_quality = (
                extraction_quality
                or getattr(filing, "quality", None)
                or getattr(filing, "extraction_quality", None)
            )

        # If a FilingRef (without .text) was passed and we have a shared FilingFetcher, look up the full Filing
        acc = (accession or "").strip()
        if not canonical_text and self.filing_fetcher is not None and acc:
            memo = getattr(self.filing_fetcher, "_memo", None)
            full_filing = memo.get(acc) if isinstance(memo, Mapping) else None
            if full_filing is None and company_obj is not None and hasattr(self.filing_fetcher, "for_company"):
                try:
                    full_filing = self.filing_fetcher.for_company(company_obj)
                except CompanyUnavailable as exc:
                    return CompanyExtractionOutcome(
                        company_key=company_key,
                        company_name=company_name,
                        status=exc.status,
                        error_message=exc.message,
                    )
            if full_filing is not None:
                canonical_text = getattr(full_filing, "text", None) or getattr(full_filing, "canonical_text", None)
                sections = sections if sections is not None else getattr(full_filing, "sections", None)
                extraction_quality = (
                    extraction_quality
                    or getattr(full_filing, "quality", None)
                    or getattr(full_filing, "extraction_quality", None)
                )

        quality: Literal["sections", "fallback"] = (
            "fallback" if extraction_quality == "fallback" else "sections"
        )

        if filing_status in {"no_sec_filing", "unsupported_form", "sec_contact_missing", "error"}:
            return CompanyExtractionOutcome(
                company_key=company_key,
                company_name=company_name,
                status=filing_status,
                extraction_quality=extraction_quality,
                error_message=f"Filing unavailable: {filing_status}",
            )

        text = (canonical_text or "").strip()
        form_typed = _parse_form(form)
        filed_date = _parse_date(filed)
        url_str = (filing_url or f"https://www.sec.gov/Archives/edgar/data/{acc}").strip()
        resolver = resolve_target_key or self.resolve_target_key
        portfolio_keys = portfolio_company_keys if portfolio_company_keys is not None else self.portfolio_company_keys
        model_name = getattr(self.client, "extractor_model", DEFAULT_EXTRACTOR_MODEL)

        if not acc:
            return CompanyExtractionOutcome(
                company_key=company_key,
                company_name=company_name,
                status="no_sec_filing",
                extraction_quality=extraction_quality,
                error_message="No SEC 10-K or 20-F filing accession available.",
            )

        filing_ref = FilingRef(
            company_key=company_key,
            form=form_typed,
            accession=acc,
            filed=filed_date,
            url=url_str,
        )

        # 1. Check disk cache first (supports keyless warm replay & cache_only=True)
        if self.cache is not None:
            cached = self.cache.get_any_model(
                company_key,
                acc,
                models=(model_name, DEFAULT_EXTRACTOR_MODEL, DEFAULT_ORCHESTRATOR_MODEL),
                prompt_version=self.prompt_version,
            )
            if cached is not None:
                raw_edges = cached.get("raw_edges")
                if not isinstance(raw_edges, list):
                    raw_edges = cached.get("edges")
                if isinstance(raw_edges, list) and text:
                    quote_verified, rejected = verify_and_build_edges(
                        raw_edges,
                        source_company_key=company_key,
                        source_company_name=company_name,
                        source_in_portfolio=source_in_portfolio,
                        canonical_text=text,
                        filing_ref=filing_ref,
                        sections=sections,
                        portfolio_company_keys=portfolio_keys,
                        resolve_target_key=resolver,
                    )
                    interp_res = verify_company_interpretations(
                        quote_verified,
                        text,
                        client=self.client,
                        cache=self.cache,
                        cache_only=cache_only,
                        is_reverse=not source_in_portfolio,
                    )
                    verified = interp_res.edges
                    interp_rejected = interp_res.interpretation_rejected
                else:
                    loaded_edges = [
                        VerifiedEdge.model_validate(edge_dict)
                        for edge_dict in cached.get("edges", [])
                        if isinstance(edge_dict, Mapping)
                    ]
                    rejected = int(cached.get("rejected_count", 0))
                    if loaded_edges and all(e.interpretation is not None for e in loaded_edges):
                        verified = loaded_edges
                        interp_rejected = int(cached.get("interpretation_rejected_count", 0))
                    else:
                        interp_res = verify_company_interpretations(
                            loaded_edges,
                            text,
                            client=self.client,
                            cache=self.cache,
                            cache_only=cache_only,
                            is_reverse=not source_in_portfolio,
                        )
                        verified = interp_res.edges
                        interp_rejected = interp_res.interpretation_rejected
                return CompanyExtractionOutcome(
                    company_key=company_key,
                    company_name=company_name,
                    status="cached",
                    edges=verified,
                    verified_count=len(verified),
                    rejected_count=rejected,
                    interpretation_rejected_count=interp_rejected,
                    model=str(cached.get("model") or model_name),
                    from_cache=True,
                    filing=filing_ref,
                    extraction_quality=quality,
                )

        if not text:
            return CompanyExtractionOutcome(
                company_key=company_key,
                company_name=company_name,
                status="no_sec_filing",
                filing=filing_ref,
                extraction_quality=extraction_quality,
                error_message="Filing text is empty.",
            )

        # 2. If cache_only=True or no API key is configured, return missing_api_key cleanly
        if cache_only or not getattr(self.client, "has_api_key", True):
            return CompanyExtractionOutcome(
                company_key=company_key,
                company_name=company_name,
                status="missing_api_key",
                filing=filing_ref,
                extraction_quality=quality,
                error_message="GEMINI_API_KEY is not set and no cached extraction is available for this filing.",
            )

        # 3. Pack filing sections up to 160K chars and call Gemini
        packed = pack_filing_sections(
            text,
            sections,
            extra_snippets=extra_snippets,
            max_chars=MAX_PACKED_CHARS,
        )
        prompt = build_extraction_prompt(
            company_key=company_key,
            company_name=company_name,
            form=form_typed,
            filed=filed_date.isoformat(),
            packed_sections=packed,
        )

        try:
            response_json, used_model = self.client.generate_json(
                prompt,
                EXTRACTION_SCHEMA,
                model=model_name,
                system_instruction=EXTRACTOR_SYSTEM_INSTRUCTION,
                thinking_level="low",
            )
        except GeminiMissingKeyError as exc:
            return CompanyExtractionOutcome(
                company_key=company_key,
                company_name=company_name,
                status="missing_api_key",
                filing=filing_ref,
                extraction_quality=quality,
                error_message=str(exc),
            )
        except GeminiError as exc:
            return CompanyExtractionOutcome(
                company_key=company_key,
                company_name=company_name,
                status="error",
                filing=filing_ref,
                extraction_quality=quality,
                error_message=str(exc),
            )

        raw_edges_list = response_json.get("edges", []) if isinstance(response_json, Mapping) else []
        if not isinstance(raw_edges_list, list):
            raw_edges_list = []

        quote_verified, rejected = verify_and_build_edges(
            raw_edges_list,
            source_company_key=company_key,
            source_company_name=company_name,
            source_in_portfolio=source_in_portfolio,
            canonical_text=text,
            filing_ref=filing_ref,
            sections=sections,
            portfolio_company_keys=portfolio_keys,
            resolve_target_key=resolver,
        )

        interp_res = verify_company_interpretations(
            quote_verified,
            text,
            client=self.client,
            cache=self.cache,
            cache_only=cache_only,
            is_reverse=not source_in_portfolio,
        )
        verified = interp_res.edges
        interp_rejected = interp_res.interpretation_rejected

        if self.cache is not None:
            self.cache.put(
                company_key,
                acc,
                model=used_model,
                prompt_version=self.prompt_version,
                payload={
                    "company_key": company_key,
                    "company_name": company_name,
                    "accession": acc,
                    "form": form_typed,
                    "filed": filed_date.isoformat(),
                    "filing_url": url_str,
                    "model": used_model,
                    "prompt_version": self.prompt_version,
                    "raw_edges": raw_edges_list,
                    "edges": [e.model_dump(mode="json") for e in verified],
                    "verified_count": len(verified),
                    "rejected_count": rejected,
                    "interpretation_rejected_count": interp_rejected,
                },
            )

        return CompanyExtractionOutcome(
            company_key=company_key,
            company_name=company_name,
            status="done",
            edges=verified,
            verified_count=len(verified),
            rejected_count=rejected,
            interpretation_rejected_count=interp_rejected,
            model=used_model,
            from_cache=False,
            filing=filing_ref,
            extraction_quality=quality,
        )

    def extract_many(
        self,
        items: Iterable[Mapping[str, Any]],
        *,
        on_progress: Callable[[CompanyExtractionOutcome], None] | None = None,
    ) -> list[CompanyExtractionOutcome]:
        """Extract dependencies across multiple companies concurrently (capped at `max_concurrency`)."""
        item_list = list(items)
        if not item_list:
            return []

        results: list[CompanyExtractionOutcome | None] = [None] * len(item_list)

        def _worker(idx: int, kwargs: Mapping[str, Any]) -> tuple[int, CompanyExtractionOutcome]:
            try:
                outcome = self.extract_company(**kwargs)
            except Exception as exc:  # noqa: BLE001
                outcome = CompanyExtractionOutcome(
                    company_key=str(kwargs.get("company_key", "")),
                    company_name=str(kwargs.get("company_name", "")),
                    status="error",
                    error_message=f"{type(exc).__name__}: {exc}",
                )
            return idx, outcome

        with ThreadPoolExecutor(max_workers=min(self.max_concurrency, len(item_list))) as pool:
            futures = [pool.submit(_worker, i, item) for i, item in enumerate(item_list)]
            for fut in as_completed(futures):
                idx, outcome = fut.result()
                results[idx] = outcome
                if on_progress is not None:
                    on_progress(outcome)

        return [r for r in results if r is not None]
