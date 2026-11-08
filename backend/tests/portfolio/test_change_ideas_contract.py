"""The additive FIX-17 contract and invented UI card variants, independent of the engine."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hoc.contract import ChangeIdea, ChangeIdeasRequest, ChangeIdeasResponse

FIXTURE = Path(__file__).resolve().parents[3] / "frontend/api/__fixtures__/synthetic-change-ideas.json"


def load_fixture():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert "SYNTHETIC" in data.pop("_comment")
    return ChangeIdeasResponse.model_validate(data)


def test_fixture_has_consistent_concentration_and_dependency_cards():
    response = load_fixture()
    assert {i.addresses for i in response.ideas} == {"top_sector", "dependency"}
    for idea in response.ideas:
        assert idea.ticker.startswith("ZZ") and idea.etf_name.startswith("SYNTHETIC")
        assert sum(h.allocation for h in idea.holdings) == pytest.approx(1)
        assert len({h.ticker for h in idea.holdings}) == len(idea.holdings)
        assert next(h for h in idea.holdings if h.ticker == idea.ticker).allocation == idea.add_fraction
        assert (idea.status == "partial") == bool(idea.candidate_unanalysed)
        for delta in idea.concentration_deltas:
            assert delta.delta == pytest.approx(delta.candidate - delta.baseline)
        if idea.addresses == "dependency":
            delta = idea.biggest_dependency_delta
            assert delta.metric_id == idea.metric_id
            assert delta.delta == pytest.approx(delta.candidate - delta.baseline)
            assert delta.delta < 0


def test_title_request_and_response_bounds():
    data = load_fixture().ideas[0].model_dump()
    for title in ("", "Add 20 percent", "one two three four five six seven eight nine"):
        with pytest.raises(ValidationError):
            ChangeIdea.model_validate({**data, "title": title})
    for top in (0, 31):
        with pytest.raises(ValidationError):
            ChangeIdeasRequest(holdings=data["holdings"], top_n=top)
    with pytest.raises(ValidationError):
        ChangeIdeasResponse(status="ok", ideas=[data] * 4)
    with pytest.raises(ValidationError):
        ChangeIdea.model_validate({**data, "add_fraction": .15})
    with pytest.raises(ValidationError):
        ChangeIdeasRequest(holdings=[])


def test_addressed_dependency_and_delta_must_agree():
    data = load_fixture().ideas[1].model_dump()
    for updates in ({"metric_id": None}, {"metric_id": "top_sector"}, {"metric_id": "dep."},
                    {"biggest_dependency_delta": None}, {"metric_id": "dep.different"},
                    {"addresses": "top_sector"}):
        with pytest.raises(ValidationError):
            ChangeIdea.model_validate({**data, **updates})
    with pytest.raises(ValidationError):
        ChangeIdea.model_validate({**data, "holdings": [{"ticker": "ZZBASE", "allocation": .2}]})


def test_ai_contract_defaults_pending_metadata_and_swap_consistency():
    data = load_fixture().ideas[0].model_dump()
    for field in ("proposed_by", "action", "swap_from", "rationale"):
        data.pop(field)
    legacy = ChangeIdea.model_validate(data)
    assert (legacy.proposed_by, legacy.action, legacy.swap_from, legacy.rationale) == ("rules", "add", None, None)
    swap = ChangeIdea.model_validate({**data, "proposed_by": "ai", "action": "swap", "swap_from": "ZZBASE",
                                     "add_fraction": .3, "rationale": "SYNTHETIC verified text"})
    assert swap.action == "swap" and swap.add_fraction == .3
    for updates in ({"action": "swap"}, {"action": "swap", "swap_from": data["ticker"]},
                    {"action": "add", "swap_from": "ZZBASE"}):
        with pytest.raises(ValidationError):
            ChangeIdea.model_validate({**data, **updates})
    response = ChangeIdeasResponse(status="ok", ai_status="pending", model="synthetic-model",
                                   prompt_version="synthetic-v1", ideas=[legacy], rejected_proposals=[
                                       {"ticker": "ZZBAD", "action": "invalid", "reason": "invalid_action"}])
    assert ChangeIdeasResponse.model_validate_json(response.model_dump_json()) == response
