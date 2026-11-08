"""AI change-idea proposer + deterministic proposal rationale verifier (FIX-17).

Rules (FIXES.md FIX-17 & docs/hoc/CONTRACT.md):
- Receives Python's portfolio issues (`top_sector` using the same >=40% rule as
  `diversificationVerdict`, top `dep.*` dependencies, `top10`, `effective_n`),
  current holdings, and a pinned universe of loadable ETFs (with name, category,
  and largest industry).
- Uses the orchestrator model (`DEFAULT_ORCHESTRATOR_MODEL = "gemini-4-argon"`,
  falling back to `DEFAULT_EXTRACTOR_MODEL` on rate-limit/quota errors) via
  `hoc.ai.client.GeminiClient` without modifying `hoc/ai`.
- Asks for up to 5 proposals (`add` or `swap`, fraction in `{0.1, 0.2, 0.3}`,
  target `issue_id`, short `title` <= 8 words with no digits, and `rationale`
  using `{{metric:<id>}}` placeholders only).
- Reuses `hoc.graph.orchestrator`'s placeholder, zero-invented-number,
  ticker/entity-lock, and trade-verb checks.
- Cached on disk per `(holdings, issues, prompt_version, model, user_prompt_sha256)`
  and never raises on missing API key, timeout, or transport errors.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from hoc.ai.client import GeminiClient, GeminiError, GeminiQuotaError
from hoc.config import DEFAULT_EXTRACTOR_MODEL, DEFAULT_ORCHESTRATOR_MODEL, Settings
from hoc.contract import EtfHoldings, PortfolioItem, Sector
from hoc.contract.api import AnalysisResponse, CompanyExposure, EtfReport
from hoc.contract.dependencies import MetricFact, VerifiedEdge
from hoc.graph.metrics import format_metric_value
from hoc.graph.orchestrator import (
    _COMMON_UPPER_ACRONYMS,
    _FORBIDDEN_PLAIN_JARGON_RE,
    _FORBIDDEN_TRADE_VERBS_RE,
    _PLACEHOLDER_RE,
    _WHITELISTED_DIGIT_TOKENS_RE,
    _normalise_entity_token,
    build_allowed_vocabulary,
)
from hoc.portfolio.sectors import etf_sectors

log = logging.getLogger("hoc.graph.idea_proposer")

IDEA_PROPOSER_PROMPT_VERSION = "hoc-ideas-v3.1"
DEFAULT_PROPOSER_MODEL = DEFAULT_ORCHESTRATOR_MODEL
PROPOSER_FRACTIONS: tuple[float, ...] = (0.1, 0.2, 0.3)
INDUSTRY_CONCENTRATION_THRESHOLD = 0.40

IdeaAiStatus = Literal["ok", "missing_api_key", "failed", "timeout", "not_used"]
ProposalAction = Literal["add", "swap"]
IssueAddresses = Literal["top_sector", "dependency", "top10", "effective_n"]


@dataclass(frozen=True)
class EtfUniverseEntry:
    """Candidate ETF metadata passed to the AI proposer."""

    ticker: str
    etf_name: str
    category: str
    largest_industry: str


# Pinned universe of 18 loadable ETFs across broad, equal-weight, value, dividend/factor,
# international, small/mid-cap, and non-tech defensive/cyclical sectors.
PINNED_ETF_UNIVERSE: tuple[EtfUniverseEntry, ...] = (
    EtfUniverseEntry("RSP", "Invesco S&P 500 Equal Weight ETF", "US Equal-Weight Broad", "Industrials"),
    EtfUniverseEntry("VTV", "Vanguard Value ETF", "US Large-Cap Value", "Financials"),
    EtfUniverseEntry("IWD", "iShares Russell 1000 Value ETF", "US Large-Cap Value", "Financials"),
    EtfUniverseEntry("QUAL", "iShares MSCI USA Quality Factor ETF", "US Quality Factor", "Information Technology"),
    EtfUniverseEntry("USMV", "iShares MSCI USA Min Vol Factor ETF", "US Minimum Volatility", "Information Technology"),
    EtfUniverseEntry("SCHD", "Schwab U.S. Dividend Equity ETF", "US Dividend Value", "Financials"),
    EtfUniverseEntry("VIG", "Vanguard Dividend Appreciation ETF", "US Dividend Growth", "Information Technology"),
    EtfUniverseEntry("VXUS", "Vanguard Total International Stock ETF", "International Broad", "Financials"),
    EtfUniverseEntry("IEFA", "iShares Core MSCI EAFE ETF", "Developed International", "Financials"),
    EtfUniverseEntry("IEMG", "iShares Core MSCI Emerging Markets ETF", "Emerging Markets", "Information Technology"),
    EtfUniverseEntry("IWM", "iShares Russell 2000 ETF", "US Small-Cap Broad", "Financials"),
    EtfUniverseEntry("IJH", "iShares Core S&P Mid-Cap ETF", "US Mid-Cap Broad", "Industrials"),
    EtfUniverseEntry("XLV", "Health Care Select Sector SPDR Fund", "Sector — Health Care", "Health Care"),
    EtfUniverseEntry("XLP", "Consumer Staples Select Sector SPDR Fund", "Sector — Consumer Staples", "Consumer Staples"),
    EtfUniverseEntry("XLU", "Utilities Select Sector SPDR Fund", "Sector — Utilities", "Utilities"),
    EtfUniverseEntry("XLF", "Financial Select Sector SPDR Fund", "Sector — Financials", "Financials"),
    EtfUniverseEntry("XLI", "Industrial Select Sector SPDR Fund", "Sector — Industrials", "Industrials"),
    EtfUniverseEntry("XLE", "Energy Select Sector SPDR Fund", "Sector — Energy", "Energy"),
)


@dataclass(frozen=True)
class PortfolioIssue:
    """A deterministic portfolio diversification issue exposed to the AI proposer."""

    issue_id: str
    addresses: IssueAddresses
    metric_id: str
    label: str
    value: float
    unit: Literal["fraction", "count"] = "fraction"
    formatted_value: str = ""

    def __post_init__(self) -> None:
        if not self.formatted_value:
            formatted = (
                f"{self.value * 100:.2f}%"
                if self.unit == "fraction"
                else (f"{round(self.value)}" if abs(self.value - round(self.value)) < 1e-6 else f"{self.value:.1f}")
            )
            object.__setattr__(self, "formatted_value", formatted)


@dataclass(frozen=True)
class RawIdeaProposal:
    """A structurally valid AI proposal ready for Python before/after verification."""

    action: ProposalAction
    ticker: str
    fraction: float
    swap_from: str | None
    issue_id: str
    addresses: IssueAddresses
    metric_id: str | None
    title: str
    rationale_template: str
    cited_metric_ids: tuple[str, ...]


@dataclass(frozen=True)
class IdeaProposerResult:
    """Result of running the AI change-idea proposer."""

    ai_status: IdeaAiStatus
    model: str | None
    prompt_version: str
    proposals: list[RawIdeaProposal]
    rejected_proposals: list[dict[str, str]]


IDEA_PROPOSER_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "swap"],
                    },
                    "ticker": {"type": "string"},
                    "fraction": {"type": "number"},
                    "swap_from": {"type": "string"},
                    "issue_id": {"type": "string"},
                    "title": {"type": "string"},
                    "rationale": {"type": "string"},
                    "cited_metric_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "action",
                    "ticker",
                    "fraction",
                    "issue_id",
                    "title",
                    "rationale",
                    "cited_metric_ids",
                ],
            },
        },
    },
    "required": ["proposals"],
}

IDEA_PROPOSER_SYSTEM_INSTRUCTION = """You are the House of Cards portfolio diversification idea proposer.
You receive:
1. `holdings`: the user's current ETF portfolio allocations.
2. `issues`: deterministic portfolio concentration and supply-chain dependency issues computed by Python (in priority order, with exact `issue_id` / `metric_id` and `placeholder`).
3. `candidate_etfs`: a pinned universe of loadable ETFs (with `ticker`, `etf_name`, `category`, and `largest_industry`).

