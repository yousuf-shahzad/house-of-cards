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
    r"manufacturing|manufactures|manufactured|fabrication|facilities|packaging|"
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


def tier_for_score(score: float) -> ImportanceTier:
    """Return the canonical ImportanceTier for a numeric score in [0, 1]."""
    for tier, floor in _TIER_THRESHOLDS:
        if score >= floor:
            return tier
    return "low"


def _customer_base_score(edge: VerifiedEdge) -> tuple[float, str]:
    """Compute base score and reason for a customer edge from its revenue share."""
    best_pct: float | None = None
    best_phrase: str | None = None

    for source_text in (edge.qualifier or "", edge.evidence_quote):
        if not source_text:
            continue
        for match in _REVENUE_PCT_RE.finditer(source_text):
            try:
                pct = float(match.group(1))
            except ValueError:
                continue
            if 0.0 < pct <= 100.0 and (best_pct is None or pct > best_pct):
                best_pct = pct
                best_phrase = (
                    edge.qualifier.strip()
                    if source_text is edge.qualifier and edge.qualifier and "%" in edge.qualifier
                    else match.group(0)
                )

    if best_pct is not None and best_phrase is not None:
        if best_pct >= 20.0:
            return 0.90, f"Customer at >=20% of revenue ('{best_phrase}')"
        if best_pct >= 10.0:
            return 0.70, f"Customer at 10-20% of revenue ('{best_phrase}')"
    return 0.50, "Customer relationship"


def _facility_base_score(edge: VerifiedEdge) -> tuple[float, str]:
    """Compute base score and reason for a facility edge (production vs HQ/office/R&D)."""
    for text in (edge.evidence_quote, edge.qualifier or "", edge.target_name):
        if not text:
            continue
        prod_match = _FACILITY_PRODUCTION_RE.search(text)
        if prod_match:
            return 0.70, f"Production facility ('{prod_match.group(0)}')"

    for text in (edge.evidence_quote, edge.qualifier or "", edge.target_name):
        if not text:
            continue
        hq_match = _FACILITY_HQ_RD_RE.search(text)
        if hq_match:
            return 0.30, f"Headquarters, office, or R&D facility ('{hq_match.group(0)}')"

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
    sole_cue_matched = False

    for pattern, delta, label in _UP_CUE_PATTERNS:
        match = pattern.search(quote)
        if match:
            cue_word = match.group(0)
            score += delta
            reasons.append(f"{label} ('{cue_word}')")
            if label == "Named as the sole source":
                sole_cue_matched = True

    for pattern, delta, label in _DOWN_CUE_PATTERNS:
        match = pattern.search(quote)
        if match:
            cue_word = match.group(0)
            score -= delta
            reasons.append(f"{label} ('{cue_word}')")

    if edge.sole_source or sole_cue_matched:
        score = max(score, 0.95)
        if not sole_cue_matched:
            reasons.append("Marked as sole-source relationship")

    score = round(min(1.0, max(0.0, score)), 4)

    # V-INT flagged cap: unclear or flagged interpretations are capped at medium (< 0.60)
    if edge.interpretation is not None and edge.interpretation.status == "flagged":
        if score >= 0.60:
            score = 0.55
        reasons.append("Capped at medium: interpretation flagged")

    tier = tier_for_score(score)
    return EdgeImportance(score=score, tier=tier, reasons=reasons)


def attach_edge_importance(edges: Sequence[VerifiedEdge]) -> list[VerifiedEdge]:
    """Return a copy of `edges` with `importance` populated (and capped if `interpretation` is flagged)."""
    out: list[VerifiedEdge] = []
    for edge in edges:
        if edge.importance is not None:
            # Ensure V-INT flagged cap still holds if edge.importance was pre-populated before V-INT
            if (
                edge.interpretation is not None
                and edge.interpretation.status == "flagged"
                and edge.importance.score >= 0.60
            ):
                capped_reasons = list(edge.importance.reasons)
                if "Capped at medium: interpretation flagged" not in capped_reasons:
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
