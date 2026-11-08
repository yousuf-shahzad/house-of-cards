"""AI proposals are untrusted: Python verifies actions, gains, text and trade-offs."""
from dataclasses import replace

import pytest

from hoc.contract import Sector
from hoc.graph.idea_proposer import (
    EtfUniverseEntry,
    IdeaProposerResult,
    RawIdeaProposal,
    build_portfolio_issues,
)
from hoc.portfolio.ideas import (
    baseline_idea_metrics,
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
    {'title': 'Add 20 percent'}, {'title': 'Add MSFT'},
])
def test_invalid_proposals_are_explained_and_fall_back_to_rules(updates):
    request, baseline, loaded, scenarios = setup()
    proposal = proposal_for(request, baseline, loaded, **updates)
    result = verify(request, baseline, loaded, scenarios, [proposal])
    assert result.rejected_proposals and result.rejected_proposals[0].reason
    assert result.ideas and all(i.proposed_by == 'rules' for i in result.ideas)


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


def test_every_ai_proposal_is_accounted_for_in_selected_or_rejected_results():
    request, baseline, loaded, scenarios = setup()
    proposals = [proposal_for(request, baseline, loaded, ticker=t)
                 for t in loaded if t != 'ZZBASE']
    proposals.append(replace(proposals[0], fraction=.1))
    result = verify(request, baseline, loaded, scenarios, proposals)
    assert len(result.ideas) == 3 and all(i.proposed_by == 'ai' for i in result.ideas)
    assert len(result.rejected_proposals) == 2
    assert len(result.ideas) + len(result.rejected_proposals) == len(proposals)
    assert len({i.ticker for i in result.ideas}) == 3
