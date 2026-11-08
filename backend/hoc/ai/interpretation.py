"""Package V-INT: Interpretation verification (rules layer on quote ±300 chars + independent Flash judge).

Owner: Kendrick's Gemini (`@kendricklow2008 (Gemini)`).
Spec (`docs/hoc/PLAN-v3.md` §5 & `docs/hoc/CONTRACT.md` §8):
- `VerifiedEdge.interpretation = EdgeInterpretation{status, method, flags, reason, model}`,
  set in `backend/hoc/ai/` after `verify_quote` (before `R-IMP` scores importance).
- **Rules first.** Run on the quote plus ~300 characters of context on each side from `Filing.text`.
  Flags:
  - `competitor_mention` (compete, competitor(s), rival — in the same sentence as the target name or reverse-link subject)
  - `negated` (not, no, never, without, nor, or "do not rely" in the clause/sentence that names the target)
  - `hypothetical` (if, could, may, might, would, with no factual verb)
  - `direction_mismatch` (supplier or customer patterns pointing the wrong way, e.g. "we sell to X" labelled supplier)
  - `generic_reference` (a target that is a class, not an entity)
  - `subject_mismatch` (reverse links: the filer is not the subject, or biographical/litigation mention)
- **Then an independent judge.** Handles every edge that the rules flag, plus a 20% sample of unflagged edges.
  - One Flash call per company, with a separate prompt (`hoc-v3-judge-1`) that never sees the extractor's output,
    only the quote, its context, and the claimed relationship.
  - Label is one of `supports`, `contradicts`, `competitor`, `unrelated`, or `unclear`.
- **Decision (Python):**
  - `supports` (with all flags cleared) -> `confirmed`
  - `contradicts`, `competitor`, or `unrelated` -> `rejected`: removed from `edges` and counted in
    `DependencyCounts.interpretation_rejected`
  - `unclear`, or any flag the judge did not clear -> `flagged`: kept, with a badge (`R-IMP` caps importance at `medium`).
- **Caching:** per edge, keyed on `(edge_id, model, "hoc-v3-judge-1")`.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from hoc.ai.cache import ExtractionCache
from hoc.ai.client import (
    DEFAULT_EXTRACTOR_MODEL,
    DEFAULT_ORCHESTRATOR_MODEL,
    GeminiError,
    GeminiMissingKeyError,
)
from hoc.ai.verifier import find_quote_span, is_generic_company_target, normalise_for_verify
from hoc.contract import EdgeInterpretation, VerifiedEdge
from hoc.contract.dependencies import InterpretationFlag

log = logging.getLogger("hoc.ai.interpretation")

JUDGE_PROMPT_VERSION = "hoc-v3-judge-1"
CONTEXT_WINDOW_CHARS = 300
DEFAULT_UNFLAGGED_SAMPLE_RATE = 0.20

InterpretationMethod = Literal["rules", "rules+model"]
JudgeLabel = Literal["supports", "contradicts", "competitor", "unrelated", "unclear"]

INTERPRETATION_FLAGS: tuple[InterpretationFlag, ...] = (
    "competitor_mention",
    "negated",
    "hypothetical",
    "direction_mismatch",
    "generic_reference",
    "subject_mismatch",
    "judge_unclear",
)

JUDGE_LABELS: tuple[JudgeLabel, ...] = (
    "supports",
    "contradicts",
    "competitor",
    "unrelated",
    "unclear",
)

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "edge_id": {"type": "string"},
                    "label": {
                        "type": "string",
                        "enum": list(JUDGE_LABELS),
                    },
                    "cleared_flags": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "reason": {"type": "string"},
                },
                "required": ["edge_id", "label", "cleared_flags", "reason"],
            },
        }
    },
    "required": ["verdicts"],
}

JUDGE_SYSTEM_INSTRUCTION = (
    "You are an independent financial filing verification judge (`hoc-v3-judge-1`).\n"
    "For each candidate item, you are given ONLY:\n"
    "1. The filer company name,\n"
    "2. A claimed supply-chain/customer/facility relationship,\n"
    "3. A verbatim quote from the filer's SEC Form 10-K or 20-F and ~300 characters of surrounding context,\n"
    "4. Any deterministic warning flags triggered by the rules layer.\n\n"
    "Classify each item with `label` in:\n"
    "- `supports`: The quote and context genuinely state that the claimed relationship holds in the stated direction.\n"
    "  Include in `cleared_flags` any rule flags that are false alarms in context.\n"
    "- `contradicts`: The quote negates the relationship (e.g. 'we do not rely on X', 'no single customer > 10%') "
    "or states the opposite direction (e.g. 'we sell to X' when X is claimed as a supplier).\n"
    "- `competitor`: The target is mentioned as a competitor or rival of the filer, not a supplier/customer/partner.\n"
    "- `unrelated`: The target is mentioned in a biography, board membership, litigation, or unrelated third-party context "
    "where the filer is not the subject of the claimed dependency.\n"
    "- `unclear`: The quote is purely hypothetical/conditional ('if we were to', 'could potentially') or ambiguous."
)

# ---------- Regexes for the 6 deterministic V-INT rules ----------

_COMPETITOR_RE = re.compile(
    r"\b(compete|competes|competing|competitor|competitors|rival|rivals)\b",
    re.IGNORECASE,
)

_NEGATION_CLAUSE_RE = re.compile(
    r"\b("
    r"do\s+not|does\s+not|did\s+not|don't|doesn't|didn't|cannot|can't|will\s+not|won't|"
    r"never|neither|nor|without|"
    r"not\s+(?:rely|depend|dependent|reliant|purchase|buy|sell|use|source|contract|manufacture|operate|have|material|significant)|"
    r"no\s+(?:single|one|individual|material|significant|direct|external|third[\-\s]party)?\s*"
    r"(?:supplier|suppliers|customer|customers|vendor|vendors|manufacturer|manufacturers|foundry|foundries|partner|partners|company|counterparty)|"
    r"no\s+longer|ceased\s+to|terminated\s+our"
    r")\b",
    re.IGNORECASE,
)

_HYPOTHETICAL_MODAL_RE = re.compile(
    r"\b(if|could|might|would|were\s+to|in\s+the\s+event|hypothetically|may(?!\s+\d{1,4}\b))\b",
    re.IGNORECASE,
)

_STRICT_HYPOTHETICAL_PHRASE_RE = re.compile(
    r"\b("
    r"if\s+we\s+were\s+to|were\s+we\s+to|if\s+we\s+choose\s+to|if\s+we\s+decide\s+to|"
    r"may\s+in\s+the\s+future\s+(?:seek|choose|decide|engage|partner|source|contract)|"
    r"could\s+potentially\s+(?:engage|partner|source|use|rely)|"
    r"would\s+have\s+to\s+find\s+alternative"
    r")\b",
    re.IGNORECASE,
)

_FACTUAL_VERB_RE = re.compile(
    r"\b("
    r"rely|relies|relied|depend|depends|depended|is|are|was|were|has|have|had|"
    r"manufacture|manufactures|manufactured|supply|supplies|supplied|"
    r"purchase|purchases|purchased|buy|buys|bought|sell|sells|sold|"
    r"operate|operates|operated|lease|leases|leased|own|owns|owned|located|"
    r"account|accounts|accounted|represent|represents|represented|"
    r"use|uses|used|contract|contracts|contracted|produce|produces|produced|"
    r"fabricate|fabricates|fabricated|assemble|assembles|assembled|"
    r"provide|provides|provided|partner|partners|partnered|source|sources|sourced|"
    r"obtain|obtains|obtained|procure|procures|procured|enter|entered|"
    r"launch|launches|launched|establish|established|engage|engages|engaged|utilize|utilizes|utilized"
    r")\b",
    re.IGNORECASE,
)

# Patterns indicating the target is a CUSTOMER (company sells to target / earns revenue from target)
_DOWNSTREAM_CUSTOMER_CUE_RE = re.compile(
    r"\b("
    r"we\s+sell\s+to|sold\s+to|sales\s+to|revenue\s+from|revenues\s+from|net\s+revenue\s+from|"
    r"our\s+(?:largest\s+|major\s+|principal\s+|primary\s+|key\s+|direct\s+)?customer(?:s)?\b|"
    r"customers\s+(?:include|such\s+as)|shipments\s+to|deliveries\s+to|we\s+supply\s+to|"
    r"accounted\s+for\s+(?:approximately\s+|more\s+than\s+)?\d{1,2}(?:\.\d+)?\s*%\s+of\s+(?:our\s+)?(?:total\s+|net\s+|consolidated\s+)?(?:revenue|revenues|sales)"
    r")\b",
    re.IGNORECASE,
)

# Patterns indicating the target is an UPSTREAM SUPPLIER / FOUNDRY / MAKER (company buys/sources from target)
_UPSTREAM_SUPPLIER_CUE_RE = re.compile(
    r"\b("
    r"we\s+purchase\s+(?:[\w\-]+\s+){0,4}from|purchased\s+(?:[\w\-]+\s+){0,4}from|"
    r"we\s+buy\s+(?:[\w\-]+\s+){0,4}from|bought\s+(?:[\w\-]+\s+){0,4}from|"
    r"we\s+source\s+(?:[\w\-]+\s+){0,4}from|sourced\s+(?:[\w\-]+\s+){0,4}from|"
    r"we\s+obtain\s+(?:[\w\-]+\s+){0,4}from|procured\s+from|"
    r"supplied\s+by|manufactured\s+by|fabricated\s+by|assembled\s+by|"
    r"our\s+(?:primary|principal|sole|single|key)?\s*(?:wafer\s+)?(?:supplier|suppliers|foundry|foundries|contract\s+manufacturer|vendor|subcontractor)|"
    r"(?:suppliers|foundries|vendors)\s+(?:include|such\s+as)"
    r")\b",
    re.IGNORECASE,
)

_GENERIC_NON_COMPANY_TARGETS = frozenset({
    "various countries", "foreign countries", "other countries", "multiple countries",
    "international locations", "various locations", "multiple regions", "certain regions",
    "other regions", "raw materials", "certain materials", "various materials",
    "components", "certain components", "various components", "electronic components",
    "facilities", "manufacturing facilities", "production facilities", "various facilities",
    "leased facilities", "offices", "warehouses", "data centers", "plants", "factories",
})

_BIOGRAPHICAL_OR_LITIGATION_RE = re.compile(
    r"\b("
    r"previously\s+served\s+as|formerly\s+served\s+as|prior\s+to\s+joining|joined\s+us\s+from|"
    r"served\s+on\s+the\s+board|board\s+of\s+directors\s+of|former\s+(?:executive|officer|president|vice\s+president|director)|"
    r"patent\s+infringement\s+(?:suit|action|litigation)|lawsuit\s+against|litigation\s+with"
    r")\b",
    re.IGNORECASE,
)

_FIRST_PERSON_FILER_RE = re.compile(
    r"\b(we|our|us|the\s+company|the\s+corporation|the\s+group|the\s+registrant)\b",
    re.IGNORECASE,
)

# Sentence boundary regex: splits on [.!?] followed by whitespace + uppercase/digit/quote (or end of string),
# while ignoring mid-sentence abbreviations like "Inc. and" (lowercase after period) or "Mr. Smith".
_SENTENCE_BOUNDARY_RE = re.compile(
    r"(?<!\bMr)(?<!\bMs)(?<!\bDr)(?<!\bNo)(?<!\bSt)(?<!\bvs)(?:[.!?](?:\s+(?=[A-Z0-9\"'\[])|$)|\n+)",
)


@dataclass(frozen=True)
class InterpretationResult:
    """Result of running V-INT across a company's quote-verified edges."""

    edges: list[VerifiedEdge]
    rejected_edges: list[VerifiedEdge] = field(default_factory=list)
    interpretation_rejected: int = 0
    sampled_edge_ids: list[str] = field(default_factory=list)
    flagged_edge_ids: list[str] = field(default_factory=list)
    interpretations: dict[str, EdgeInterpretation] = field(default_factory=dict)


