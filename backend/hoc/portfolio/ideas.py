"""FIX-17: test a bounded ETF shortlist using one verified cache snapshot, with no AI.

ETF loading belongs to the service. These functions only use supplied holdings/analyses
and compare_portfolios; unavailable dependency metrics retain compare's null semantics.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from hoc.contract import (
    MAX_ETFS,
    AnalysisResponse,
    ChangeIdea,
    ChangeIdeasRequest,
    ChangeIdeasResponse,
    CompareRequest,
    CompareResponse,
    EtfHoldings,
    MetricDelta,
    PortfolioItem,
    PortfolioRequest,
    Sector,
    VerifiedEdge,
    wsum,
)
from hoc.identity.resolver import Aliases

from .analyse import analyse
from .compare import compare_portfolios

# Stable candidate order; source failures are skipped, never replaced by invented data.
IDEA_TICKERS = ("RSP", "IWD", "IEFA", "IWM", "XLV", "XLP", "XLU")
CHANGE_IDEA_CANDIDATES = IDEA_TICKERS
ADD_FRACTIONS = (0.1, 0.2)
INDUSTRY_THRESHOLD = 0.4
EPSILON = 1e-9


@dataclass(frozen=True)
class IdeaScenario:
    ticker: str
    etf_name: str
    add_fraction: float
    analysis: AnalysisResponse


def build_idea_scenarios(
    request: ChangeIdeasRequest,
    baseline: AnalysisResponse,
    loaded: Mapping[str, EtfHoldings],
    candidate_tickers: Sequence[str] = IDEA_TICKERS,
) -> list[IdeaScenario]:
    """Scale the current portfolio and add each new ETF at both tested fractions."""
    if len(request.holdings) >= MAX_ETFS or baseline.coverage.missing_allocation > 0:
        return []
    current = {item.ticker for item in request.holdings}
    scenarios = []
    for ticker in sorted(set(candidate_tickers) - current):
        etf = loaded.get(ticker)
        # A cash-heavy or empty fund cannot appear to diversify by removing exposure.
        if etf is None or etf.holdings_weight < 0.95:
            continue
        for fraction in ADD_FRACTIONS:
            total = wsum(item.allocation for item in request.holdings)
            items = [PortfolioItem(ticker=item.ticker, allocation=item.allocation / total * (1 - fraction))
                     for item in sorted(request.holdings, key=lambda h: h.ticker)]
            items.append(PortfolioItem(ticker=ticker, allocation=fraction))
            scenario = analyse(PortfolioRequest(holdings=items), loaded, {},
                               today=baseline.generated_at.date(), generated_at=baseline.generated_at)
            scenarios.append(IdeaScenario(ticker, etf.etf_name, fraction, scenario))
    return scenarios


def _dependencies(comparison: CompareResponse) -> list[MetricDelta]:
    return [d for d in comparison.dependency_deltas
            if d.metric_id.startswith("dep.") and d.unit == "fraction"]


def _known_sectors(analysis: AnalysisResponse) -> bool:
    return analysis.coverage.sector_known_weight >= 0.95 * analysis.coverage.covered_weight > 0


def rank_change_ideas(
    request: ChangeIdeasRequest,
    baseline: AnalysisResponse,
    scenarios: Sequence[IdeaScenario],
    cached: Mapping[str, Sequence[VerifiedEdge]],
    *,
    aliases: Aliases | None = None,
    notes: Sequence[str] = (),
) -> ChangeIdeasResponse:
    """Return at most three distinct ETFs improving the same baseline issue.

    Priority: largest industry >=40% with usable sector data, else largest cached
    dependency fraction, else top ten company exposure (effective N breaks ties).
    A missing dependency metric never counts as an improvement.
    """
    self_compare = compare_portfolios(
        CompareRequest(baseline=request.holdings, candidate=request.holdings, top_n=request.top_n),
        baseline, baseline, cached, aliases=aliases,
    )
    biggest = sorted((d for d in _dependencies(self_compare) if (d.baseline or 0) > 0),
                     key=lambda d: (-d.baseline, d.metric_id))
    sector = max((s.weight for s in baseline.sectors if s.sector != Sector.unknown), default=0)
    addresses = ("top_sector" if sector >= INDUSTRY_THRESHOLD and _known_sectors(baseline)
                 else biggest[0].metric_id if biggest else "top10")
    results = []
    for scenario in scenarios:
        result = compare_portfolios(
            CompareRequest(baseline=request.holdings, candidate=scenario.analysis.request.holdings,
                           top_n=request.top_n), baseline, scenario.analysis, cached, aliases=aliases,
        )
        concentration = {d.name: d for d in result.concentration_deltas}
        dependency = {d.metric_id: d for d in _dependencies(result)}
        effective_gain = concentration["effective_n"].delta
        issue = addresses
        if issue.startswith("dep."):
            metric = dependency.get(issue)
            if metric is None or metric.delta is None:
                continue
            improvement = -metric.delta
            label = f"Your {metric.label[:1].lower()}{metric.label[1:]}"
            old, new = metric.baseline, metric.candidate
        else:
            if issue == "top_sector" and not _known_sectors(scenario.analysis):
                continue
            metric = concentration[issue]
            improvement = -metric.delta
            label = "Your largest industry's share" if issue == "top_sector" else "Your top ten companies' share"
            old, new = metric.baseline, metric.candidate
            # Small portfolios may have all exposure in their top ten on both sides.
            if issue == "top10" and abs(improvement) <= EPSILON and effective_gain > EPSILON:
                issue, improvement = "effective_n", effective_gain
                metric = concentration[issue]
                old, new, label = metric.baseline, metric.candidate, "Your effective company count"
        if improvement <= EPSILON:
            continue
        deps = sorted((d for d in dependency.values() if d.delta is not None),
                      key=lambda d: (-abs(d.delta), d.metric_id))
        holdings = scenario.analysis.request.holdings
        identity = json.dumps({"baseline": sorted((h.ticker, round(h.allocation, 10)) for h in request.holdings),
                               "holdings": sorted((h.ticker, round(h.allocation, 10)) for h in holdings),
                               "top_n": request.top_n}, sort_keys=True)
        values = (f"{old:.1f} to {new:.1f}" if issue == "effective_n" else f"{old:.1%} to {new:.1%}")
        idea = ChangeIdea(
            idea_id="idea_" + hashlib.sha256(identity.encode()).hexdigest()[:16],
            ticker=scenario.ticker, etf_name=scenario.etf_name, add_fraction=scenario.add_fraction,
            addresses="dependency" if issue.startswith("dep.") else issue,
            metric_id=issue if issue.startswith("dep.") else None,
            title=f"Add {scenario.ticker} to spread exposure",
            reason=f"{label} would {'rise' if issue == 'effective_n' else 'fall'} from {values}.",
            holdings=holdings, concentration_deltas=result.concentration_deltas,
            biggest_dependency_delta=dependency[issue] if issue.startswith("dep.") else deps[0] if deps else None,
            status=result.status,
            candidate_unanalysed=result.candidate_unanalysed, notes=result.notes,
        )
        results.append((improvement, effective_gain, idea))
    results.sort(key=lambda r: (r[2].addresses == "effective_n", -r[0], -r[1], r[2].ticker, r[2].add_fraction))
    selected, seen = [], set()
    for _, _, idea in results:
        if idea.ticker not in seen:
            selected.append(idea)
            seen.add(idea.ticker)
        if len(selected) == 3:
            break
    messages = [("Tests a fixed ETF shortlist at ten and twenty percent using cached dependencies only; "
                 "unknown dependencies are not zero. Whole-share rounding can change these results."), *notes]
    if len(request.holdings) >= MAX_ETFS:
        messages.append(f"The portfolio already has the maximum of {MAX_ETFS} ETFs; no ETF can be added.")
    if baseline.coverage.missing_allocation > 0:
        messages.append("Some current ETF holdings are unavailable; ideas cannot be compared reliably.")
    if not selected:
        messages.append("No tested ETF measurably improved the selected issue with the available data.")
    return ChangeIdeasResponse(
        status="partial" if notes or baseline.coverage.missing_allocation > 0
        or any(i.status == "partial" for i in selected) else "ok", ideas=selected, notes=messages,
    )
