"""Evaluation runner (`hoc eval [--live|--replay]`) for package E-RUN.

Owner: Bekarys's Gemini (E-RUN).
Rules (docs/hoc/PLAN-v3.md §1):
- `--replay` (default): runs 100% offline from recorded responses (`backend/tests/eval/recorded/<TICKER>.json`
  or the local `ExtractionCache`, falling back to the deterministic 10-company synthetic held-out baseline
  when no adjudicated gold files are present yet). Never touches the network or requires `GEMINI_API_KEY`.
- `--live`: fetches the 10 held-out 10-K filings via `FilingFetcher`, runs `DependencyExtractor` + `V-INT`
  interpretation verification + `R-IMP` importance scoring, records predictions to `recorded_dir`, and
  writes `docs/hoc/EVAL.md` and `docs/hoc/eval/results.json`.
"""

from __future__ import annotations

import argparse
import inspect
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, Literal

from hoc.ai.extractor import make_edge_id
from hoc.ai.verifier import PROMPT_VERSION
from hoc.contract.dependencies import (
    EdgeImportance,
    EdgeInterpretation,
    FilingRef,
    VerifiedEdge,
)
from hoc.eval.matching import (
    compare_annotator_docs,
    fallback_importance_tier,
)
from hoc.eval.metrics import (
    DEFAULT_BOOTSTRAP_ITERATIONS,
    DEFAULT_BOOTSTRAP_SEED,
    CompanyEvalBundle,
    aggregate_eval_report,
    evaluate_agentic_acceptance,
    evaluate_company,
    format_agentic_acceptance_summary,
)
from hoc.eval.report import write_eval_outputs
from hoc.eval.schema import (
    HELD_OUT_BY_TICKER,
    HELD_OUT_COMPANIES,
    EvalRunReport,
    GoldCompany,
    GoldDocument,
    GoldFiling,
    GoldNegative,
    GoldRelationship,
    RecordedCompanyPrediction,
    load_gold_directory,
    load_gold_document,
    verify_gold_quotes,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GOLD_DIR = REPO_ROOT / "backend" / "tests" / "eval" / "gold"
DEFAULT_RECORDED_DIR = REPO_ROOT / "docs" / "hoc" / "eval" / "recorded"
DEFAULT_EVAL_MD = REPO_ROOT / "docs" / "hoc" / "EVAL.md"
DEFAULT_EVAL_JSON = REPO_ROOT / "docs" / "hoc" / "eval" / "results.json"


def detect_git_commit() -> str:
    """Return short git commit SHA of the current checkout, or `'unknown'`."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return "unknown"


def detect_extractor_prompt_version() -> str:
    return PROMPT_VERSION


def detect_judge_prompt_version() -> str:
    try:
        from hoc.ai import verifier as _ver

        ver = getattr(_ver, "JUDGE_PROMPT_VERSION", None)
        if isinstance(ver, str) and ver.strip():
            return ver.strip()
    except ImportError:
        ver = None
    try:
        import hoc.ai as _ai

        ver = getattr(_ai, "JUDGE_PROMPT_VERSION", None)
        if isinstance(ver, str) and ver.strip():
            return ver.strip()
    except ImportError:
        return "hoc-v3-judge-1"
    return "hoc-v3-judge-1"


def _attach_importance_if_needed(edges: Sequence[VerifiedEdge]) -> list[VerifiedEdge]:
    """Attach `EdgeImportance` via `hoc.graph.importance.attach_edge_importance` when available,
    or deterministic `fallback_importance_tier`."""
    try:
        from hoc.graph.importance import attach_edge_importance  # type: ignore[import-not-found]

        scored = attach_edge_importance(list(edges))
        if isinstance(scored, list):
            return scored
    except (ImportError, AttributeError, TypeError, ValueError):
        scored = None

    tier_to_score = {"critical": 0.90, "high": 0.70, "medium": 0.50, "low": 0.30}
    enriched: list[VerifiedEdge] = []
    for edge in edges:
        if edge.importance is not None:
            enriched.append(edge)
            continue
        tier = fallback_importance_tier(edge)
        imp = EdgeImportance(
            score=tier_to_score[tier],
            tier=tier,
            reasons=[f"Deterministic tier '{tier}' from quote and edge type '{edge.edge_type}'"],
        )
        enriched.append(edge.model_copy(update={"importance": imp}))
    return enriched


def _hydrate_recorded_edges(raw_edges: Sequence[Mapping[str, Any] | VerifiedEdge]) -> list[VerifiedEdge]:
    edges: list[VerifiedEdge] = []
    for item in raw_edges:
        if isinstance(item, VerifiedEdge):
            edges.append(item)
        elif isinstance(item, Mapping):
            edges.append(VerifiedEdge.model_validate(dict(item)))
    return _attach_importance_if_needed(edges)


def load_recorded_predictions(recorded_dir: Path) -> dict[str, RecordedCompanyPrediction]:
    """Load recorded prediction files `<TICKER>.json` from `recorded_dir`."""
    if not recorded_dir.exists():
        return {}
    by_ticker: dict[str, RecordedCompanyPrediction] = {}
    for path in sorted(recorded_dir.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        rec = RecordedCompanyPrediction.model_validate(raw)
        by_ticker[rec.ticker.upper()] = rec
    return by_ticker


def save_recorded_prediction(recorded_dir: Path, rec: RecordedCompanyPrediction) -> Path:
    recorded_dir.mkdir(parents=True, exist_ok=True)
    out = recorded_dir / f"{rec.ticker.upper()}.json"
    out.write_text(rec.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return out


def build_synthetic_held_out_fixture() -> tuple[list[GoldDocument], dict[str, RecordedCompanyPrediction]]:
    """Build a deterministic, offline 10-company synthetic held-out dataset covering all 10 held-out
    filers (`NKE`, `F`, `GM`, `BA`, `SWKS`, `QRVO`, `GLW`, `PFE`, `DE`, `SBUX`), all 7 `edge_type`s,
    both directions, all 4 importance tiers, and all hard-negative categories (`competitor`, `negated`,
    `hypothetical`, `generic`, `unrelated`), including before- vs. after-V-INT rejections."""
    specs: list[dict[str, Any]] = [
        {
            "ticker": "NKE",
            "rels": [
                ("NKE-1", "contract_manufacturer", "footwear factories in Vietnam", "country", "depends_on_target",
                 "In fiscal 2025, contract factories in Vietnam manufactured approximately 50% of total NIKE Brand footwear.",
                 "critical", False, "50% of footwear", "gold"),
                ("NKE-2", "contract_manufacturer", "footwear factories in Indonesia", "country", "depends_on_target",
                 "Contract manufacturers in Indonesia produced 27% of total NIKE Brand footwear in fiscal 2025.",
                 "high", False, "27% of footwear", "gold"),
                ("NKE-3", "facility", "Beaverton, Oregon", "facility", "depends_on_target",
                 "Our world headquarters are located in Beaverton, Oregon, where we conduct product design and development.",
                 "low", False, "world headquarters", "gold"),
            ],
            "negs": [
                ("NKE-N1", "adidas", "competitor",
                 "The athletic footwear and apparel industry is highly competitive, and we compete globally with adidas, Puma, and Anta."),
                ("NKE-N2", "independent contract manufacturers", "generic",
                 "Virtually all of our footwear is produced by independent contract manufacturers outside the United States."),
            ],
            "pred_matches": [0, 1, 2],
            "vint_rejected": [
                ("supplier", "adidas", "company",
                 "The athletic footwear and apparel industry is highly competitive, and we compete globally with adidas, Puma, and Anta.",
                 "competitor_mention", "Mentioned in a competitor list, not as a supplier."),
            ],
        },
        {
            "ticker": "F",
            "rels": [
                ("F-1", "jv_partner", "SK On", "company", "depends_on_target",
                 "We formed the BlueOval SK joint venture with SK On to manufacture battery cells in Kentucky and Tennessee.",
                 "high", False, "BlueOval SK battery joint venture", "gold"),
                ("F-2", "key_input", "automotive-grade semiconductors", "component", "depends_on_target",
                 "Our vehicles depend on a continuous supply of automotive-grade semiconductors and lithium-ion battery cells.",
                 "high", False, None, "gold"),
                ("F-3", "facility", "Dearborn, Michigan", "facility", "depends_on_target",
                 "We operate major vehicle assembly and stamping facilities in Dearborn, Michigan.",
                 "medium", False, "assembly facility", "gold"),
            ],
            "negs": [
                ("F-N1", "General Motors", "competitor",
                 "Our principal automotive competitors in North America include General Motors, Toyota, Stellantis, and Tesla."),
                ("F-N2", "lithium mines", "negated",
                 "We do not own or operate any lithium mines directly and instead source processed battery materials from suppliers."),
            ],
            "pred_matches": [0, 1, 2],
            "vint_rejected": [
                ("supplier", "General Motors", "company",
                 "Our principal automotive competitors in North America include General Motors, Toyota, Stellantis, and Tesla.",
                 "competitor_mention", "Named as an automotive competitor."),
            ],
        },
        {
            "ticker": "GM",
            "rels": [
                ("GM-1", "jv_partner", "LG Energy Solution", "company", "depends_on_target",
                 "Through our Ultium Cells LLC joint venture with LG Energy Solution, we manufacture battery cells in Ohio and Tennessee.",
                 "critical", False, "Ultium Cells LLC joint venture", "gold"),
                ("GM-2", "facility", "Arlington, Texas", "facility", "depends_on_target",
                 "Our full-size SUV assembly plant in Arlington, Texas produces Chevrolet Tahoe, Suburban, and GMC Yukon vehicles.",
                 "medium", False, "SUV assembly plant", "gold"),
            ],
            "negs": [
                ("GM-N1", "Ford Motor Company", "competitor",
                 "We face intense competition in trucks and EVs from Ford Motor Company, Toyota, and Hyundai."),
            ],
            "pred_matches": [0, 1],
            "vint_rejected": [],
        },
        {
            "ticker": "BA",
            "rels": [
                ("BA-1", "supplier", "Spirit AeroSystems Holdings, Inc.", "company", "depends_on_target",
                 "Spirit AeroSystems is the sole-source supplier of the 737 fuselage and key aerostructures across our commercial airplanes.",
                 "critical", True, "sole-source 737 fuselage", "gold"),
                ("BA-2", "supplier", "CFM International", "company", "depends_on_target",
                 "CFM International is the exclusive engine supplier for the 737 MAX family with the LEAP-1B engine.",
                 "critical", True, "exclusive 737 MAX engine supplier", "gold"),
                ("BA-3", "facility", "Everett, Washington", "facility", "depends_on_target",
                 "We conduct widebody commercial airplane manufacturing and final assembly at our facilities in Everett, Washington.",
                 "medium", False, "widebody assembly", "gold"),
            ],
            "negs": [
                ("BA-N1", "Airbus", "competitor",
                 "In the commercial jetliner market, our principal global competitor is Airbus."),
                ("BA-N2", "hypothetical tariff disruption", "hypothetical",
                 "Future geopolitical tensions could potentially disrupt titanium supply if new sanctions were enacted."),
            ],
            "pred_matches": [0, 1, 2],
            "vint_rejected": [
                ("customer", "Airbus", "company",
                 "In the commercial jetliner market, our principal global competitor is Airbus.",
                 "competitor_mention", "Airbus is identified as Boeing's principal competitor."),
            ],
        },
        {
            "ticker": "SWKS",
            "rels": [
                ("SWKS-1", "customer", "Apple Inc.", "company", "target_depends_on_company",
                 "In fiscal 2025, Apple Inc., through sales to its contract manufacturers and distributors, accounted for 66% of our net revenue.",
                 "critical", False, "66% of net revenue", "gold"),
                ("SWKS-2", "facility", "Mexicali, Mexico", "facility", "depends_on_target",
                 "We operate back-end assembly, packaging, and test manufacturing facilities in Mexicali, Mexico.",
                 "medium", False, "assembly and test", "gold"),
                ("SWKS-3", "foundry", "Taiwan Semiconductor Manufacturing Co., Ltd.", "company", "depends_on_target",
                 "We rely on external silicon foundries, including TSMC, for wafer fabrication of advanced CMOS and SOI components.",
                 "high", False, "wafer fabrication", "pooled"),
            ],
            "negs": [
                ("SWKS-N1", "Qorvo", "competitor",
                 "Our primary RF front-end semiconductor competitors include Qorvo, Broadcom, and Qualcomm."),
            ],
            "pred_matches": [0, 1, 2],
            "vint_rejected": [
                ("supplier", "Qorvo", "company",
                 "Our primary RF front-end semiconductor competitors include Qorvo, Broadcom, and Qualcomm.",
                 "competitor_mention", "Qorvo is listed among RF semiconductor competitors."),
            ],
        },
        {
            "ticker": "QRVO",
            "rels": [
                ("QRVO-1", "customer", "Apple Inc.", "company", "target_depends_on_company",
                 "Sales to Apple Inc. and its designated contract manufacturers accounted for approximately 46% of total revenue in fiscal 2025.",
                 "critical", False, "46% of total revenue", "gold"),
                ("QRVO-2", "customer", "Samsung Electronics", "company", "target_depends_on_company",
                 "Samsung Electronics accounted for approximately 12% of our total revenue in fiscal 2025.",
                 "high", False, "12% of total revenue", "gold"),
                ("QRVO-3", "facility", "Richardson, Texas", "facility", "depends_on_target",
                 "Our primary GaAs and GaN wafer fabrication operations are located in Richardson, Texas and Hillsboro, Oregon.",
                 "medium", False, "wafer fabrication", "gold"),
            ],
            "negs": [
                ("QRVO-N1", "Skyworks Solutions", "competitor",
                 "We compete directly with Skyworks Solutions, Qualcomm, and Murata in cellular RF front-end modules."),
                ("QRVO-N2", "Philadelphia Semiconductor Index", "unrelated",
                 "The stock performance graph compares Qorvo's cumulative return against the Philadelphia Semiconductor Index."),
            ],
            "pred_matches": [0, 1, 2],
            "vint_rejected": [],
        },
        {
            "ticker": "GLW",
            "rels": [
                ("GLW-1", "key_input", "noble metals (platinum and rhodium)", "material", "depends_on_target",
                 "Our glass melting processes require significant quantities of noble metals, primarily platinum and rhodium, which are critical inputs.",
                 "high", False, "glass melting noble metals", "gold"),
                ("GLW-2", "customer", "Unnamed customer", "unnamed_customer", "target_depends_on_company",
                 "In the Display Technologies segment, one customer accounted for 28% of segment net sales in 2025.",
                 "high", False, "28% of segment net sales", "gold"),
                ("GLW-3", "facility", "Tainan, Taiwan", "facility", "depends_on_target",
                 "We manufacture display glass substrates at our large-generation facilities in Tainan and Taichung, Taiwan.",
                 "medium", False, "display glass substrates", "gold"),
            ],
            "negs": [
                ("GLW-N1", "AGC Inc.", "competitor",
                 "In Display Technologies, our principal competitors are AGC Inc. and Nippon Electric Glass."),
            ],
            "pred_matches": [0, 1, 2],
            "vint_rejected": [],
        },
        {
            "ticker": "PFE",
            "rels": [
                ("PFE-1", "jv_partner", "BioNTech SE", "company", "depends_on_target",
                 "We collaborate with BioNTech SE under a global co-development and 50/50 gross profit sharing agreement for Comirnaty.",
                 "critical", False, "50/50 profit sharing alliance", "gold"),
                ("PFE-2", "customer", "McKesson Corporation", "company", "target_depends_on_company",
                 "McKesson Corporation accounted for approximately 31% of our total biopharmaceutical revenues in 2025.",
                 "critical", False, "31% of total revenues", "gold"),
                ("PFE-3", "customer", "Cencora, Inc.", "company", "target_depends_on_company",
                 "Cencora, Inc. accounted for approximately 21% of our total biopharmaceutical revenues in 2025.",
                 "high", False, "21% of total revenues", "gold"),
                ("PFE-4", "facility", "Puurs, Belgium", "facility", "depends_on_target",
                 "Our sterile injectable and vaccine manufacturing site in Puurs, Belgium supplies global markets.",
                 "medium", False, "sterile injectable manufacturing", "gold"),
            ],
            "negs": [
                ("PFE-N1", "Merck & Co.", "competitor",
                 "Our vaccines and oncology products compete with offerings from Merck & Co., AstraZeneca, and Novartis."),
            ],
            "pred_matches": [0, 1, 2],  # PFE-4 left as FN to exercise non-trivial recall < 100%
            "vint_rejected": [
                ("supplier", "Merck & Co.", "company",
                 "Our vaccines and oncology products compete with offerings from Merck & Co., AstraZeneca, and Novartis.",
                 "competitor_mention", "Merck & Co. is named as a competitor."),
            ],
        },
        {
            "ticker": "DE",
            "rels": [
                ("DE-1", "key_input", "hot-rolled and cold-rolled steel", "material", "depends_on_target",
                 "Steel and grey iron castings are principal raw materials required across our agricultural and construction equipment operations.",
                 "high", False, "principal raw materials", "gold"),
                ("DE-2", "facility", "Waterloo, Iowa", "facility", "depends_on_target",
                 "We manufacture large agricultural tractors and powertrains at our facilities in Waterloo, Iowa and Mannheim, Germany.",
                 "medium", False, "tractor manufacturing", "gold"),
            ],
            "negs": [
                ("DE-N1", "CNH Industrial", "competitor",
                 "In agricultural equipment, our primary global competitors include CNH Industrial, AGCO, and Kubota."),
            ],
            "pred_matches": [0, 1],
            "vint_rejected": [],
        },
        {
            "ticker": "SBUX",
            "rels": [
                ("SBUX-1", "key_input", "high-quality arabica green coffee", "material", "depends_on_target",
                 "We purchase significant quantities of high-quality arabica green coffee from coffee-producing regions worldwide.",
                 "high", False, "arabica coffee beans", "gold"),
                ("SBUX-2", "facility", "Kent, Washington", "facility", "depends_on_target",
                 "We operate six domestic coffee roasting and packaging plants, including Kent, Washington and Minden, Nevada.",
                 "medium", False, "roasting plant", "gold"),
            ],
            "negs": [
                ("SBUX-N1", "Luckin Coffee", "competitor",
                 "In China and international specialty coffee markets, we compete with Luckin Coffee, Costa Coffee, and local chains."),
            ],
            "pred_matches": [0, 1],
            "vint_rejected": [
                ("customer", "Luckin Coffee", "company",
                 "In China and international specialty coffee markets, we compete with Luckin Coffee, Costa Coffee, and local chains.",
                 "competitor_mention", "Luckin Coffee is listed as a specialty coffee competitor."),
            ],
        },
    ]

    gold_docs: list[GoldDocument] = []
    recorded: dict[str, RecordedCompanyPrediction] = {}

    for spec in specs:
        held = HELD_OUT_BY_TICKER[spec["ticker"]]
        filing_url = (
            f"https://www.sec.gov/Archives/edgar/data/{int(held.cik)}/"
            f"{held.pinned_accession.replace('-', '')}/{held.ticker.lower()}-20251231.htm"
        )
        rels = [
            GoldRelationship(
                id=r[0],
                edge_type=r[1],
                target_name=r[2],
                target_kind=r[3],
                direction=r[4],
                quote=r[5],
                importance=r[6],
                sole_source=r[7],
                qualifier=r[8],
                source=r[9],
            )
            for r in spec["rels"]
        ]
        negs = [
            GoldNegative(
                id=n[0],
                target_name=n[1],
                kind=n[2],
                quote=n[3],
            )
            for n in spec["negs"]
        ]
        doc = GoldDocument(
            company=GoldCompany(name=held.name, cik=held.cik, ticker=held.ticker),
            filing=GoldFiling(
                form="10-K",
                accession=held.pinned_accession,
                url=filing_url,
                filed="2026-01-15",
            ),
            annotator="synthetic_baseline",
            relationships=rels,
            negatives=negs,
        )
        gold_docs.append(doc)

        filing_ref = FilingRef(
            company_key=held.company_key,
            form="10-K",
            accession=held.pinned_accession,
            filed=date(2026, 1, 15),
            url=filing_url,
        )

        surviving_edges: list[dict[str, Any]] = []
        for idx in spec["pred_matches"]:
            rel = rels[idx]
            pred_target_name = "TSMC" if "Taiwan Semiconductor" in rel.target_name else rel.target_name
            pred_edge_type = "supplier" if rel.id == "DE-1" else rel.edge_type
            eid = make_edge_id(held.pinned_accession, rel.quote, pred_edge_type, pred_target_name)
            edge = VerifiedEdge(
                edge_id=eid,
                source_company_key=held.company_key,
                source_company_name=held.name,
                source_in_portfolio=True,
                edge_type=pred_edge_type,
                target_name=pred_target_name,
                target_kind=rel.target_kind,
                sole_source=bool(rel.sole_source),
                qualifier=rel.qualifier,
                evidence_quote=rel.quote,
                section="Item 1",
                filing=filing_ref,
                interpretation=EdgeInterpretation(
                    status="confirmed",
                    method="rules",
                    flags=[],
                ),
            )
            scored_edge = _attach_importance_if_needed([edge])[0]
            surviving_edges.append(scored_edge.model_dump(mode="json"))

        vint_rej_edges: list[dict[str, Any]] = []
        for vr in spec["vint_rejected"]:
            v_type, v_target, v_kind, v_quote, v_flag, v_reason = vr
            eid = make_edge_id(held.pinned_accession, v_quote, v_type, v_target)
            edge = VerifiedEdge(
                edge_id=eid,
                source_company_key=held.company_key,
                source_company_name=held.name,
                source_in_portfolio=True,
                edge_type=v_type,
                target_name=v_target,
                target_kind=v_kind,
                sole_source=False,
                evidence_quote=v_quote,
                section="Item 1",
                filing=filing_ref,
                interpretation=EdgeInterpretation(
                    status="rejected",
                    method="rules",
                    flags=[v_flag],
                    reason=v_reason,
                ),
            )
            vint_rej_edges.append(edge.model_dump(mode="json"))

        recorded[held.ticker] = RecordedCompanyPrediction(
            ticker=held.ticker,
            company_key=held.company_key,
            company_name=held.name,
            filing_accession=held.pinned_accession,
            filing_form="10-K",
            filing_filed="2026-01-15",
            filing_url=filing_url,
            prompt_version=detect_extractor_prompt_version(),
            judge_prompt_version=detect_judge_prompt_version(),
            model="synthetic-replay",
            edges=surviving_edges,
            vint_rejected_edges=vint_rej_edges,
        )

    return gold_docs, recorded


def _run_vint_if_available(
    edges: Sequence[VerifiedEdge],
    canonical_text: str,
    *,
    client: Any = None,
    cache: Any = None,
    cache_only: bool = False,
) -> tuple[list[VerifiedEdge], list[VerifiedEdge]]:
    """Run `hoc.ai.verify_company_interpretations` when available, or partition by existing `edge.interpretation`."""
    already_rejected = [
        e for e in edges if e.interpretation is not None and e.interpretation.status == "rejected"
    ]
    surviving = [
        e for e in edges if e.interpretation is None or e.interpretation.status != "rejected"
    ]
    if any(e.interpretation is not None for e in edges):
        return surviving, already_rejected

    try:
        from hoc.ai import verify_company_interpretations  # type: ignore[attr-defined]

        res = verify_company_interpretations(
            list(edges),
            canonical_text,
            client=client,
            cache=cache,
            cache_only=cache_only,
        )
        post_edges = list(getattr(res, "edges", surviving))
        rej_edges = list(getattr(res, "rejected_edges", already_rejected))
        return post_edges, rej_edges
    except (ImportError, AttributeError, TypeError, ValueError):
        return surviving, already_rejected


def _recover_vint_rejected_from_cache(
    *,
    extractor: Any,
    company_key: str,
    company_name: str,
    filing: Any,
    model_name: str | None,
) -> list[VerifiedEdge]:
    """Recover V-INT rejected edges from `extractor.cache` (`raw_edges`) + cached `ai/judge` verdicts."""
    if extractor is None or getattr(extractor, "cache", None) is None or filing is None:
        return []
    try:
        from hoc.ai import verify_and_build_edges, verify_company_interpretations
        from hoc.ai.client import DEFAULT_EXTRACTOR_MODEL

        used_model = model_name or getattr(extractor.client, "extractor_model", None) or DEFAULT_EXTRACTOR_MODEL
        cached = extractor.cache.get(
            company_key,
            filing.accession,
            model=used_model,
            prompt_version=extractor.prompt_version,
        )
        if not isinstance(cached, Mapping):
            return []
        raw_edges = cached.get("raw_edges")
        if not isinstance(raw_edges, list):
            return []
        filing_ref = FilingRef(
            company_key=company_key,
            form="20-F" if "20-F" in str(filing.form).upper() else "10-K",
            accession=filing.accession,
            filed=filing.filed,
            url=filing.url,
        )
        quote_verified, _rej = verify_and_build_edges(
            raw_edges,
            source_company_key=company_key,
            source_company_name=company_name,
            source_in_portfolio=True,
            canonical_text=filing.text,
            filing_ref=filing_ref,
            sections=filing.sections,
            resolve_target_key=extractor.resolve_target_key,
        )
        interp_res = verify_company_interpretations(
            quote_verified,
            filing.text,
            client=extractor.client,
            cache=extractor.cache,
            cache_only=True,
        )
        return list(getattr(interp_res, "rejected_edges", ()))
    except (ImportError, AttributeError, TypeError, ValueError):
        return []


def _run_agentic_if_available(
    *,
    company_key: str,
    company_name: str,
    ticker: str,
    filing: Any,
    edges_before_agentic: Sequence[VerifiedEdge],
    depth: Literal["none", "light", "thorough"] = "light",
    client: Any = None,
    fetcher: Any = None,
    cache: Any = None,
    disk_cache: Any = None,
    aliases: Any = None,
    resolve_target_key: Any = None,
    cache_only: bool = False,
) -> tuple[list[VerifiedEdge], list[dict[str, Any]], list[str], int, int, int]:
    """Run per-company agentic research (`A1`) when available.

    Returns `(final_edges, findings_dicts, rejected_edge_ids, steps_done, steps_total, interp_rejected)`.
    """
    if depth == "none":
        return list(edges_before_agentic), [], [], 0, 0, 0

    try:
        import hoc.research as _res_mod
        from hoc.contract import CompanyExposure
    except ImportError:
        return list(edges_before_agentic), [], [], 0, 0, 0

    company_exp = CompanyExposure(
        rank=1,
        company_key=company_key,
        company_name=company_name,
        identity_status="resolved",
        symbols=[ticker] if ticker else [],
        sector="unknown",
        country=None,
        exposure=0.10,
        etf_count=1,
        contributions=[],
        securities=[],
    )

    runner_fn = getattr(_res_mod, "research_company", None)
    if runner_fn is None:
        loop_cls = getattr(_res_mod, "ResearchLoop", None)
        if loop_cls is not None and client is not None and fetcher is not None:
            try:
                loop_inst = loop_cls(
                    client=client,
                    fetcher=fetcher,
                    cache=cache,
                    disk_cache=disk_cache,
                    aliases=aliases,
                )
                runner_fn = getattr(loop_inst, "research_company", None) or getattr(
                    loop_inst, "run_company", None
                )
            except Exception:
                runner_fn = None

    if runner_fn is None:
        return list(edges_before_agentic), [], [], 0, 0, 0

    try:
        sig = inspect.signature(runner_fn)
        kwargs: dict[str, Any] = {
            "depth": depth,
            "cache_only": cache_only,
        }
        if "resolve_target_key" in sig.parameters and resolve_target_key is not None:
            kwargs["resolve_target_key"] = resolve_target_key
        if "filing_obj" in sig.parameters and filing is not None:
            kwargs["filing_obj"] = filing
        if "client" in sig.parameters and client is not None:
            kwargs["client"] = client
        if "fetcher" in sig.parameters and fetcher is not None:
            kwargs["fetcher"] = fetcher
        if "cache" in sig.parameters and cache is not None:
            kwargs["cache"] = cache
        if "disk_cache" in sig.parameters and disk_cache is not None:
            kwargs["disk_cache"] = disk_cache
        if "aliases" in sig.parameters and aliases is not None:
            kwargs["aliases"] = aliases

        res = runner_fn(company_exp, filing, list(edges_before_agentic), **kwargs)
        final_edges = _attach_importance_if_needed(
            list(getattr(res, "edges", edges_before_agentic))
        )
        raw_findings = list(getattr(res, "findings", ()) or ())
        findings_dicts = [
            f.model_dump(mode="json") if hasattr(f, "model_dump") else dict(f)
            for f in raw_findings
        ]
        rejected_ids = [str(eid) for eid in (getattr(res, "rejected_edge_ids", ()) or ())]
        steps_done = int(getattr(res, "steps_done", 0) or 0)
        steps_total = int(getattr(res, "steps_total", 0) or 0)
        interp_rej = int(getattr(res, "interpretation_rejected", 0) or 0)
        return final_edges, findings_dicts, rejected_ids, steps_done, steps_total, interp_rej
    except Exception as exc:
        if not cache_only:
            print(
                f"[eval warning] agentic research failed for {ticker} ({company_key}): {exc}",
                file=sys.stderr,
            )
        return list(edges_before_agentic), [], [], 0, 0, 0


def run_evaluation(
    *,
    live: bool = False,
    gold_dir: Path = DEFAULT_GOLD_DIR,
    recorded_dir: Path = DEFAULT_RECORDED_DIR,
    tickers: Sequence[str] | None = None,
    depth: Literal["none", "light", "thorough"] = "light",
    bootstrap_iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> EvalRunReport:
    """Execute the unseen-data evaluation harness in `--replay` or `--live` mode and return `EvalRunReport`."""
    gold_docs = load_gold_directory(gold_dir, tickers=list(tickers) if tickers else None)
    recorded_by_ticker = load_recorded_predictions(recorded_dir)

    run_mode: Literal["replay", "live", "synthetic_baseline"] = "live" if live else "replay"
    if not gold_docs and not live:
        gold_docs, recorded_by_ticker = build_synthetic_held_out_fixture()
        if tickers:
            wanted = {t.upper() for t in tickers}
            gold_docs = [d for d in gold_docs if d.company.ticker.upper() in wanted]
        run_mode = "synthetic_baseline"

    fetcher = None
    extractor = None
    extractor_cache = None
    gemini_client = None
    disk_cache = None
    aliases = None
    resolver = None

    if live or any(d.company.ticker.upper() not in recorded_by_ticker for d in gold_docs):
        try:
            from hoc.ai import DependencyExtractor, ExtractionCache, GeminiClient
            from hoc.config import Settings
            from hoc.core.cache import DiskCache
            from hoc.core.http import CachedHttpClient
            from hoc.filings.fetch import FilingFetcher
            from hoc.filings.names import NameResolver
            from hoc.identity.resolver import load_aliases

            settings = Settings.from_env()
            disk_cache = DiskCache(settings.cache_dir)
            extractor_cache = ExtractionCache(disk_cache)
            http = CachedHttpClient(settings, disk_cache)
            fetcher = FilingFetcher(http, settings)
            gemini_client = GeminiClient(http, settings)
            aliases = load_aliases()
            resolver = NameResolver([], aliases).resolve
            extractor = DependencyExtractor(
                gemini_client,
                extractor_cache,
                filing_fetcher=fetcher,
                resolve_target_key=resolver,
            )
        except Exception:
            if live:
                raise

    bundles: list[CompanyEvalBundle] = []
    for gold_doc in gold_docs:
        ticker = gold_doc.company.ticker.upper()
        cik = gold_doc.company.normalised_cik
        company_key = gold_doc.company.company_key

        if not live and ticker in recorded_by_ticker:
            rec = recorded_by_ticker[ticker]
            edges_before_ag = _hydrate_recorded_edges(rec.edges)
            edges_after_ag = (
                _hydrate_recorded_edges(rec.agentic_edges)
                if rec.agentic_edges is not None and depth != "none"
                else edges_before_ag
            )
            edges_rej = _hydrate_recorded_edges(rec.vint_rejected_edges)
            before_ids = {e.edge_id for e in edges_before_ag}
            after_ids = {e.edge_id for e in edges_after_ag}
            new_cnt = len(after_ids - before_ids)
            rej_cnt = len(rec.agentic_rejected_edge_ids) or len(before_ids - after_ids)
            bundles.append(
                evaluate_company(
                    gold_doc,
                    edges_after_ag,
                    vint_rejected_edges=edges_rej,
                    before_agentic_edges=edges_before_ag,
                    agentic_findings=rec.agentic_findings if depth != "none" else (),
                    agentic_findings_count=len(rec.agentic_findings) if depth != "none" else 0,
                    agentic_steps_done=rec.agentic_steps_done if depth != "none" else 0,
                    agentic_steps_total=rec.agentic_steps_total if depth != "none" else 0,
                    agentic_new_edges_count=new_cnt if depth != "none" else 0,
                    agentic_rejected_edges_count=rej_cnt if depth != "none" else 0,
                )
            )
            continue

        # Live mode or cache-only fallback from ExtractionCache
        edges_before_ag: list[VerifiedEdge] = []
        edges_after_ag: list[VerifiedEdge] = []
        edges_rej: list[VerifiedEdge] = []
        ag_findings: list[dict[str, Any]] = []
        ag_rej_ids: list[str] = []
        ag_steps_done = 0
        ag_steps_total = 0
        ag_interp_rej = 0

        if fetcher is not None and extractor is not None:
            try:
                filing = fetcher.latest(cik)
                quote_errors = verify_gold_quotes(gold_doc, filing.text)
                if quote_errors:
                    for err in quote_errors:
                        print(f"[eval warning] {err}", file=sys.stderr)

                existing_rec = recorded_by_ticker.get(ticker)
                used_model: str | None = None
                quote_rej_count: int = 0
                if (
                    existing_rec is not None
                    and existing_rec.edges
                    and existing_rec.filing_accession == filing.accession
                    and existing_rec.prompt_version == detect_extractor_prompt_version()
                ):
                    edges_before_ag = _hydrate_recorded_edges(existing_rec.edges)
                    edges_rej = _hydrate_recorded_edges(existing_rec.vint_rejected_edges)
                    used_model = existing_rec.model
                    quote_rej_count = existing_rec.quote_rejected_count
                else:
                    outcome = extractor.extract_company(
                        company_key=company_key,
                        company_name=gold_doc.company.name,
                        filing=filing,
                        cache_only=(not live),
                    )
                    if live and outcome.status not in {"done", "cached"}:
                        raise RuntimeError(
                            f"Live extraction failed for {ticker} ({company_key}): "
                            f"status={outcome.status}, error={outcome.error_message}"
                        )
                    used_model = outcome.model
                    quote_rej_count = outcome.rejected_count
                    raw_verified = list(outcome.edges)
                    explicit_vint_rej = list(getattr(outcome, "rejected_edges_list", ()) or ())
                    if not explicit_vint_rej:
                        explicit_vint_rej = _recover_vint_rejected_from_cache(
                            extractor=extractor,
                            company_key=company_key,
                            company_name=gold_doc.company.name,
                            filing=filing,
                            model_name=outcome.model,
                        )
                    if explicit_vint_rej:
                        edges_before_ag = _attach_importance_if_needed(raw_verified)
                        edges_rej = _attach_importance_if_needed(explicit_vint_rej)
                    else:
                        post_edges, rej_edges = _run_vint_if_available(
                            raw_verified,
                            filing.text,
                            client=gemini_client,
                            cache=disk_cache,
                            cache_only=(not live),
                        )
                        edges_before_ag = _attach_importance_if_needed(post_edges)
                        edges_rej = _attach_importance_if_needed(rej_edges)

                (
                    edges_after_ag,
                    ag_findings,
                    ag_rej_ids,
                    ag_steps_done,
                    ag_steps_total,
                    ag_interp_rej,
                ) = _run_agentic_if_available(
                    company_key=company_key,
                    company_name=gold_doc.company.name,
                    ticker=ticker,
                    filing=filing,
                    edges_before_agentic=edges_before_ag,
                    depth=depth,
                    client=gemini_client,
                    fetcher=fetcher,
                    cache=extractor_cache,
                    disk_cache=disk_cache,
                    aliases=aliases,
                    resolve_target_key=resolver,
                    cache_only=(not live),
                )

                if live:
                    save_recorded_prediction(
                        recorded_dir,
                        RecordedCompanyPrediction(
                            ticker=ticker,
                            company_key=company_key,
                            company_name=gold_doc.company.name,
                            filing_accession=filing.accession,
                            filing_form=filing.form,
                            filing_filed=filing.filed.isoformat(),
                            filing_url=filing.url,
                            prompt_version=detect_extractor_prompt_version(),
                            judge_prompt_version=detect_judge_prompt_version(),
                            model=used_model,
                            edges=[e.model_dump(mode="json") for e in edges_before_ag],
                            vint_rejected_edges=[e.model_dump(mode="json") for e in edges_rej],
                            quote_rejected_count=quote_rej_count,
                            research_depth=depth,
                            agentic_edges=[e.model_dump(mode="json") for e in edges_after_ag],
                            agentic_findings=ag_findings,
                            agentic_rejected_edge_ids=ag_rej_ids,
                            agentic_steps_done=ag_steps_done,
                            agentic_steps_total=ag_steps_total,
                            agentic_interpretation_rejected=ag_interp_rej,
                        ),
                    )
            except Exception as exc:
                if live:
                    raise
                print(
                    f"[eval replay] {ticker} not in recorded_dir or local cache ({exc}); scoring with 0 predictions.",
                    file=sys.stderr,
                )

        before_ids = {e.edge_id for e in edges_before_ag}
        after_ids = {e.edge_id for e in edges_after_ag}
        new_cnt = len(after_ids - before_ids)
        rej_cnt = len(ag_rej_ids) or len(before_ids - after_ids)
        bundles.append(
            evaluate_company(
                gold_doc,
                edges_after_ag,
                vint_rejected_edges=edges_rej,
                before_agentic_edges=edges_before_ag,
                agentic_findings=ag_findings,
                agentic_findings_count=len(ag_findings),
                agentic_steps_done=ag_steps_done,
                agentic_steps_total=ag_steps_total,
                agentic_new_edges_count=new_cnt,
                agentic_rejected_edges_count=rej_cnt,
            )
        )

    return aggregate_eval_report(
        bundles,
        mode=run_mode,
        git_commit=detect_git_commit(),
        extractor_prompt_version=detect_extractor_prompt_version(),
        judge_prompt_version=detect_judge_prompt_version(),
        research_depth=depth,
        bootstrap_iterations=bootstrap_iterations,
        bootstrap_seed=bootstrap_seed,
    )


def format_console_summary(report: EvalRunReport) -> str:
    """Format a concise console summary for `hoc eval`."""
    p = report.overall_after_vint.precision
    r = report.overall_after_vint.recall
    f1 = report.overall_after_vint.f1
    blind = report.blind_overall_after_vint or report.overall_after_vint
    p_blind = blind.precision
    f1_blind = blind.f1
    p_pre = report.overall_before_vint.precision
    hn_pre = report.hard_negative_fp_rate_before_vint
    hn_post = report.hard_negative_fp_rate_after_vint
    dir_acc = report.direction_accuracy
    fac_acc = report.facility_country_accuracy
    kappa = report.importance_weighted_kappa

    pre_ag = report.overall_before_agentic or report.overall_after_vint
    pre_ag_blind = report.blind_overall_before_agentic or blind

    src_str = ", ".join(f"{k}={v}" for k, v in sorted(report.gold_core_by_source.items())) or "none"
    lines = [
        (
            f"House of Cards v3.1 Evaluation ({report.mode}, depth={report.research_depth}, commit {report.git_commit}, "
            f"extractor {report.extractor_prompt_version}, judge {report.judge_prompt_version})"
        ),
        (
            f"Companies: {report.companies_evaluated} | Gold: {report.gold_relationships_total} "
            f"(core: {report.gold_core_total} [{src_str}], extended: {report.gold_extended_total}, "
            f"pooled: {report.gold_pooled_total}) | Hard negatives: {report.gold_negatives_total}"
        ),
        "",
        (
            f"  Micro Precision (blind)      : {p_blind.value * 100:5.1f}% [{p_blind.ci_low * 100:5.1f}%, {p_blind.ci_high * 100:5.1f}%] "
            f"({p_blind.numerator}/{p_blind.denominator}; before agentic: {pre_ag_blind.precision.value * 100:5.1f}%, {pre_ag_blind.precision.numerator}/{pre_ag_blind.precision.denominator})"
        ),
        (
            f"  Micro Precision (pooled)     : {p.value * 100:5.1f}% [{p.ci_low * 100:5.1f}%, {p.ci_high * 100:5.1f}%] "
            f"({p.numerator}/{p.denominator}; before agentic: {pre_ag.precision.value * 100:5.1f}%, {pre_ag.precision.numerator}/{pre_ag.precision.denominator}; before V-INT: {p_pre.value * 100:5.1f}%)"
        ),
        (
            f"  Micro Recall    (core, post) : {r.value * 100:5.1f}% [{r.ci_low * 100:5.1f}%, {r.ci_high * 100:5.1f}%] "
            f"({r.numerator}/{r.denominator}; before agentic: {pre_ag.recall.value * 100:5.1f}%, {pre_ag.recall.numerator}/{pre_ag.recall.denominator})"
        ),
        (
            f"  Micro F1        (blind/pool) : {f1_blind.value * 100:5.1f}% [{f1_blind.ci_low * 100:5.1f}%, {f1_blind.ci_high * 100:5.1f}%] / "
            f"{f1.value * 100:5.1f}% [{f1.ci_low * 100:5.1f}%, {f1.ci_high * 100:5.1f}%] "
            f"(before agentic: {pre_ag_blind.f1.value * 100:5.1f}% / {pre_ag.f1.value * 100:5.1f}%)"
        ),
        (
            f"  Agentic Sub-Agents           : {report.agentic_findings_total} findings, "
            f"{report.agentic_steps_done_total}/{report.agentic_steps_total} steps, "
            f"+{report.agentic_new_edges_total} new / -{report.agentic_rejected_edges_total} rejected edges"
        ),
        f"  Direction Accuracy           : {dir_acc.value * 100:5.1f}% ({dir_acc.numerator}/{dir_acc.denominator})",
        (
            f"  Hard-Negative FP Rate        : {hn_post.value * 100:5.1f}% ({hn_post.numerator}/{hn_post.denominator}) "
            f"(before V-INT: {hn_pre.value * 100:5.1f}%, {hn_pre.numerator}/{hn_pre.denominator})"
        ),
        f"  Facility-Country Accuracy    : {fac_acc.value * 100:5.1f}% ({fac_acc.numerator}/{fac_acc.denominator})",
        f"  Importance Weighted Kappa    : {kappa.value:5.3f} [{kappa.ci_low:5.3f}, {kappa.ci_high:5.3f}]",
    ]
    if report.agentic_acceptance is not None and report.agentic_acceptance.findings_total > 0:
        lines.append("")
        lines.append(format_agentic_acceptance_summary(report.agentic_acceptance))
    return "\n".join(lines)


def _load_agentic_check_target(path_or_tag: str, recorded_dir: Path) -> Any:
    if path_or_tag.strip().lower() == "recorded":
        return list(load_recorded_predictions(recorded_dir).values())
    p = Path(path_or_tag)
    if p.is_dir():
        return list(load_recorded_predictions(p).values())
    return json.loads(p.read_text(encoding="utf-8"))


def _run_check_agentic(
    target: str,
    thorough_target: str | None,
    recorded_dir: Path,
    *,
    as_json: bool = False,
) -> int:
    light_obj = _load_agentic_check_target(target, recorded_dir)
    thorough_obj = (
        _load_agentic_check_target(thorough_target, recorded_dir)
        if thorough_target
        else None
    )
    acc = evaluate_agentic_acceptance(light_obj, thorough_obj)
    if as_json:
        print(acc.model_dump_json(indent=2))
    else:
        print(format_agentic_acceptance_summary(acc))
    return 0


def _run_compare_annotators(gold_dir: Path) -> int:
    """Compare `<TICKER>.a.json` (or `<TICKER>.json`) vs `<TICKER>.b.json` across the 10 held-out companies."""
    found = 0
    for comp in HELD_OUT_COMPANIES:
        path_a = gold_dir / f"{comp.ticker}.a.json"
        if not path_a.exists():
            path_a = gold_dir / f"{comp.ticker}.json"
        path_b = gold_dir / f"{comp.ticker}.b.json"
        if not path_a.exists() or not path_b.exists():
            continue
        doc_a = load_gold_document(path_a)
        doc_b = load_gold_document(path_b)
        summary = compare_annotator_docs(doc_a, doc_b)
        found += 1
        print(
            f"{summary.ticker:<6} A={summary.a_count:>2} B={summary.b_count:>2} "
            f"matched={summary.matched_count:>2} F1={summary.f1_agreement:.2f} "
            f"dir={summary.direction_agreement:.2f} kappa={summary.importance_quadratic_kappa:.2f}"
        )
    if found == 0:
        print(f"No annotator A/B pairs found in {gold_dir}", file=sys.stderr)
        return 1
    return 0


def build_eval_arg_parser(
    parser: argparse.ArgumentParser | None = None,
) -> argparse.ArgumentParser:
    """Configure CLI arguments on `parser` (can be used standalone or as a subparser in `hoc.cli`)."""
    p = parser or argparse.ArgumentParser(
        prog="hoc eval",
        description="House of Cards v3 unseen-data dependency evaluation harness (E-RUN)",
    )
    mode_group = p.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--replay",
        action="store_true",
        default=True,
        help="score recorded predictions offline without network or Gemini API calls (default)",
    )
    mode_group.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="fetch held-out 10-K filings, run live extraction + V-INT, record outputs, and score",
    )
    p.add_argument(
        "--gold-dir",
        type=Path,
        default=DEFAULT_GOLD_DIR,
        help="directory containing adjudicated <TICKER>.json gold files",
    )
    p.add_argument(
        "--recorded-dir",
        type=Path,
        default=DEFAULT_RECORDED_DIR,
        help="directory for recorded prediction snapshots (<TICKER>.json)",
    )
    p.add_argument(
        "--out-md",
        type=Path,
        default=DEFAULT_EVAL_MD,
        help="output path for the Markdown evaluation report (default: docs/hoc/EVAL.md)",
    )
    p.add_argument(
        "--out-json",
        type=Path,
        default=DEFAULT_EVAL_JSON,
        help="output path for the JSON evaluation results (default: docs/hoc/eval/results.json)",
    )
    p.add_argument(
        "--tickers",
        help="optional comma-separated subset of tickers to evaluate (e.g. NKE,BA,SWKS)",
    )
    p.add_argument(
        "--depth",
        choices=("none", "light", "thorough"),
        default="light",
        help="agentic sub-agent research depth: 'light' (default), 'thorough', or 'none'",
    )
    p.add_argument(
        "--check-agentic",
        metavar="PATH_OR_RECORDED",
        help="evaluate FIX-1/FIX-2/FIX-14 agentic acceptance metrics on a DependencyResult/Job JSON file, directory, or 'recorded'",
    )
    p.add_argument(
        "--check-agentic-thorough",
        metavar="PATH",
        help="optional thorough DependencyResult/Job JSON file or directory to verify FIX-2 (thorough contains light)",
    )
    p.add_argument(
        "--compare-annotators",
        action="store_true",
        help="compare annotator A and B gold files (<TICKER>.a.json / <TICKER>.json vs <TICKER>.b.json)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="print the full EvalRunReport JSON to stdout",
    )
    return p


def run_eval_from_args(args: argparse.Namespace) -> int:
    """Execute `hoc eval` from parsed `argparse.Namespace`."""
    if getattr(args, "compare_annotators", False):
        return _run_compare_annotators(args.gold_dir)

    if getattr(args, "check_agentic", None):
        return _run_check_agentic(
            args.check_agentic,
            getattr(args, "check_agentic_thorough", None),
            args.recorded_dir,
            as_json=bool(getattr(args, "json", False)),
        )

    tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if getattr(args, "tickers", None)
        else None
    )
    depth_arg = getattr(args, "depth", "light") or "light"
    report = run_evaluation(
        live=bool(getattr(args, "live", False)),
        gold_dir=args.gold_dir,
        recorded_dir=args.recorded_dir,
        tickers=tickers,
        depth=depth_arg,
    )
    write_eval_outputs(
        report,
        markdown_path=args.out_md,
        json_path=args.out_json,
    )
    if getattr(args, "json", False):
        print(report.model_dump_json(indent=2))
    else:
        print(format_console_summary(report))
        print(f"\nWrote {args.out_md} and {args.out_json}")
    return 0


def run_eval_cli(argv: Sequence[str] | None = None) -> int:
    """Standalone CLI entry point for `python -m hoc.eval` and `hoc eval`."""
    parser = build_eval_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run_eval_from_args(args)
