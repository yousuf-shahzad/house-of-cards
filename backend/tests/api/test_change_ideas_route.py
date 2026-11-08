"""FIX-17: real service/route with synthetic sources, forbidden AI, deadline and memo checks."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from hoc.api.app import create_app
from hoc.config import Settings
from hoc.contract import ChangeIdeasRequest

BASELINE = [{"ticker": "ZZAAA", "allocation": .6}, {"ticker": "ZZBBB", "allocation": .4}]


class ForbiddenPipeline:
    def __getattr__(self, name):
        raise AssertionError(f"change ideas touched the dependency pipeline: {name}")


@pytest.fixture
def ideas_service(make_service, monkeypatch, tmp_path):
    from dataclasses import replace

    service, source = make_service()
    service.settings = replace(service.settings, cache_dir=tmp_path / 'cache')
    service.dependency_pipeline = ForbiddenPipeline()
    service.research_runner = ForbiddenPipeline()
    monkeypatch.setattr("hoc.service.IDEA_TICKERS", ("ZZCCC", "ZZMISSING"))
    reads = []

    def cached(cache_dir, keys, **kwargs):
        reads.append(set(keys))
        return {}

    monkeypatch.setattr("hoc.service.read_cached_extractions", cached)
    return service, source, reads


def test_route_is_cache_only_returns_partial_skips_unavailable_and_memoises(ideas_service):
    service, _, reads = ideas_service
    client = TestClient(create_app(lambda: service, Settings()))
    first = client.post("/api/change-ideas", json={"holdings": BASELINE})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "partial" and len(body["ideas"]) == 1
    assert body["ideas"][0]["ticker"] == "ZZCCC"
    assert any("Skipped ZZMISSING" in note for note in body["notes"])
    assert reads and len(reads) == 1  # shared snapshot, not one disk scan per candidate/fraction
    second = client.post("/api/change-ideas", json={"holdings": list(reversed(BASELINE))})
    assert second.json() == body and len(reads) == 1


def test_invalid_current_portfolios_keep_analysis_error_codes(ideas_service):
    service, _, reads = ideas_service
    client = TestClient(create_app(lambda: service, Settings()))
    for holdings, code in (([{"ticker": "ZZAAA", "allocation": .2}], "ALLOCATION_SUM_INVALID"),
                           ([{"ticker": "ZZNOPE", "allocation": 1}], "UNKNOWN_TICKER")):
        response = client.post("/api/change-ideas", json={"holdings": holdings})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == code
    assert reads == []


def test_cold_slow_load_is_bounded_and_retry_reuses_inflight_result(ideas_service, monkeypatch):
    service, _, reads = ideas_service
    entered, release = threading.Event(), threading.Event()
    real = service.analyse

    def slow(request):
        entered.set()
        assert release.wait(2)
        return real(request)

    monkeypatch.setattr(service, "analyse", slow)
    monkeypatch.setattr("hoc.service.IDEAS_WAIT_SECONDS", .02)
    request = ChangeIdeasRequest(holdings=BASELINE)
    try:
        first = service.change_ideas(request)
        assert entered.is_set()
        assert first.status == "partial" and first.ideas == []
        assert "ZZCCC, ZZMISSING" in first.notes[0]
        assert len(service._ideas) == 1
    finally:
        release.set()
    monkeypatch.setattr("hoc.service.IDEAS_WAIT_SECONDS", 2)
    assert service.change_ideas(request).ideas
    assert len(reads) == 1


def test_concurrent_requests_share_one_computation(ideas_service):
    service, _, reads = ideas_service
    request = ChangeIdeasRequest(holdings=BASELINE)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.change_ideas(request), range(4)))
    assert all(result == results[0] for result in results)
    assert len(reads) == 1


def test_memo_expiry_refreshes_dependency_snapshot(ideas_service, monkeypatch):
    service, _, reads = ideas_service
    clock = [100.0]
    monkeypatch.setattr("hoc.service._clock", lambda: clock[0])
    request = ChangeIdeasRequest(holdings=BASELINE)
    service.change_ideas(request)
    service.change_ideas(request)
    assert len(reads) == 1
    clock[0] += 61
    service.change_ideas(request)
    assert len(reads) == 2


def test_current_sources_unavailable_is_503_and_incomplete_baseline_has_no_ideas(make_service, monkeypatch):
    monkeypatch.setattr("hoc.service.IDEA_TICKERS", ("ZZCCC",))
    monkeypatch.setattr("hoc.service.read_cached_extractions", lambda *a, **k: {})
    service, _ = make_service(unavailable=["ZZAAA", "ZZBBB"])
    client = TestClient(create_app(lambda: service, Settings()))
    response = client.post("/api/change-ideas", json={"holdings": BASELINE})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SOURCES_UNAVAILABLE"
    service, _ = make_service(unavailable=["ZZBBB"])
    requested = []
    original = service._load_many

    def load(tickers):
        requested.extend(tickers)
        return original(tickers)

    monkeypatch.setattr(service, "_load_many", load)
    response = service.change_ideas(ChangeIdeasRequest(holdings=BASELINE))
    assert response.status == "partial" and response.ideas == []
    assert "ZZCCC" not in requested


class DelayedIdeaProposer:
    prompt_version = 'SYNTHETIC-proposer-v1'

    def __init__(self, *, status='ok', fail=False, cached=None):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.status = status
        self.fail = fail
        self.cached = cached

    def read_cached(self, holdings, issues, **kwargs):
        return self.cached

    def propose(self, holdings, issues, **kwargs):
        from hoc.graph.idea_proposer import IdeaProposerResult, RawIdeaProposal
        self.calls += 1
        self.entered.set()
        assert self.release.wait(3)
        if self.fail:
            raise RuntimeError('SYNTHETIC-provider-error')
        issue = issues[0]
        return IdeaProposerResult(ai_status=self.status, model='SYNTHETIC-model',
                                   prompt_version=self.prompt_version, rejected_proposals=[], proposals=[
            RawIdeaProposal(action='add', ticker='ZZCCC', fraction=.2, swap_from=None,
                            issue_id=issue.issue_id, addresses=issue.addresses,
                            metric_id=issue.issue_id if issue.addresses == 'dependency' else None,
                            title='Add ZZCCC for broader exposure',
                            rationale_template='Consider broader exposure for the current '
                                               '{{metric:' + issue.metric_id + '}} share.',
                            cited_metric_ids=(issue.metric_id,))] if self.status == 'ok' else [])


def enable_ai(service, monkeypatch, proposer):
    from dataclasses import replace

    from hoc.graph.idea_proposer import EtfUniverseEntry
    service.settings = replace(service.settings, gemini_api_key='SYNTHETIC-test-key')
    service.idea_proposer = proposer
    monkeypatch.setattr('hoc.graph.idea_proposer.PINNED_ETF_UNIVERSE',
                        (EtfUniverseEntry('ZZCCC', 'SYNTHETIC ZZCCC', 'broad', 'unknown'),))


def wait_for_ai(service):
    future = next(iter(service._idea_ai_jobs.values()))[1]
    return future.result(timeout=3)


def test_pending_returns_rules_and_polling_reuses_one_background_job(ideas_service, monkeypatch):
    service, _, _ = ideas_service
    proposer = DelayedIdeaProposer()
    enable_ai(service, monkeypatch, proposer)
    request = ChangeIdeasRequest(holdings=BASELINE)
    try:
        first = service.change_ideas(request)
        assert first.ai_status == 'pending' and first.ideas
        assert all(i.proposed_by == 'rules' for i in first.ideas)
        assert proposer.entered.wait(2)
        for _ in range(3):
            assert service.change_ideas(request).ai_status == 'pending'
        assert proposer.calls == 1 and len(service._idea_ai_jobs) == 1
    finally:
        proposer.release.set()
    wait_for_ai(service)
    final = service.change_ideas(request)
    assert final.ai_status == 'ok' and final.ideas and final.ideas[0].proposed_by == 'ai'
    assert proposer.calls == 1
    # The response is isolated from memoised state.
    final.ideas.clear()
    assert service.change_ideas(request).ideas


@pytest.mark.parametrize('status', ['missing_api_key', 'timeout', 'failed'])
def test_background_ai_outcomes_preserve_rules(ideas_service, monkeypatch, status):
    service, _, _ = ideas_service
    proposer = DelayedIdeaProposer(status=status)
    enable_ai(service, monkeypatch, proposer)
    proposer.release.set()
    request = ChangeIdeasRequest(holdings=BASELINE)
    service.change_ideas(request)
    wait_for_ai(service)
    final = service.change_ideas(request)
    assert final.ai_status == status and final.ideas
    assert all(i.proposed_by == 'rules' for i in final.ideas)


def test_unexpected_background_error_is_failed_without_retrying_each_poll(ideas_service, monkeypatch):
    service, _, _ = ideas_service
    proposer = DelayedIdeaProposer(fail=True)
    enable_ai(service, monkeypatch, proposer)
    proposer.release.set()
    request = ChangeIdeasRequest(holdings=BASELINE)
    service.change_ideas(request)
    with pytest.raises(RuntimeError, match='SYNTHETIC-provider-error'):
        wait_for_ai(service)
    for _ in range(3):
        result = service.change_ideas(request)
        assert result.ai_status == 'failed' and result.ideas
        assert all('SYNTHETIC-provider-error' not in note for note in result.notes)
    assert proposer.calls == 1


def test_missing_key_returns_rules_without_starting_model_work(ideas_service):
    service, _, _ = ideas_service
    result = service.change_ideas(ChangeIdeasRequest(holdings=BASELINE))
    assert result.ai_status == 'missing_api_key' and result.ideas
    assert service._idea_ai_jobs == {}


def test_disk_proposals_replay_across_service_restart_without_key(make_service, monkeypatch, tmp_path):
    from dataclasses import replace

    from hoc.graph.idea_proposer import EtfUniverseEntry, IdeaProposer

    class Model:
        has_api_key = True
        calls = 0

        def generate_orchestrator_json(self, **kwargs):
            import json

            self.calls += 1
            issue = json.loads(kwargs['user_prompt'].split('\n\n', 1)[1])['issues'][0]
            return {'proposals': [{'action': 'add', 'ticker': 'ZZCCC', 'fraction': .2,
                                    'issue_id': issue['issue_id'], 'title': 'Add ZZCCC for broader exposure',
                                    'rationale': 'Consider broader exposure for ' + issue['placeholder'] + '.',
                                    'cited_metric_ids': [issue['metric_id']]}]}

    monkeypatch.setattr('hoc.service.IDEA_TICKERS', ('ZZCCC',))
    monkeypatch.setattr('hoc.service.read_cached_extractions', lambda *a, **k: {})
    monkeypatch.setattr('hoc.graph.idea_proposer.PINNED_ETF_UNIVERSE',
                        (EtfUniverseEntry('ZZCCC', 'SYNTHETIC ZZCCC', 'broad', 'unknown'),))
    first, _ = make_service()
    first.settings = replace(first.settings, cache_dir=tmp_path / 'cache', gemini_api_key='SYNTHETIC-test-key')
    model = Model()
    first.idea_proposer = IdeaProposer(settings=first.settings, ai_client=model)
    request = ChangeIdeasRequest(holdings=BASELINE)
    first.change_ideas(request)
    wait_for_ai(first)
    original = first.change_ideas(request)
    assert original.ai_status == 'ok' and original.ideas[0].proposed_by == 'ai', [r.model_dump() for r in original.rejected_proposals]
    assert model.calls == 1
    second, _ = make_service()
    second.settings = replace(second.settings, cache_dir=first.settings.cache_dir, gemini_api_key=None)
    second.idea_proposer = IdeaProposer(settings=second.settings)
    second.change_ideas(request)
    wait_for_ai(second)
    replay = second.change_ideas(request)
    assert replay.ai_status == 'ok' and replay.ideas[0].proposed_by == 'ai'
    assert replay.ideas == original.ideas and model.calls == 1
