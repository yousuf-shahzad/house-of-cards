"""FIX-17: verify AI ETF changes and rank rules using a verified cache snapshot.

ETF loading belongs to the service. These functions only use supplied holdings/analyses
and compare_portfolios; unavailable dependency metrics retain compare's null semantics.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
    MetricFact,
    PortfolioItem,
    PortfolioRequest,
    RejectedIdeaProposal,
    Sector,
    VerifiedEdge,
    wsum,
)
from hoc.identity.resolver import Aliases

from .analyse import analyse
from .compare import compare_portfolios

if TYPE_CHECKING:
    from hoc.graph.idea_proposer import EtfUniverseEntry, IdeaProposerResult, RawIdeaProposal

# Stable candidate order; source failures are skipped, never replaced by invented data.
IDEA_TICKERS = ("RSP", "IWD", "IEFA", "IWM", "XLV", "XLP", "XLU")
CHANGE_IDEA_CANDIDATES = IDEA_TICKERS
ADD_FRACTIONS = (0.1, 0.2)
INDUSTRY_THRESHOLD = 0.4
EPSILON = 1e-9
# Half a percentage point of portfolio exposure; never a relative percentage.
WORSENING_TOLERANCE = 0.005
FUND_ADDITIONS = {
    "RSP": "equal-weight companies", "IWD": "value companies", "IEFA": "international companies",
    "IWM": "smaller companies", "XLV": "health care", "XLP": "consumer staples", "XLU": "utilities",
}
REJECTION_REASONS = {
    "outside_universe": "The ETF is outside the supported universe.",
    "invalid_action": "The action must be add or swap.",
    "invalid_fraction": "The fraction must be ten, twenty or thirty percent.",
    "add_has_swap_source": "An add cannot move money from a swap source.",
    "invalid_swap_source": "A swap must move money from a different ETF you hold.",
    "insufficient_swap_allocation": "The source ETF has insufficient allocation for this swap.",
    "candidate_unavailable": "The proposed ETF's holdings are unavailable.",
    "insufficient_company_holdings": "Too little of the ETF has usable company holdings.",
    "current_holdings_unavailable": "Some current ETF holdings are unavailable.",
    "too_many_etfs": "The change would exceed the portfolio's ETF limit.",
    "unknown_or_mismatched_issue": "The proposal does not name a matching portfolio issue.",
    "unknown_cited_metric": "The rationale cites an unknown metric.",
    "invalid_title": "The title must be short and contain no numbers.",
    "sector_coverage_decreased": "New missing industry labels cannot count as a diversification gain.",
    "addressed_dependency_unknown": "The addressed dependency cannot be measured on both sides.",
    "no_measurable_gain": "The change does not measurably improve the issue it names.",
    "already_held_ticker": "The proposed ETF is already in your portfolio.",
    "unknown_issue_id": "The proposal names an unknown portfolio issue.",
    "unknown_metric_id": "The rationale includes an unknown metric placeholder.",
    "unverified_literal_number": "The rationale includes a number that Python did not supply.",
    "forbidden_jargon_or_trade_verb": "The rationale uses unsupported jargon or a trading instruction.",
    "rationale_too_long": "The rationale is too long.",
    "empty_rationale": "The rationale is empty.",
    "unexpanded_placeholder": "The rationale includes an invalid metric placeholder.",
}


def _explain_rejection(reason: str) -> str:
    code, _, detail = reason.partition(":")
    if code == "unknown_entity":
        return f"The text names an unsupported company or name: {detail}."
    if code in ("unknown_ticker_in_rationale", "unknown_ticker_in_title"):
        return f"The text names an unsupported ticker: {detail}."
    if code == "unsupported_fraction":
        return REJECTION_REASONS["invalid_fraction"]
    if code in ("unknown_swap_source", "swap_fraction_exceeds_holding"):
        return REJECTION_REASONS["invalid_swap_source" if code == "unknown_swap_source"
                                 else "insufficient_swap_allocation"]
    return REJECTION_REASONS.get(code, reason)


@dataclass(frozen=True)
class IdeaScenario:
    ticker: str
    etf_name: str
    add_fraction: float
    analysis: AnalysisResponse
    proposal: RawIdeaProposal | None = None


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


def _sector_data_preserved(before: AnalysisResponse, after: AnalysisResponse) -> bool:
    """Missing industry labels must not create an apparent diversification gain."""
    def known_share(analysis):
        covered = analysis.coverage.covered_weight
        return analysis.coverage.sector_known_weight / covered if covered > 0 else 0

    return known_share(after) + EPSILON >= known_share(before)


def baseline_idea_metrics(request: ChangeIdeasRequest, baseline: AnalysisResponse,
                          cached: Mapping[str, Sequence[VerifiedEdge]], *, aliases: Aliases | None = None
                          ) -> list[MetricFact]:
    """Facts for the proposer; the same cache-only arithmetic used by the verifier."""
    result = compare_portfolios(
        CompareRequest(baseline=request.holdings, candidate=request.holdings, top_n=request.top_n),
        baseline, baseline, cached, aliases=aliases,
    )
    return [MetricFact(metric_id=d.metric_id, label=d.label, value=d.baseline, unit=d.unit)
            for d in _dependencies(result) if d.baseline is not None]


def build_proposal_scenarios(
    request: ChangeIdeasRequest, baseline: AnalysisResponse, loaded: Mapping[str, EtfHoldings],
    proposals: Sequence[RawIdeaProposal], universe: Sequence[EtfUniverseEntry],
) -> tuple[list[IdeaScenario], list[RejectedIdeaProposal]]:
    """Validate actions independently of the model, then build exact portfolio allocations."""
    allowed = {entry.ticker for entry in universe}
    current = {h.ticker: h.allocation for h in request.holdings}
    scenarios, rejected = [], []
    for proposal in proposals[:5]:
        reason = None
        if proposal.ticker not in allowed:
            reason = "outside_universe"
        elif proposal.ticker in current:
            reason = "already_held_ticker"
        elif proposal.action not in ("add", "swap"):
            reason = "invalid_action"
        elif proposal.fraction not in (0.1, 0.2, 0.3):
            reason = "invalid_fraction"
        elif proposal.action == "add" and proposal.swap_from is not None:
            reason = "add_has_swap_source"
        elif proposal.action == "swap" and (proposal.swap_from not in current
                                             or proposal.swap_from == proposal.ticker):
            reason = "invalid_swap_source"
        elif proposal.action == "swap" and current[proposal.swap_from] + EPSILON < proposal.fraction:
            reason = "insufficient_swap_allocation"
        elif proposal.ticker not in loaded:
            reason = "candidate_unavailable"
        elif loaded[proposal.ticker].holdings_weight < 0.95:
            reason = "insufficient_company_holdings"
        elif baseline.coverage.missing_allocation > 0:
            reason = "current_holdings_unavailable"
        if reason is None:
            if proposal.action == "add":
                total = wsum(current.values())
                weights = {t: a / total * (1 - proposal.fraction) for t, a in current.items()}
            else:
                weights = dict(current)
                weights[proposal.swap_from] = max(0.0, weights[proposal.swap_from] - proposal.fraction)
            weights[proposal.ticker] = wsum([weights.get(proposal.ticker, 0), proposal.fraction])
            weights = {t: a for t, a in weights.items() if a > EPSILON}
            if len(weights) > MAX_ETFS:
                reason = "too_many_etfs"
        if reason is not None:
            rejected.append(RejectedIdeaProposal(ticker=proposal.ticker, action=proposal.action,
                                                 reason=_explain_rejection(reason)))
            continue
        items = [PortfolioItem(ticker=t, allocation=a) for t, a in sorted(weights.items())]
        scenario = analyse(PortfolioRequest(holdings=items), loaded, {}, today=baseline.generated_at.date(),
                           generated_at=baseline.generated_at)
        scenarios.append(IdeaScenario(proposal.ticker, loaded[proposal.ticker].etf_name,
                                      proposal.fraction, scenario, proposal))
    return scenarios, rejected


def _industry_reason(before: AnalysisResponse, after: AnalysisResponse, old: float, new: float) -> str:
    def largest(analysis):
        return min((s for s in analysis.sectors if s.sector != Sector.unknown),
                   key=lambda s: (-s.weight, s.sector))

    old_sector, new_sector = largest(before), largest(after)
    old_name = _sector_name(old_sector.sector)
    new_name = _sector_name(new_sector.sector)
    if old_sector.sector == new_sector.sector:
        return f"Your largest industry, {old_name}, would fall from {old:.1%} to {new:.1%}."
    return f"Your largest industry would change from {old_name} at {old:.1%} to {new_name} at {new:.1%}."


def _sector_name(sector: Sector) -> str:
    return "Technology" if sector == Sector.information_technology else sector.value.replace("_", " ").title()


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
    addresses = ("top_sector" if sector >= INDUSTRY_THRESHOLD
                 else biggest[0].metric_id if biggest else "top10")
    results, rejected = [], []
    for scenario in scenarios:
        proposal = scenario.proposal

        def reject(reason, proposal=proposal, scenario=scenario):
            if proposal is not None:
                rejected.append(RejectedIdeaProposal(ticker=scenario.ticker, action=proposal.action,
                                                     reason=_explain_rejection(reason)))

        result = compare_portfolios(
            CompareRequest(baseline=request.holdings, candidate=scenario.analysis.request.holdings,
                           top_n=request.top_n), baseline, scenario.analysis, cached, aliases=aliases,
        )
        concentration = {d.name: d for d in result.concentration_deltas}
        dependency = {d.metric_id: d for d in _dependencies(result)}
        effective_gain = concentration["effective_n"].delta
        issue = proposal.issue_id if proposal is not None else addresses
        rationale = None
        if proposal is not None:
            from hoc.graph.idea_proposer import build_portfolio_issues, verify_and_render_proposal_rationale

            facts = baseline_idea_metrics(request, baseline, cached, aliases=aliases)
            issues = build_portfolio_issues(baseline, facts)
            # Render rationale values on the same shared comparison window as the
            # displayed deltas, which may include baseline sources below top N.
            issue_facts = {}
            for fact in issues:
                measured = dependency.get(fact.issue_id) or concentration.get(fact.issue_id)
                value = measured.baseline if measured is not None else fact.value
                if value is not None:
                    issue_facts[fact.metric_id] = MetricFact(metric_id=fact.metric_id, label=fact.label,
                                                           value=value, unit=fact.unit)
            named = next((i for i in issues if i.issue_id == issue), None)
            if (named is None or proposal.addresses != named.addresses
                    or proposal.metric_id != (issue if issue.startswith("dep.") else None)):
                reject("unknown_or_mismatched_issue")
                continue
            if any(mid not in issue_facts for mid in proposal.cited_metric_ids):
                reject("unknown_cited_metric")
                continue
            from hoc.graph.orchestrator import build_allowed_vocabulary

            allowed_tickers, allowed_entities = build_allowed_vocabulary(
                baseline.exposures, [e for edges in cached.values() for e in edges], baseline.etfs,
            )
            allowed_tickers |= {h.ticker for h in request.holdings} | {scenario.ticker}
            allowed_entities |= {c.company_name for c in baseline.exposures} | {
                baseline_sector.sector.value.replace("_", " ").title() for baseline_sector in baseline.sectors
            } | {scenario.etf_name, *(i.label for i in issues)}
            rationale, error = verify_and_render_proposal_rationale(
                proposal.rationale_template, metrics_by_id=issue_facts,
                allowed_tickers=allowed_tickers, allowed_entities=allowed_entities,
            )
            if error is not None or not rationale:
                reject(_explain_rejection(error or "empty_rationale"))
                continue
            if (not proposal.title.strip() or len(proposal.title.split()) > 8
                    or any(c.isdigit() for c in proposal.title)):
                reject("invalid_title")
                continue
            # Check the title through the same name/number lock as the rationale.
            _, error = verify_and_render_proposal_rationale(
                proposal.title, metrics_by_id=issue_facts,
                allowed_tickers=allowed_tickers, allowed_entities=allowed_entities,
            )
            if error is not None:
                reject(_explain_rejection(error))
                continue
            if not _sector_data_preserved(baseline, scenario.analysis):
                reject("sector_coverage_decreased")
                continue
            if (concentration["top_sector"].baseline > 0
                    and concentration["top_sector"].delta > WORSENING_TOLERANCE + EPSILON):
                largest = max((s for s in scenario.analysis.sectors if s.sector != Sector.unknown),
                              key=lambda s: s.weight)
                name = _sector_name(largest.sector)
                reject(f"Would raise the largest industry, {name}, by "
                       f"{concentration['top_sector'].delta * 100:.1f} pts.")
                continue
            before_dep = max((d.baseline for d in dependency.values() if d.baseline is not None), default=0)
            after_dep = max((d.candidate for d in dependency.values() if d.candidate is not None), default=0)
            if after_dep > before_dep + WORSENING_TOLERANCE + EPSILON:
                top_dep = max((d for d in dependency.values() if d.candidate is not None),
                              key=lambda d: d.candidate)
                reject(f"Would raise the top dependency ({top_dep.label}) by "
                       f"{(after_dep - before_dep) * 100:.1f} pts.")
                continue
        if issue.startswith("dep."):
            metric = dependency.get(issue)
            if metric is None or metric.delta is None:
                reject("addressed_dependency_unknown")
                continue
            improvement = -metric.delta
            label = f"Your {metric.label[:1].lower()}{metric.label[1:]}"
            old, new = metric.baseline, metric.candidate
        else:
            if issue == "top_sector" and not _sector_data_preserved(baseline, scenario.analysis):
                continue
            metric = concentration[issue]
            improvement = metric.delta if issue == "effective_n" else -metric.delta
            label = ("Your largest industry's share" if issue == "top_sector" else "Your effective company count"
                     if issue == "effective_n" else "Your top ten companies' share")
            old, new = metric.baseline, metric.candidate
            # Small portfolios may have all exposure in their top ten on both sides.
            if proposal is None and issue == "top10" and abs(improvement) <= EPSILON and effective_gain > EPSILON:
                issue, improvement = "effective_n", effective_gain
                metric = concentration[issue]
                old, new, label = metric.baseline, metric.candidate, "Your effective company count"
        if improvement <= EPSILON:
            reject("no_measurable_gain")
            continue
        deps = sorted((d for d in dependency.values() if d.delta is not None),
                      key=lambda d: (-abs(d.delta), d.metric_id))
        holdings = scenario.analysis.request.holdings
        identity = json.dumps({"baseline": sorted((h.ticker, round(h.allocation, 10)) for h in request.holdings),
                               "holdings": sorted((h.ticker, round(h.allocation, 10)) for h in holdings),
                               "top_n": request.top_n, "issue": issue,
                               "action": proposal.action if proposal else "add"}, sort_keys=True)
        values = (f"{old:.1f} to {new:.1f}" if issue == "effective_n" else f"{old:.1%} to {new:.1%}")
        adds = FUND_ADDITIONS.get(scenario.ticker, scenario.etf_name)
        reason = (_industry_reason(baseline, scenario.analysis, old, new) if issue == "top_sector"
                  else f"{label} would {'rise' if issue == 'effective_n' else 'fall'} from {values}.")
        title = (proposal.title if proposal else f"Add {adds} ({scenario.ticker})"
                 if scenario.ticker in FUND_ADDITIONS else f"Add {scenario.ticker} to spread exposure")
        change = (f"Moves exposure from {proposal.swap_from} into {scenario.ticker}"
                  if proposal and proposal.action == "swap" else f"Adds {adds}")
        idea = ChangeIdea(
            idea_id="idea_" + hashlib.sha256(identity.encode()).hexdigest()[:16],
            ticker=scenario.ticker, etf_name=scenario.etf_name, add_fraction=scenario.add_fraction,
            addresses="dependency" if issue.startswith("dep.") else issue,
            metric_id=issue if issue.startswith("dep.") else None,
            proposed_by="ai" if proposal else "rules", action=proposal.action if proposal else "add",
            swap_from=proposal.swap_from if proposal else None, rationale=rationale,
            title=title, reason=f"{change}; {reason[:1].lower()}{reason[1:]}",
            holdings=holdings, concentration_deltas=result.concentration_deltas,
            biggest_dependency_delta=dependency[issue] if issue.startswith("dep.") else deps[0] if deps else None,
            status=result.status,
            candidate_unanalysed=result.candidate_unanalysed, notes=result.notes,
        )
        priority = 0 if issue == addresses else 1 if issue.startswith("dep.") else 2 if issue == "top10" else 3
        results.append((improvement, effective_gain, idea, priority))
    results.sort(key=lambda r: (r[3], r[2].addresses == "effective_n", -r[0], -r[1],
                                r[2].ticker, r[2].add_fraction))
    selected, seen = [], set()
    for _, _, idea, _ in results:
        if idea.ticker not in seen:
            selected.append(idea)
            seen.add(idea.ticker)
        if len(selected) == 3:
            break
    # Keep a useful broad alternative in the rules fallback when sector funds tie.
    broad = {"RSP", "IWD", "IEFA", "IWM"}
    if len(selected) == 3 and all(i.proposed_by == "rules" and i.ticker not in broad for i in selected):
        alternative = next((r[2] for r in results if r[2].ticker in broad), None)
        if alternative is not None:
            selected[-1] = alternative
    for _, _, idea, _ in results:
        if idea.proposed_by == "ai" and not any(idea is chosen for chosen in selected):
            explanation = ("Another proposal for this ETF ranked higher."
                           if any(idea.ticker == chosen.ticker for chosen in selected)
                           else "Other verified ideas ranked higher for your portfolio's issues.")
            rejected.append(RejectedIdeaProposal(ticker=idea.ticker, action=idea.action, reason=explanation))
    has_ai = any(s.proposal is not None for s in scenarios)
    method = ("Verifies AI ETF proposals" if has_ai
              else "Tests a fixed ETF shortlist at ten and twenty percent")
    messages = [(f"{method} using cached dependencies only; unknown dependencies are not zero. "
                 "Whole-share rounding can change these results."), *notes]
    if len(request.holdings) >= MAX_ETFS and not has_ai:
        messages.append(f"The portfolio already has the maximum of {MAX_ETFS} ETFs; no ETF can be added.")
    if baseline.coverage.missing_allocation > 0:
        messages.append("Some current ETF holdings are unavailable; ideas cannot be compared reliably.")
    if not selected:
        messages.append("No tested ETF measurably improved the selected issue with the available data.")
    return ChangeIdeasResponse(
        status="partial" if notes or baseline.coverage.missing_allocation > 0
        or any(i.status == "partial" for i in selected) else "ok", ideas=selected, notes=messages,
        rejected_proposals=rejected,
    )


def verify_change_ideas(
    request: ChangeIdeasRequest, baseline: AnalysisResponse, loaded: Mapping[str, EtfHoldings],
    cached: Mapping[str, Sequence[VerifiedEdge]], proposer_result: IdeaProposerResult,
    universe: Sequence[EtfUniverseEntry], *, fallback: ChangeIdeasResponse, aliases: Aliases | None = None,
) -> ChangeIdeasResponse:
    """Return verified AI ideas or rules, retaining the AI outcome and every rejection."""
    proposals = proposer_result.proposals if proposer_result.ai_status == "ok" else []
    scenarios, rejected = build_proposal_scenarios(request, baseline, loaded, proposals, universe)
    verified = rank_change_ideas(request, baseline, scenarios, cached, aliases=aliases)
    response = (verified if verified.ideas else fallback).model_copy(deep=True)
    response.ai_status = proposer_result.ai_status
    response.model = proposer_result.model
    response.prompt_version = proposer_result.prompt_version
    response.rejected_proposals = [RejectedIdeaProposal(ticker=r["ticker"], action=r["action"],
                                                       reason=_explain_rejection(r["reason"]))
                                   for r in proposer_result.rejected_proposals]
    response.rejected_proposals.extend([*rejected, *verified.rejected_proposals])
    return response
