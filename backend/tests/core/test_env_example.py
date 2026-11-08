"""backend/.env.example must load with dotenv semantics (`uv run --env-file .env`).

uv and python-dotenv stop at the first line they can't parse, so one unquoted value with a space (the old
HOC_USER_AGENT line) silently dropped every variable after it, GEMINI_API_KEY and HOC_SEC_CONTACT included.
"""

from __future__ import annotations

import re
from pathlib import Path

from hoc.config import Settings

EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"
LINE = re.compile(r"""^(?P<key>[A-Z_][A-Z0-9_]*)=(?P<value>"[^"]*"|'[^']*'|[^\s"'#]*)$""")


def parse(text: str) -> dict[str, str]:
    values = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = LINE.match(line)
        assert match, f".env.example line {number} won't parse (quote values with spaces): {line!r}"
        value = match["value"]
        values[match["key"]] = value[1:-1] if value[:1] in "\"'" and len(value) > 1 else value
    return values


def test_every_line_parses_and_spaces_are_quoted():
    values = parse(EXAMPLE.read_text(encoding="utf-8"))
    assert values["HOC_USER_AGENT"] == "HouseOfCards-PoC/0.1 (hackathon prototype)"
    assert "GEMINI_API_KEY" in values and "HOC_SEC_CONTACT" in values and "HOC_DEPS_REVERSE_LIMIT" in values


def test_the_example_loads_into_settings():
    settings = Settings.from_env(parse(EXAMPLE.read_text(encoding="utf-8")))
    assert settings.user_agent == "HouseOfCards-PoC/0.1 (hackathon prototype)"
    assert settings.deps_reverse_limit == 3 and settings.deps_top_n == 15
    assert settings.gemini_api_key is None and settings.sec_contact is None  # no secrets in the example


def test_an_unquoted_space_is_caught():
    try:
        parse("HOC_USER_AGENT=Name (with spaces)\n")
    except AssertionError as exc:
        assert "quote values with spaces" in str(exc)
    else:
        raise AssertionError("an unquoted value with spaces must fail")
