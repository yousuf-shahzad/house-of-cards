"""Offline unit and replay tests for the v3 unseen-data evaluation harness (package E-RUN).

Owner: Bekarys's Gemini (E-RUN).
Tests all matching, scoring, V-INT before/after comparison, hard-negative detection,
weighted Cohen's kappa, 95% bootstrap CIs, annotator agreement, and CLI offline replay
without touching the network or requiring `GEMINI_API_KEY`.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from hoc.ai.extractor import make_edge_id
from hoc.contract.dependencies import (
    EdgeImportance,
    EdgeInterpretation,
    FilingRef,
    VerifiedEdge,
)
from hoc.eval import (
    HELD_OUT_COMPANIES,
    GoldCompany,
    GoldDocument,
    GoldFiling,
    GoldNegative,
    GoldRelationship,
    aggregate_eval_report,
    bootstrap_ci,
    build_synthetic_held_out_fixture,
    compare_annotator_docs,
    compatible_edge_types,
    compute_weighted_kappa,
    evaluate_company,
    infer_edge_direction,
    load_gold_directory,
    match_predictions_to_gold,
    render_eval_markdown,
    run_eval_cli,
    save_recorded_prediction,
    targets_match,
    verify_gold_quotes,
)


def _make_filing_ref(cik: str = "0000320187", accession: str = "0000320187-26-000088") -> FilingRef:
    return FilingRef(
        company_key=f"CIK:{cik.zfill(10)}",
        form="10-K",
        accession=accession,
        filed=date(2026, 1, 15),
        url=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/form10k.htm",
    )


def _make_edge(
    *,
    edge_type: str = "supplier",
    target_name: str = "TSMC",
    target_kind: str = "company",
    quote: str = "We rely on TSMC for wafer fabrication.",
    sole_source: bool = False,
    qualifier: str | None = None,
    importance_tier: str | None = None,
    vint_status: str | None = None,
    vint_flags: list[str] | None = None,
    source_company_key: str = "CIK:0000320187",
    target_key: str | None = None,
    accession: str = "0000320187-26-000088",
) -> VerifiedEdge:
    filing = _make_filing_ref(source_company_key.removeprefix("CIK:"), accession)
    eid = make_edge_id(accession, quote, edge_type, target_name)
    imp = (
        EdgeImportance(
            score={"critical": 0.9, "high": 0.7, "medium": 0.5, "low": 0.25}[importance_tier],
            tier=importance_tier,  # type: ignore[arg-type]
            reasons=["test"],
        )
        if importance_tier
        else None
    )
    interp = (
        EdgeInterpretation(
            status=vint_status,  # type: ignore[arg-type]
            method="rules",
            flags=vint_flags or [],  # type: ignore[arg-type]
            reason="test interpretation",
        )
        if vint_status
        else None
    )
    return VerifiedEdge(
        edge_id=eid,
        source_company_key=source_company_key,
        source_company_name="Test Corp",
        source_in_portfolio=True,
        edge_type=edge_type,  # type: ignore[arg-type]
        target_name=target_name,
        target_kind=target_kind,  # type: ignore[arg-type]
        target_key=target_key,
        sole_source=sole_source,
        qualifier=qualifier,
        evidence_quote=quote,
        section="Item 1",
        filing=filing,
        importance=imp,
        interpretation=interp,
    )


def test_held_out_manifest_has_ten_companies() -> None:
    assert len(HELD_OUT_COMPANIES) == 10
    tickers = [c.ticker for c in HELD_OUT_COMPANIES]
    assert tickers == ["NKE", "F", "GM", "BA", "SWKS", "QRVO", "GLW", "PFE", "DE", "SBUX"]
    for comp in HELD_OUT_COMPANIES:
        assert len(comp.cik) == 10 and comp.cik.isdigit()
        assert comp.company_key == f"CIK:{comp.cik}"
        assert "-" in comp.pinned_accession


def test_load_gold_directory_skips_raw_annotator_a_and_b_files(tmp_path: Path) -> None:
    gold_docs, _ = build_synthetic_held_out_fixture()
    nke_doc = gold_docs[0]
    (tmp_path / "NKE.json").write_text(nke_doc.model_dump_json(indent=2), encoding="utf-8")
    (tmp_path / "NKE.a.json").write_text(nke_doc.model_dump_json(indent=2), encoding="utf-8")
    (tmp_path / "NKE.b.json").write_text(nke_doc.model_dump_json(indent=2), encoding="utf-8")

    loaded_default = load_gold_directory(tmp_path)
    assert len(loaded_default) == 1
    assert loaded_default[0].company.ticker == "NKE"

    loaded_all = load_gold_directory(tmp_path, include_raw_annotators=True)
    assert len(loaded_all) == 3


def test_verify_gold_quotes_normalises_and_detects_missing() -> None:
    doc = GoldDocument(
        company=GoldCompany(name="Nike, Inc.", cik="0000320187", ticker="NKE"),
        filing=GoldFiling(form="10-K", accession="0000320187-26-000088"),
        relationships=[
            GoldRelationship(
                id="NKE-1",
                edge_type="contract_manufacturer",
                target_name="Vietnam factories",
                target_kind="country",
                direction="depends_on_target",
                quote="Contract factories in Vietnam manufactured 50% of NIKE Brand footwear.",
                importance="critical",
            )
        ],
        negatives=[
            GoldNegative(
                id="NKE-N1",
                target_name="adidas",
                kind="competitor",
                quote="We compete globally with adidas and Puma.",
            )
        ],
    )
    filing_text = (
        "Item 1. Business.\n"
        "Contract  factories\nin\u00a0Vietnam manufactured 50% of NIKE Brand footwear.\n"
        "We compete globally with adidas and Puma."
    )
    assert verify_gold_quotes(doc, filing_text) == []

    bad_filing_text = "Contract factories in Vietnam manufactured 50% of NIKE Brand footwear."
    errors = verify_gold_quotes(doc, bad_filing_text)
    assert len(errors) == 1
    assert "NKE-N1" in errors[0]


def test_compatible_edge_types_and_target_matching() -> None:
    # supplier <-> key_input compatibility
    assert compatible_edge_types("supplier", "key_input")
    assert compatible_edge_types("key_input", "supplier")
    assert compatible_edge_types("foundry", "supplier", pred_sole_source=True)
    # foundry <-> contract_manufacturer compatibility
    assert compatible_edge_types("foundry", "contract_manufacturer")
    assert compatible_edge_types("contract_manufacturer", "foundry")
    # Incompatible pairs
    assert not compatible_edge_types("customer", "supplier")
    assert not compatible_edge_types("facility", "supplier")

    # Alias and legal suffix canonicalisation (TSMC <-> Taiwan Semiconductor Manufacturing Co., Ltd.)
    gold_tsmc = GoldRelationship(
        id="SWKS-1",
        edge_type="foundry",
        target_name="Taiwan Semiconductor Manufacturing Co., Ltd.",
        target_kind="company",
        direction="depends_on_target",
        quote="We rely on Taiwan Semiconductor Manufacturing Co., Ltd. for wafer fabrication.",
        importance="critical",
    )
    pred_tsmc = _make_edge(edge_type="contract_manufacturer", target_name="TSMC", target_kind="company")
    assert targets_match(pred_tsmc, gold_tsmc)

    # Facility ISO-2 country matching ("Mexicali, Mexico" <-> "Baja California, Mexico")
    gold_fac = GoldRelationship(
        id="SWKS-2",
        edge_type="facility",
        target_name="Mexicali, Mexico",
        target_kind="facility",
        direction="depends_on_target",
        quote="We operate assembly facilities in Mexicali, Mexico.",
        importance="medium",
    )
    pred_fac = _make_edge(
        edge_type="facility",
        target_name="Baja California, Mexico",
        target_kind="facility",
        quote="We operate assembly facilities in Baja California, Mexico.",
    )
    assert targets_match(pred_fac, gold_fac)

    # Unnamed customer percentage matching via notes (adjudicator rule #6716140717)
    gold_unnamed = GoldRelationship(
        id="GLW-2",
        edge_type="customer",
        target_name="Unnamed customer",
        target_kind="unnamed_customer",
        direction="target_depends_on_company",
        quote="One customer accounted for 28% of segment net sales.",
        importance="high",
        notes="28% of segment net sales",
    )
    pred_unnamed_match = _make_edge(
        edge_type="customer",
        target_name="Unnamed Customer",
        target_kind="unnamed_customer",
        qualifier="28% of revenue",
        quote="One customer accounted for 28% of segment net sales.",
    )
    pred_unnamed_other = _make_edge(
        edge_type="customer",
        target_name="Unnamed Customer",
        target_kind="unnamed_customer",
        qualifier="14% of revenue",
        quote="Another customer accounted for 14% of segment net sales.",
    )
    assert targets_match(pred_unnamed_match, gold_unnamed)
    assert not targets_match(pred_unnamed_other, gold_unnamed)


def test_bipartite_matching_prevents_double_counting_and_prioritizes_exact_type() -> None:
    doc = GoldDocument(
        company=GoldCompany(name="Boeing", cik="0000012927", ticker="BA"),
        filing=GoldFiling(form="10-K", accession="0001628280-26-004357"),
        relationships=[
            GoldRelationship(
                id="BA-1",
                edge_type="supplier",
                target_name="Spirit AeroSystems Holdings, Inc.",
                target_kind="company",
                direction="depends_on_target",
                quote="Spirit AeroSystems is the sole-source supplier of the 737 fuselage.",
                importance="critical",
                sole_source=True,
            )
        ],
    )
    # Two predicted edges targeting Spirit AeroSystems: one compatible ('key_input') and one exact ('supplier')
    e_compat = _make_edge(
        edge_type="key_input",
        target_name="Spirit AeroSystems",
        target_kind="company",
        quote="Spirit AeroSystems supplies 737 aerostructures.",
    )
    e_exact = _make_edge(
        edge_type="supplier",
        target_name="Spirit AeroSystems",
        target_kind="company",
        quote="Spirit AeroSystems is the sole-source supplier of the 737 fuselage.",
        sole_source=True,
    )
    res = match_predictions_to_gold([e_compat, e_exact], doc)
    # Only 1 gold relationship exists, so tp_core must be 1 (no double-counted recall),
    # exact match wins primary match, and compatible duplicate is not penalized as an FP
    assert res.tp_core == 1
    assert len(res.matched_gold_ids) == 1
    assert len(res.matches) == 2
    assert res.matches[0].edge_id == e_exact.edge_id
    assert res.matches[0].exact_type_match is True
    assert res.matches[0].is_primary_gold_match is True
    assert res.matches[1].edge_id == e_compat.edge_id
    assert res.matches[1].is_primary_gold_match is False
    assert res.tp_total == 2
    assert len(res.unmatched_edges) == 0


def test_before_vs_after_vint_and_hard_negative_kinds() -> None:
    doc = GoldDocument(
        company=GoldCompany(name="Qorvo, Inc.", cik="0001604778", ticker="QRVO"),
        filing=GoldFiling(form="10-K", accession="0001628280-26-032873"),
        relationships=[
            GoldRelationship(
                id="QRVO-1",
                edge_type="customer",
                target_name="Apple Inc.",
                target_kind="company",
                direction="target_depends_on_company",
                quote="Sales to Apple Inc. accounted for 46% of total revenue.",
                importance="critical",
                source="gold",
            ),
            GoldRelationship(
                id="QRVO-2",
                edge_type="facility",
                target_name="Richardson, Texas",
                target_kind="facility",
                direction="depends_on_target",
                quote="Our primary wafer fabrication operations are located in Richardson, Texas.",
                importance="medium",
                source="pooled",
            ),
        ],
        negatives=[
            GoldNegative(
                id="QRVO-N1",
                target_name="Skyworks Solutions",
                kind="competitor",
                quote="We compete directly with Skyworks Solutions and Qualcomm.",
            ),
            GoldNegative(
                id="QRVO-N2",
                target_name="Philadelphia Semiconductor Index",
                kind="unrelated",
                quote="The graph compares return against the Philadelphia Semiconductor Index.",
            ),
        ],
    )

    e_apple = _make_edge(
        edge_type="customer",
        target_name="Apple",
        target_kind="company",
        quote="Sales to Apple Inc. accounted for 46% of total revenue.",
        importance_tier="critical",
        vint_status="confirmed",
    )
    e_fac = _make_edge(
        edge_type="facility",
        target_name="Richardson, Texas",
        target_kind="facility",
        quote="Our primary wafer fabrication operations are located in Richardson, Texas.",
        importance_tier="medium",
        vint_status="confirmed",
    )
    # Two hard negatives that passed quote verification BEFORE V-INT, but were rejected by V-INT
    e_comp_rej = _make_edge(
        edge_type="supplier",
        target_name="Skyworks Solutions",
        target_kind="company",
        quote="We compete directly with Skyworks Solutions and Qualcomm.",
        vint_status="rejected",
        vint_flags=["competitor_mention"],
    )
    e_unrel_rej = _make_edge(
        edge_type="supplier",
        target_name="Philadelphia Semiconductor Index",
        target_kind="company",
        quote="The graph compares return against the Philadelphia Semiconductor Index.",
        vint_status="rejected",
        vint_flags=["subject_mismatch"],
    )

    bundle = evaluate_company(
        doc,
        [e_apple, e_fac],
        vint_rejected_edges=[e_comp_rej, e_unrel_rej],
    )
    s = bundle.summary
    assert s.gold_total == 2
    assert s.gold_blind_count == 1
    assert s.gold_pooled_count == 1
    # Before V-INT: 2 TP, 2 FP -> Precision = 50%, Hard-neg FP = 2/2
    assert s.tp_before_vint == 2
    assert s.fp_before_vint == 2
    assert s.precision_before_vint == 0.5
    assert s.hard_neg_fp_before_vint == 2
    # After V-INT: 2 TP, 0 FP -> Precision = 100%, Hard-neg FP = 0/2
    assert s.tp_after_vint == 2
    assert s.fp_after_vint == 0
    assert s.precision_after_vint == 1.0
    assert s.recall_after_vint == 1.0
    assert s.hard_neg_fp_after_vint == 0
    assert s.direction_correct == 2
    assert s.facility_country_correct == 1
    assert s.facility_country_total == 1

    report = aggregate_eval_report([bundle], bootstrap_iterations=200)
    assert report.hard_negative_by_kind["competitor"]["fp_before_vint"] == 1
    assert report.hard_negative_by_kind["competitor"]["fp_after_vint"] == 0
    assert report.hard_negative_by_kind["unrelated"]["fp_before_vint"] == 1
    assert report.hard_negative_by_kind["unrelated"]["fp_after_vint"] == 0


def test_weighted_kappa_and_direction_inference() -> None:
    perfect = [("critical", "critical"), ("high", "high"), ("medium", "medium"), ("low", "low")]
    assert compute_weighted_kappa(perfect, weights="quadratic") == 1.0
    assert compute_weighted_kappa(perfect, weights="linear") == 1.0

    near_pairs = [("critical", "high"), ("high", "high"), ("medium", "medium"), ("low", "low")]
    quad_k = compute_weighted_kappa(near_pairs, weights="quadratic")
    lin_k = compute_weighted_kappa(near_pairs, weights="linear")
    assert 0.6 < lin_k < quad_k < 1.0

    # Reverse-link customer edge: another filer (TSMC) says evaluated company (NKE) is its customer
    # -> NKE depends_on_target (TSMC)
    rev_edge = _make_edge(
        edge_type="customer",
        target_name="Nike",
        target_kind="company",
        source_company_key="CIK:0001046179",
        target_key="CIK:0000320187",
    )
    assert infer_edge_direction(rev_edge, evaluated_company_key="CIK:0000320187") == "depends_on_target"


def test_bootstrap_ci_is_deterministic() -> None:
    values = [0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0, 0.75, 0.88, 0.92]
    ci_1 = bootstrap_ci(values, lambda seq: sum(seq) / len(seq), iterations=500, seed=20261108)
    ci_2 = bootstrap_ci(values, lambda seq: sum(seq) / len(seq), iterations=500, seed=20261108)
    assert ci_1 == ci_2
    assert ci_1.ci_low <= ci_1.value <= ci_1.ci_high


def test_compare_annotator_docs_computes_agreement() -> None:
    gold_docs, _ = build_synthetic_held_out_fixture()
    doc_a = gold_docs[0]
    doc_b = doc_a.model_copy(deep=True)
    doc_b.relationships = doc_b.relationships[:-1]  # drop 1 of 3 relationships in B
    agreement = compare_annotator_docs(doc_a, doc_b)
    assert agreement.ticker == "NKE"
    assert agreement.a_count == 3
    assert agreement.b_count == 2
    assert agreement.matched_count == 2
    assert agreement.f1_agreement == 0.8
    assert agreement.direction_agreement == 1.0


def test_cli_offline_replay_writes_eval_md_and_results_json(tmp_path: Path) -> None:
    gold_dir = tmp_path / "gold"
    rec_dir = tmp_path / "recorded"
    out_md = tmp_path / "EVAL.md"
    out_json = tmp_path / "results.json"

    gold_dir.mkdir()
    rec_dir.mkdir()

    gold_docs, recorded = build_synthetic_held_out_fixture()
    for doc in gold_docs:
        (gold_dir / f"{doc.company.ticker}.json").write_text(
            doc.model_dump_json(indent=2), encoding="utf-8"
        )
    for rec in recorded.values():
        save_recorded_prediction(rec_dir, rec)

    rc = run_eval_cli(
        [
            "--replay",
            "--gold-dir",
            str(gold_dir),
            "--recorded-dir",
            str(rec_dir),
            "--out-md",
            str(out_md),
            "--out-json",
            str(out_json),
        ]
    )
    assert rc == 0
    assert out_md.exists()
    assert out_json.exists()

    md_text = out_md.read_text(encoding="utf-8")
    assert "## 2. Headline Metrics (After V-INT, with 95% Bootstrap CIs)" in md_text
    assert "## 3. Before vs. After V-INT" in md_text
    assert "## 4. Per-`edge_type` Breakdown" in md_text

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["mode"] == "replay"
    assert payload["companies_evaluated"] == 10
    assert payload["overall_after_vint"]["precision"]["value"] > payload["overall_before_vint"]["precision"]["value"]
    assert payload["hard_negative_fp_rate_after_vint"]["value"] == 0.0
    assert payload["hard_negative_fp_rate_before_vint"]["value"] > 0.0
    assert len(render_eval_markdown(aggregate_eval_report([]))) > 100


def test_adjudicated_gold_fields_tier_aliases_alternatives_and_country() -> None:
    from hoc.eval import DEFAULT_GOLD_DIR

    docs = load_gold_directory(DEFAULT_GOLD_DIR)
    assert len(docs) == 10
    total_core = sum(1 for d in docs for r in d.relationships if r.tier == "core")
    total_ext = sum(1 for d in docs for r in d.relationships if r.tier == "extended" and r.source != "pooled")
    total_pooled = sum(1 for d in docs for r in d.relationships if r.source == "pooled")
    total_neg = sum(len(d.negatives) for d in docs)
    assert total_core == 115
    assert total_ext == 97  # blind annotators' optional items
    assert total_pooled == 10  # lead pooled review after the first live run (docs/hoc/eval/ADJUDICATION.md)
    assert all(r.tier == "extended" for d in docs for r in d.relationships if r.source == "pooled")
    assert total_neg == 79

    # Find NKE document and verify Cambodia ('KH'), aliases, edge_type_alternatives, and core vs extended recall
    nke_doc = next(d for d in docs if d.company.ticker == "NKE")
    # Predict:
    # 1. NKE-2 (China, edge_type="contract_manufacturer", edge_type_alternatives=["facility"], aliases=["footwear factories in China"])
    #    using alternative edge_type="facility" and alias "footwear factories in China"
    pred_china = _make_edge(
        edge_type="facility",
        target_name="footwear factories in China",
        target_kind="country",
        quote="For fiscal 2026, factories in Vietnam, Indonesia and China manufactured approximately 52%, 27% and 16% of total NIKE Brand footwear, respectively.",
    )
    # 2. NKE-5 (Cambodia, country="KH")
    pred_cambodia = _make_edge(
        edge_type="contract_manufacturer",
        target_name="apparel factories in Cambodia",
        target_kind="country",
        quote="For fiscal 2026, factories in Vietnam, Cambodia and China manufactured approximately 34%, 15% and 12% of total NIKE Brand apparel, respectively.",
    )
    # 3. NKE-1 (extended tier, Laakdal Belgium distribution facility)
    pred_ext_be = _make_edge(
        edge_type="facility",
        target_name="Laakdal, Belgium",
        target_kind="facility",
        quote="The most significant distribution facilities outside the United States are located in Laakdal, Belgium; Taicang, China; Tomisato, Japan and Icheon, Korea, all of which we own.",
    )

    bundle = evaluate_company(nke_doc, [pred_china, pred_cambodia, pred_ext_be])
    s = bundle.summary
    assert s.gold_core_total == 9
    assert s.gold_extended_total == 16
    assert s.gold_core_by_source == {"both": 5, "a": 3, "b": 1}
    # All 3 predictions matched (2 core + 1 extended) -> Precision = 3/3 = 100%, FP = 0
    assert s.tp_after_vint == 3
    assert s.tp_core_after_vint == 2
    assert s.tp_extended_after_vint == 1
    assert s.fp_after_vint == 0
    assert s.precision_after_vint == 1.0
    # Missing extended items (15 of 16) do NOT count as FN; only the 7 missing core items count as FN
    assert s.fn_after_vint == 7
    assert round(s.recall_after_vint, 4) == round(2 / 9, 4)

