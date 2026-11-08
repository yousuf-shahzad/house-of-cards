"""Deterministic quote verification against canonical SEC filing text.

Owner: package G-AI (Kendrick's Gemini).
Rules (docs/hoc/PLAN-v2.md & docs/hoc/CONTRACT.md section 7):
- An edge exists only if `normalise(evidence_quote)` is found in `normalise(html_to_text(filing))`
  from `hoc.filings.text`.
- Up to one `...` splice is allowed, when both halves are at least 25 characters
  and appear in order within 300 characters.
- The target/counterparty name (or significant token / customer % qualifier) must
  appear in the quote itself so the LLM cannot attach an unrelated true sentence
  to a hallucinated counterparty.
"""

from __future__ import annotations

import re

from hoc.filings.text import normalise

PROMPT_VERSION = "hoc-v2-extract-1"

_CORP_STOPWORDS = frozenset({
    "inc", "incorporated", "corp", "corporation", "co", "company",
    "ltd", "limited", "llc", "llp", "lp", "plc", "nv", "bv", "se",
    "ag", "sa", "spa", "kk", "ab", "oyj", "asa", "holdings", "holding",
    "group", "international", "technologies", "technology", "systems",
    "the", "and", "of",
})


def normalise_for_verify(text: str) -> str:
    """Normalise text using `hoc.filings.text.normalise`."""
    if not text:
        return ""
    return normalise(text)


def _target_mentioned_in_quote(
    norm_quote_cf: str,
    target_name: str,
    target_kind: str,
    qualifier: str,
) -> bool:
    """Check that the extracted target (or customer concentration qualifier) is grounded in the quote."""
    if target_kind == "unnamed_customer" or target_name.strip().casefold().startswith("unnamed"):
        if any(tok in norm_quote_cf for tok in ("customer", "revenue", "sales", "%", "percent")):
            return True
        if qualifier:
            norm_qual = normalise(qualifier).casefold()
            if norm_qual and norm_qual in norm_quote_cf:
                return True
        return False

    norm_target = normalise(target_name).casefold()
    if not norm_target:
        return False
    if norm_target in norm_quote_cf:
        return True

    tokens = [
        tok for tok in re.split(r"[^a-z0-9]+", norm_target)
        if len(tok) >= 3 and tok not in _CORP_STOPWORDS
    ]
    if not tokens:
        tokens = [tok for tok in re.split(r"[^a-z0-9]+", norm_target) if len(tok) >= 2]
    return any(tok in norm_quote_cf for tok in tokens)


def verify_quote(
    evidence_quote: str,
    canonical_text: str,
    *,
    target_name: str = "",
    target_kind: str = "",
    qualifier: str = "",
    already_normalised_doc: bool = False,
) -> bool:
    """Return True iff `evidence_quote` appears verbatim in `canonical_text` and grounds `target_name`.

    Rules (CONTRACT.md section 7):
    - Quote must be non-empty (at least 15 normalised chars, at most 400 chars).
    - Up to one `...` splice is allowed when both halves are >= 25 characters
      and appear in order within 300 characters in the normalised document.
    - If `target_name` is given, it (or a significant token / customer qualifier) must appear in the quote.
    """
    if not evidence_quote or not canonical_text:
        return False

    norm_quote = normalise(evidence_quote)
    if len(norm_quote) < 15 or len(norm_quote) > 400:
        return False

    norm_doc = canonical_text if already_normalised_doc else normalise(canonical_text)
    norm_doc_cf = norm_doc.casefold()
    norm_quote_cf = norm_quote.casefold()

    if "..." in norm_quote_cf:
        parts = [part.strip() for part in norm_quote_cf.split("...")]
        if len(parts) != 2:
            return False
        left, right = parts
        if len(left) < 25 or len(right) < 25:
            return False
        matched_splice = False
        start = 0
        while True:
            idx_left = norm_doc_cf.find(left, start)
            if idx_left == -1:
                break
            after_left = idx_left + len(left)
            idx_right = norm_doc_cf.find(right, after_left, after_left + 300 + len(right))
            if idx_right != -1 and (idx_right - after_left) <= 300:
                matched_splice = True
                break
            start = idx_left + 1
        if not matched_splice:
            return False
    else:
        if norm_quote_cf not in norm_doc_cf:
            return False

    return not (
        (target_name or target_kind == "unnamed_customer")
        and not _target_mentioned_in_quote(norm_quote_cf, target_name, target_kind, qualifier)
    )
