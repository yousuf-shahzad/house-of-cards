"""Agentic research loop package for House of Cards v3 (package A-RES).

Owner: Kendrick's Gemini (`@kendricklow2008 (Gemini)`).
"""

from __future__ import annotations

from hoc.research.loop import (
    MAX_RESEARCH_STEPS,
    RESEARCH_PROMPT_VERSION,
    RESEARCH_STEP_SCHEMA,
    AgenticResearchRunner,
    ResearchItem,
    ResearchLoop,
    merge_research_findings,
    select_research_items,
     strip_unquoted_numbers,
)

__all__ = [
    "MAX_RESEARCH_STEPS",
    "RESEARCH_PROMPT_VERSION",
    "RESEARCH_STEP_SCHEMA",
    "AgenticResearchRunner",
    "ResearchItem",
    "ResearchLoop",
    "merge_research_findings",
    "select_research_items",
    "strip_unquoted_numbers",
]