Propose up to 5 concrete ETF changes (`proposals`) across distinct candidate ETFs that best address the portfolio's top issues:
- `action`: either `"add"` (put fraction `fraction` into candidate `ticker`, scaling current holdings by `1 - fraction`) or `"swap"` (move fraction `fraction` of the portfolio out of held ETF `swap_from` into candidate `ticker`, where `swap_from` has allocation >= `fraction` or is being replaced).
- `ticker`: MUST be a ticker from `candidate_etfs` that is NOT already in `holdings`. Choose diverse categories (e.g. equal-weight broad like RSP, value like VTV/IWD, international like VXUS/IEFA, or defensive sectors like XLV/XLP/XLU) so the user gets distinct choices.
- `fraction`: MUST be one of `0.1`, `0.2`, or `0.3`.
- `swap_from`: required when `action == "swap"` (must be a ticker in `holdings`); omit or empty string `""` when `action == "add"`.
- `issue_id`: MUST be an exact `issue_id` from `issues` (prioritise `top_sector` when present and >= 40%, or the biggest `dep.*` dependency).
- `title`: <= 8 words, plain everyday English, zero numbers/digits, naming what the ETF adds or swaps (e.g. "Add equal-weight US stocks with RSP" or "Swap tech-heavy XLK into healthcare XLV").
- `rationale`: 1 short plain-English sentence (<= 30 words) explaining why this ETF helps address `issue_id`.
  STRICT NUMBER RULE: NEVER write any literal digit, number, or percentage in `title` or `rationale`. Any number in `rationale` MUST be written as a `{{metric:<metric_id>}}` placeholder using an exact `metric_id` from `issues` (e.g. "{{metric:top_sector}}" or "{{metric:dep.ALIAS:TSMC}}"), and listed in `cited_metric_ids`. Never use financial jargon (`HHI`, `GICS`, `look-through`, `10-K`, `20-F`, `CIK`, `edges`, `orchestrator`).