def attach_edge_interpretation(
    edge: VerifiedEdge,
    interpretation: EdgeInterpretation,
) -> VerifiedEdge:
    """Attach `EdgeInterpretation` to `VerifiedEdge` (`R-IMP` reads `edge.interpretation` to cap importance)."""
    return edge.model_copy(update={"interpretation": interpretation})


def should_sample_unflagged_edge(
    edge_id: str,
    *,
    sample_rate: float = DEFAULT_UNFLAGGED_SAMPLE_RATE,
) -> bool:
    """Deterministic 20% audit sampling of unflagged edges based on `edge_id` hash."""
    if sample_rate <= 0.0:
        return False
    if sample_rate >= 1.0:
        return True
    bucket = int(hashlib.sha256(edge_id.encode("utf-8")).hexdigest()[:8], 16) % 1000
    return bucket < round(sample_rate * 1000)


def extract_quote_context(
    evidence_quote: str,
    canonical_text: str,
    *,
    match_span: tuple[int, int] | None = None,
    window_chars: int = CONTEXT_WINDOW_CHARS,
    already_normalised_doc: bool = False,
) -> tuple[str, tuple[int, int]]:
    """Return `(context_window, (quote_start_in_window, quote_end_in_window))` with ±300 chars around the quote."""
    norm_doc = canonical_text if already_normalised_doc else normalise_for_verify(canonical_text)
    if not norm_doc:
        norm_q = normalise_for_verify(evidence_quote)
        return norm_q, (0, len(norm_q))

    span = (
        match_span
        if match_span is not None
        else find_quote_span(evidence_quote, norm_doc, already_normalised_doc=True)
    )
    if span is None:
        norm_q = normalise_for_verify(evidence_quote)
        return norm_q, (0, len(norm_q))

    start, end = span
    ctx_start = max(0, start - window_chars)
    ctx_end = min(len(norm_doc), end + window_chars)
    return norm_doc[ctx_start:ctx_end], (start - ctx_start, end - ctx_start)


