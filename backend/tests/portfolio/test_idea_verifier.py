"""AI proposals are untrusted: Python verifies actions, gains, text and trade-offs."""
from dataclasses import replace

import pytest

from hoc.contract import ChangeIdeasRequest, PortfolioItem, PortfolioRequest, Sector
from hoc.graph.idea_proposer import (
    EtfUniverseEntry,
    IdeaProposerResult,
    RawIdeaProposal,
    build_portfolio_issues,
)
from hoc.portfolio.analyse import analyse
from hoc.portfolio.ideas import (
    baseline_idea_metrics,
    build_idea_scenarios,
    build_proposal_scenarios,
    rank_change_ideas,
    verify_change_ideas,
)
from tests.portfolio.test_compare import edge
from tests.portfolio.test_ideas import fund, setup


def proposal_for(request, baseline, loaded, cache=None, **updates):
    facts = baseline_idea_metrics(request, baseline, cache or {})
    issue = build_portfolio_issues(baseline, facts)[0]
    raw = RawIdeaProposal(action='add', ticker='ZZADD', fraction=.2, swap_from=None,
                          issue_id=issue.issue_id, addresses=issue.addresses,
                          metric_id=issue.issue_id if issue.addresses == 'dependency' else None,
                          title='Add ZZADD for broader exposure',
                          rationale_template='Consider broader exposure because the current share is '
                                             '{{metric:' + issue.metric_id + '}}.',
                          cited_metric_ids=(issue.metric_id,))
    return replace(raw, **updates)


def verify(request, baseline, loaded, scenarios, proposals, cache=None, status='ok'):
    cache = cache or {}
    universe = [EtfUniverseEntry(t, f'SYNTHETIC {t}', 'broad', 'unknown') for t in loaded]
    fallback = rank_change_ideas(request, baseline, scenarios, cache)
    result = IdeaProposerResult(ai_status=status, model='SYNTHETIC-model', prompt_version='synthetic-v1',
                                proposals=proposals, rejected_proposals=[])
    return verify_change_ideas(request, baseline, loaded, cache, result, universe, fallback=fallback)


def test_ai_add_and_swap_use_exact_allocations_and_python_rendered_rationale():
    request, baseline, loaded, scenarios = setup()
    proposal = proposal_for(request, baseline, loaded)
    for action, source, fraction in [('add', None, .2), ('swap', 'ZZBASE', .3)]:
        result = verify(request, baseline, loaded, scenarios,
                        [replace(proposal, action=action, swap_from=source, fraction=fraction)])
        assert len(result.ideas) == 1 and not result.rejected_proposals
        idea = result.ideas[0]
        assert (idea.proposed_by, idea.action, idea.swap_from) == ('ai', action, source)
        assert {h.ticker: h.allocation for h in idea.holdings} == {'ZZBASE': 1-fraction, 'ZZADD': fraction}
        assert '{{' not in idea.rationale and '51' in idea.rationale
        assert result.model == 'SYNTHETIC-model' and result.ai_status == 'ok'
        delta = next(d for d in idea.concentration_deltas if d.name == 'top_sector')
        assert delta.delta < 0


@pytest.mark.parametrize('updates', [
    {'ticker': 'ZZOUTSIDE'}, {'ticker': 'ZZBASE'}, {'fraction': .15}, {'fraction': float('nan')}, {'action': 'invented'},
    {'action': 'swap', 'swap_from': 'ZZNOTHELD'}, {'action': 'swap', 'swap_from': 'ZZADD'},
    {'swap_from': 'ZZBASE'}, {'issue_id': 'invented'}, {'metric_id': 'dep.invented'},
    {'rationale_template': 'This falls to 5%.'}, {'rationale_template': 'Use {{metric:invented}}.'},
    {'rationale_template': 'Adding ZZADD reduces reliance on Cyberdyne.'},
    {'rationale_template': ''}, {'rationale_template': '   '},
    {'title': 'Add 20 percent'}, {'title': 'Add MSFT'},
])
def test_invalid_proposals_are_explained_and_fall_back_to_rules(updates):
    request, baseline, loaded, scenarios = setup()
    proposal = proposal_for(request, baseline, loaded, **updates)
    result = verify(request, baseline, loaded, scenarios, [proposal])
    assert result.rejected_proposals and result.rejected_proposals[0].reason
    assert result.ideas and all(i.proposed_by == 'rules' for i in result.ideas)


