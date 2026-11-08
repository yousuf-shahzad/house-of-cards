"""v3: before/after portfolio comparison (POST /api/compare). FROZEN.

Mirrored in frontend/api/types.ts. Rules (docs/hoc/PLAN-v3.md section 2):
- Synchronous and cache-only: it never calls Gemini or fetches filings; it reuses verified edges already
  extracted for each portfolio's top-N companies and recomputes metrics in Python.
- Companies in the candidate's top N with no cached extraction are listed in candidate_unanalysed, and the
  response status is 'partial', so the UI never implies they were checked.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .api import PortfolioItem
from .dependencies import DEFAULT_TOP_N, MetricUnit, UnanalysedCompany
from .units import Weight


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompareRequest(_Model):
    baseline: Annotated[list[PortfolioItem], Field(min_length=1, max_length=50)]
    """The current portfolio (fractions, like POST /api/analysis)."""
    candidate: Annotated[list[PortfolioItem], Field(min_length=1, max_length=50)]
    """The scenario to test."""
    top_n: Annotated[int, Field(ge=1, le=30)] = DEFAULT_TOP_N


class MetricDelta(_Model):
    metric_id: str
    """A dependency metric id (dep.*, critical.*, facility.*, spof.*)."""
    label: str
    unit: MetricUnit
    baseline: float | None = None
    """None when the metric does not exist for that portfolio."""
    candidate: float | None = None
    delta: float | None = None
    """candidate - baseline when both exist, else None."""


ConcentrationName = Literal["top5", "top10", "top20", "effective_n", "largest_company"]


class ConcentrationDelta(_Model):
    name: ConcentrationName
    baseline: Annotated[float, Field(allow_inf_nan=False)]
    candidate: Annotated[float, Field(allow_inf_nan=False)]
    delta: Annotated[float, Field(allow_inf_nan=False)]


class CompareResponse(_Model):
    status: Literal["ok", "partial"]
    """'partial' when candidate_unanalysed is non-empty."""
    baseline_top_n_weight: Weight
    candidate_top_n_weight: Weight
    dependency_deltas: list[MetricDelta] = []
    """Fraction metrics first, then count metrics; within each unit by |delta| largest first (a metric
    present on only one side sorts by its value), ties by metric_id."""
    concentration_deltas: list[ConcentrationDelta] = []
    candidate_unanalysed: list[UnanalysedCompany] = []
    notes: list[str] = []
    """Plain English, e.g. 'Dependencies for 2 new companies are unknown until you run Find dependencies'."""
