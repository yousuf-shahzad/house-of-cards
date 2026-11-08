"""G-DOC: section offsets on SYNTHETIC filing text (shapes copy real 10-K/20-F quirks)."""

from __future__ import annotations

from hoc.filings.sections import FALLBACK_CHARS, find_sections, section_map
from hoc.filings.text import normalise

FILLER = "The company designs widgets. " * 100  # ~2,900 chars per section body


def ten_k() -> str:
    toc = ("TABLE OF CONTENTS PART I Item 1. Business 3 Item 1A. Risk Factors 9 Item 1B. Unresolved Staff "
           "Comments 20 Item 2. Properties 21 Item 3. Legal Proceedings 22 ")
    body = (f"PART I Item 1. Business ZZ Corp makes widgets. We rely on ZZ Foundry for wafers. {FILLER}"
            f"Item 1A. Risk Factors Our supply depends on a sole source supplier. See Item 7, Management's "
            f"Discussion, and as described in Item 2. Properties we lease fabs. {FILLER}"
            f"ITEM 1B UNRESOLVED STAFF COMMENTS None. ITEM 2 PROPERTIES Our fabs are in Arizona. {FILLER}"
            f"Item 3. Legal Proceedings None. One customer accounted for 22% of our total revenue. {FILLER}")
    return normalise(toc + body)


def test_10k_sections_skip_toc_and_cross_references():
    text = ten_k()
    sections = find_sections(text, ("1", "1A", "2"))
    item1, risk, props = (text[s:e] for s, e in (sections["1"], sections["1A"], sections["2"]))
    assert item1.startswith("Item 1. Business ZZ Corp") and "Risk Factors Our supply" not in item1
    assert risk.startswith("Item 1A. Risk Factors Our supply") and "described in Item 2. Properties we lease" in risk
    assert props.startswith("ITEM 2 PROPERTIES Our fabs") and "Legal Proceedings None" not in props


def test_item_1_business_is_not_read_as_item_1b():
    text = normalise(f"Item 1 Business We make widgets. {FILLER} Item 1A Risk Factors {FILLER}")
    assert set(find_sections(text, ("1", "1A", "1B"))) == {"1", "1A"}


def test_section_map_adds_concentration_paragraphs_outside_sections():
    sections, quality = section_map(ten_k(), "10-K")
    assert quality == "sections" and {"1", "1A", "2"} <= set(sections)
    extra = [k for k in sections if k.startswith("concentration_")]
    assert extra and "22% of our total revenue" in ten_k()[slice(*sections[extra[0]])]


def test_20f_items_and_thin_space_headings():
    text = normalise(f"ITEM 3. KEY INFORMATION D. Risk Factors We depend on ZZ Optics. {FILLER}"
                     f"ITEM 4. INFORMATION ON THE COMPANY Our fabs are in Taiwan. {FILLER}"
                     f"ITEM 5. OPERATING AND FINANCIAL REVIEW {FILLER} ITEM 6. DIRECTORS {FILLER}")
    sections, quality = section_map(text, "20-F")
    assert quality == "sections" and {"3", "4", "5"} <= set(sections)
    assert "We depend on ZZ Optics" in text[slice(*sections["3"])]


def test_fallback_is_capped_when_no_headings_found():
    text = normalise("No item headings here. " * 10_000)
    sections, quality = section_map(text, "10-K")
    assert quality == "fallback" and sections == {"document": (0, FALLBACK_CHARS)}