@pytest.mark.parametrize('ticker,target,action,addresses,template', [
    ('VTV', 'OpenAI', 'swap', 'top_sector',
     ('Moving part of QQQ into large value companies led by financials cuts the '
      '{{metric:top_sector}} technology weight and reduces reliance on {{metric:dependency}}.')),
    ('SCHD', 'graphics processing units', 'add', 'dependency',
     ('Adding dividend-paying healthcare and consumer companies dilutes the '
      '{{metric:dependency}} reliance on chip hardware and cuts the {{metric:top_sector}} technology share.')),
])
def test_live_rationale_drops_keep_verified_ai_ideas_with_python_reason(ticker, target, action,
                                                                     addresses, template):
    base = fund('QQQ', [.51, .49], [Sector.information_technology, Sector.health_care])
    candidate = fund(ticker, [.01] * 100)
    loaded = {'QQQ': base, ticker: candidate}
    request = ChangeIdeasRequest(holdings=[PortfolioItem(ticker='QQQ', allocation=1)], top_n=30)
    baseline = analyse(PortfolioRequest(holdings=request.holdings), loaded, {},
                       today=base.as_of, generated_at=base.retrieved_at)
    scenarios = build_idea_scenarios(request, baseline, loaded, [ticker])
    cache = {holding.company_key: [] for etf in loaded.values() for holding in etf.holdings}
    cache['QQQ:0'] = [edge(source='QQQ:0', target=target, target_key=None)]
    dependency = next(f for f in baseline_idea_metrics(request, baseline, cache)
                      if f.metric_id.startswith('dep.') and f.unit == 'fraction')
    proposal = proposal_for(
        request, baseline, loaded, cache, ticker=ticker, action=action,
        swap_from='QQQ' if action == 'swap' else None, title=f'Consider {ticker} for broader exposure',
        issue_id=dependency.metric_id if addresses == 'dependency' else 'top_sector',
        addresses=addresses, metric_id=dependency.metric_id if addresses == 'dependency' else None,
        rationale_template=template.replace('{{metric:dependency}}', '{{metric:' + dependency.metric_id + '}}'),
        cited_metric_ids=('top_sector', dependency.metric_id),
    )

    result = verify(request, baseline, loaded, scenarios, [proposal], cache)

    assert not result.rejected_proposals
    assert len(result.ideas) == 1
    idea = result.ideas[0]
    assert (idea.ticker, idea.proposed_by, idea.action, idea.addresses) == (ticker, 'ai', action, addresses)
    assert idea.rationale is None
    metric = (idea.biggest_dependency_delta if addresses == 'dependency'
              else next(d for d in idea.concentration_deltas if d.name == 'top_sector'))
    expected_after = .408 if addresses == 'dependency' else .428
    assert (metric.baseline, metric.candidate) == pytest.approx((.51, expected_after))
    assert f'51.0% to {expected_after:.1%}' in idea.reason
    assert (target if addresses == 'dependency' else 'Technology') in idea.reason
    assert '{{' not in idea.reason


def test_swap_cannot_move_more_than_the_source_allocation_or_exceed_etf_limit():
    request, baseline, loaded, _ = setup()
    proposal = proposal_for(request, baseline, loaded, action='swap', swap_from='ZZBASE', fraction=.2)
    request.holdings = [request.holdings[0].model_copy(update={'allocation': .1}),
                        request.holdings[0].model_copy(update={'ticker': 'ZZOTHER', 'allocation': .9})]
    universe = [EtfUniverseEntry('ZZADD', 'Synthetic', 'broad', 'unknown')]
    scenarios, rejected = build_proposal_scenarios(request, baseline, loaded, [proposal], universe)
    assert not scenarios and 'insufficient' in rejected[0].reason.lower()


