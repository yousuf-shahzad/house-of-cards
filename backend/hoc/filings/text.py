"""Canonical filing text. Owner: G-DOC (Kendrick's Claude).

Every evidence quote is checked against `normalise(html_to_text(filing))`, and the verifier (G-AI)
normalises the quote with the same `normalise`, so both sides of the substring test agree:
- Unicode NFKC (thin/no-break spaces -> space, the ellipsis character -> "...", ligatures split);
- curly quotes -> ' and ", every dash/minus variant -> -;
- soft hyphens and zero-width characters removed;
- all whitespace runs collapsed to one space, ends stripped.
Case is kept (quotes are shown to users); compare with str.casefold() if case should not matter.
"""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser

_TRANSLATE = str.maketrans({
    **dict.fromkeys(map(chr, (0x2018, 0x2019, 0x201A, 0x201B, 0x2032, 0x02BC)), "'"),  # curly/prime single quotes
    **dict.fromkeys(map(chr, (0x201C, 0x201D, 0x201E, 0x201F, 0x2033)), '"'),  # curly/prime double quotes
    **dict.fromkeys(map(chr, (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212, 0xFE58, 0xFE63, 0xFF0D)), "-"),
    **dict.fromkeys(map(chr, (0x00AD, 0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF))),  # soft hyphen, zero-width: dropped
})
_SPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """The one text normalisation for filings and quotes (see module docstring)."""
    return _SPACE.sub(" ", unicodedata.normalize("NFKC", text).translate(_TRANSLATE)).strip()


_BLOCK_TAGS = frozenset({
    "address", "article", "br", "dd", "div", "dl", "dt", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li",
    "ol", "p", "section", "table", "td", "th", "tr", "ul",
})
_SKIP_TAGS = frozenset({"script", "style", "head", "title", "ix:header"})
"""ix:header holds the hidden iXBRL facts block: machine data, not filing prose."""
_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip: list[str] = []  # open tags inside a dropped element (script, style, iXBRL header, display:none)

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:  # no end tag follows, so never count it
            if tag in _BLOCK_TAGS and not self._skip:
                self.parts.append("\n")
            return
        style = (dict(attrs).get("style") or "").replace(" ", "").lower()
        if self._skip or tag in _SKIP_TAGS or "display:none" in style:
            self._skip.append(tag)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK_TAGS and not self._skip:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        if self._skip:
            if tag in self._skip:  # pop down to the matching open tag, so unclosed <p>s inside can't leak
                del self._skip[len(self._skip) - 1 - self._skip[::-1].index(tag):]
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Filing HTML/iXBRL -> canonical text (already normalised). Inline tags join without a space,
    so 'PR<span>OPERTIES</span>' stays 'PROPERTIES'; block tags separate words."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return normalise("".join(parser.parts))
