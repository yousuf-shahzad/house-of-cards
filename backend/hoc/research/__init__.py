"""Agentic research loop package for House of Cards v3 & v3.1 (package A-RES & A1).

Owner: Kendrick's Gemini (`@kendricklow2008 (Gemini)`).
"""

from __future__ import annotations

from hoc.research.loop import (
    MAX_RESEARCH_STEPS,
    RESEARCH_COMPANY_CACHE_NAMESPACE,
    RESEARCH_DEPTH_PRESETS,
    RESEARCH_DEPTH_TIMEOUT_SECONDS,
    RESEARCH_PROMPT_VERSION,
    RESEARCH_STEP_SCHEMA,
    AgenticResearchRunner,
    CompanyResearch,
    CompanyResearchResult,
    ResearchDepthOption,
    ResearchItem,
    ResearchLoop,
    merge_research_findings,
    research_company,
    select_company_research_items,
    select_research_items,
    strip_unquoted_numbers,
)

__all__ = [
    "MAX_RESEARCH_STEPS",
    "RESEARCH_COMPANY_CACHE_NAMESPACE",
    "RESEARCH_DEPTH_PRESETS",
    "RESEARCH_DEPTH_TIMEOUT_SECONDS",
    "RESEARCH_PROMPT_VERSION",
    "RESEARCH_STEP_SCHEMA",
    "AgenticResearchRunner",
    "CompanyResearch",
    "CompanyResearchResult",
    "ResearchDepthOption",
    "ResearchItem",
    "ResearchLoop",
    "merge_research_findings",
    "research_company",
    "select_company_research_items",
    "select_research_items",
    "strip_unquoted_numbers",
]