def _significant_tokens(name: str) -> list[str]:
    norm_name = normalise_for_verify(name).casefold()
    return [
        t
        for t in re.split(r"[^a-z0-9]+", norm_name)
        if len(t) >= 3
        and t not in {"inc", "corp", "corporation", "ltd", "limited", "llc", "plc", "company", "the", "and", "group"}
    ]


def _extract_enclosing_sentence_window(
    context_window: str,
    q_start: int,
    q_end: int,
) -> str:
    """Expand `context_window[q_start:q_end]` to its enclosing sentence boundaries without spilling into adjacent sentences."""
    left_prefix = context_window[:q_start]
    if re.search(r"[.!?]\s*$|\n\s*$", left_prefix):
        sent_start = q_start
    else:
        sent_start = 0
        for m in _SENTENCE_BOUNDARY_RE.finditer(left_prefix):
            sent_start = m.end()

    quote_slice = context_window[q_start:q_end].rstrip()
    if re.search(r"(?<!\bMr)(?<!\bMs)(?<!\bDr)(?<!\bNo)[.!?]$", quote_slice):
        sent_end = q_end
    else:
        right_suffix = context_window[q_end:]
        m_right = _SENTENCE_BOUNDARY_RE.search(right_suffix)
        sent_end = q_end + m_right.end() if m_right else len(context_window)

    return context_window[sent_start:sent_end].strip() or context_window[q_start:q_end]