"""


def _format_sector_display_name(sector: Sector | str) -> str:
    raw = sector.value if isinstance(sector, Sector) else str(sector)
    if raw == "information_technology" or raw == "technology":
        return "Technology"
    return raw.replace("_", " ").title()


def enrich_universe_from_loaded(
    loaded: Mapping[str, EtfHoldings],
    universe: Sequence[EtfUniverseEntry] = PINNED_ETF_UNIVERSE,
    *,
    notes: list[str] | None = None,
) -> list[EtfUniverseEntry]:
    """Return universe entries enriched from loaded `EtfHoldings` using authoritative `etf_sectors`."""
    if not loaded:
        return list(universe)
    enriched: list[EtfUniverseEntry] = []
    for entry in universe:
        etf = loaded.get(entry.ticker.upper())
        if etf is None or etf.holdings_weight < 0.95:
            if notes is not None:
                notes.append(f"Skipped candidate {entry.ticker}: holdings unavailable or incomplete.")
            continue
        basis, raw_sector_weights = etf_sectors(etf)
        sector_weights: dict[str, float] = {
            _format_sector_display_name(sec): float(weight)
            for sec, weight in raw_sector_weights.items()
            if sec != Sector.unknown and float(weight) > 0
        }
        largest_ind = (
            max(sector_weights.items(), key=lambda kv: (kv[1], kv[0]))[0]
            if basis != "none" and sector_weights
            else entry.largest_industry
        )
        enriched.append(
            EtfUniverseEntry(
                ticker=entry.ticker.upper(),
                etf_name=etf.etf_name or entry.etf_name,
                category=entry.category,
                largest_industry=largest_ind,
            )
        )
    return enriched


def build_portfolio_issues(
    analysis: AnalysisResponse,
    dependency_metrics: Sequence[MetricFact] = (),
) -> list[PortfolioIssue]:
    """Build the ordered list of portfolio issues using the same >=40% rule as `diversificationVerdict`."""
    issues: list[PortfolioIssue] = []

    # 1. Largest known industry from analysis.sectors (same >=40% threshold as diversificationVerdict)
    known_sectors = [s for s in analysis.sectors if s.sector != Sector.unknown and s.weight > 0]
    if known_sectors:
        top_sec = min(known_sectors, key=lambda s: (-s.weight, str(s.sector)))
        sec_name = _format_sector_display_name(top_sec.sector)
        if top_sec.weight >= INDUSTRY_CONCENTRATION_THRESHOLD:
            issues.append(
                PortfolioIssue(
                    issue_id="top_sector",
                    addresses="top_sector",
                    metric_id="top_sector",
                    label=f"Largest industry ({sec_name})",
                    value=float(top_sec.weight),
                    unit="fraction",
                )
            )

    # 2. Top supplier/counterparty dependencies (`dep.*` fraction metrics)
    dep_facts = sorted(
        (
            m
            for m in dependency_metrics
            if m.metric_id.startswith("dep.")
            and not m.metric_id.endswith(".companies")
            and m.unit == "fraction"
            and m.value > 0
        ),
        key=lambda m: (-m.value, m.metric_id),
    )
    for m in dep_facts[:5]:
        issues.append(
            PortfolioIssue(
                issue_id=m.metric_id,
                addresses="dependency",
                metric_id=m.metric_id,
                label=m.label,
                value=float(m.value),
                unit="fraction",
                formatted_value=format_metric_value(m),
            )
        )

    # 3. If top_sector was < 40% but known, still expose it as a secondary metric/issue
    if known_sectors and not any(i.issue_id == "top_sector" for i in issues):
        top_sec = min(known_sectors, key=lambda s: (-s.weight, str(s.sector)))
        sec_name = _format_sector_display_name(top_sec.sector)
        issues.append(
            PortfolioIssue(
                issue_id="top_sector",
                addresses="top_sector",
                metric_id="top_sector",
                label=f"Largest industry ({sec_name})",
                value=float(top_sec.weight),
                unit="fraction",
            )
        )

    # 4. Top-10 company concentration and effective_n
    top10_val = float(analysis.concentration.top10)
    eff_n_val = float(analysis.concentration.effective_companies)
    issues.append(
        PortfolioIssue(
            issue_id="top10",
            addresses="top10",
            metric_id="top10",
            label="Top 10 companies' share",
            value=top10_val,
            unit="fraction",
        )
    )
    issues.append(
        PortfolioIssue(
            issue_id="effective_n",
            addresses="effective_n",
            metric_id="effective_n",
            label="Effective number of equal holdings",
            value=eff_n_val,
            unit="count",
        )
    )
    return issues


def _coerce_issues(
    issues: Sequence[PortfolioIssue | MetricFact | Mapping[str, Any]],
    analysis: AnalysisResponse | None = None,
    dependency_metrics: Sequence[MetricFact] = (),
) -> list[PortfolioIssue]:
    if not issues and analysis is not None:
        return build_portfolio_issues(analysis, dependency_metrics)
    out: list[PortfolioIssue] = []
    for item in issues:
        if isinstance(item, PortfolioIssue):
            out.append(item)
        elif isinstance(item, MetricFact):
            addr: IssueAddresses = (
                "dependency"
                if item.metric_id.startswith("dep.")
                else "top_sector"
                if item.metric_id == "top_sector"
                else "effective_n"
                if item.metric_id == "effective_n"
                else "top10"
            )
            unit: Literal["fraction", "count"] = "count" if item.unit == "count" else "fraction"
            out.append(
                PortfolioIssue(
                    issue_id=item.metric_id,
                    addresses=addr,
                    metric_id=item.metric_id,
                    label=item.label,
                    value=float(item.value),
                    unit=unit,
                    formatted_value=format_metric_value(item),
                )
            )
        elif isinstance(item, Mapping):
            iid = str(item.get("issue_id") or item.get("metric_id") or "").strip()
            if not iid:
                continue
            mid = str(item.get("metric_id") or iid).strip()
            raw_addr = str(item.get("addresses") or "").strip()
            if raw_addr in {"top_sector", "dependency", "top10", "effective_n"}:
                addr = raw_addr  # type: ignore[assignment]
            elif iid.startswith("dep."):
                addr = "dependency"
            elif iid == "top_sector":
                addr = "top_sector"
            elif iid == "effective_n":
                addr = "effective_n"
            else:
                addr = "top10"
            unit = "count" if str(item.get("unit") or "") == "count" or addr == "effective_n" else "fraction"
            val = float(item.get("value") or 0.0)
            out.append(
                PortfolioIssue(
                    issue_id=iid,
                    addresses=addr,
                    metric_id=mid,
                    label=str(item.get("label") or iid),
                    value=val,
                    unit=unit,
                    formatted_value=str(item.get("formatted_value") or ""),
                )
            )
    return out


def _format_lookup_metric(entry: MetricFact | PortfolioIssue | float | str) -> str:
    if isinstance(entry, MetricFact):
        return format_metric_value(entry)
    if isinstance(entry, PortfolioIssue):
        return entry.formatted_value
    if isinstance(entry, str):
        return entry
    if isinstance(entry, (int, float)):
        return f"{float(entry) * 100:.1f}%"
    return str(entry)


_COMMON_PROSE_WORDS: frozenset[str] = frozenset(
    {
        "add",
        "adds",
        "adding",
        "swap",
        "swaps",
        "swapping",
        "shift",
        "shifts",
        "shifting",
        "move",
        "moves",
        "moving",
        "reduce",
        "reduces",
        "reducing",
        "lower",
        "lowers",
        "lowering",
        "spread",
        "spreads",
        "spreading",
        "broaden",
        "broadens",
        "broadening",
        "replace",
        "replaces",
        "replacing",
        "trim",
        "trims",
        "trimming",
        "cut",
        "cuts",
        "cutting",
        "diversify",
        "diversifies",
        "diversifying",
        "diversification",
        "put",
        "puts",
        "putting",
        "tilt",
        "tilts",
        "tilting",
        "keep",
        "keeps",
        "keeping",
        "avoid",
        "avoids",
        "avoiding",
        "limit",
        "limits",
        "limiting",
        "balance",
        "balances",
        "balancing",
        "help",
        "helps",
        "helping",
        "cap",
        "caps",
        "capping",
        "your",
        "the",
        "this",
        "these",
        "that",
        "those",
        "into",
        "from",
        "with",
        "across",
        "outside",
        "beyond",
        "while",
        "without",
        "through",
        "toward",
        "towards",
        "away",
        "out",
        "over",
        "under",
        "equal",
        "weight",
        "weighted",
        "value",
        "growth",
        "broad",
        "core",
        "total",
        "large",
        "mid",
        "small",
        "international",
        "developed",
        "emerging",
        "global",
        "world",
        "foreign",
        "domestic",
        "american",
        "united",
        "states",
        "markets",
        "market",
        "stocks",
        "stock",
        "equities",
        "equity",
        "shares",
        "share",
        "funds",
        "fund",
        "etf",
        "etfs",
        "index",
        "portfolio",
        "holdings",
        "holding",
        "allocation",
        "sector",
        "sectors",
        "industry",
        "industries",
        "companies",
        "company",
        "firms",
        "firm",
        "names",
        "name",
        "giants",
        "giant",
        "leaders",
        "leader",
        "suppliers",
        "supplier",
        "customers",
        "customer",
        "partners",
        "partner",
        "reliance",
        "dependency",
        "dependencies",
        "concentration",
        "exposure",
        "overlap",
        "risk",
        "risks",
        "single",
        "top",
        "biggest",
        "largest",
        "main",
        "heavy",
        "heavily",
        "high",
        "higher",
        "low",
        "more",
        "less",
        "fewer",
        "other",
        "new",
        "current",
        "existing",
        "overall",
        "direct",
        "indirect",
        "supply",
        "chain",
        "chip",
        "chips",
        "semiconductor",
        "semiconductors",
        "foundry",
        "foundries",
        "factory",
        "factories",
        "manufacturing",
        "makers",
        "maker",
        "hardware",
        "software",
        "cloud",
        "tech",
        "technology",
        "information",
        "financial",
        "financials",
        "healthcare",
        "health",
        "care",
        "consumer",
        "staples",
        "discretionary",
        "utilities",
        "utility",
        "energy",
        "industrial",
        "industrials",
        "materials",
        "material",
        "communication",
        "communications",
        "services",
        "real",
        "estate",
        "defensive",
        "cyclical",
        "dividend",
        "income",
        "bond",
        "bonds",
        "treasury",
        "gold",
        "commodity",
        "commodities",
    }
)


def _expand_allowed_entity_tokens(
    allowed_entities: set[str] | None,
    metrics_by_id: Mapping[str, MetricFact | PortfolioIssue | float | str] | None = None,
) -> set[str]:
    """Normalise `allowed_entities` (plus metric labels/IDs when needed) into surface forms and words."""
    expanded: set[str] = set()
    sources: list[str] = list(allowed_entities or ())
    if metrics_by_id:
        for mid, entry in metrics_by_id.items():
            if mid.startswith("dep.ALIAS:"):
                sources.append(mid.split("dep.ALIAS:", 1)[1].replace("_", " "))
            label = getattr(entry, "label", "")
            if isinstance(label, str) and label:
                if "dependent on " in label:
                    sources.append(label.split("dependent on ", 1)[1])
                else:
                    sources.append(label)
    for raw in sources:
        norm = _normalise_entity_token(str(raw))
        if len(norm) >= 2:
            expanded.add(norm)
            for tok in norm.split():
                if len(tok) >= 3:
                    expanded.add(tok)
    return expanded


def _find_unknown_entity_in_text(
    stripped_text: str,
    *,
    allowed_entities: set[str] | None,
    allowed_tickers: set[str] | None = None,
    metrics_by_id: Mapping[str, MetricFact | PortfolioIssue | float | str] | None = None,
    explicit_entities: Sequence[str] = (),
) -> str | None:
    """Return the first unverified company/entity name found in `explicit_entities` or `stripped_text`."""
    permitted_upper = set(allowed_tickers or ()) | set(_COMMON_UPPER_ACRONYMS)
    norm_allowed = _expand_allowed_entity_tokens(allowed_entities, metrics_by_id)

    for ent in explicit_entities:
        norm_ent = _normalise_entity_token(ent)
        if not norm_ent:
            continue
        if (
            ent.upper() not in permitted_upper
            and norm_ent not in norm_allowed
            and not any(
                norm_ent in allowed or allowed in norm_ent
                for allowed in norm_allowed
                if len(allowed) >= 3
            )
        ):
            return ent

    for token in re.findall(r"\b[A-Z][A-Za-z0-9.\-]*\b", stripped_text):
        if token.isupper() and 2 <= len(token) <= 5 and token in permitted_upper:
            continue
        norm_tok = _normalise_entity_token(token)
        if len(norm_tok) < 3 or norm_tok in _COMMON_PROSE_WORDS:
            continue
        if token.upper() in permitted_upper:
            continue
        if norm_tok in norm_allowed or any(
            norm_tok in allowed or allowed in norm_tok
            for allowed in norm_allowed
            if len(allowed) >= 4
        ):
            continue
        return token
    return None


def verify_and_render_proposal_rationale(
    rationale_template: str,
    *,
    metrics_by_id: Mapping[str, MetricFact | PortfolioIssue | float | str],
    allowed_tickers: set[str] | None = None,
    allowed_entities: set[str] | None = None,
    explicit_entities: Sequence[str] = (),
    max_words: int = 35,
) -> tuple[str | None, str | None]:
    """Verify a proposal `rationale` template using the orchestrator's grounding rules and render placeholders."""
    if not isinstance(rationale_template, str):
        return None, "empty_rationale"
    cleaned = rationale_template.strip()
    if not cleaned:
        return None, "empty_rationale"

    placeholders = _PLACEHOLDER_RE.findall(cleaned)
    for mid in placeholders:
        if mid not in metrics_by_id:
            return None, f"unknown_metric_id:{mid}"

    stripped = _PLACEHOLDER_RE.sub(" ", cleaned)
    stripped_no_whitelist = _WHITELISTED_DIGIT_TOKENS_RE.sub(" ", stripped)
    if re.search(r"\d", stripped_no_whitelist):
        return None, "unverified_literal_number"

    if _FORBIDDEN_PLAIN_JARGON_RE.search(stripped) or _FORBIDDEN_TRADE_VERBS_RE.search(stripped):
        return None, "forbidden_jargon_or_trade_verb"

    if allowed_tickers is not None:
        permitted_upper = set(allowed_tickers) | set(_COMMON_UPPER_ACRONYMS)
        for token in re.findall(r"\b[A-Z]{2,5}\b", stripped):
            if token not in permitted_upper:
                return None, f"unknown_ticker_in_rationale:{token}"

    unknown_ent = _find_unknown_entity_in_text(
        stripped,
        allowed_entities=allowed_entities,
        allowed_tickers=allowed_tickers,
        metrics_by_id=metrics_by_id if allowed_entities is None else None,
        explicit_entities=explicit_entities,
    )
    if unknown_ent is not None:
        return None, f"unknown_entity:{unknown_ent}"

    def _expand(match: re.Match[str]) -> str:
        mid = match.group(1)
        return _format_lookup_metric(metrics_by_id[mid])

    rendered = re.sub(r"\s+", " ", _PLACEHOLDER_RE.sub(_expand, cleaned)).strip()
    if not rendered or "{{metric:" in rendered:
        return None, "unexpanded_placeholder"
    if len(rendered.split()) > max_words:
        return None, "rationale_too_long"
    return rendered, None


