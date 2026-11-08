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