def _extract_target_sentences(
    enclosing_text: str,
    edge: VerifiedEdge,
    *,
    is_reverse: bool = False,
) -> list[str]:
    """Return only the sentence(s) within `enclosing_text` that mention `edge.target_name`
    (or the edge's subject `edge.source_company_name` in reverse links).
    """
    sentences = [
        s.strip()
        for s in _SENTENCE_BOUNDARY_RE.split(enclosing_text)
        if s.strip()
    ]
    if not sentences:
        return [enclosing_text]

    norm_target = normalise_for_verify(edge.target_name).casefold()
    target_tokens = _significant_tokens(edge.target_name)
    subject_tokens = _significant_tokens(edge.source_company_name) if is_reverse else []

    matching: list[str] = []
    for sent in sentences:
        sent_cf = sent.casefold()
        if (
            edge.target_kind == "unnamed_customer"
            and re.search(r"\b\d{1,2}(?:\.\d+)?\s*%", sent_cf)
            and "no other" not in sent_cf
        ):
            matching.append(sent)
            continue
        if (
            (norm_target and norm_target in sent_cf)
            or any(tok in sent_cf for tok in target_tokens)
            or (is_reverse and any(tok in sent_cf for tok in subject_tokens))
        ):
            matching.append(sent)

    return matching if matching else [enclosing_text]


def _extract_target_clauses(text: str, target_name: str, *, target_kind: str = "company", subject_name: str = "") -> list[str]:
    """Split `text` into clauses and return those mentioning `target_name` (or `subject_name` if provided)."""
    clauses = [
        c.strip()
        for c in re.split(
            r"[.;]|\b(?:whereas|while|although|however|but)\b|,\s+(?:and|but|while|whereas)\s+",
            text,
            flags=re.IGNORECASE,
        )
        if c.strip()
    ]
    if not clauses:
        return [text]

    if target_kind == "unnamed_customer":
        pct_clauses = [
            c for c in clauses
            if re.search(r"\b\d{1,2}(?:\.\d+)?\s*%", c) and "no other" not in c.casefold()
        ]
        if pct_clauses:
            return pct_clauses

    norm_target = normalise_for_verify(target_name).casefold()
    tokens = _significant_tokens(target_name)
    subj_tokens = _significant_tokens(subject_name) if subject_name else []
    matching = [
        c for c in clauses
        if (norm_target and norm_target in c.casefold())
        or any(tok in c.casefold() for tok in tokens)
        or any(tok in c.casefold() for tok in subj_tokens)
    ]
    return matching if matching else [text]