def build_idea_proposer_prompt(
    holdings: Sequence[PortfolioItem],
    issues: Sequence[PortfolioIssue],
    universe: Sequence[EtfUniverseEntry] = PINNED_ETF_UNIVERSE,
) -> str:
    """Build the deterministic JSON grounding payload for the AI change-idea proposer."""
    held_tickers = {h.ticker.upper() for h in holdings}
    holdings_payload = [
        {
            "ticker": h.ticker.upper(),
            "allocation_fraction": round(float(h.allocation), 6),
            "allocation_pct": f"{float(h.allocation) * 100:.2f}%",
        }
        for h in sorted(holdings, key=lambda x: (-float(x.allocation), x.ticker.upper()))
    ]
    issues_payload = [
        {
            "issue_id": iss.issue_id,
            "addresses": iss.addresses,
            "metric_id": iss.metric_id,
            "label": iss.label,
            "formatted_value": iss.formatted_value,
            "placeholder": f"{{{{metric:{iss.metric_id}}}}}",
        }
        for iss in issues
    ]
    universe_payload = [
        {
            "ticker": u.ticker.upper(),
            "etf_name": u.etf_name,
            "category": u.category,
            "largest_industry": u.largest_industry,
        }
        for u in universe
        if u.ticker.upper() not in held_tickers
    ]
    payload = {
        "holdings": holdings_payload,
        "issues": issues_payload,
        "allowed_fractions": list(PROPOSER_FRACTIONS),
        "candidate_etfs": universe_payload,
    }
    return (
        "Propose up to 5 concrete ETF diversification ideas (`add` or `swap`) from `candidate_etfs` "
        "to address the portfolio's main `issues`.\n"
        "Remember: NEVER write literal digits or percentages in `title` or `rationale` — "
        "write numbers in `rationale` ONLY as `{{metric:<metric_id>}}` placeholders from `issues`.\n\n"
        + json.dumps(payload, indent=2)
    )


