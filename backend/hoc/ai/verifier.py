"""Deterministic quote verification, section attribution, and generic-company guard against canonical SEC filing text.

Owner: package G-AI (Kendrick's Gemini).
Rules (docs/hoc/PLAN-v2.md & docs/hoc/CONTRACT.md section 7):
- An edge exists only if `normalise(evidence_quote)` is found in `normalise(html_to_text(filing))`
  from `hoc.filings.text`.
- Up to one `...` splice is allowed, when both halves are at least 25 characters
  and appear in order within 300 characters.
- The target/counterparty name (or significant token / customer % qualifier) must
  appear in the quote itself so the LLM cannot attach an unrelated true sentence
  to a hallucinated counterparty.
- Generic common nouns (e.g. 'contract manufacturers', 'third-party suppliers', 'wafer foundries')
  are rejected when `target_kind == 'company'`.
- After `verify_quote` passes, `edge.section` is set deterministically in Python from the
  `Filing.sections` span that contains the quote match (`'document'` when none), never from the model.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from hoc.filings.text import normalise

PROMPT_VERSION = "hoc-v2-extract-1"

_CORP_STOPWORDS = frozenset({
    "inc", "incorporated", "corp", "corporation", "co", "company",
    "ltd", "limited", "llc", "llp", "lp", "plc", "nv", "bv", "se",
    "ag", "sa", "spa", "kk", "ab", "oyj", "asa", "holdings", "holding",
    "group", "international", "technologies", "technology", "systems",
    "the", "and", "of", "in", "to", "for", "on", "at", "by", "or", "as",
    "is", "be", "an", "no", "so", "up", "it", "we", "us", "do", "if",
})

_NON_DISTINCTIVE_NAME_TOKENS = frozenset({
    "advanced", "micro", "devices", "device", "applied", "materials", "material",
    "general", "motors", "motor", "western", "digital", "united", "american",
    "national", "global", "pacific", "standard", "first", "analog", "instruments",
    "instrument", "semiconductor", "semiconductors", "electronic", "electronics",
    "electric", "electrical", "power", "energy", "health", "healthcare", "medical",
    "financial", "capital", "partners", "partner", "solutions", "solution",
    "services", "service", "network", "networks", "communications", "communication",
    "industries", "industrial", "manufacturing", "chemical", "chemicals", "air",
    "lines", "line", "airlines", "airline", "parcel", "realty", "arts", "dynamics",
    "scientific", "precision", "optical", "photon", "photonics", "robotics",
    "data", "cloud", "software", "hardware", "computing", "computer", "computers",
    "storage", "memory", "wafer", "wafers", "silicon", "chip", "chips", "foundry",
    "foundries", "packaging", "assembly", "testing", "test", "supply", "supplies",
    "supplier", "suppliers", "vendor", "vendors", "customer", "customers",
    "counterparty", "counterparties", "company", "companies", "enterprise",
    "enterprises", "commercial", "central", "northern", "southern", "eastern",
    "north", "south", "east", "west", "new", "world",
})

_KNOWN_TARGET_ACRONYMS: dict[str, tuple[str, ...]] = {
    "advanced micro devices": ("amd",),
    "taiwan semiconductor manufacturing": ("tsmc",),
    "international business machines": ("ibm",),
    "applied materials": ("amat",),
    "texas instruments": ("ti",),
    "general electric": ("ge",),
    "general motors": ("gm",),
    "united parcel service": ("ups",),
}

_CLAUSE_SPLIT_RE = re.compile(
    r"[.;]"
    r"|\b(?:whereas|while|although|however|but)\b"
    r"|,\s+(?:and|but|while|whereas)\s+"
    r"|\s+and\s+(?=(?:our|we|the\s+company)\s+|\w+\s+(?:is|are|was|were|serves|served|acts|acted|supplies|supplied|manufactures|manufactured|provides|provided|accounted|represented)\b)",
    re.IGNORECASE,
)

_SOLE_SOURCE_GROUNDING_RE = re.compile(
    r"\b("
    r"sole(?:ly)?|"
    r"single[\-\s]source(?:d)?|"
    r"single\s+(?:supplier|vendor|foundry|manufacturer|provider|subcontractor|packager)|"
    r"only\s+(?:supplier|vendor|foundry|manufacturer|provider|source|subcontractor|packager|qualified)|"
    r"exclusive(?:ly)?|"
    r"100%\s+of\s+(?:our\s+)?(?:wafer|chip|component|product|supply|manufacturing|packaging|production)"
    r")\b",
    re.IGNORECASE,
)

_MULTI_SOURCE_CONTRADICTION_RE = re.compile(
    r"\b("
    r"alongside\s+(?:several|multiple|many|various|other|numerous)\b|"
    r"among\s+(?:several|multiple|many|various|our)\s+(?:other\s+)?(?:suppliers|vendors|manufacturers|foundries|providers|sources)|"
    r"one\s+of\s+(?:several|multiple|many|various|our)\s+(?:suppliers|vendors|manufacturers|foundries|providers|sources)|"
    r"(?:several|multiple|many|various|other)\s+(?:other\s+)?(?:suppliers|vendors|manufacturers|foundries|providers|sources)|"
    r"non[\-\s]exclusive"
    r")\b",
    re.IGNORECASE,
)

_LEGAL_CORPORATE_SUFFIXES = frozenset({
    "inc", "incorporated", "corp", "corporation", "ltd", "limited",
    "llc", "llp", "lp", "plc", "nv", "bv", "se", "ag", "sa", "spa",
    "kk", "ab", "oyj", "asa", "gmbh", "bhd", "tbk", "pte", "srl", "co",
})

_GENERIC_PLURAL_ROLE_NOUNS = frozenset({
    "manufacturers", "suppliers", "vendors", "foundries", "customers",
    "subcontractors", "distributors", "resellers", "partners", "providers",
    "carriers", "assemblers", "integrators", "fabricators", "packagers",
    "producers", "exporters", "importers", "competitors", "counterparties",
    "parties", "entities", "firms", "agencies", "authorities", "governments",
    "regulators", "subsidiaries", "affiliates", "licensees", "licensors",
    "lessors", "lessees", "lenders", "creditors", "insurers", "brokers",
    "dealers", "clients", "buyers", "sellers", "shippers", "operators",
    "hyperscalers", "oems", "odms", "osats", "cms", "fabs", "facilities",
    "plants", "factories", "sites", "locations", "operations",
})

_GENERIC_SINGULAR_ROLE_NOUNS = frozenset({
    "manufacturer", "supplier", "vendor", "foundry", "customer",
    "subcontractor", "distributor", "reseller", "partner", "provider",
    "carrier", "assembler", "integrator", "fabricator", "packager",
    "producer", "exporter", "importer", "competitor", "counterparty",
    "party", "entity", "firm", "agency", "authority", "government",
    "regulator", "subsidiary", "affiliate", "licensee", "licensor",
    "lessor", "lessee", "lender", "creditor", "insurer", "broker",
    "dealer", "client", "buyer", "seller", "shipper", "operator",
    "hyperscaler", "oem", "odm", "osat", "cm", "fab", "facility",
    "plant", "factory", "site", "location", "operation", "source",
})

_GENERIC_MODIFIERS = frozenset({
    "a", "an", "the", "our", "their", "its", "some", "many", "various",
    "certain", "several", "multiple", "numerous", "other", "single",
    "sole", "source", "exclusive", "primary", "principal", "major",
    "key", "critical", "significant", "selected", "qualified", "approved",
    "authorized", "independent", "external", "outside", "third", "party",
    "contract", "commercial", "industrial", "global", "international",
    "domestic", "foreign", "local", "regional", "overseas", "offshore",
    "onshore", "direct", "indirect", "end", "tier", "raw", "material",
    "materials", "component", "components", "semiconductor", "semiconductors",
    "wafer", "wafers", "chip", "chips", "silicon", "memory", "packaging",
    "assembly", "test", "testing", "manufacturing", "fabrication", "production",
    "supply", "chain", "logistics", "shipping", "freight", "cloud", "data",
    "center", "enterprise", "retail", "wholesale", "institutional", "channel",
    "strategic", "joint", "venture", "outsourced", "original", "equipment",
    "design", "system", "systems", "hardware", "software", "service",
    "services", "technology", "technologies", "unnamed", "anonymous",
    "undisclosed", "unspecified", "one", "two", "three", "four", "five",
    "large", "small", "leading", "top", "and", "or", "of", "for", "in", "to",
})

_ALL_GENERIC_COMPANY_WORDS = (
    _GENERIC_PLURAL_ROLE_NOUNS | _GENERIC_SINGULAR_ROLE_NOUNS | _GENERIC_MODIFIERS
)


def normalise_for_verify(text: str) -> str:
    """Normalise text using `hoc.filings.text.normalise`."""
    if not text:
        return ""
    return normalise(text)


def is_generic_company_target(target_name: str, evidence_quote: str = "") -> bool:
    """Return True if `target_name` is a generic common noun phrase (e.g. 'contract manufacturers')
    rather than a named company.
    """
    cleaned = normalise(target_name).strip()
    if not cleaned or not re.search(r"[A-Za-z]", cleaned):
        return True
    # A real company name or ticker always contains at least one uppercase letter
    if cleaned == cleaned.lower():
        return True

    tokens = [tok for tok in re.split(r"[^a-z0-9]+", cleaned.casefold()) if tok]
    if not tokens:
        return True

    if tokens[0] in {
        "unnamed", "undisclosed", "anonymous", "unspecified",
        "various", "certain", "multiple", "several", "numerous", "other",
    }:
        return True

    has_legal_suffix = tokens[-1] in _LEGAL_CORPORATE_SUFFIXES
    if not has_legal_suffix and tokens[-1] in _GENERIC_PLURAL_ROLE_NOUNS:
        return True

    if not has_legal_suffix and all(tok in _ALL_GENERIC_COMPANY_WORDS for tok in tokens):
        return True

    # If the target phrase appears in the verbatim quote ONLY in all-lowercase (e.g. the model
    # Title-Cased "Contract Manufacturers" from "...rely on contract manufacturers..."), reject it.
    if not has_legal_suffix and evidence_quote:
        norm_q = normalise(evidence_quote)
        matches = list(re.finditer(re.escape(cleaned), norm_q, re.IGNORECASE))
        if matches and all(m.group(0) == m.group(0).lower() for m in matches):
            return True

    return False


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

    norm_target = normalise(target_name).casefold().strip()
    if not norm_target:
        return False
    if re.search(rf"(?<![a-z0-9]){re.escape(norm_target)}(?![a-z0-9])", norm_quote_cf):
        return True

    tokens = [
        tok for tok in re.split(r"[^a-z0-9]+", norm_target)
        if len(tok) >= 2 and tok not in _CORP_STOPWORDS
    ]
    if not tokens:
        tokens = [tok for tok in re.split(r"[^a-z0-9]+", norm_target) if len(tok) >= 2]
    if not tokens:
        return False

    joined_tokens = " ".join(tokens)
    for key_phrase, aliases in _KNOWN_TARGET_ACRONYMS.items():
        if (key_phrase in norm_target or key_phrase == joined_tokens) and any(
            re.search(rf"\b{re.escape(alias)}\b", norm_quote_cf) for alias in aliases
        ):
            return True

    if len(tokens) == 1:
        return bool(re.search(rf"\b{re.escape(tokens[0])}\b", norm_quote_cf))

    distinctive_tokens = [tok for tok in tokens if tok not in _NON_DISTINCTIVE_NAME_TOKENS]
    if any(re.search(rf"\b{re.escape(tok)}\b", norm_quote_cf) for tok in distinctive_tokens):
        return True

    # For multi-word names made only of common corporate words (e.g. "Advanced Micro Devices",
    # "Applied Materials", "Western Digital"), require at least two consecutive tokens as whole words.
    return any(
        re.search(rf"\b{re.escape(tokens[i])}\s+{re.escape(tokens[i + 1])}\b", norm_quote_cf)
        for i in range(len(tokens) - 1)
    )


def _extract_target_clauses_from_quote(
    evidence_quote: str,
    target_name: str,
    *,
    target_kind: str = "company",
) -> list[str]:
    """Return the clause(s) within `evidence_quote` that mention `target_name`."""
    norm_q = normalise(evidence_quote)
    clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(norm_q) if c.strip()]
    if not clauses:
        return [norm_q]

    if target_kind == "unnamed_customer" or target_name.strip().casefold().startswith("unnamed"):
        pct_clauses = [
            c for c in clauses
            if re.search(r"\b\d{1,2}(?:\.\d+)?\s*%", c) and "no other" not in c.casefold()
        ]
        if pct_clauses:
            return pct_clauses

    matching = [
        c for c in clauses
        if _target_mentioned_in_quote(c.casefold(), target_name, target_kind, "")
    ]
    return matching if matching else [norm_q]


def is_sole_source_grounded_in_quote(
    evidence_quote: str,
    target_name: str,
    *,
    target_kind: str = "company",
) -> bool:
    """Return True iff the clause(s) mentioning `target_name` in `evidence_quote` contain explicit
    sole/single/only/exclusive-source language and do not state that multiple/other vendors are used.
    """
    if not evidence_quote or not target_name:
        return False
    target_clauses = _extract_target_clauses_from_quote(
        evidence_quote,
        target_name,
        target_kind=target_kind,
    )
    clause_text = " ".join(target_clauses)
    if _MULTI_SOURCE_CONTRADICTION_RE.search(clause_text):
        return False
    return bool(_SOLE_SOURCE_GROUNDING_RE.search(clause_text))


def ground_qualifier_in_quote(
    qualifier: str | None,
    evidence_quote: str,
    target_name: str,
    *,
    target_kind: str = "company",
    sole_source: bool = False,
) -> str | None:
    """Validate that any percentage/revenue share or sole-source wording in `qualifier` is grounded
    in the target-specific clause of `evidence_quote`; otherwise drop the ungrounded qualifier (`None`).
    """
    if not qualifier or not qualifier.strip():
        return None
    cleaned = normalise(qualifier).strip()
    if not cleaned:
        return None

    target_clauses = _extract_target_clauses_from_quote(
        evidence_quote,
        target_name,
        target_kind=target_kind,
    )
    clause_text = " ".join(target_clauses)
    clause_compact = re.sub(r"\s+", "", clause_text.casefold())

    # 1. Any percentage in `qualifier` must appear in the target's clause of `evidence_quote`
    pct_matches = re.findall(
        r"(\d+(?:\.\d+)?)\s*(%|(?:percent|per\s+cent)\b)",
        cleaned,
        flags=re.IGNORECASE,
    )
    for num_str, _ in pct_matches:
        has_pct_symbol = f"{num_str}%" in clause_compact
        has_pct_word = bool(
            re.search(rf"\b{re.escape(num_str)}\s*(?:%|percent|per\s+cent)\b", clause_text, re.IGNORECASE)
        )
        if not (has_pct_symbol or has_pct_word):
            return None

    # 2. If `sole_source` is not grounded for this target, `qualifier` must not smuggle sole-source wording
    if not sole_source and _SOLE_SOURCE_GROUNDING_RE.search(cleaned):
        return None

    return cleaned


def find_quote_span(
    evidence_quote: str,
    canonical_text: str,
    *,
    already_normalised_doc: bool = False,
) -> tuple[int, int] | None:
    """Return `(start, end)` character offsets of `evidence_quote` inside `normalise(canonical_text)`,
    or `None` if the quote does not satisfy the verbatim / single-ellipsis rules.
    """
    if not evidence_quote or not canonical_text:
        return None

    norm_quote = normalise(evidence_quote)
    if len(norm_quote) < 15 or len(norm_quote) > 400:
        return None

    norm_doc = canonical_text if already_normalised_doc else normalise(canonical_text)
    norm_doc_cf = norm_doc.casefold()
    norm_quote_cf = norm_quote.casefold()

    if "..." in norm_quote_cf:
        parts = [part.strip() for part in norm_quote_cf.split("...")]
        if len(parts) != 2:
            return None
        left, right = parts
        if len(left) < 25 or len(right) < 25:
            return None
        start = 0
        while True:
            idx_left = norm_doc_cf.find(left, start)
            if idx_left == -1:
                break
            after_left = idx_left + len(left)
            idx_right = norm_doc_cf.find(right, after_left, after_left + 300 + len(right))
            if idx_right != -1 and (idx_right - after_left) <= 300:
                return (idx_left, idx_right + len(right))
            start = idx_left + 1
        return None

    idx = norm_doc_cf.find(norm_quote_cf)
    if idx == -1:
        return None
    return (idx, idx + len(norm_quote_cf))


def resolve_quote_section(
    evidence_quote: str,
    canonical_text: str,
    sections: Mapping[str, tuple[int, int] | str] | None = None,
    *,
    match_span: tuple[int, int] | None = None,
    already_normalised_doc: bool = False,
) -> str:
    """Return the `Filing.sections` key whose span contains the verified quote match, or `'document'` when none.

    Never uses the free-text section label emitted by the model.
    """
    if not sections:
        return "document"

    norm_doc = canonical_text if already_normalised_doc else normalise(canonical_text)
    span = (
        match_span
        if match_span is not None
        else find_quote_span(evidence_quote, norm_doc, already_normalised_doc=True)
    )
    if span is None:
        return "document"

    match_start, match_end = span
    same_length = len(norm_doc) == len(canonical_text)

    # Check non-'document' sections first, preferring primary Item sections over concentration windows
    ordered_items = sorted(
        ((k, v) for k, v in sections.items() if k != "document"),
        key=lambda kv: (kv[0].startswith("concentration_"), kv[0]),
    )
    for sec_name, val in ordered_items:
        if isinstance(val, tuple) and len(val) == 2:
            sec_start, sec_end = int(val[0]), int(val[1])
            if same_length:
                if sec_start <= match_start and match_end <= sec_end:
                    return sec_name
            else:
                sec_slice = canonical_text[max(0, sec_start) : max(0, sec_end)]
                if find_quote_span(evidence_quote, sec_slice) is not None:
                    return sec_name
        elif isinstance(val, str) and find_quote_span(evidence_quote, val) is not None:
            return sec_name

    return "document"


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
    - If `target_kind == 'company'`, rejects generic common nouns (e.g. 'contract manufacturers').
    - If `target_name` is given, it (or a significant token / customer qualifier) must appear in the quote.
    """
    if target_kind == "company" and target_name and is_generic_company_target(target_name, evidence_quote):
        return False

    span = find_quote_span(
        evidence_quote,
        canonical_text,
        already_normalised_doc=already_normalised_doc,
    )
    if span is None:
        return False

    norm_quote_cf = normalise(evidence_quote).casefold()
    return not (
        (target_name or target_kind == "unnamed_customer")
        and not _target_mentioned_in_quote(norm_quote_cf, target_name, target_kind, qualifier)
    )