def test_ai_keeps_named_issue_no_gain_is_rejected_and_never_silently_changes_objective():
    base = fund('ZZBASE', [.51, .49], [Sector.information_technology, Sector.health_care], prefix='ZZ')
    added = base.model_copy(update={'etf_ticker': 'ZZADD'})
    request, baseline, loaded, scenarios = setup(base, [added])
    result = verify(request, baseline, loaded, scenarios, [proposal_for(request, baseline, loaded)])
    assert not result.ideas and result.rejected_proposals
    assert 'does not measurably improve' in result.rejected_proposals[0].reason


def test_ai_rejects_larger_known_dependency_even_when_industry_improves():
    candidate = fund('ZZADD', [.25] * 4)
    request, baseline, loaded, scenarios = setup(candidates=[candidate])
    cache = {key: [edge(source=key, target='ZZ Foundry', edge_id=key)]
             for key in ['ZZBASE:0', *[f'ZZADD:{i}' for i in range(4)]]}
    proposal = proposal_for(request, baseline, loaded, cache)
    result = verify(request, baseline, loaded, scenarios, [proposal], cache)
    assert all(i.proposed_by == 'rules' for i in result.ideas)
    assert any('top dependency' in r.reason and '9.8 pts' in r.reason for r in result.rejected_proposals)


def test_ai_rejects_larger_industry_even_when_company_concentration_improves():
    base = fund('ZZBASE', [.05] * 20)
    candidate = fund('ZZADD', [.01] * 100, [Sector.information_technology])
    request, baseline, loaded, scenarios = setup(base, [candidate])
    proposal = proposal_for(request, baseline, loaded)
    result = verify(request, baseline, loaded, scenarios, [proposal])
    assert any('largest industry' in r.reason and 'pts' in r.reason for r in result.rejected_proposals)


def test_industry_priority_matches_screen_even_with_incomplete_sector_coverage():
    base = fund('ZZBASE', [.51, .29, .2], [Sector.information_technology, Sector.health_care, Sector.unknown])
    base = base.model_copy(update={'sector_basis': 'fund_reported', 'sector_weights': {
        Sector.information_technology: .51, Sector.health_care: .29, Sector.unknown: .2}})
    request, baseline, _, scenarios = setup(base)
    assert baseline.coverage.sector_known_weight == pytest.approx(.8)
    result = rank_change_ideas(request, baseline, scenarios, {})
    assert result.ideas and all(i.addresses == 'top_sector' for i in result.ideas)


@pytest.mark.parametrize('status', ['missing_api_key', 'timeout', 'failed', 'not_used'])
def test_ai_failure_keeps_rules_and_metadata(status):
    request, baseline, loaded, scenarios = setup()
    result = verify(request, baseline, loaded, scenarios, [], status=status)
    assert result.ai_status == status and result.ideas
    assert all(i.proposed_by == 'rules' for i in result.ideas)


def test_effective_company_count_improvement_has_positive_direction():
    request, baseline, loaded, scenarios = setup(fund('ZZBASE', [.6, .4], [Sector.unknown]))
    proposal = proposal_for(request, baseline, loaded, issue_id='effective_n', addresses='effective_n',
                            metric_id=None, rationale_template='Consider a broader company mix.')
    result = verify(request, baseline, loaded, scenarios, [proposal])
    assert result.ideas and result.ideas[0].proposed_by == 'ai'
    assert result.ideas[0].addresses == 'effective_n'
    assert 'would rise' in result.ideas[0].reason


def test_unknown_candidate_industries_never_create_a_verified_gain():
    request, baseline, loaded, scenarios = setup(candidates=[fund('ZZADD', [.01] * 100, [Sector.unknown])])
    proposal = proposal_for(request, baseline, loaded)
    result = verify(request, baseline, loaded, scenarios, [proposal])
    assert not result.ideas and any('missing industry' in r.reason for r in result.rejected_proposals)
    assert "ZZADD's industry breakdown isn't available" in result.rejected_proposals[0].reason