def check_interpretation_rules(
    edge: VerifiedEdge,
    canonical_text: str,
    *,
    is_reverse: bool = False,
    match_span: tuple[int, int] | None = None,
    already_normalised_doc: bool = False,
) -> tuple[list[InterpretationFlag], str | None, str]:
    """Run the 6 deterministic V-INT rules on `edge.evidence_quote` + ±300 chars of `Filing.text`.

    - `competitor_mention` and `negated` require the cue word to appear in the SAME sentence as the
      target name (or as the edge's subject in reverse links), avoiding window spill-over from adjacent
      sentences while preserving the full `±300`-char `context_window` for the Flash judge.

    Returns `(flags, reason, context_window)`.
    """
    norm_doc = canonical_text if already_normalised_doc else normalise_for_verify(canonical_text)
    context_window, (q_start, q_end) = extract_quote_context(
        edge.evidence_quote,
        norm_doc,
        match_span=match_span,
        window_chars=CONTEXT_WINDOW_CHARS,
        already_normalised_doc=True,
    )
    quote_text = edge.evidence_quote
    enclosing_window = _extract_enclosing_sentence_window(context_window, q_start, q_end)
    target_sentences = _extract_target_sentences(enclosing_window, edge, is_reverse=is_reverse)
    target_sentence_joined = " ".join(target_sentences)
    target_clauses = _extract_target_clauses(
        target_sentence_joined,
        edge.target_name,
        target_kind=edge.target_kind,
        subject_name=edge.source_company_name if is_reverse else "",
    )

    flags: list[InterpretationFlag] = []
    reasons: list[str] = []

    # 1. competitor_mention: cue must be in the same sentence as the target name (or reverse-link subject)
    comp_match = _COMPETITOR_RE.search(target_sentence_joined)
    if comp_match:
        flags.append("competitor_mention")
        reasons.append(f"Competitor cue ('{comp_match.group(0)}') in target sentence for '{edge.target_name}'")

    # 2. negated: cue must be in the target clause of the target sentence
    for clause in target_clauses:
        neg_match = _NEGATION_CLAUSE_RE.search(clause)
        if neg_match:
            if (
                edge.target_kind == "unnamed_customer"
                and "no other" in clause.casefold()
                and re.search(r"\b\d{1,2}(?:\.\d+)?\s*%", clause)
            ):
                continue
            flags.append("negated")
            reasons.append(f"Negation cue ('{neg_match.group(0)}') in target clause")
            break

    # 3. hypothetical
    has_modal = _HYPOTHETICAL_MODAL_RE.search(target_sentence_joined)
    has_strict_hypo = _STRICT_HYPOTHETICAL_PHRASE_RE.search(target_sentence_joined)
    has_factual_verb = bool(_FACTUAL_VERB_RE.search(target_sentence_joined))
    if has_strict_hypo or (has_modal and not has_factual_verb):
        cue = (has_strict_hypo or has_modal).group(0)  # type: ignore[union-attr]
        flags.append("hypothetical")
        reasons.append(f"Hypothetical/modal phrasing ('{cue}') without factual anchor")

    # 4. direction_mismatch
    clause_joined = " ".join(target_clauses)
    has_customer_cue = bool(_DOWNSTREAM_CUSTOMER_CUE_RE.search(clause_joined))
    has_supplier_cue = bool(_UPSTREAM_SUPPLIER_CUE_RE.search(clause_joined))
    if edge.edge_type in {"supplier", "foundry", "contract_manufacturer", "key_input"}:
        if has_customer_cue and not has_supplier_cue:
            flags.append("direction_mismatch")
            reasons.append(
                f"Quote describes downstream customer/sales relationship but edge_type is '{edge.edge_type}'"
            )
    elif edge.edge_type == "customer" and has_supplier_cue and not has_customer_cue:
        flags.append("direction_mismatch")
        reasons.append(
            "Quote describes upstream supplier/manufacturing relationship but edge_type is 'customer'"
        )

    # 5. generic_reference
    norm_target_cf = normalise_for_verify(edge.target_name).casefold()
    if (
        (edge.target_kind == "company" and is_generic_company_target(edge.target_name, quote_text))
        or (edge.target_kind != "unnamed_customer" and norm_target_cf in _GENERIC_NON_COMPANY_TARGETS)
    ):
        flags.append("generic_reference")
        reasons.append(f"Target '{edge.target_name}' is a generic class/category, not a specific entity")

    # 6. subject_mismatch
    bio_match = _BIOGRAPHICAL_OR_LITIGATION_RE.search(target_sentence_joined)
    if bio_match:
        flags.append("subject_mismatch")
        reasons.append(
            f"Biographical or litigation context ('{bio_match.group(0)}') rather than operational dependency"
        )
    elif is_reverse:
        filer_tokens = _significant_tokens(edge.source_company_name)
        has_filer_anchor = bool(_FIRST_PERSON_FILER_RE.search(context_window)) or any(
            tok in context_window.casefold() for tok in filer_tokens
        )
        if not has_filer_anchor:
            flags.append("subject_mismatch")
            reasons.append(
                f"Reverse-link quote has no reference to filer '{edge.source_company_name}'"
            )

    reason_str = "; ".join(reasons) if reasons else None
    return flags, reason_str, context_window