def compute_idea_proposer_cache_key(
    holdings: Sequence[PortfolioItem],
    issues: Sequence[PortfolioIssue | MetricFact | Mapping[str, Any]] = (),
    prompt_ver: str = IDEA_PROPOSER_PROMPT_VERSION,
    *,
    model: str | None = None,
    user_prompt: str | None = None,
) -> str:
    """Compute the deterministic sha256 disk cache key for the AI idea proposer."""
    coerced_issues = _coerce_issues(issues)
    alloc_part = [
        (h.ticker.upper(), f"{float(h.allocation):.10f}")
        for h in sorted(holdings, key=lambda x: x.ticker.upper())
    ]
    issues_part = [
        (iss.issue_id, iss.metric_id, f"{float(iss.value):.10f}")
        for iss in coerced_issues
    ]
    payload = json.dumps(
        {
            "holdings": alloc_part,
            "issues": issues_part,
            "prompt_version": prompt_ver,
            "model": model or DEFAULT_PROPOSER_MODEL,
            "user_prompt_sha256": (
                hashlib.sha256(user_prompt.encode("utf-8")).hexdigest()
                if user_prompt is not None
                else None
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_raw_proposals(
    raw_payload: Mapping[str, Any],
    *,
    holdings: Sequence[PortfolioItem],
    issues: Sequence[PortfolioIssue],
    universe: Sequence[EtfUniverseEntry] = PINNED_ETF_UNIVERSE,
    exposures: Sequence[CompanyExposure] = (),
    edges: Sequence[VerifiedEdge] = (),
    etfs: Sequence[EtfReport] | Sequence[PortfolioItem] = (),
) -> tuple[list[RawIdeaProposal], list[dict[str, str]]]:
    """Validate raw AI proposals against universe, fraction, swap-source, title, and rationale rules."""
    held_by_ticker = {h.ticker.upper(): float(h.allocation) for h in holdings}
    universe_by_ticker = {
        u.ticker.upper(): u for u in universe if u.ticker.upper() not in held_by_ticker
    }
    issues_by_id: dict[str, PortfolioIssue] = {}
    metrics_by_id: dict[str, PortfolioIssue] = {}
    for iss in issues:
        issues_by_id[iss.issue_id] = iss
        issues_by_id[iss.metric_id] = iss
        metrics_by_id[iss.metric_id] = iss
        metrics_by_id[iss.issue_id] = iss

    allowed_tickers, allowed_entities = build_allowed_vocabulary(
        exposures, edges, etfs if etfs else holdings
    )
    for u in universe:
        allowed_tickers.add(u.ticker.upper())
        norm_name = _normalise_entity_token(u.etf_name)
        if norm_name:
            allowed_entities.add(norm_name)
    for h in holdings:
        allowed_tickers.add(h.ticker.upper())
    allowed_entities |= _expand_allowed_entity_tokens(allowed_entities, metrics_by_id)
    for iss in issues:
        if iss.metric_id.startswith("dep.ALIAS:"):
            alias_code = iss.metric_id.split("dep.ALIAS:", 1)[1].strip().upper()
            if 2 <= len(alias_code) <= 5 and alias_code.isalpha():
                allowed_tickers.add(alias_code)

    verified: list[RawIdeaProposal] = []
    rejected: list[dict[str, str]] = []

    raw_list = raw_payload.get("proposals")
    if not isinstance(raw_list, list):
        return [], [{"ticker": "", "action": "add", "reason": "invalid_proposals_payload"}]

    for raw in raw_list[:5]:
        if not isinstance(raw, Mapping):
            rejected.append({"ticker": "", "action": "add", "reason": "non_object_proposal"})
            continue

        ticker = str(raw.get("ticker") or "").strip().upper()
        action_raw = str(raw.get("action") or "add").strip().lower()
        if action_raw not in {"add", "swap"}:
            rejected.append({"ticker": ticker, "action": action_raw, "reason": f"invalid_action:{action_raw}"})
            continue
        action: ProposalAction = action_raw  # type: ignore[assignment]

        if not ticker or ticker in held_by_ticker or ticker not in universe_by_ticker:
            reason = "already_held_ticker" if ticker in held_by_ticker else f"outside_universe:{ticker}"
            rejected.append({"ticker": ticker, "action": action, "reason": reason})
            continue

        try:
            frac_raw = round(float(raw.get("fraction") or 0.0), 2)
        except (TypeError, ValueError):
            rejected.append({"ticker": ticker, "action": action, "reason": "invalid_fraction"})
            continue
        if frac_raw not in PROPOSER_FRACTIONS:
            rejected.append({"ticker": ticker, "action": action, "reason": f"unsupported_fraction:{frac_raw}"})
            continue

        swap_from_raw = str(raw.get("swap_from") or "").strip().upper() or None
        if action == "swap":
            if not swap_from_raw or swap_from_raw not in held_by_ticker:
                rejected.append(
                    {
                        "ticker": ticker,
                        "action": action,
                        "reason": f"unknown_swap_source:{swap_from_raw or ''}",
                    }
                )
                continue
            if held_by_ticker[swap_from_raw] + 1e-9 < frac_raw:
                rejected.append(
                    {
                        "ticker": ticker,
                        "action": action,
                        "reason": f"swap_fraction_exceeds_holding:{swap_from_raw}",
                    }
                )
                continue
        else:
            swap_from_raw = None

        raw_issue_id = str(raw.get("issue_id") or "").strip()
        issue = issues_by_id.get(raw_issue_id)
        if issue is None:
            rejected.append({"ticker": ticker, "action": action, "reason": f"unknown_issue_id:{raw_issue_id}"})
            continue

        raw_title = str(raw.get("title") or "").strip()
        if not raw_title:
            raw_title = (
                f"Swap {swap_from_raw} into {ticker}"
                if action == "swap" and swap_from_raw
                else f"Add {ticker} to diversify exposure"
            )
        if len(raw_title.split()) > 8 or any(c.isdigit() for c in raw_title):
            rejected.append({"ticker": ticker, "action": action, "reason": "invalid_title"})
            continue
        for tok in re.findall(r"\b[A-Z]{2,5}\b", raw_title):
            if tok not in (allowed_tickers | set(_COMMON_UPPER_ACRONYMS)):
                rejected.append({"ticker": ticker, "action": action, "reason": f"unknown_ticker_in_title:{tok}"})
                raw_title = ""
                break
        if not raw_title:
            continue
        title_unknown_ent = _find_unknown_entity_in_text(
            raw_title,
            allowed_entities=allowed_entities,
            allowed_tickers=allowed_tickers,
        )
        if title_unknown_ent is not None:
            rejected.append({"ticker": ticker, "action": action, "reason": f"unknown_entity:{title_unknown_ent}"})
            continue

        explicit_entities = [
            str(ent).strip()
            for ent in (raw.get("entities") or raw.get("referenced_companies") or [])
            if str(ent).strip()
        ]
        rationale_template = str(raw.get("rationale") or "").strip()
        rendered_rat, rat_err = verify_and_render_proposal_rationale(
            rationale_template,
            metrics_by_id=metrics_by_id,
            allowed_tickers=allowed_tickers,
            allowed_entities=allowed_entities,
            explicit_entities=explicit_entities,
        )
        if rendered_rat is None or rat_err is not None:
            rejected.append({"ticker": ticker, "action": action, "reason": rat_err or "invalid_rationale"})
            continue

        cited_mids = tuple(dict.fromkeys(_PLACEHOLDER_RE.findall(rationale_template)))
        verified.append(
            RawIdeaProposal(
                action=action,
                ticker=ticker,
                fraction=frac_raw,
                swap_from=swap_from_raw,
                issue_id=issue.issue_id,
                addresses=issue.addresses,
                metric_id=issue.metric_id if issue.addresses == "dependency" else None,
                title=raw_title,
                rationale_template=rationale_template,
                cited_metric_ids=cited_mids,
            )
        )

    return verified, rejected


class IdeaProposer:
    """Proposes ETF additions/swaps with Gemini 4 Argon (Flash fallback) and caches on disk."""

    prompt_version: str = IDEA_PROPOSER_PROMPT_VERSION

    def __init__(
        self,
        http: Any | None = None,
        settings: Settings | None = None,
        *,
        ai_client: Any | None = None,
        http_client: Any | None = None,
        cache_dir: Path | str | None = None,
        model: str | None = None,
        fallback_model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._http_client = http if http is not None else http_client
        self._settings = settings
        self._ai_client = ai_client
        self._cache_dir = (
            Path(cache_dir)
            if cache_dir is not None
            else (settings.cache_dir if settings is not None else None)
        )
        self._model = (
            model
            or (settings.gemini_orchestrator_model if settings is not None else None)
            or os.environ.get("HOC_GEMINI_ORCHESTRATOR_MODEL")
            or DEFAULT_ORCHESTRATOR_MODEL
        )
        self._fallback_model = (
            fallback_model
            or (settings.gemini_extractor_model if settings is not None else None)
            or os.environ.get("HOC_GEMINI_EXTRACTOR_MODEL")
            or DEFAULT_EXTRACTOR_MODEL
        )
        self._explicit_api_key = api_key

    def _resolve_api_key(self) -> str | None:
        if self._explicit_api_key is not None:
            return self._explicit_api_key.strip() or None
        if self._settings is not None and self._settings.gemini_api_key:
            return self._settings.gemini_api_key.strip() or None
        if self._ai_client is not None and hasattr(self._ai_client, "has_api_key"):
            return "injected-client-key" if self._ai_client.has_api_key else None
        return (
            os.environ.get("GOOGLE_API_KEY", "").strip()
            or os.environ.get("GEMINI_API_KEY", "").strip()
            or None
        )

    def _cache_path(self, cache_key: str) -> Path | None:
        if self._cache_dir is None:
            return None
        return self._cache_dir / "idea_proposer" / f"{cache_key}.json"

    def _read_cache(self, cache_key: str) -> dict[str, Any] | None:
        path = self._cache_path(cache_key)
        if path is None or not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "raw_payload" in data:
                return data
        except (OSError, ValueError, TypeError):
            return None
        return None

    def _write_cache(
        self,
        cache_key: str,
        *,
        model: str,
        raw_payload: Mapping[str, Any],
    ) -> None:
        path = self._cache_path(cache_key)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "cache_key": cache_key,
                        "prompt_version": self.prompt_version,
                        "model": model,
                        "raw_payload": dict(raw_payload),
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError as exc:
            log.debug("Could not write idea_proposer cache %s: %s", path, exc)

    def read_cached(
        self,
        holdings: Sequence[PortfolioItem],
        issues: Sequence[PortfolioIssue | MetricFact | Mapping[str, Any]] = (),
        *,
        universe: Sequence[EtfUniverseEntry] = PINNED_ETF_UNIVERSE,
        analysis: AnalysisResponse | None = None,
        dependency_metrics: Sequence[MetricFact] = (),
        exposures: Sequence[CompanyExposure] = (),
        edges: Sequence[VerifiedEdge] = (),
    ) -> IdeaProposerResult | None:
        """Return the cached `IdeaProposerResult` from disk if present, else `None` (zero network/AI calls)."""
        coerced_issues = _coerce_issues(issues, analysis=analysis, dependency_metrics=dependency_metrics)
        if not holdings or not coerced_issues:
            return None
        user_prompt = build_idea_proposer_prompt(holdings, coerced_issues, universe)
        cache_key = compute_idea_proposer_cache_key(
            holdings,
            coerced_issues,
            prompt_ver=self.prompt_version,
            model=self._model,
            user_prompt=user_prompt,
        )
        cached = self._read_cache(cache_key)
        if cached is None:
            return None
        exp = exposures or (analysis.exposures if analysis is not None else ())
        etf_ctx = analysis.etfs if analysis is not None else holdings
        verified, rejected = verify_raw_proposals(
            cached["raw_payload"],
            holdings=holdings,
            issues=coerced_issues,
            universe=universe,
            exposures=exp,
            edges=edges,
            etfs=etf_ctx,
        )
        return IdeaProposerResult(
            ai_status="ok",
            model=cached.get("model") or self._model,
            prompt_version=self.prompt_version,
            proposals=verified,
            rejected_proposals=rejected,
        )

    def _call_ai_client(
        self,
        model: str,
        user_prompt: str,
        *,
        timeout_s: float = 90.0,
    ) -> tuple[dict[str, Any], str]:
        client = self._ai_client
        if client is None and self._http_client is not None:
            client = GeminiClient(
                self._http_client,
                self._settings,
                api_key=self._resolve_api_key(),
                extractor_model=self._fallback_model,
                orchestrator_model=self._model,
                timeout=timeout_s,
            )
        if client is None:
            raise RuntimeError("No AI client or HTTP client configured")

        used_model = model
        if hasattr(client, "generate_idea_proposals_json"):
            raw = client.generate_idea_proposals_json(
                model=model,
                system_instruction=IDEA_PROPOSER_SYSTEM_INSTRUCTION,
                user_prompt=user_prompt,
                response_schema=IDEA_PROPOSER_RESPONSE_SCHEMA,
            )
        elif hasattr(client, "generate_orchestrator_json"):
            raw = client.generate_orchestrator_json(
                model=model,
                system_instruction=IDEA_PROPOSER_SYSTEM_INSTRUCTION,
                user_prompt=user_prompt,
                response_schema=IDEA_PROPOSER_RESPONSE_SCHEMA,
            )
        elif hasattr(client, "generate_json"):
            sig = inspect.signature(client.generate_json)
            if "fallback_model" in sig.parameters:
                raw, used_model = client.generate_json(
                    user_prompt,
                    IDEA_PROPOSER_RESPONSE_SCHEMA,
                    model=model,
                    system_instruction=IDEA_PROPOSER_SYSTEM_INSTRUCTION,
                    thinking_level="low",
                    fallback_model=self._fallback_model,
                )
            else:
                raw = client.generate_json(
                    model=model,
                    system_instruction=IDEA_PROPOSER_SYSTEM_INSTRUCTION,
                    prompt=user_prompt,
                    schema=IDEA_PROPOSER_RESPONSE_SCHEMA,
                )
        elif callable(client):
            raw = client(
                model=model,
                system_instruction=IDEA_PROPOSER_SYSTEM_INSTRUCTION,
                user_prompt=user_prompt,
                response_schema=IDEA_PROPOSER_RESPONSE_SCHEMA,
            )
        else:
            raise TypeError(f"Unsupported AI client type: {type(client)!r}")

        if isinstance(raw, str):
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise TypeError("Idea proposer response JSON root must be an object")
            return parsed, used_model
        if isinstance(raw, Mapping):
            return dict(raw), used_model
        raise TypeError(f"Unexpected idea proposer response type: {type(raw)!r}")

    def propose(
        self,
        holdings: Sequence[PortfolioItem],
        issues: Sequence[PortfolioIssue | MetricFact | Mapping[str, Any]] = (),
        *,
        universe: Sequence[EtfUniverseEntry] = PINNED_ETF_UNIVERSE,
        analysis: AnalysisResponse | None = None,
        dependency_metrics: Sequence[MetricFact] = (),
        exposures: Sequence[CompanyExposure] = (),
        edges: Sequence[VerifiedEdge] = (),
        cache_only: bool = False,
        timeout_s: float = 90.0,
    ) -> IdeaProposerResult:
        """Propose up to 5 ETF changes with Argon (Flash fallback) and verify their structure & rationales."""
        coerced_issues = _coerce_issues(issues, analysis=analysis, dependency_metrics=dependency_metrics)
        if not holdings or not coerced_issues:
            return IdeaProposerResult(
                ai_status="not_used",
                model=None,
                prompt_version=self.prompt_version,
                proposals=[],
                rejected_proposals=[],
            )

        cached_res = self.read_cached(
            holdings,
            coerced_issues,
            universe=universe,
            analysis=analysis,
            dependency_metrics=dependency_metrics,
            exposures=exposures,
            edges=edges,
        )
        if cached_res is not None:
            return cached_res

        api_key = self._resolve_api_key()
        is_offline = bool(self._settings and self._settings.offline) and self._ai_client is None
        client_missing_key = (
            self._ai_client is not None
            and hasattr(self._ai_client, "has_api_key")
            and not self._ai_client.has_api_key
        )
        has_transport = (
            (self._ai_client is not None and not client_missing_key)
            or (self._http_client is not None and bool(api_key))
        )

        if cache_only or is_offline or not has_transport:
            status: IdeaAiStatus = (
                "missing_api_key"
                if (not api_key and not cache_only and (self._ai_client is None or client_missing_key))
                else "not_used"
            )
            return IdeaProposerResult(
                ai_status=status,
                model=None,
                prompt_version=self.prompt_version,
                proposals=[],
                rejected_proposals=[],
            )

        user_prompt = build_idea_proposer_prompt(holdings, coerced_issues, universe)
        cache_key = compute_idea_proposer_cache_key(
            holdings,
            coerced_issues,
            prompt_ver=self.prompt_version,
            model=self._model,
            user_prompt=user_prompt,
        )

        used_model = self._model
        raw_payload: dict[str, Any] | None = None
        last_exc: Exception | None = None

        try:
            raw_payload, used_model = self._call_ai_client(
                self._model, user_prompt, timeout_s=timeout_s
            )
        except GeminiQuotaError as exc:
            last_exc = exc
            if self._fallback_model and self._fallback_model != self._model:
                try:
                    raw_payload, used_model = self._call_ai_client(
                        self._fallback_model, user_prompt, timeout_s=timeout_s
                    )
                except Exception as fb_exc:  # noqa: BLE001
                    last_exc = fb_exc
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if (
                self._fallback_model
                and self._fallback_model != self._model
                and any(
                    tok in str(exc).lower()
                    for tok in ("429", "quota", "rate", "resource_exhausted", "overloaded")
                )
            ):
                try:
                    raw_payload, used_model = self._call_ai_client(
                        self._fallback_model, user_prompt, timeout_s=timeout_s
                    )
                except Exception as fb_exc:  # noqa: BLE001
                    last_exc = fb_exc

        if raw_payload is None:
            is_timeout = isinstance(last_exc, TimeoutError) or (
                last_exc is not None and "timeout" in str(last_exc).lower()
            )
            if isinstance(last_exc, GeminiError) and "timeout" in str(last_exc).lower():
                is_timeout = True
            return IdeaProposerResult(
                ai_status="timeout" if is_timeout else "failed",
                model=used_model,
                prompt_version=self.prompt_version,
                proposals=[],
                rejected_proposals=[],
            )

        exp = exposures or (analysis.exposures if analysis is not None else ())
        etf_ctx = analysis.etfs if analysis is not None else holdings
        verified, rejected = verify_raw_proposals(
            raw_payload,
            holdings=holdings,
            issues=coerced_issues,
            universe=universe,
            exposures=exp,
            edges=edges,
            etfs=etf_ctx,
        )
        if verified:
            self._write_cache(cache_key, model=used_model, raw_payload=raw_payload)

        return IdeaProposerResult(
            ai_status="ok",
            model=used_model,
            prompt_version=self.prompt_version,
            proposals=verified,
            rejected_proposals=rejected,
        )


def propose_change_ideas(
    holdings: Sequence[PortfolioItem],
    issues: Sequence[PortfolioIssue | MetricFact | Mapping[str, Any]] = (),
    *,
    universe: Sequence[EtfUniverseEntry] = PINNED_ETF_UNIVERSE,
    analysis: AnalysisResponse | None = None,
    dependency_metrics: Sequence[MetricFact] = (),
    exposures: Sequence[CompanyExposure] = (),
    edges: Sequence[VerifiedEdge] = (),
    ai_client: Any | None = None,
    http_client: Any | None = None,
    settings: Settings | None = None,
    cache_dir: Path | str | None = None,
    model: str | None = None,
    cache_only: bool = False,
    timeout_s: float = 90.0,
) -> IdeaProposerResult:
    """Module-level convenience wrapper around `IdeaProposer.propose`."""
    proposer = IdeaProposer(
        http_client=http_client,
        settings=settings,
        ai_client=ai_client,
        cache_dir=cache_dir,
        model=model,
    )
    return proposer.propose(
        holdings,
        issues,
        universe=universe,
        analysis=analysis,
        dependency_metrics=dependency_metrics,
        exposures=exposures,
        edges=edges,
        cache_only=cache_only,
        timeout_s=timeout_s,
    )
