"""Deterministic dependency graph metrics (package G-ORCH).

Rules (docs/hoc/PLAN-v2.md & docs/hoc/CONTRACT.md):
- Python owns every number: supplier dependency %, facility-country concentration,
  and shared single points of failure are computed deterministically with math.fsum (wsum).
- Union by (dependent_company_key, target) before summing portfolio exposure so a
  company with multiple verified edges to the same supplier or country is never
  double-counted.
- Every MetricFact carries its canonical metric_id, label, value, unit ('fraction' | 'count'),
  subject_key, and sorted supporting_edge_ids.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from hoc.contract.api import CompanyExposure
from hoc.contract.dependencies import MetricFact, MetricUnit, VerifiedEdge
from hoc.contract.units import wsum

SUPPLY_EDGE_TYPES: frozenset[str] = frozenset(
    {
        "supplier",
        "contract_manufacturer",
        "foundry",
        "key_input",
        "jv_partner",
    }
)

FACILITY_TARGET_KINDS: frozenset[str] = frozenset({"country", "region", "facility"})

# Canonical (ISO-style code, display name) for facility countries/regions.
_COUNTRY_MAP: Mapping[str, tuple[str, str]] = {
    "tw": ("TW", "Taiwan"),
    "taiwan": ("TW", "Taiwan"),
    "taiwan roc": ("TW", "Taiwan"),
    "republic of china": ("TW", "Taiwan"),
    "hsinchu": ("TW", "Taiwan"),
    "tainan": ("TW", "Taiwan"),
    "taichung": ("TW", "Taiwan"),
    "us": ("US", "United States"),
    "usa": ("US", "United States"),
    "u s": ("US", "United States"),
    "u s a": ("US", "United States"),
    "united states": ("US", "United States"),
    "united states of america": ("US", "United States"),
    "arizona": ("US", "United States"),
    "california": ("US", "United States"),
    "cupertino": ("US", "United States"),
    "texas": ("US", "United States"),
    "oregon": ("US", "United States"),
    "ohio": ("US", "United States"),
    "new mexico": ("US", "United States"),
    "cn": ("CN", "China"),
    "china": ("CN", "China"),
    "prc": ("CN", "China"),
    "mainland china": ("CN", "China"),
    "china mainland": ("CN", "China"),
    "kr": ("KR", "South Korea"),
    "korea": ("KR", "South Korea"),
    "south korea": ("KR", "South Korea"),
    "republic of korea": ("KR", "South Korea"),
    "jp": ("JP", "Japan"),
    "japan": ("JP", "Japan"),
    "kumamoto": ("JP", "Japan"),
    "de": ("DE", "Germany"),
    "germany": ("DE", "Germany"),
    "dresden": ("DE", "Germany"),
    "nl": ("NL", "Netherlands"),
    "netherlands": ("NL", "Netherlands"),
    "the netherlands": ("NL", "Netherlands"),
    "veldhoven": ("NL", "Netherlands"),
    "vn": ("VN", "Vietnam"),
    "vietnam": ("VN", "Vietnam"),
    "in": ("IN", "India"),
    "india": ("IN", "India"),
    "ie": ("IE", "Ireland"),
    "ireland": ("IE", "Ireland"),
    "sg": ("SG", "Singapore"),
    "singapore": ("SG", "Singapore"),
    "il": ("IL", "Israel"),
    "israel": ("IL", "Israel"),
    "my": ("MY", "Malaysia"),
    "malaysia": ("MY", "Malaysia"),
    "gb": ("GB", "United Kingdom"),
    "uk": ("GB", "United Kingdom"),
    "united kingdom": ("GB", "United Kingdom"),
}


def slugify_metric_token(text: str) -> str:
    """Turn an arbitrary key or name into a stable metric_id token."""
    cleaned = re.sub(r"[^A-Za-z0-9:_\-]+", "-", text.strip()).strip("-")
    return cleaned or "unknown"


def canonical_country_info(
    raw_name: str,
    target_key: str | None = None,
    qualifier: str | None = None,
) -> tuple[str, str]:
    """Return (country_code, country_display_name) for a facility/country edge."""
    if target_key and str(target_key).strip():
        clean_key = str(target_key).strip()
        tail = clean_key.split(":", 1)[-1].strip()
        norm_tail = re.sub(r"[^a-z0-9]+", " ", tail.lower()).strip()
        if norm_tail in _COUNTRY_MAP:
            return _COUNTRY_MAP[norm_tail]

    for candidate in (raw_name, qualifier or ""):
        if not candidate:
            continue
        norm = re.sub(r"[^a-z0-9]+", " ", candidate.strip().lower()).strip()
        if norm in _COUNTRY_MAP:
            return _COUNTRY_MAP[norm]
        for token, info in _COUNTRY_MAP.items():
            if len(token) >= 4 and re.search(rf"\b{re.escape(token)}\b", norm):
                return info

    cleaned = re.sub(r"\s+", " ", raw_name.strip()) or "Unknown"
    code = re.sub(r"[^A-Za-z0-9]+", "_", cleaned.upper()).strip("_") or "UNKNOWN"
    return code, cleaned


def canonical_target_identity(edge: VerifiedEdge) -> tuple[str, str]:
    """Return (target_id, display_name) for an edge's target."""
    if edge.edge_type == "facility" or edge.target_kind in FACILITY_TARGET_KINDS:
        code, country_name = canonical_country_info(
            edge.target_name, edge.target_key, edge.qualifier
        )
        return code, country_name

    if edge.target_key and edge.target_key.strip():
        clean_key = edge.target_key.strip()
        return clean_key, edge.target_name.strip() or clean_key

    slug = re.sub(r"[^a-z0-9]+", "-", edge.target_name.strip().lower()).strip("-") or "unknown"
    return f"NAME:{slug}", edge.target_name.strip() or slug


