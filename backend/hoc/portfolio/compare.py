"""Deterministic before/after comparison using verified extraction caches only (X-API).

The comparison receives completed portfolio analyses and an explicit cache snapshot. The
optional disk reader reads verified ``edges`` only; neither function invokes an extractor,
fetches a filing, or constructs a model client. An absent cache key means unknown, whereas
a present empty list means a completed extraction with no disclosed relationships.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping, Sequence
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from hoc.ai.cache import EXTRACTION_CACHE_NAMESPACE, make_extraction_cache_key
from hoc.contract import (
    AnalysisResponse,
    CompanyExposure,
    CompareRequest,
    CompareResponse,
    ConcentrationDelta,
    MetricDelta,
    MetricFact,
    PortfolioRequest,
    Sector,
    UnanalysedCompany,
    VerifiedEdge,
    wsum,
)
from hoc.contract.dependencies import CompanyStatus
from hoc.core.cache import DiskCache
from hoc.filings.names import NameResolver
from hoc.graph.metrics import compute_dependency_metrics
from hoc.identity.resolver import Aliases, load_aliases

from .validation import validate_request

METRIC_PREFIXES = ("dep.", "critical.", "facility.", "spof.")


def read_cached_extractions(
    cache_dir: Path,
    company_keys: Collection[str],
    *,
    models: Sequence[str],
    prompt_version: str,
) -> dict[str, list[VerifiedEdge]]:
    """Latest *cached* filing per company for the specified extractor version.

    Metadata filters the scan before any extraction body is read. Filing date, accession,
    then caller-supplied model preference break ties deterministically. Malformed or
    mismatched payloads are cache misses; raw/unverified predictions are never replayed.
    A newer SEC filing may exist: discovering it is deliberately outside this operation.
    """
    wanted = set(company_keys)
    priorities = {model: -index for index, model in reversed(list(enumerate(models)))}
    if not wanted or not priorities:
        return {}
    disk = DiskCache(Path(cache_dir))
    selected: dict[str, tuple[tuple[date, str, int], list[VerifiedEdge]]] = {}
    for path in sorted((disk.root / EXTRACTION_CACHE_NAMESPACE).glob("*.json")):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
            company, accession, model, version = meta["key"].split("|")
            if company not in wanted or model not in priorities or version != prompt_version:
                continue
            key = make_extraction_cache_key(company, accession, model, version)
            entry = disk.get(EXTRACTION_CACHE_NAMESPACE, key)
            if entry is None or entry.meta.get("status") != 200:
                continue
            payload = json.loads(entry.body)
            if (payload.get("company_key"), payload.get("accession"), payload.get("model"),
                    payload.get("prompt_version")) != (company, accession, model, version):
                continue
            filed = date.fromisoformat(payload["filed"])
            if not isinstance(payload.get("edges"), list):
                continue
            edges = [VerifiedEdge.model_validate(row) for row in payload["edges"]]
            if any(edge.source_company_key != company or edge.filing.company_key != company
                   or edge.filing.accession != accession or edge.filing.filed != filed for edge in edges):
                continue
            rank = (filed, accession, priorities[model])
            if company not in selected or rank > selected[company][0]:
                selected[company] = (rank, [edge for edge in edges if not _rejected(edge)])
        except (OSError, ValueError, KeyError, TypeError, AttributeError, ValidationError):
            continue
    return {company: selected[company][1] for company in sorted(selected)}


def _rejected(edge: VerifiedEdge) -> bool:
    return edge.interpretation is not None and edge.interpretation.status == "rejected"


def _top(analysis: AnalysisResponse, count: int) -> list[CompanyExposure]:
    return sorted((c for c in analysis.exposures if c.exposure > 0),
                  key=lambda c: (-c.exposure, c.company_key))[:count]


def _concentration_value(analysis: AnalysisResponse, name: str) -> float:
    if name == "effective_n":
        return analysis.concentration.effective_companies
    if name == "largest_company":
        return max((c.exposure for c in analysis.exposures), default=0.0)
    if name == "top_sector":
        return max((s.weight for s in analysis.sectors if s.sector != Sector.unknown), default=0.0)
    return getattr(analysis.concentration, name)


def _metrics(
    analysis: AnalysisResponse,
    top: Sequence[CompanyExposure],
    cached: Mapping[str, Sequence[VerifiedEdge]],
    aliases: Aliases,
) -> dict[str, MetricFact]:
    resolver = NameResolver(analysis.exposures, aliases)
    names = {c.company_key: c.company_name for c in analysis.exposures}
    resolved: dict[str, VerifiedEdge] = {}
    for company in top:
        for edge in cached.get(company.company_key, ()):
            if edge.source_company_key != company.company_key or _rejected(edge):
                continue
            # Cached resolutions and portfolio flags belong to the portfolio that wrote
            # them. Resolve company targets anew, even when the old key was non-null.
            target = resolver.resolve(edge.target_name) if edge.target_kind == "company" else edge.target_key
            resolved[edge.edge_id] = edge.model_copy(update={
                "target_key": target,
                "source_company_name": names[company.company_key],
                "source_in_portfolio": True,
                "target_in_portfolio": target in names,
            })
    edges = [resolved[key] for key in sorted(resolved)]
    return {m.metric_id: m for m in compute_dependency_metrics(top, edges)
            if m.metric_id.startswith(METRIC_PREFIXES)}


def compare_portfolios(
    request: CompareRequest,
    baseline: AnalysisResponse,
    candidate: AnalysisResponse,
    cached_extractions: Mapping[str, Sequence[VerifiedEdge]],
    *,
    aliases: Aliases | None = None,
    company_statuses: Mapping[str, CompanyStatus] | None = None,
) -> CompareResponse:
    """Compare analyses on the union of both top-N company sets and one cache snapshot.

    Caller runs the two ETF analyses and obtains the snapshot with
    ``read_cached_extractions``. Concentration uses the full analyses, independently of
    dependency selection. Each side uses its actual exposure for every selected company
    it holds, even below its own top N. The returned weights cover this shared window.
    Missing metric values remain None (including delta), per C0-v3.
    Optional known run statuses distinguish unavailable SEC filings from cache misses;
    this helper never discovers filing availability itself.
    """
    for holdings, analysis in ((request.baseline, baseline), (request.candidate, candidate)):
        validate_request(PortfolioRequest(holdings=holdings))
        if sorted((h.ticker, h.allocation) for h in holdings) != sorted(
            (h.ticker, h.allocation) for h in analysis.request.holdings
        ):
            raise ValueError("Compare analyses must correspond to the requested portfolios.")
    company_keys = {c.company_key for analysis in (baseline, candidate) for c in _top(analysis, request.top_n)}
    baseline_top = [c for c in _top(baseline, len(baseline.exposures)) if c.company_key in company_keys]
    candidate_top = [c for c in _top(candidate, len(candidate.exposures)) if c.company_key in company_keys]
    aliases = aliases if aliases is not None else load_aliases()
    before = _metrics(baseline, baseline_top, cached_extractions, aliases)
    after = _metrics(candidate, candidate_top, cached_extractions, aliases)
    deltas = []
    for metric_id in sorted(before.keys() | after.keys()):
        old, new = before.get(metric_id), after.get(metric_id)
        fact = new if new is not None else old
        deltas.append(MetricDelta(
            metric_id=metric_id, label=fact.label, unit=fact.unit,
            baseline=old.value if old is not None else None,
            candidate=new.value if new is not None else None,
            delta=wsum([new.value, -old.value]) if old is not None and new is not None else None,
        ))
    # Fractions describe portfolio exposure; counts must not outrank them by units alone.
    deltas.sort(key=lambda d: (d.unit != "fraction", -abs(d.delta if d.delta is not None else (
        d.candidate if d.candidate is not None else d.baseline
    )), d.metric_id))
    concentration_deltas = []
    for name in ("top5", "top10", "top20", "effective_n", "largest_company", "top_sector"):
        old_value = _concentration_value(baseline, name)
        new_value = _concentration_value(candidate, name)
        concentration_deltas.append(ConcentrationDelta(
            name=name, baseline=old_value, candidate=new_value,
            delta=wsum([new_value, -old_value]),
        ))
    missing = [UnanalysedCompany(company_key=c.company_key, company_name=c.company_name, exposure=c.exposure)
               for c in candidate_top if c.company_key not in cached_extractions]
    company_statuses = company_statuses or {}
    scenario_uncached = [c for c in missing if company_statuses.get(c.company_key) != "no_sec_filing"]
    baseline_uncached = [c for c in baseline_top if c.company_key not in cached_extractions
                         and company_statuses.get(c.company_key) != "no_sec_filing"]
    notes = [("Uses the union of both portfolios' top companies at each portfolio's actual weights, "
              "including companies below its own top N. Coverage weights refer to this shared company set. "
              "Uses the latest cached filing extractions; "
              "no new filings or model calls. Concentration uses the full portfolio analysis.")]
    for label, companies in (("scenario", candidate_top), ("current portfolio", baseline_top)):
        for company in companies:
            if (company.company_key not in cached_extractions
                    and company_statuses.get(company.company_key) == "no_sec_filing"):
                notes.append(f"{company.company_name} in the {label} has no SEC filing; "
                             "its dependencies cannot be extracted from an SEC filing.")
    if scenario_uncached:
        count = len(scenario_uncached)
        notes.append(f"Dependencies for {count} scenario {'company are' if count == 1 else 'companies are'} "
                     "unknown without a cached extraction. Run Find dependencies for this scenario "
                     "to analyse companies with available SEC filings.")
    if baseline_uncached:
        count = len(baseline_uncached)
        notes.append(f"The current portfolio also has {count} top "
                     f"{'company' if count == 1 else 'companies'} without a cached extraction; "
                     "extraction requires an available SEC filing.")
    if any(delta.baseline is None or delta.candidate is None for delta in deltas):
        notes.append("A metric shown on only one side has no numeric delta; missing values are not treated as zero.")
    if baseline.coverage.missing_allocation > 0 or candidate.coverage.missing_allocation > 0:
        notes.append("Some ETF holdings were unavailable; these analyses cover only the holdings that loaded.")
    return CompareResponse(
        status="partial" if missing else "ok",
        baseline_top_n_weight=wsum(c.exposure for c in baseline_top),
        candidate_top_n_weight=wsum(c.exposure for c in candidate_top),
        dependency_deltas=deltas, concentration_deltas=concentration_deltas,
        candidate_unanalysed=missing, notes=notes,
    )