def build_judge_prompt(
    items: Sequence[tuple[VerifiedEdge, list[InterpretationFlag], str]],
) -> str:
    """Build the `hoc-v3-judge-1` prompt for one company's batch of flagged + sampled edges.

    Never includes the extractor's raw JSON or prompt — only the filer name, claimed relationship,
    quote, ±300-char context window, and rule flags.
    """
    blocks: list[str] = [
        f"PROMPT_VERSION: {JUDGE_PROMPT_VERSION}",
        "Evaluate each candidate dependency claim against its SEC filing quote and ±300-character context.\n",
    ]
    for idx, (edge, flags, context_window) in enumerate(items, start=1):
        direction_desc = (
            f"Target '{edge.target_name}' ({edge.target_kind}) is a downstream CUSTOMER of filer '{edge.source_company_name}'"
            if edge.edge_type == "customer"
            else (
                f"Filer '{edge.source_company_name}' depends on target '{edge.target_name}' ({edge.target_kind}) "
                f"as edge_type='{edge.edge_type}' (sole_source={edge.sole_source})"
            )
        )
        blocks.append(
            f"[ITEM {idx}]\n"
            f"edge_id: {edge.edge_id}\n"
            f"filer: {edge.source_company_name} ({edge.source_company_key})\n"
            f"claimed_relationship: {direction_desc}\n"
            f"rule_flags: {', '.join(flags) if flags else 'none'}\n"
            f"evidence_quote: {edge.evidence_quote}\n"
            f"context_window: {context_window}\n"
        )
    return "\n".join(blocks)


def _valid_flags(raw_flags: Sequence[str]) -> list[InterpretationFlag]:
    valid_set = set(INTERPRETATION_FLAGS)
    out: list[InterpretationFlag] = []
    for f in raw_flags:
        s = str(f).strip()
        if s in valid_set and s not in out:
            out.append(s)  # type: ignore[arg-type]
    return out


def decide_interpretation_from_judge(
    flags: Sequence[InterpretationFlag],
    rule_reason: str | None,
    *,
    label: str,
    cleared_flags: Sequence[str] = (),
    judge_reason: str | None = None,
    model: str | None = None,
) -> EdgeInterpretation:
    """Deterministic Python decision rule combining `flags` and the judge's `label` (`PLAN-v3.md` §5):

    - `contradicts`, `competitor`, or `unrelated` -> `rejected`
    - `unclear`, or any flag in `flags` that the judge did not clear -> `flagged`
    - `supports` (with all flags cleared) -> `confirmed`
    """
    cleaned_label = label.strip().lower()
    cleared_set = {str(f).strip() for f in cleared_flags if str(f).strip()}
    remaining_flags = _valid_flags([f for f in flags if f not in cleared_set])
    combined_reason = (judge_reason or "").strip() or rule_reason

    if cleaned_label in {"contradicts", "competitor", "unrelated"}:
        rej_flags = _valid_flags(flags)
        return EdgeInterpretation(
            status="rejected",
            method="rules+model",
            flags=rej_flags,
            reason=combined_reason or f"Judge classified relationship as '{cleaned_label}'",
            model=model,
        )

    if cleaned_label == "unclear" or remaining_flags:
        flag_list = list(remaining_flags) if remaining_flags else _valid_flags(flags)
        if cleaned_label == "unclear" and "judge_unclear" not in flag_list:
            flag_list.append("judge_unclear")
        return EdgeInterpretation(
            status="flagged",
            method="rules+model",
            flags=flag_list,
            reason=combined_reason or "Judge could not clear ambiguity in quote context",
            model=model,
        )

    return EdgeInterpretation(
        status="confirmed",
        method="rules+model",
        flags=[],
        reason=combined_reason or None,
        model=model,
    )