def format_metric_value(metric: MetricFact) -> str:
    """Format a MetricFact value deterministically for {{metric:<id>}} placeholder expansion."""
    if metric.unit == "count":
        return str(round(metric.value))
    if metric.unit == "days":
        return f"{round(metric.value)} days"
    if metric.unit == "ratio":
        return f"{metric.value:.2f}x"
    # Default: 'fraction' (0.58 -> '58.00%')
    pct = metric.value * 100.0
    if abs(pct) < 0.005:
        pct = 0.0
    return f"{pct:.2f}%"


@dataclass(frozen=True)
class SupplierDependencySummary:
    """Deterministic summary for one supplier, foundry, contract manufacturer, or input."""

    target_id: str
    target_name: str
    dependent_weight: float
    dependent_company_keys: tuple[str, ...]
    dependent_company_names: tuple[str, ...]
    etf_tickers: tuple[str, ...]
    sole_source: bool
    target_in_portfolio: bool
    edge_types: tuple[str, ...]
    supporting_edge_ids: tuple[str, ...]


@dataclass(frozen=True)
class FacilityCountrySummary:
    """Deterministic summary for portfolio exposure with verified facilities in a country/region."""

    country_code: str
    country_name: str
    dependent_weight: float
    company_keys: tuple[str, ...]
    company_names: tuple[str, ...]
    etf_tickers: tuple[str, ...]
    supporting_edge_ids: tuple[str, ...]


@dataclass(frozen=True)
class SinglePointOfFailureSummary:
    """A supplier/foundry/input shared by >=2 holdings OR flagged sole_source."""

    target_id: str
    target_name: str
    dependent_weight: float
    dependent_company_keys: tuple[str, ...]
    dependent_company_names: tuple[str, ...]
    etf_tickers: tuple[str, ...]
    sole_source: bool
    target_in_portfolio: bool
    supporting_edge_ids: tuple[str, ...]


@dataclass(frozen=True)
class DependencyGraphSummary:
    """Rich deterministic breakdown alongside the flat MetricFact list."""

    metrics: list[MetricFact]
    metrics_by_id: dict[str, MetricFact]
    suppliers: list[SupplierDependencySummary]
    facilities_by_country: list[FacilityCountrySummary]
    single_points_of_failure: list[SinglePointOfFailureSummary]
    analysed_weight: float
    verified_edges_count: int


