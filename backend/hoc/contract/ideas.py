"""FIX-17: AI/rules ETF ideas verified by Python. Additive, lead-approved contract."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .api import PortfolioItem
from .compare import ConcentrationDelta, MetricDelta
from .dependencies import DEFAULT_TOP_N, UnanalysedCompany
from .units import ALLOCATION_TOLERANCE, wsum


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChangeIdeasRequest(_Model):
    holdings: Annotated[list[PortfolioItem], Field(min_length=1, max_length=50)]
    top_n: Annotated[int, Field(ge=1, le=30)] = DEFAULT_TOP_N


class ChangeIdea(_Model):
    idea_id: str
    ticker: str
    etf_name: str
    add_fraction: Literal[0.1, 0.2, 0.3]
    proposed_by: Literal["ai", "rules"] = "rules"
    action: Literal["add", "swap"] = "add"
    swap_from: str | None = None
    rationale: str | None = None
    """Verified text with every numeric placeholder rendered by Python."""
    addresses: Literal["top_sector", "dependency", "top10", "effective_n"]
    metric_id: str | None = None
    """The dep.<key> when addresses is dependency, otherwise null."""
    title: str
    reason: str
    holdings: Annotated[list[PortfolioItem], Field(min_length=1, max_length=50)]
    """Complete scenario; add scales existing holdings, swap moves a portfolio fraction."""
    concentration_deltas: list[ConcentrationDelta]
    biggest_dependency_delta: MetricDelta | None = None
    status: Literal["ok", "partial"]
    candidate_unanalysed: list[UnanalysedCompany] = []
    notes: list[str] = []

    @field_validator("title")
    @classmethod
    def short_title(cls, value: str) -> str:
        if not value.strip() or len(value.split()) > 8 or any(c.isdigit() for c in value):
            raise ValueError("title must have one to eight words and no digits")
        return value

    @model_validator(mode="after")
    def consistent_idea(self) -> ChangeIdea:
        if self.action == "swap":
            if not self.swap_from or self.swap_from == self.ticker:
                raise ValueError("swap requires a different source ETF")
        elif self.swap_from is not None:
            raise ValueError("add cannot have a swap source")
        if self.addresses == "dependency":
            if not self.metric_id or not self.metric_id.startswith("dep.") or self.metric_id == "dep.":
                raise ValueError("dependency ideas require a dep.* metric_id")
            if self.biggest_dependency_delta is None or self.biggest_dependency_delta.metric_id != self.metric_id:
                raise ValueError("dependency delta must match the addressed metric_id")
        elif self.metric_id is not None:
            raise ValueError("metric_id must be null for concentration ideas")
        if abs(wsum(h.allocation for h in self.holdings) - 1) > ALLOCATION_TOLERANCE:
            raise ValueError("idea holdings must sum to one")
        return self


class RejectedIdeaProposal(_Model):
    ticker: str
    action: str
    reason: str


class ChangeIdeasResponse(_Model):
    status: Literal["ok", "partial"]
    ideas: Annotated[list[ChangeIdea], Field(max_length=3)] = []
    notes: list[str] = []
    ai_status: Literal["ok", "pending", "missing_api_key", "failed", "timeout", "not_used"] = "not_used"
    model: str | None = None
    prompt_version: str | None = None
    rejected_proposals: list[RejectedIdeaProposal] = []