def verify_company_interpretations(
    edges: Sequence[VerifiedEdge],
    canonical_text: str,
    *,
    client: Any = None,
    cache: ExtractionCache | None = None,
    cache_only: bool = False,
    is_reverse: bool = False,
    sample_rate: float = DEFAULT_UNFLAGGED_SAMPLE_RATE,
) -> InterpretationResult:
    """Run V-INT (rules layer + per-company independent Flash judge `hoc-v3-judge-1`) over `edges`.

    - Every edge that the rules flag + a deterministic 20% sample of unflagged edges is sent to the
      independent judge (or replayed from the per-edge judge disk cache).
    - `rejected` edges are removed from `result.edges`, placed in `result.rejected_edges`, and counted
      in `result.interpretation_rejected`.
    - `flagged` edges remain in `result.edges` with `EdgeInterpretation(status='flagged', ...)`.
    - `confirmed` edges remain in `result.edges` with `EdgeInterpretation(status='confirmed', ...)`.
    """
    if not edges:
        return InterpretationResult(edges=[])

    norm_doc = normalise_for_verify(canonical_text)
    rule_outputs: dict[str, tuple[list[InterpretationFlag], str | None, str]] = {}
    to_judge: list[tuple[VerifiedEdge, list[InterpretationFlag], str]] = []
    sampled_edge_ids: list[str] = []
    flagged_by_rules_ids: list[str] = []
    interpretations: dict[str, EdgeInterpretation] = {}

    model_name = (
        getattr(client, "extractor_model", DEFAULT_EXTRACTOR_MODEL)
        if client is not None
        else DEFAULT_EXTRACTOR_MODEL
    )

    # 1. Run deterministic rules layer on all edges and select edges for the judge
    for edge in edges:
        if edge.interpretation is not None:
            interpretations[edge.edge_id] = edge.interpretation
            continue
        flags, rule_reason, context_window = check_interpretation_rules(
            edge,
            norm_doc,
            is_reverse=is_reverse,
            already_normalised_doc=True,
        )
        rule_outputs[edge.edge_id] = (flags, rule_reason, context_window)
        if flags:
            flagged_by_rules_ids.append(edge.edge_id)
            to_judge.append((edge, flags, context_window))
        elif should_sample_unflagged_edge(edge.edge_id, sample_rate=sample_rate):
            sampled_edge_ids.append(edge.edge_id)
            to_judge.append((edge, flags, context_window))
        else:
            interpretations[edge.edge_id] = EdgeInterpretation(
                status="confirmed",
                method="rules",
                flags=[],
                reason=None,
                model=None,
            )

    # 2. Check per-edge judge cache for selected edges
    uncached_to_judge: list[tuple[VerifiedEdge, list[InterpretationFlag], str]] = []
    for edge, flags, context_window in to_judge:
        cached_verdict = (
            cache.get_judge_any_model(
                edge.edge_id,
                models=(model_name, DEFAULT_EXTRACTOR_MODEL, DEFAULT_ORCHESTRATOR_MODEL),
                prompt_version=JUDGE_PROMPT_VERSION,
            )
            if cache is not None
            else None
        )
        if cached_verdict is not None:
            _, rule_reason, _ = rule_outputs[edge.edge_id]
            interpretations[edge.edge_id] = decide_interpretation_from_judge(
                flags,
                rule_reason,
                label=str(cached_verdict.get("label", "supports")),
                cleared_flags=cached_verdict.get("cleared_flags", []),
                judge_reason=cached_verdict.get("reason"),
                model=str(cached_verdict.get("model") or model_name),
            )
        else:
            uncached_to_judge.append((edge, flags, context_window))

    # 3. Call the independent Flash judge once for this company's uncached items
    if uncached_to_judge and client is not None and not cache_only and getattr(client, "has_api_key", True):
        prompt = build_judge_prompt(uncached_to_judge)
        try:
            response_json, used_model = client.generate_json(
                prompt,
                JUDGE_SCHEMA,
                model=model_name,
                system_instruction=JUDGE_SYSTEM_INSTRUCTION,
                thinking_level="low",
            )
            raw_verdicts = response_json.get("verdicts", []) if isinstance(response_json, Mapping) else []
            verdict_by_id: dict[str, Mapping[str, Any]] = {
                str(v.get("edge_id", "")).strip(): v
                for v in raw_verdicts
                if isinstance(v, Mapping) and str(v.get("edge_id", "")).strip()
            }
            for edge, flags, _ in uncached_to_judge:
                _, rule_reason, _ = rule_outputs[edge.edge_id]
                v = verdict_by_id.get(edge.edge_id)
                if v is not None:
                    label = str(v.get("label", "unclear" if flags else "supports"))
                    cleared = v.get("cleared_flags", [])
                    if not isinstance(cleared, list):
                        cleared = []
                    j_reason = str(v.get("reason") or "").strip() or None
                    if cache is not None:
                        cache.put_judge(
                            edge.edge_id,
                            model=used_model,
                            prompt_version=JUDGE_PROMPT_VERSION,
                            payload={
                                "edge_id": edge.edge_id,
                                "label": label,
                                "cleared_flags": cleared,
                                "reason": j_reason,
                                "model": used_model,
                                "prompt_version": JUDGE_PROMPT_VERSION,
                            },
                        )
                    interpretations[edge.edge_id] = decide_interpretation_from_judge(
                        flags,
                        rule_reason,
                        label=label,
                        cleared_flags=cleared,
                        judge_reason=j_reason,
                        model=used_model,
                    )
                else:
                    interpretations[edge.edge_id] = (
                        EdgeInterpretation(
                            status="flagged",
                            method="rules",
                            flags=_valid_flags(flags),
                            reason=rule_reason,
                            model=None,
                        )
                        if flags
                        else EdgeInterpretation(
                            status="confirmed",
                            method="rules",
                            flags=[],
                            reason=None,
                            model=None,
                        )
                    )
        except (GeminiMissingKeyError, GeminiError) as exc:
            log.warning("V-INT judge call failed (%s); falling back to rules layer", exc)

    # 4. Any remaining unjudged edges fall back to deterministic rules
    for edge, flags, _ in uncached_to_judge:
        if edge.edge_id not in interpretations:
            _, rule_reason, _ = rule_outputs[edge.edge_id]
            if flags:
                interpretations[edge.edge_id] = EdgeInterpretation(
                    status="flagged",
                    method="rules",
                    flags=_valid_flags(flags),
                    reason=rule_reason,
                    model=None,
                )
            else:
                interpretations[edge.edge_id] = EdgeInterpretation(
                    status="confirmed",
                    method="rules",
                    flags=[],
                    reason=None,
                    model=None,
                )

    # 5. Partition into kept (confirmed + flagged) vs rejected
    kept_edges: list[VerifiedEdge] = []
    rejected_edges: list[VerifiedEdge] = []
    final_flagged_ids: list[str] = []

    for edge in edges:
        interp = interpretations[edge.edge_id]
        updated_edge = attach_edge_interpretation(edge, interp)
        interpretations[edge.edge_id] = interp
        if interp.status == "rejected":
            rejected_edges.append(updated_edge)
        else:
            if interp.status == "flagged":
                final_flagged_ids.append(edge.edge_id)
            kept_edges.append(updated_edge)

    return InterpretationResult(
        edges=kept_edges,
        rejected_edges=rejected_edges,
        interpretation_rejected=len(rejected_edges),
        sampled_edge_ids=sampled_edge_ids,
        flagged_edge_ids=final_flagged_ids,
        interpretations=interpretations,
    )


def verify_edge_interpretation(
    edge: VerifiedEdge,
    canonical_text: str,
    *,
    client: Any = None,
    cache: ExtractionCache | None = None,
    cache_only: bool = False,
    is_reverse: bool = False,
) -> EdgeInterpretation:
    """Verify interpretation of a single `VerifiedEdge` (used by `A-RES` research loop)."""
    res = verify_company_interpretations(
        [edge],
        canonical_text,
        client=client,
        cache=cache,
        cache_only=cache_only,
        is_reverse=is_reverse,
        sample_rate=1.0,
    )
    return res.interpretations[edge.edge_id]
