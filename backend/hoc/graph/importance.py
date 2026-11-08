"""Deterministic relationship importance scoring (v3 package R-IMP).

Rules (docs/hoc/PLAN-v3.md §4 & docs/hoc/CONTRACT.md §8):
- Python computes every EdgeImportance{score 0..1, tier, reasons} from verified fields only.
- Base score by edge_type:
  - foundry: 0.90
  - contract_manufacturer: 0.85
  - key_input: 0.60
  - supplier: 0.50
  - jv_partner: 0.40
  - customer: 0.90 at >=20% of revenue, 0.70 at >=10%, else 0.50
  - facility: 0.70 for production (fab, factory, plant, assembly, manufacturing),
    0.30 for headquarters, office or R&D, else 0.50
- Cues in the verified quote (whole words, case-insensitive):
  - up: sole, single source, only source, limited number of, substantially all,
    critical, depend(s/ent) on, rely/relies on
  - down: one of several, multiple sources, alternative sources, readily available
- Overrides:
  - sole_source -> score >= 0.95
  - interpretation.status == "flagged" -> capped at medium (score <= 0.55)
- Tiers: critical >= 0.8, high >= 0.6, medium >= 0.4, else low.
- Every single-quoted phrase in `reasons` is copied verbatim from the verified evidence.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from hoc.contract.dependencies import EdgeImportance, ImportanceTier, VerifiedEdge

_TIER_THRESHOLDS: tuple[tuple[ImportanceTier, float], ...] = (
    ("critical", 0.8),
    ("high", 0.6),
    ("medium", 0.4),
    ("low", 0.0),
)

_BASE_SCORES: dict[str, tuple[float, str]] = {
    "foundry": (0.90, "Foundry relationship"),
    "contract_manufacturer": (0.85, "Contract manufacturer relationship"),
    "key_input": (0.60, "Key input relationship"),
    "supplier": (0.50, "Supplier relationship"),
    "jv_partner": (0.40, "Joint-venture partner relationship"),
}

_REVENUE_PCT_RE = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*%")

_FACILITY_PRODUCTION_RE = re.compile(
    r"\b(final\s+assembly|wafer\s+fabrication|cleanroom|megafactory|gigafactory|"
    r"manufacturing|manufactures|manufactured|fabrication|packaging|"
    r"production|assembly|testing|foundry|factories|factory|plants|plant|fabs|fab)\b",
    re.IGNORECASE,
)

_FACILITY_HQ_RD_RE = re.compile(
    r"\b(principal\s+executive\s+offices?|principal\s+offices?|corporate\s+headquarters|"
    r"corporate\s+offices?|headquartered|headquarters|research\s+and\s+development|"
    r"r&d|laboratories|laboratory|studios?|offices?)\b",
    re.IGNORECASE,
)

# Upward cue patterns (ordered from strongest/most specific to general)
_UP_CUE_PATTERNS: tuple[tuple[re.Pattern[str], float, str], ...] = (
    (
        re.compile(
            r"\b(sole\s+source|single\s+source|only\s+source|sole-source|single-source|"
            r"sole\s+foundry|sole\s+supplier|sole\s+manufacturer|sole)\b",
            re.IGNORECASE,
        ),
        0.15,
        "Named as the sole source",
    ),
    (
        re.compile(
            r"\b(limited\s+number\s+of|small\s+number\s+of|few\s+suppliers|few\s+sources)\b",
            re.IGNORECASE,
        ),
        0.10,
        "Limited supply alternatives",
    ),
    (
        re.compile(
            r"\b(substantially\s+all|vast\s+majority|significant\s+majority)\b",
            re.IGNORECASE,
        ),
        0.10,
        "High concentration",
    ),
    (
        re.compile(r"\b(critical|essential|indispensable)\b", re.IGNORECASE),
        0.10,
        "Criticality cue",
    ),
    (
        re.compile(
            r"\b(depends\s+on|depend\s+on|dependent\s+on|relies\s+on|rely\s+on|reliant\s+on)\b",
            re.IGNORECASE,
        ),
        0.05,
        "Dependency cue",
    ),
)

# Downward cue patterns
_DOWN_CUE_PATTERNS: tuple[tuple[re.Pattern[str], float, str], ...] = (
    (
        re.compile(
            r"\b(one\s+of\s+several|multiple\s+sources|alternative\s+sources|"
            r"readily\s+available|multiple\s+suppliers|several\s+suppliers)\b",
            re.IGNORECASE,
        ),
        0.15,
        "Multiple or alternative sources",
    ),
)


_LEGAL_SUFFIX_RE = re.compile(
    r",?\s*\b(?:Co\.,?\s*Ltd\.?|Corp(?:oration)?\.?|Inc(?:orporated)?\.?|Ltd\.?|L\.?L\.?C\.?|L\.?P\.?|PLC|N\.?V\.?|S\.?A\.?|SE|AG|Company|Holdings|Group|International|Limited)\.?\s*$",
    re.IGNORECASE,
)
_STOP_TOKENS: frozenset[str] = frozenset({"the", "and", "for", "from", "with", "inc", "ltd", "llc", "plc", "corp"})
_CLAUSE_SPLIT_RE = re.compile(
    r";|\n|(?<!\bInc)(?<!\bLtd)(?<!\bCo)(?<!\bCorp)\.\s+|,\s+(?:while|whereas|but|however|and)\s+|\s+(?:while|whereas)\s+",
    re.IGNORECASE,
)
_CUE_CLAUSE_SPLIT_RE = re.compile(
    r";|\n|(?<!\bInc)(?<!\bLtd)(?<!\bCo)(?<!\bCorp)\.\s+|,\s+(?:while|whereas|but|however)\s+|\band\s+(?=(?:our|the|a|an)\s+(?:sole|single|only)\b)",
    re.IGNORECASE,
)


def _target_identifying_tokens(target_name: str) -> list[str]:
    cleaned = _LEGAL_SUFFIX_RE.sub("", (target_name or "").strip()).strip().rstrip(",.")
    tokens: list[str] = []
    for raw_tok in re.findall(r"[A-Za-z0-9]+", cleaned):
        low = raw_tok.lower()
        if low in _STOP_TOKENS:
            continue
        if len(low) >= 3 or (len(raw_tok) >= 2 and raw_tok.isupper()):
            tokens.append(low)
    return tokens


def _clause_mentions_target(clause: str, target_name: str, tokens: Sequence[str]) -> bool:
    low_clause = clause.lower()
    clean_target = _LEGAL_SUFFIX_RE.sub("", (target_name or "").strip()).strip().lower()
    if clean_target and clean_target in low_clause:
        return True
    return any(bool(re.search(rf"\b{re.escape(tok)}\b", low_clause)) for tok in tokens)


def _target_customer_clauses(quote: str, target_name: str) -> list[str]:
    """Return the clause(s) in `quote` grounded to `target_name` (or `[quote]` if target is unnamed in quote)."""
    if not quote:
        return []
    tokens = _target_identifying_tokens(target_name)
    raw_clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(quote) if c and c.strip()]
    if not raw_clauses:
        return [quote]
    matching = [c for c in raw_clauses if _clause_mentions_target(c, target_name, tokens)]
    return matching if matching else [quote]


def _target_cue_text(quote: str, target_name: str) -> str:
    """Return the portion of `quote` whose cues apply to `target_name` (excluding clauses about another named entity)."""
    if not quote:
        return ""
    tokens = _target_identifying_tokens(target_name)
    raw_clauses = [c.strip() for c in _CUE_CLAUSE_SPLIT_RE.split(quote) if c and c.strip()]
    if len(raw_clauses) <= 1 or not any(_clause_mentions_target(c, target_name, tokens) for c in raw_clauses):
        return quote
    kept: list[str] = []
    for clause in raw_clauses:
        if _clause_mentions_target(clause, target_name, tokens):
            kept.append(clause)
            continue
        # Exclude a non-target clause if it names a different mid-clause capitalized proper noun
        words = clause.split()
        has_other_proper_noun = any(
            bool(re.match(r"^[A-Z][A-Za-z0-9.&-]*$", w.strip(".,;:()[]\"'")))
            for w in words[1:]
        )
        if not has_other_proper_noun:
            kept.append(clause)
    return " ; ".join(kept) if kept else quote


def tier_for_score(score: float) -> ImportanceTier:
    """Return the canonical ImportanceTier for a numeric score in [0, 1]."""
    for tier, floor in _TIER_THRESHOLDS:
        if score >= floor:
            return tier
    return "low"


def _customer_base_score(edge: VerifiedEdge) -> tuple[float, str]:
    """Compute base score and reason for a customer edge from its target-grounded revenue share."""
    quote = edge.evidence_quote or ""
    target_clauses = _target_customer_clauses(quote, edge.target_name)
    target_text = " ; ".join(target_clauses)

    # 1. If edge.qualifier has a percentage that is grounded in the target's clause(s), use ONLY that share.
    best_pct: float | None = None
    best_phrase: str | None = None
    if edge.qualifier:
        for q_match in _REVENUE_PCT_RE.finditer(edge.qualifier):
            try:
                q_pct = float(q_match.group(1))
            except ValueError:
                continue
            if not (0.0 < q_pct <= 100.0):
                continue
            # Check that the same numeric percentage appears in the target's clause in evidence_quote
            grounded_match = next(
                (
                    m
                    for m in _REVENUE_PCT_RE.finditer(target_text)
                    if abs(float(m.group(1)) - q_pct) < 1e-6
                ),
                None,
            )
            if grounded_match is not None and (best_pct is None or q_pct > best_pct):
                best_pct = q_pct
                qual_stripped = edge.qualifier.strip()
                best_phrase = qual_stripped if qual_stripped in quote else grounded_match.group(0)

    # 2. Otherwise, scan only the target-grounded clause(s) in evidence_quote (never another customer's clause)
    if best_pct is None and not (edge.qualifier and _REVENUE_PCT_RE.search(edge.qualifier)):
        for match in _REVENUE_PCT_RE.finditer(target_text):
            try:
                pct = float(match.group(1))
            except ValueError:
                continue
            if 0.0 < pct <= 100.0 and (best_pct is None or pct > best_pct):
                best_pct = pct
                best_phrase = match.group(0)

    if best_pct is not None and best_phrase is not None:
        if best_pct >= 20.0:
            return 0.90, f"Customer at >=20% of revenue ('{best_phrase}')"
        if best_pct >= 10.0:
            return 0.70, f"Customer at 10-20% of revenue ('{best_phrase}')"
    return 0.50, "Customer relationship"


def _facility_base_score(edge: VerifiedEdge) -> tuple[float, str]:
    """Compute base score and reason for a facility edge (production vs HQ/office/R&D)."""
    quote = edge.evidence_quote or ""
    for text in (quote, edge.qualifier or "", edge.target_name):
        if not text:
            continue
        prod_match = _FACILITY_PRODUCTION_RE.search(text)
        if prod_match:
            phrase = prod_match.group(0)
            if phrase in quote:
                return 0.70, f"Production facility ('{phrase}')"
            return 0.70, "Production facility"

    for text in (quote, edge.qualifier or "", edge.target_name):
        if not text:
            continue
        hq_match = _FACILITY_HQ_RD_RE.search(text)
        if hq_match:
            phrase = hq_match.group(0)
            if phrase in quote:
                return 0.30, f"Headquarters, office, or R&D facility ('{phrase}')"
            return 0.30, "Headquarters, office, or R&D facility"

    return 0.50, "Facility location"


def score_edge_importance(edge: VerifiedEdge) -> EdgeImportance:
    """Deterministically compute EdgeImportance{score, tier, reasons} for a VerifiedEdge."""
    reasons: list[str] = []

    if edge.edge_type == "customer":
        score, base_reason = _customer_base_score(edge)
    elif edge.edge_type == "facility":
        score, base_reason = _facility_base_score(edge)
    else:
        score, base_reason = _BASE_SCORES.get(edge.edge_type, (0.50, "Operational relationship"))
    reasons.append(base_reason)

    quote = edge.evidence_quote or ""
    cue_text = _target_cue_text(quote, edge.target_name)
    sole_cue_matched = False

    for pattern, delta, label in _UP_CUE_PATTERNS:
        match = pattern.search(cue_text)
        if match:
            cue_word = match.group(0)
            score += delta
            reasons.append(f"{label} ('{cue_word}')")
            if label == "Named as the sole source":
                sole_cue_matched = True

    for pattern, delta, label in _DOWN_CUE_PATTERNS:
        match = pattern.search(cue_text)
        if match:
            cue_word = match.group(0)
            score -= delta
            reasons.append(f"{label} ('{cue_word}')")

    if edge.sole_source or sole_cue_matched:
        score = max(score, 0.95)
        if not sole_cue_matched:
            reasons.append("Marked as sole-source relationship")

    score = round(min(1.0, max(0.0, score)), 4)

    # Reverse customer link cap: a supplier's customer revenue disclosure ("X is 30% of our sales")
    # shows the supplier depends on X for revenue, not that buyer X critically depends on the supplier.
    if edge.edge_type == "customer" and not edge.source_in_portfolio and score >= 0.60:
        score = 0.55
        reasons.append("Capped at medium: reverse customer disclosure")

    # V-INT flagged cap: unclear or flagged interpretations are capped at medium (< 0.60)
    if edge.interpretation is not None and edge.interpretation.status == "flagged":
        if score >= 0.60:
            score = 0.55
        reasons.append("Capped at medium: interpretation flagged")

    tier = tier_for_score(score)
    return EdgeImportance(score=score, tier=tier, reasons=reasons)


def attach_edge_importance(edges: Sequence[VerifiedEdge]) -> list[VerifiedEdge]:
    """Return a copy of `edges` with `importance` populated (and capped if `interpretation` is flagged or reverse customer)."""
    out: list[VerifiedEdge] = []
    for edge in edges:
        if edge.importance is not None:
            # Ensure reverse-customer and V-INT flagged caps still hold if edge.importance was pre-populated
            is_reverse_customer = edge.edge_type == "customer" and not edge.source_in_portfolio
            is_flagged = edge.interpretation is not None and edge.interpretation.status == "flagged"
            if (is_reverse_customer or is_flagged) and edge.importance.score >= 0.60:
                capped_reasons = list(edge.importance.reasons)
                if is_reverse_customer and "Capped at medium: reverse customer disclosure" not in capped_reasons:
                    capped_reasons.append("Capped at medium: reverse customer disclosure")
                if is_flagged and "Capped at medium: interpretation flagged" not in capped_reasons:
                    capped_reasons.append("Capped at medium: interpretation flagged")
                capped = EdgeImportance(
                    score=0.55,
                    tier="medium",
                    reasons=capped_reasons,
                )
                out.append(edge.model_copy(update={"importance": capped}))
            else:
                out.append(edge)
        else:
            out.append(edge.model_copy(update={"importance": score_edge_importance(edge)}))
    return out