@pytest.mark.parametrize('action,source', [('add', None), ('swap', 'ZZBASE')])
def test_ai_uses_fund_reported_industries_when_holding_labels_are_unavailable(action, source):
    candidate = fund('ZZADD', [.01] * 100, [Sector.unknown]).model_copy(update={
        'sector_basis': 'fund_reported', 'sector_weights': {Sector.financials: 1.0}})
    request, baseline, loaded, scenarios = setup(candidates=[candidate])
    proposal = proposal_for(request, baseline, loaded, action=action, swap_from=source)
    result = verify(request, baseline, loaded, scenarios, [proposal])
    assert not result.rejected_proposals
    assert result.ideas[0].proposed_by == 'ai'
    assert result.ideas[0].addresses == 'top_sector'
    delta = next(d for d in result.ideas[0].concentration_deltas if d.name == 'top_sector')
    assert (delta.baseline, delta.candidate) == pytest.approx((.51, .408))


@pytest.mark.parametrize('action,source', [('add', None), ('swap', 'ZZBASE')])
def test_partial_industries_can_pass_only_with_a_worst_case_gain(action, source):
    candidate = fund('ZZADD', [.98, .02], [Sector.financials, Sector.unknown])
    request, baseline, loaded, scenarios = setup(candidates=[candidate])
    proposal = proposal_for(request, baseline, loaded, action=action, swap_from=source)
    result = verify(request, baseline, loaded, scenarios, [proposal])
    assert not result.rejected_proposals
    assert result.ideas[0].proposed_by == 'ai'
    delta = next(d for d in result.ideas[0].concentration_deltas if d.name == 'top_sector')
    assert delta.baseline - delta.candidate - .2 * .02 > .005


@pytest.mark.parametrize('technology,unknown', [(.50, .02), (.48, .01), (.479, .01)])
def test_partial_industries_reject_a_gain_that_fails_the_worst_case_margin(technology, unknown):
    candidate = fund('ZZADD', [technology, 1-technology-unknown, unknown],
                     [Sector.information_technology, Sector.health_care, Sector.unknown])
    request, baseline, loaded, scenarios = setup(candidates=[candidate])
    result = verify(request, baseline, loaded, scenarios, [proposal_for(request, baseline, loaded)])
    assert not result.ideas
    assert "ZZADD's industry breakdown is incomplete" in result.rejected_proposals[0].reason
    assert '0.5 percentage points' in result.rejected_proposals[0].reason


def test_complete_candidate_does_not_get_an_unavailable_breakdown_explanation():
    candidate = fund('ZZADD', [.00995] * 100, [Sector.unknown]).model_copy(update={
        'sector_basis': 'fund_reported', 'sector_weights': {
            Sector.information_technology: .50745, Sector.health_care: .48755}})
    request, _, loaded, _ = setup(candidates=[candidate])
    loaded['ZZUNKNOWN'] = fund('ZZUNKNOWN', [.01] * 100, [Sector.unknown])
    request.holdings = [PortfolioItem(ticker='ZZBASE', allocation=.6),
                        PortfolioItem(ticker='ZZUNKNOWN', allocation=.4)]
    baseline = analyse(PortfolioRequest(holdings=request.holdings), loaded, {},
                       today=candidate.as_of, generated_at=candidate.retrieved_at)
    proposal = proposal_for(request, baseline, loaded, action='swap', swap_from='ZZBASE',
                            issue_id='top10', addresses='top10', metric_id=None,
                            rationale_template='Consider a broader company mix.')
    result = verify(request, baseline, loaded, [], [proposal])
    assert not result.ideas
    reason = result.rejected_proposals[0].reason
    assert "ZZADD's industry breakdown is available" in reason
    assert 'existing holdings with missing industry labels' in reason


def test_every_ai_proposal_is_accounted_for_in_selected_or_rejected_results():
    request, baseline, loaded, scenarios = setup()
    proposals = [proposal_for(request, baseline, loaded, ticker=t, title=f'Add {t} for broader exposure')
                 for t in loaded if t != 'ZZBASE']
    proposals.append(replace(proposals[0], fraction=.1))
    result = verify(request, baseline, loaded, scenarios, proposals)
    assert len(result.ideas) == 3 and all(i.proposed_by == 'ai' for i in result.ideas)
    assert len(result.rejected_proposals) == 2
    assert len(result.ideas) + len(result.rejected_proposals) == len(proposals)
    assert len({i.ticker for i in result.ideas}) == 3
