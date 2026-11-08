"""G-DOC: canonical filing text. Synthetic snippets only."""

from __future__ import annotations

from hoc.filings.text import html_to_text, normalise


def test_normalise_unifies_quotes_dashes_spaces_and_ellipsis():
    raw = "We\u2019re  \u201csole\u201d\u00a0source\u2009\u2014 foundry\u2026\n\tcost \u2212 5%\u00ad"
    assert normalise(raw) == "We're \"sole\" source - foundry... cost - 5%"


def test_normalise_is_idempotent_and_keeps_case():
    once = normalise("  Taiwan Semiconductor\u200b Manufacturing \uff0d TSMC ")
    assert once == "Taiwan Semiconductor Manufacturing - TSMC" and normalise(once) == once


def test_html_to_text_drops_hidden_and_machine_content():
    html = """<html><head><title>10-K</title><style>p{}</style></head><body>
    <div style="display: none"><ix:header><ix:hidden>dei:Fact 123</ix:hidden></ix:header><p>unclosed
    <div>nested hidden</div></div>
    <img style="display:none" src="x.png">
    <p>ITEM&#160;2.&nbsp;PR<span>OPERTIES</span></p><p>Our fabs are in Arizona.</p><br/>
    <script>var x = 1;</script><table><tr><td>Taiwan</td><td>45%</td></tr></table></body></html>"""
    assert html_to_text(html) == "ITEM 2. PROPERTIES Our fabs are in Arizona. Taiwan 45%"


def test_quote_matches_across_markup_once_both_sides_are_normalised():
    text = html_to_text("<p>We rely on <b>Taiwan Semiconductor\nManufacturing</b> Company&#8217;s foundries.</p>")
    quote = normalise("We rely on Taiwan Semiconductor Manufacturing Company\u2019s foundries.")
    assert quote in text
