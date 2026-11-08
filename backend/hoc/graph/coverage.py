"""Deterministic dependency coverage reporting (v3 package C-COV).

Rules (docs/hoc/PLAN-v3.md §5 & docs/hoc/CONTRACT.md §8):
- Every portfolio has a 1.0 total weight split across 5 mutually-exclusive CoverageBuckets:
  1. 'verified': Analysed (in top N), filing found, >=1 verified edge extracted.
  2. 'no_disclosures': Analysed, filing found, 0 edges survived verification.
  3. 'no_sec_filing': In top N, but no 10-K/20-F on EDGAR (foreign-only / non-SEC issuer).
  4. 'not_analysed': In top N, but skipped for budget or errored this run.
  5. 'outside_top_n': Holdings beyond the top-N cutoff (not analysed).
- Bucket weights sum to 1.0 within ±1e-6.
- Per-ETF verified share (by_etf), top-10 largest unanalysed holdings (largest_unanalysed),
  and plain-English CoverageGaps using the exact plural CoverageGapKind literals.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date

from hoc.contract.api import AnalysisResponse, CompanyExposure, EtfReport
from hoc.contract.dependencies import (
    CompanyRunStatus,
    CoverageBucket,
    CoverageGap,
    CoverageKind,
    CoverageReport,
    EtfCoverage,
    UnanalysedCompany,
    VerifiedEdge,
)
from hoc.contract.units import wsum
from hoc.graph.metrics import (
    FACILITY_TARGET_KINDS,
    SUPPLY_EDGE_TYPES,
    canonical_country_info,
    canonical_target_identity,
)

BUCKET_LABELS: dict[CoverageKind, str] = {
    "verified": "Analysed, with verified dependencies",
    "no_disclosures": "Analysed, but the filing names no dependencies",
    "no_sec_filing": "No SEC annual report to read",
    "not_analysed": "Could not be analysed this run",
    "outside_top_n": "Outside the companies we analysed",
}

BUCKET_ORDER: tuple[CoverageKind, ...] = (
    "verified",
    "no_disclosures",
    "no_sec_filing",
    "not_analysed",
    "outside_top_n",
)

# 15 months in days (~365.25 * 15 / 12 = 456.56 days)
OLD_FILING_THRESHOLD_DAYS = 456

_UNNAMED_CUSTOMER_CUES: tuple[str, ...] = (
    "unnamed",
    "undisclosed",
    "customer a",
    "customer b",
    "customer c",
    "single customer",
    "one customer",
    "major customer",
    "largest customer",
)


def _clamp_weight(val: float) -> float:
    return round(min(1.0, max(0.0, val)), 10)


def _classify_company_bucket(
    comp: CompanyRunStatus,
    companies_with_edges: set[str],
) -> CoverageKind:
    if comp.status in ("done", "cached"):
        if comp.verified_edges > 0 or comp.company_key in companies_with_edges:
            return "verified"
        return "no_disclosures"
    if comp.status in ("no_sec_filing", "unsupported_form"):
        return "no_sec_filing"
    return "not_analysed"


def _is_unnamed_customer_edge(edge: VerifiedEdge) -> bool:
    if edge.target_kind == "unnamed_customer":
        return True
    if edge.edge_type != "customer":
        return False
    if edge.target_key and edge.target_key.strip():
        return False
    lower_name = (edge.target_name or "").lower()
    return any(cue in lower_name for cue in _UNNAMED_CUSTOMER_CUES)


def _is_non_sec_supplier_edge(
    edge: VerifiedEdge,
    sec_filing_company_keys: set[str],
) -> bool:
    if edge.edge_type not in SUPPLY_EDGE_TYPES:
        return False
    if edge.target_kind in FACILITY_TARGET_KINDS or edge.target_kind in ("material", "component"):
        return False
    target_key = (edge.target_key or "").strip()
    return not (target_key.startswith("CIK:") or target_key in sec_filing_company_keys)


def compute_coverage_report(
    analysis: AnalysisResponse | Sequence[CompanyExposure],
    companies: Sequence[CompanyRunStatus],
    edges: Sequence[VerifiedEdge],
    *,
    etfs: Sequence[EtfReport] | None = None,
    as_of_date: date | None = None,
) -> CoverageReport:
    """Compute the deterministic v3 CoverageReport for a dependency run."""
    if isinstance(analysis, AnalysisResponse):
        exposures: Sequence[CompanyExposure] = analysis.exposures
        etf_reports: Sequence[EtfReport] = etfs if etfs is not None else analysis.etfs
        ref_date: date | None = as_of_date or analysis.as_of_date
    else:
        exposures = analysis
        etf_reports = etfs or ()
        ref_date = as_of_date

    exposure_by_key: dict[str, CompanyExposure] = {
        c.company_key: c for c in exposures if c.exposure > 0
    }

    # Portfolio companies that have at least one verified edge (as filer)
    companies_with_edges: set[str] = {
        e.source_company_key.strip()
        for e in edges
        if e.edge_id.strip() and e.source_company_key.strip()
    }

    # Track SEC filers known to have a filing
    sec_filing_company_keys: set[str] = {
        c.company_key
        for c in companies
        if c.filing is not None or c.company_key.startswith("CIK:")
    }

    # 1. Classify top-N companies into the first 4 buckets
    bucket_weights_raw: dict[CoverageKind, list[float]] = {k: [] for k in BUCKET_ORDER}
    bucket_counts: dict[CoverageKind, int] = {k: 0 for k in BUCKET_ORDER}
    verified_company_keys: set[str] = set()
    analysed_keys: set[str] = set()

    for comp in companies:
        analysed_keys.add(comp.company_key)
        kind = _classify_company_bucket(comp, companies_with_edges)
        weight = (
            exposure_by_key[comp.company_key].exposure
            if comp.company_key in exposure_by_key
            else float(comp.exposure)
        )
        bucket_weights_raw[kind].append(max(0.0, weight))
        bucket_counts[kind] += 1
        if kind == "verified":
            verified_company_keys.add(comp.company_key)

    # Unanalysed holdings outside the top-N list
    unanalysed_exposures: list[CompanyExposure] = [
        c for c in exposures if c.company_key not in analysed_keys and c.exposure > 0
    ]
    unanalysed_exposures.sort(key=lambda c: (-c.exposure, c.company_key))
    bucket_counts["outside_top_n"] = len(unanalysed_exposures)

    first_four_kinds: tuple[CoverageKind, ...] = (
        "verified",
        "no_disclosures",
        "no_sec_filing",
        "not_analysed",
    )
    first_four_weights: dict[CoverageKind, float] = {
        k: wsum(bucket_weights_raw[k]) for k in first_four_kinds
    }
    first_four_sum = math.fsum(first_four_weights.values())

    # Normalise if first_four_sum > 1.0 (defensive guard), otherwise outside_top_n absorbs the remainder to 1.0
    if first_four_sum > 1.0:
        for k in first_four_kinds:
            first_four_weights[k] = first_four_weights[k] / first_four_sum

    rounded_weights: dict[CoverageKind, float] = {
        k: _clamp_weight(first_four_weights[k]) for k in first_four_kinds
    }
    # Ensure exact sum to 1.0 within ±1e-6 after rounding
    rounded_first_four_sum = math.fsum(rounded_weights.values())
    rounded_weights["outside_top_n"] = _clamp_weight(max(0.0, 1.0 - rounded_first_four_sum))

    buckets: list[CoverageBucket] = [
        CoverageBucket(
            kind=k,
            weight=rounded_weights[k],
            companies=bucket_counts[k],
            label=BUCKET_LABELS[k],
        )
        for k in BUCKET_ORDER
    ]

    # 2. Per-ETF verified coverage (by_etf)
    #    For each ETF, compute the share of its look-through weight in 'verified' companies.
    etf_order: list[str] = []
    etf_allocations: dict[str, float] = {}
    for etf in etf_reports:
        t = etf.ticker.strip().upper()
        if t and t not in etf_allocations:
            etf_order.append(t)
            etf_allocations[t] = float(etf.allocation)

    # Also discover any ETF tickers referenced in exposure contributions
    etf_total_contrib: dict[str, list[float]] = {}
    etf_verified_contrib: dict[str, list[float]] = {}
    etf_verified_weight_in_etf: dict[str, list[float]] = {}

    for comp_exp in exposures:
        is_verified = comp_exp.company_key in verified_company_keys
        for contrib in comp_exp.contributions:
            t = contrib.etf_ticker.strip().upper()
            if not t:
                continue
            if t not in etf_allocations and t not in etf_order:
                etf_order.append(t)
            etf_total_contrib.setdefault(t, []).append(max(0.0, float(contrib.contribution)))
            if is_verified:
                etf_verified_contrib.setdefault(t, []).append(max(0.0, float(contrib.contribution)))
                etf_verified_weight_in_etf.setdefault(t, []).append(
                    max(0.0, float(contrib.weight_in_etf))
                )

    by_etf: list[EtfCoverage] = []
    for ticker in etf_order:
        ver_contrib = wsum(etf_verified_contrib.get(ticker, []))
        alloc = etf_allocations.get(ticker, 0.0)
        tot_contrib = wsum(etf_total_contrib.get(ticker, []))
        ver_w_in_etf = wsum(etf_verified_weight_in_etf.get(ticker, []))

        if alloc > 0.0 and ver_contrib > 0.0:
            share = ver_contrib / alloc
        elif ver_w_in_etf > 0.0:
            share = ver_w_in_etf
        elif tot_contrib > 0.0:
            share = ver_contrib / tot_contrib
        else:
            share = 0.0

        by_etf.append(
            EtfCoverage(
                ticker=ticker,
                verified_weight=_clamp_weight(share),
            )
        )

    # 3. Top-10 largest unanalysed companies outside the top-N cutoff
    largest_unanalysed: list[UnanalysedCompany] = [
        UnanalysedCompany(
            company_key=c.company_key,
            company_name=c.company_name,
            exposure=_clamp_weight(c.exposure),
        )
        for c in unanalysed_exposures[:10]
    ]

    # 4. Plain-English CoverageGaps (exact plural CoverageGapKind literals)
    gaps: list[CoverageGap] = []

    # (a) outside_top_n
    outside_w = rounded_weights["outside_top_n"]
    outside_count = bucket_counts["outside_top_n"]
    if outside_w > 1e-6 or outside_count > 0:
        comp_noun = "company" if outside_count == 1 else "companies"
        verb = "was" if outside_count == 1 else "were"
        if outside_count > 0:
            msg = (
                f"{outside_count} portfolio {comp_noun} ({outside_w * 100:.1f}% of exposure) "
                f"{verb} outside the top-{len(companies)} cutoff and {verb} not analysed."
            )
        else:
            msg = (
                f"{outside_w * 100:.1f}% of portfolio exposure was outside the "
                f"top-{len(companies)} cutoff and was not analysed."
            )
        gaps.append(
            CoverageGap(
                kind="outside_top_n",
                message=msg,
                weight=outside_w,
            )
        )

    #Lookup exposure helper for top-N companies too
    comp_exposure_lookup: dict[str, float] = {
        c.company_key: float(c.exposure) for c in companies
    }
    for k, exp_obj in exposure_by_key.items():
        comp_exposure_lookup[k] = float(exp_obj.exposure)

    # (b) unnamed_customers
    unnamed_cust_edges = [e for e in edges if _is_unnamed_customer_edge(e)]
    if unnamed_cust_edges:
        unnamed_src_keys = sorted(
            {
                e.source_company_key.strip()
                for e in unnamed_cust_edges
                if e.source_company_key.strip() in comp_exposure_lookup
            }
        )
        unnamed_w = _clamp_weight(wsum(comp_exposure_lookup[k] for k in unnamed_src_keys))
        n_disclosures = len(unnamed_cust_edges)
        disc_noun = "disclosure" if n_disclosures == 1 else "disclosures"
        gaps.append(
            CoverageGap(
                kind="unnamed_customers",
                message=f"{n_disclosures} verified customer {disc_noun} did not name the counterparty in the filing.",
                weight=unnamed_w,
            )
        )

    # (c) non_sec_counterparties
    non_sec_targets: dict[str, set[str]] = {}
    for edge in edges:
        if _is_non_sec_supplier_edge(edge, sec_filing_company_keys):
            target_id, _ = canonical_target_identity(edge)
            src_key = edge.source_company_key.strip()
            non_sec_targets.setdefault(target_id, set())
            if src_key in comp_exposure_lookup:
                non_sec_targets[target_id].add(src_key)

    if non_sec_targets:
        dependent_keys = sorted({k for keys in non_sec_targets.values() for k in keys})
        non_sec_w = _clamp_weight(wsum(comp_exposure_lookup[k] for k in dependent_keys))
        n_suppliers = len(non_sec_targets)
        sup_noun = "supplier is a non-SEC issuer" if n_suppliers == 1 else "suppliers are non-SEC issuers"
        gaps.append(
            CoverageGap(
                kind="non_sec_counterparties",
                message=f"{n_suppliers} verified {sup_noun} without a US 10-K/20-F to cross-check from the other side.",
                weight=non_sec_w,
            )
        )

    # (d) old_filings (> 15 months old relative to ref_date)
    if ref_date is None:
        all_filed_dates = [c.filing.filed for c in companies if c.filing is not None] + [
            e.filing.filed for e in edges
        ]
        if all_filed_dates:
            ref_date = max(all_filed_dates)

    if ref_date is not None:
        old_filing_keys: set[str] = set()
        for comp in companies:
            if (
                comp.filing is not None
                and (ref_date - comp.filing.filed).days > OLD_FILING_THRESHOLD_DAYS
            ):
                old_filing_keys.add(comp.company_key)
        for edge in edges:
            src_key = edge.source_company_key.strip()
            if (
                src_key in comp_exposure_lookup
                and (ref_date - edge.filing.filed).days > OLD_FILING_THRESHOLD_DAYS
            ):
                old_filing_keys.add(src_key)

        if old_filing_keys:
            sorted_old_keys = sorted(old_filing_keys)
            old_w = _clamp_weight(
                wsum(comp_exposure_lookup.get(k, 0.0) for k in sorted_old_keys)
            )
            n_old = len(sorted_old_keys)
            filing_noun = "filing is" if n_old == 1 else "filings are"
            gaps.append(
                CoverageGap(
                    kind="old_filings",
                    message=f"{n_old} annual {filing_noun} more than 15 months old.",
                    weight=old_w,
                )
            )

    # (e) region_only_facilities
    region_facility_edges: list[VerifiedEdge] = []
    region_facility_src_keys: set[str] = set()
    for edge in edges:
        if edge.edge_type == "facility" or edge.target_kind in FACILITY_TARGET_KINDS:
            resolved = canonical_country_info(
                edge.target_name,
                edge.target_key,
                edge.qualifier,
                edge.evidence_quote,
            )
            if resolved is None:
                region_facility_edges.append(edge)
                src_key = edge.source_company_key.strip()
                if src_key in comp_exposure_lookup:
                    region_facility_src_keys.add(src_key)

    if region_facility_edges:
        reg_w = _clamp_weight(
            wsum(comp_exposure_lookup[k] for k in sorted(region_facility_src_keys))
        )
        n_reg = len(region_facility_edges)
        fac_noun = "disclosure names" if n_reg == 1 else "disclosures name"
        gaps.append(
            CoverageGap(
                kind="region_only_facilities",
                message=f"{n_reg} facility {fac_noun} a broad region rather than a single country.",
                weight=reg_w,
            )
        )

    return CoverageReport(
        buckets=buckets,
        by_etf=by_etf,
        largest_unanalysed=largest_unanalysed,
        gaps=gaps,
    )
