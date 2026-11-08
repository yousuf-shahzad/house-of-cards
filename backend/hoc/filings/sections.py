"""Section offsets in canonical filing text. Owner: G-DOC (Kendrick's Claude).

The canonical text has no line breaks, so a body heading ("Item 1A. Risk Factors"), its table-of-contents
entry and a cross-reference ("see Item 1A, Risk Factors") look alike. For each item we take the
heading occurrence with the LONGEST span to the next heading of a different item: TOC entries sit a few
characters apart, and cross-references preceded by words like "see"/"in"/"under" are skipped.
Sections are only labels and chunk boundaries: quotes are verified against the whole document, so a
mis-sliced section can mislabel an edge but never let a fake quote through or reject a real one.
"""

from __future__ import annotations

import re

SECTIONS_10K = ("1", "1A", "2")
SECTIONS_20F = ("3", "3D", "4", "5")
"""20-F risk factors are Item 3.D; when only "Item 3" is headed, its span includes them."""
MIN_SECTION_CHARS = 2000
"""A section shorter than this is treated as not found (a TOC line or a stub)."""
FALLBACK_CHARS = 160_000
"""Without usable sections, send at most this much of the document (never all of ASML's 20-F)."""
CONCENTRATION_WINDOW = 600

_HEADING = re.compile(r"(?<![A-Za-z])ITEM\s+(\d{1,2})\s*\.?\s*([A-D](?![a-z]))?\s*[.:\-]?\s*(?-i:(?=[A-Z]))", re.IGNORECASE)
_CROSS_REF = re.compile(r"(?:\bsee|\bin|\bunder|\bof|\band|\bthis|\bour|[\"'(,])\s*(?:part\s+i+\s*,?\s*)?$", re.IGNORECASE)
_CONCENTRATION = re.compile(
    r"10\s?%\s+or\s+more|more\s+than\s+10\s?%|concentration\s+of|\d{1,2}(?:\.\d)?\s?%\s+of\s+(?:our\s+)?(?:total\s+)?"
    r"(?:net\s+)?(?:revenue|sales)",
    re.IGNORECASE,
)


def _headings(text: str) -> list[tuple[int, str]]:
    found = []
    for match in _HEADING.finditer(text):
        if _CROSS_REF.search(text[max(0, match.start() - 25):match.start()]):
            continue
        number, letter = match.group(1), (match.group(2) or "").upper()
        found.append((match.start(), number + letter))
    return found


def find_sections(text: str, wanted: tuple[str, ...]) -> dict[str, tuple[int, int]]:
    """item id -> (start, end) offsets into `text`, for the wanted items that were found."""
    headings = _headings(text)
    sections = {}
    for item in wanted:
        best = None
        for index, (start, name) in enumerate(headings):
            if name != item:
                continue
            # 20-F "Item 3" also matches its sub-items' context; a 10-K "Item 1" must stop at "Item 1A".
            end = next((s for s, other in headings[index + 1:] if other != item), len(text))
            if best is None or end - start > best[1] - best[0]:
                best = (start, end)
        if best and best[1] - best[0] >= MIN_SECTION_CHARS:
            sections[item] = best
    return sections


def concentration_spans(text: str) -> list[tuple[int, int]]:
    """Merged windows around customer/revenue concentration sentences (10% or more, % of revenue)."""
    spans: list[tuple[int, int]] = []
    for match in _CONCENTRATION.finditer(text):
        start = max(0, match.start() - CONCENTRATION_WINDOW // 2)
        end = min(len(text), match.end() + CONCENTRATION_WINDOW // 2)
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], end))
        else:
            spans.append((start, end))
    return spans


def section_map(text: str, form: str) -> tuple[dict[str, tuple[int, int]], str]:
    """(sections, quality). quality is 'sections', or 'fallback' with a single capped 'document' span."""
    wanted = SECTIONS_20F if form.upper().startswith("20-F") else SECTIONS_10K
    sections = find_sections(text, wanted)
    if not sections:
        return {"document": (0, min(len(text), FALLBACK_CHARS))}, "fallback"
    for index, span in enumerate(concentration_spans(text)):
        if not any(s <= span[0] and span[1] <= e for s, e in sections.values()):
            sections[f"concentration_{index + 1}"] = span
    return sections, "sections"