def _make_metric(
    metric_id: str,
    label: str,
    value: float,
    unit: MetricUnit,
    subject_key: str | None,
    supporting_edge_ids: Sequence[str],
) -> MetricFact:
    return MetricFact(
        metric_id=metric_id,
        label=label,
        value=round(value, 10) if unit == "fraction" else value,
        unit=unit,
        subject_key=subject_key,
        supporting_edge_ids=sorted(set(supporting_edge_ids)),
    )


def compute_dependency_summary(
    exposures: Sequence[CompanyExposure],
    edges: Sequence[VerifiedEdge],
) -> DependencyGraphSummary:
    """Compute all deterministic dependency metrics without double-counting."""
    portfolio_by_key: dict[str, CompanyExposure] = {
        comp.company_key: comp for comp in exposures if comp.exposure > 0
    }

    # 1. Supply-side dependencies grouped by canonical target_id.
    #    Union by (dependent_company_key, target_id) so multiple edges between
    #    the same portfolio company and supplier never double-count exposure.
    supplier_names: dict[str, str] = {}
    supplier_companies: dict[str, set[str]] = {}
    supplier_edges: dict[str, set[str]] = {}
    supplier_edge_types: dict[str, set[str]] = {}
    supplier_sole_source: dict[str, bool] = {}

    # 2. Facility/country dependencies grouped by canonical country_code.
    country_names: dict[str, str] = {}
    country_companies: dict[str, set[str]] = {}
    country_edges: dict[str, set[str]] = {}

    # 3. Customer concentration edges grouped by canonical target_id.
    customer_names: dict[str, str] = {}
    customer_companies: dict[str, set[str]] = {}
    customer_edges: dict[str, set[str]] = {}

    # 4. Track portfolio companies with at least one verified edge.
    companies_with_edges: set[str] = set()
    all_edge_ids: list[str] = []

    for edge in edges:
        edge_id = edge.edge_id.strip()
        if not edge_id:
            continue
        all_edge_ids.append(edge_id)

        src_key = edge.source_company_key.strip()
        edge_type = edge.edge_type
        target_kind = edge.target_kind
        target_key = edge.target_key.strip() if edge.target_key else None

        if src_key in portfolio_by_key:
            companies_with_edges.add(src_key)
        if target_key and target_key in portfolio_by_key:
            companies_with_edges.add(target_key)

        # Facility / country edges
        if edge_type == "facility" or target_kind in FACILITY_TARGET_KINDS:
            if src_key in portfolio_by_key:
                code, country_label = canonical_country_info(
                    edge.target_name, target_key, edge.qualifier
                )
                country_names.setdefault(code, country_label)
                country_companies.setdefault(code, set()).add(src_key)
                country_edges.setdefault(code, set()).add(edge_id)
            continue

        # Supply-chain / operational dependency edges
        if edge_type in SUPPLY_EDGE_TYPES:
            if src_key in portfolio_by_key:
                target_id, target_label = canonical_target_identity(edge)
                if target_id in portfolio_by_key:
                    target_label = portfolio_by_key[target_id].company_name
                supplier_names.setdefault(target_id, target_label)
                supplier_companies.setdefault(target_id, set()).add(src_key)
                supplier_edges.setdefault(target_id, set()).add(edge_id)
                supplier_edge_types.setdefault(target_id, set()).add(edge_type)
                if edge.sole_source:
                    supplier_sole_source[target_id] = True
            continue

        # Customer edges:
        # (a) Filer (src_key) reports revenue concentration on a customer
        # (b) Reverse link: if src_key is a supplier and target_key is a portfolio company,
        #     then target_key depends on src_key as a supplier!
        if edge_type == "customer":
            target_id, target_label = canonical_target_identity(edge)
            if src_key in portfolio_by_key:
                customer_names.setdefault(target_id, target_label)
                customer_companies.setdefault(target_id, set()).add(src_key)
                customer_edges.setdefault(target_id, set()).add(edge_id)

            if target_key and target_key in portfolio_by_key and target_key != src_key:
                dep_comp_key = target_key
                sup_id = src_key
                sup_label = (
                    portfolio_by_key[src_key].company_name
                    if src_key in portfolio_by_key
                    else (edge.source_company_name or src_key)
                )
                supplier_names.setdefault(sup_id, sup_label)
                supplier_companies.setdefault(sup_id, set()).add(dep_comp_key)
                supplier_edges.setdefault(sup_id, set()).add(edge_id)
                supplier_edge_types.setdefault(sup_id, set()).add("supplier")
                if edge.sole_source:
                    supplier_sole_source[sup_id] = True

    # Build SupplierDependencySummary list
    suppliers: list[SupplierDependencySummary] = []
    for target_id, comp_keys in supplier_companies.items():
        sorted_comp_keys = tuple(
            sorted(
                comp_keys,
                key=lambda k: (-portfolio_by_key[k].exposure, k),
            )
        )
        dep_weight = wsum(portfolio_by_key[k].exposure for k in sorted_comp_keys)
        comp_names = tuple(portfolio_by_key[k].company_name for k in sorted_comp_keys)
        etfs = tuple(
            sorted(
                {
                    contrib.etf_ticker
                    for k in sorted_comp_keys
                    for contrib in portfolio_by_key[k].contributions
                    if contrib.contribution > 0
                }
            )
        )
        suppliers.append(
            SupplierDependencySummary(
                target_id=target_id,
                target_name=supplier_names[target_id],
                dependent_weight=dep_weight,
                dependent_company_keys=sorted_comp_keys,
                dependent_company_names=comp_names,
                etf_tickers=etfs,
                sole_source=supplier_sole_source.get(target_id, False),
                target_in_portfolio=target_id in portfolio_by_key,
                edge_types=tuple(sorted(supplier_edge_types.get(target_id, set()))),
                supporting_edge_ids=tuple(sorted(supplier_edges.get(target_id, set()))),
            )
        )

    suppliers.sort(
        key=lambda s: (
            -s.dependent_weight,
            -len(s.dependent_company_keys),
            s.target_id,
        )
    )

    # Build SinglePointOfFailureSummary list (shared across >=2 companies OR sole_source)
    spofs: list[SinglePointOfFailureSummary] = []
    for sup in suppliers:
        if len(sup.dependent_company_keys) >= 2 or sup.sole_source:
            spofs.append(
                SinglePointOfFailureSummary(
                    target_id=sup.target_id,
                    target_name=sup.target_name,
                    dependent_weight=sup.dependent_weight,
                    dependent_company_keys=sup.dependent_company_keys,
                    dependent_company_names=sup.dependent_company_names,
                    etf_tickers=sup.etf_tickers,
                    sole_source=sup.sole_source,
                    target_in_portfolio=sup.target_in_portfolio,
                    supporting_edge_ids=sup.supporting_edge_ids,
                )
            )

    # Build FacilityCountrySummary list
    facilities_by_country: list[FacilityCountrySummary] = []
    for code, comp_keys in country_companies.items():
        sorted_comp_keys = tuple(
            sorted(
                comp_keys,
                key=lambda k: (-portfolio_by_key[k].exposure, k),
            )
        )
        country_weight = wsum(portfolio_by_key[k].exposure for k in sorted_comp_keys)
        comp_names = tuple(portfolio_by_key[k].company_name for k in sorted_comp_keys)
        etfs = tuple(
            sorted(
                {
                    contrib.etf_ticker
                    for k in sorted_comp_keys
                    for contrib in portfolio_by_key[k].contributions
                    if contrib.contribution > 0
                }
            )
        )
        facilities_by_country.append(
            FacilityCountrySummary(
                country_code=code,
                country_name=country_names[code],
                dependent_weight=country_weight,
                company_keys=sorted_comp_keys,
                company_names=comp_names,
                etf_tickers=etfs,
                supporting_edge_ids=tuple(sorted(country_edges.get(code, set()))),
            )
        )

    facilities_by_country.sort(
        key=lambda f: (
            -f.dependent_weight,
            -len(f.company_keys),
            f.country_code,
        )
    )

    # Assemble flat MetricFact list matching C0 conventions (dep.<target_id>, facility.<code>, spof.count, etc.)
    metrics: list[MetricFact] = []
    analysed_weight = wsum(portfolio_by_key[k].exposure for k in sorted(companies_with_edges))
    sorted_all_edges = sorted(set(all_edge_ids))

    # 1. Supplier dependency metrics (matching synthetic-dependencies.json: dep.<target_id>)
    for sup in suppliers:
        metrics.append(
            _make_metric(
                metric_id=f"dep.{sup.target_id}",
                label=f"Portfolio exposure that depends on {sup.target_name}",
                value=sup.dependent_weight,
                unit="fraction",
                subject_key=sup.target_id,
                supporting_edge_ids=sup.supporting_edge_ids,
            )
        )
        metrics.append(
            _make_metric(
                metric_id=f"dep.{sup.target_id}.companies",
                label=f"Portfolio companies dependent on {sup.target_name}",
                value=float(len(sup.dependent_company_keys)),
                unit="count",
                subject_key=sup.target_id,
                supporting_edge_ids=sup.supporting_edge_ids,
            )
        )

    # 2. Facility concentration by country (matching synthetic-dependencies.json: facility.<code>)
    for fac in facilities_by_country:
        metrics.append(
            _make_metric(
                metric_id=f"facility.{fac.country_code}",
                label=f"Portfolio exposure with key facilities in {fac.country_name}",
                value=fac.dependent_weight,
                unit="fraction",
                subject_key=fac.country_code,
                supporting_edge_ids=fac.supporting_edge_ids,
            )
        )
        metrics.append(
            _make_metric(
                metric_id=f"facility.{fac.country_code}.companies",
                label=f"Portfolio companies with facilities in {fac.country_name}",
                value=float(len(fac.company_keys)),
                unit="count",
                subject_key=fac.country_code,
                supporting_edge_ids=fac.supporting_edge_ids,
            )
        )

    # 3. Single points of failure (matching synthetic-dependencies.json: spof.count + spof.<target_id>)
    shared_spof_count = sum(1 for spof in spofs if len(spof.dependent_company_keys) >= 2 or spof.sole_source)
    metrics.append(
        _make_metric(
            metric_id="spof.count",
            label="Suppliers shared by 2+ portfolio companies or sole-source",
            value=float(shared_spof_count),
            unit="count",
            subject_key=None,
            supporting_edge_ids=[eid for spof in spofs for eid in spof.supporting_edge_ids],
        )
    )
    for spof in spofs:
        metrics.append(
            _make_metric(
                metric_id=f"spof.{spof.target_id}",
                label=f"Single point of failure exposure on {spof.target_name}",
                value=spof.dependent_weight,
                unit="fraction",
                subject_key=spof.target_id,
                supporting_edge_ids=spof.supporting_edge_ids,
            )
        )

    # 4. Customer concentration metrics
    for cust_id in sorted(customer_companies):
        comp_keys = customer_companies[cust_id]
        cust_weight = wsum(portfolio_by_key[k].exposure for k in sorted(comp_keys))
        metrics.append(
            _make_metric(
                metric_id=f"customer.{cust_id}",
                label=f"Portfolio exposure reporting customer concentration ({customer_names[cust_id]})",
                value=cust_weight,
                unit="fraction",
                subject_key=cust_id,
                supporting_edge_ids=sorted(customer_edges[cust_id]),
            )
        )

    # 5. Summary metrics
    metrics.append(
        _make_metric(
            metric_id="summary.analysed_weight",
            label="Portfolio exposure with verified dependency disclosures",
            value=analysed_weight,
            unit="fraction",
            subject_key=None,
            supporting_edge_ids=sorted_all_edges,
        )
    )
    metrics.append(
        _make_metric(
            metric_id="summary.verified_edges",
            label="Verified filing dependency edges",
            value=float(len(sorted_all_edges)),
            unit="count",
            subject_key=None,
            supporting_edge_ids=sorted_all_edges,
        )
    )

    metrics_by_id = {m.metric_id: m for m in metrics}
    return DependencyGraphSummary(
        metrics=metrics,
        metrics_by_id=metrics_by_id,
        suppliers=suppliers,
        facilities_by_country=facilities_by_country,
        single_points_of_failure=spofs,
        analysed_weight=analysed_weight,
        verified_edges_count=len(sorted_all_edges),
    )


def compute_dependency_metrics(
    exposures: Sequence[CompanyExposure],
    edges: Sequence[VerifiedEdge],
) -> list[MetricFact]:
    """Return the deterministic list[MetricFact] for the dependency response contract."""
    return compute_dependency_summary(exposures, edges).metrics
