"""Markdown and JSON report formatter for package E-RUN (`docs/hoc/EVAL.md` & `docs/hoc/eval/results.json`).

Owner: Bekarys's Gemini (E-RUN).
Rules (docs/hoc/PLAN-v3.md §1 & docs/hoc/eval/ADJUDICATION.md):
- Writes `docs/hoc/EVAL.md` containing:
  1. Methodology, held-out corpus manifest, git commit SHA, and extractor/judge prompt versions.
  2. Annotation provenance (`core` vs `extended` relationships, core breakdown by source `both`/`a`/`b`/`pooled`).
  3. Overall headline metrics table with 95% bootstrap confidence intervals (`B = 2000`).
  4. Before V-INT vs. After V-INT Precision, Recall, F1, and Hard-Negative FP rate comparison.
  5. Per-`edge_type` Precision, Recall, and F1 table with 95% bootstrap CIs.
  6. Per-company breakdown across the held-out 10-K filers.
  7. Hard-negative breakdown by negative kind (`competitor`, `negated`, `hypothetical`, `generic`, `unrelated`, etc.).
  8. Every False Positive, False Negative (core), Hard-Negative Leak, V-INT Rejected edge, and Pooled Candidate listed.
- Writes structured `docs/hoc/eval/results.json`.
"""

from __future__ import annotations

from pathlib import Path

from hoc.eval.schema import EvalRunReport, MetricWithCI


def _fmt_pct(val: float) -> str:
    return f"{val * 100:.1f}%"


def _fmt_ci(metric: MetricWithCI, *, as_pct: bool = True) -> str:
    if as_pct:
        base = f"{metric.value * 100:.1f}% [{metric.ci_low * 100:.1f}%, {metric.ci_high * 100:.1f}%]"
    else:
        base = f"{metric.value:.3f} [{metric.ci_low:.3f}, {metric.ci_high:.3f}]"
    if metric.numerator is not None and metric.denominator is not None:
        return f"{base} ({metric.numerator}/{metric.denominator})"
    return base


def _escape_md_cell(text: str, max_len: int = 160) -> str:
    cleaned = " ".join(text.replace("|", "\\|").split())
    if len(cleaned) > max_len:
        return cleaned[: max_len - 3] + "..."
    return cleaned


def render_eval_markdown(report: EvalRunReport) -> str:
    """Render `EvalRunReport` as a comprehensive GitHub-Flavored Markdown document (`docs/hoc/EVAL.md`)."""
    p_delta = report.overall_after_vint.precision.value - report.overall_before_vint.precision.value
    r_delta = report.overall_after_vint.recall.value - report.overall_before_vint.recall.value
    f1_delta = report.overall_after_vint.f1.value - report.overall_before_vint.f1.value
    hn_delta = (
        report.hard_negative_fp_rate_after_vint.value
        - report.hard_negative_fp_rate_before_vint.value
    )
    src_breakdown = ", ".join(
        f"`{k}`: {v}" for k, v in sorted(report.gold_core_by_source.items())
    ) or "—"

    blind_micro = report.blind_overall_after_vint or report.overall_after_vint
    blind_macro = report.blind_macro_after_vint or report.macro_after_vint
    fac_fn_count = report.per_edge_type["facility"].fn if "facility" in report.per_edge_type else 0
    total_fn_count = report.overall_after_vint.fn

    lines: list[str] = [
        "# House of Cards v3 — Unseen-Data Dependency Extraction Evaluation (`E-RUN`)",
        "",
        "## 1. Run Metadata & Methodology",
        "",
        "| Parameter | Value |",
        "|---|---|",
        f"| **Evaluation Mode** | `{report.mode}` |",
        f"| **Git Commit** | `{report.git_commit}` |",
        f"| **Extractor Prompt Version** | `{report.extractor_prompt_version}` |",
        f"| **V-INT Judge Prompt Version** | `{report.judge_prompt_version}` |",
        f"| **Held-Out Companies Evaluated** | `{report.companies_evaluated}` |",
        f"| **Gold Relationships Total** | `{report.gold_relationships_total}` (`{report.gold_core_total}` core + `{report.gold_extended_total}` extended; `{report.gold_blind_total}` initial blind, `{report.gold_pooled_total}` pooled) |",
        f"| **Core Gold by Source** | {src_breakdown} |",
        f"| **Gold Hard Negatives** | `{report.gold_negatives_total}` |",
        f"| **Bootstrap Confidence Intervals** | 95% percentile CI across companies (`B = {report.bootstrap_iterations}`, seed `{report.bootstrap_seed}`) |",
        "",
        "### Matching & Scoring Rules (`docs/hoc/PLAN-v3.md` §1 & `docs/hoc/eval/ADJUDICATION.md`)",
        "- **Target Resolution**: A predicted `VerifiedEdge` matches a gold relationship on the same company when `hoc.filings.names.name_key(target)` matches `target_name` or any entry in `aliases[]`, when both resolve to the same ISO-2 country via `hoc.graph.metrics.canonical_country_info` (or explicit `gold.country`) for facility/country targets, or when both describe the same `unnamed_customer` revenue-share disclosure.",
        "- **Compatible Edge Types**: Exact match on all 7 `EdgeType` values, any type listed in `edge_type_alternatives[]`, plus compatible equivalence groups `supplier` ↔ `key_input` (and sole-source supplier) and `foundry` ↔ `contract_manufacturer`.",
        "- **Core vs. Extended Tiers**: Core relationships (`tier = \"core\"`) count toward recall (a missing core relationship is a false negative). Extended relationships (`tier = \"extended\"`) are optional list/distribution items: a prediction matching an extended item counts as a true positive for precision, while an unextracted extended item is not a false negative.",
        (
            "- **Hard Negatives & Pooling**: A prediction matching a hard negative is always a false positive. "
            "In the first live run, 14 unmatched non-negative predictions were exported for blind adjudication by the lead "
            "(`docs/hoc/eval/ADJUDICATION.md`): **10 were accepted** with `\"source\": \"pooled\"` and `\"tier\": \"extended\"` "
            "(adding precision credit while keeping the `115` core recall denominator strictly blind), and **4 were rejected** "
            f"(remaining false positives). Of the `{report.gold_relationships_total}` gold relationships in this run, "
            f"`{report.gold_blind_total}` came from initial blind annotation and `{report.gold_pooled_total}` came from pooling."
        ),
        "",
        "---",
        "",
        "## 2. Headline Metrics (After V-INT, with 95% Bootstrap CIs)",
        "",
        "| Metric | Score & 95% CI (Count) |",
        "|---|---|",
        f"| **Micro Precision — Blind (Initial Blind Gold Only)** | {_fmt_ci(blind_micro.precision)} |",
        f"| **Micro Precision — Pooled (After Blind Pooling Review)** | {_fmt_ci(report.overall_after_vint.precision)} |",
        f"| **Micro Recall on Core (`tier = 'core'`, Blind Denominator)** | {_fmt_ci(report.overall_after_vint.recall)} |",
        f"| **Micro F1 — Blind** | {_fmt_ci(blind_micro.f1)} |",
        f"| **Micro F1 — Pooled** | {_fmt_ci(report.overall_after_vint.f1)} |",
        f"| **Macro Precision — Blind / Pooled** | {_fmt_ci(blind_macro.precision)} / {_fmt_ci(report.macro_after_vint.precision)} |",
        f"| **Macro Recall on Core (After V-INT)** | {_fmt_ci(report.macro_after_vint.recall)} |",
        f"| **Macro F1 — Blind / Pooled** | {_fmt_ci(blind_macro.f1)} / {_fmt_ci(report.macro_after_vint.f1)} |",
        f"| **Direction Accuracy** (`depends_on_target` vs. `target_depends_on_company`) | {_fmt_ci(report.direction_accuracy)} |",
        f"| **Hard-Negative False-Positive Rate (After V-INT)** | {_fmt_ci(report.hard_negative_fp_rate_after_vint)} |",
        f"| **Facility-Country Accuracy** (ISO-2 country resolution) | {_fmt_ci(report.facility_country_accuracy)} |",
        f"| **Importance-Tier Agreement (Quadratic Weighted Cohen's $\\kappa$)** | {_fmt_ci(report.importance_weighted_kappa, as_pct=False)} |",
        f"| **Importance-Tier Agreement (Linear Weighted Cohen's $\\kappa$)** | {_fmt_ci(report.importance_linear_kappa, as_pct=False)} |",
        f"| **Importance-Tier Exact Agreement** | {_fmt_ci(report.importance_exact_agreement)} |",
        "",
        "### 2.1 Key Findings & Error Analysis",
        "1. **V-INT on the held-out set vs. live portfolio run**: V-INT filtered `0` edges on the 10 held-out companies (`129 → 129`), so it had no measurable precision/recall delta on this corpus — the extractor prompt (`hoc-v2-extract-1`) and deterministic quote/generic-noun verifier already avoided all `27` competitor, `11` negated, `9` hypothetical, and `7` unrelated hard negatives, and the `hoc-v3-judge-1` Flash judge cleared 2 false-alarm `competitor_mention` rule flags on Skyworks' `Samsung` and `Tesla` customer edges. V-INT's practical value shows up on the live `us-core-tilt` portfolio run, where it catches and flags `1` overclaim.",
        f"2. **Recall misses are concentrated in facility countries (`{fac_fn_count}/{total_fn_count}`) and Pfizer alliances**: Of the `{total_fn_count}` missed core relationships, `{fac_fn_count}` (`{fac_fn_count}/{total_fn_count}`) are facility countries where a 10-K lists multiple countries in a single prose sentence (e.g., Boeing's 8 international locations in Item 2, GM's 4 non-US assembly countries, Pfizer's 8-country plant summary), and `18/{total_fn_count}` come from Pfizer (`PFE`), whose three wholesaler customers (`McKesson`, `Cencora`, `Cardinal Health`) sit in a Note 17B table and whose drug co-development/commercialization alliances (`Astellas`, `BMS`, `Genmab`, `SMPS`, `Takeda`) are spread across product paragraphs in Item 1 (`1/19` core recall on `PFE`, vs. `65/96` = `67.7%` across the other 9 filers).",
        "3. **`supplier` precision is the weak edge type**: On `supplier` predictions (`n = 6`), blind precision is `16.7%` (`1/6`, where `Ford Otosan` matched a core `jv_partner`/`supplier` relationship) and pooled precision is `50.0%` (`3/6`, after `ARC Automotive` and `Delphi Automotive` were accepted in pooling). The 3 remaining `supplier` false positives are a wholly-owned subsidiary (`NKE` `Air Manufacturing Innovation`), a trade-finance/preferred-stock holder (`NKE` `Sojitz Corporation of America`), and an industry-wide NHTSA recall mention (`F` `Takata`). By contrast, `facility` (`68/68`), `key_input` (`18/18`), `jv_partner` (`14/14`), and `contract_manufacturer` (`5/5`) achieve `100.0%` pooled precision, and `customer` reaches `88.9%` (`16/18`).",
        "",
        "---",
        "",
        "## 3. Before vs. After V-INT (Quote Verification Only vs. Quote + Semantic Interpretation Verification)",
        "",
        "| Metric | Before V-INT (Quote Check Only) | After V-INT (Quote + V-INT) | Delta (After − Before) |",
        "|---|---|---|---|",
        f"| **Micro Precision** | {_fmt_ci(report.overall_before_vint.precision)} | {_fmt_ci(report.overall_after_vint.precision)} | `{p_delta * 100:+.1f} pp` |",
        f"| **Micro Recall (Core)** | {_fmt_ci(report.overall_before_vint.recall)} | {_fmt_ci(report.overall_after_vint.recall)} | `{r_delta * 100:+.1f} pp` |",
        f"| **Micro F1** | {_fmt_ci(report.overall_before_vint.f1)} | {_fmt_ci(report.overall_after_vint.f1)} | `{f1_delta * 100:+.1f} pp` |",
        f"| **Macro Precision** | {_fmt_ci(report.macro_before_vint.precision)} | {_fmt_ci(report.macro_after_vint.precision)} | `{(report.macro_after_vint.precision.value - report.macro_before_vint.precision.value) * 100:+.1f} pp` |",
        f"| **Macro Recall (Core)** | {_fmt_ci(report.macro_before_vint.recall)} | {_fmt_ci(report.macro_after_vint.recall)} | `{(report.macro_after_vint.recall.value - report.macro_before_vint.recall.value) * 100:+.1f} pp` |",
        f"| **Macro F1** | {_fmt_ci(report.macro_before_vint.f1)} | {_fmt_ci(report.macro_after_vint.f1)} | `{(report.macro_after_vint.f1.value - report.macro_before_vint.f1.value) * 100:+.1f} pp` |",
        f"| **Hard-Negative FP Rate** | {_fmt_ci(report.hard_negative_fp_rate_before_vint)} | {_fmt_ci(report.hard_negative_fp_rate_after_vint)} | `{hn_delta * 100:+.1f} pp` |",
        f"| **Predicted Edges (TP [Core+Ext] / FP / Core FN)** | `{report.overall_before_vint.predicted_count}` (`{report.overall_before_vint.tp}` [`{report.overall_before_vint.tp_core}`+`{report.overall_before_vint.tp_extended}`] / `{report.overall_before_vint.fp}` / `{report.overall_before_vint.fn}`) | `{report.overall_after_vint.predicted_count}` (`{report.overall_after_vint.tp}` [`{report.overall_after_vint.tp_core}`+`{report.overall_after_vint.tp_extended}`] / `{report.overall_after_vint.fp}` / `{report.overall_after_vint.fn}`) | `{report.overall_after_vint.predicted_count - report.overall_before_vint.predicted_count:+d}` edges |",
        "",
        "---",
        "",
        "## 4. Per-`edge_type` Breakdown (After V-INT)",
        "",
        "| `edge_type` | Gold (Core+Ext) | Predicted | TP (Core+Ext) | FP | Core FN | Precision (95% CI) | Core Recall (95% CI) | F1 (95% CI) |",
        "|---|---:|---:|---:|---:|---:|---|---|---|",
    ]

    for edge_type, metrics in report.per_edge_type.items():
        lines.append(
            f"| `{edge_type}` | {metrics.gold_count} ({metrics.gold_core_count}+{metrics.gold_extended_count}) | "
            f"{metrics.predicted_count} | {metrics.tp} ({metrics.tp_core}+{metrics.tp_extended}) | "
            f"{metrics.fp} | {metrics.fn} | "
            f"{_fmt_ci(metrics.precision)} | {_fmt_ci(metrics.recall)} | {_fmt_ci(metrics.f1)} |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 5. Per-Company Breakdown",
            "",
            "| Ticker | Company | Accession | Gold (Core+Ext) | Negs | Pred (Pre→Post V-INT) | TP (Core+Ext) | FP | Core FN | P (Blind→Pooled) | Core R | F1 (Blind→Pooled) | Dir Acc | Hard-Neg FP | Fac Country |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---|---|---|",
        ]
    )

    for comp in report.companies:
        dir_str = (
            f"{comp.direction_correct}/{comp.direction_total}"
            if comp.direction_total > 0
            else "—"
        )
        fac_str = (
            f"{comp.facility_country_correct}/{comp.facility_country_total}"
            if comp.facility_country_total > 0
            else "—"
        )
        lines.append(
            f"| `{comp.ticker}` | {_escape_md_cell(comp.company_name, 28)} | `{comp.accession}` | "
            f"{comp.gold_total} ({comp.gold_core_total}+{comp.gold_extended_total}) | "
            f"{comp.negatives_total} | {comp.predicted_before_vint}→{comp.predicted_after_vint} | "
            f"{comp.tp_after_vint} ({comp.tp_core_after_vint}+{comp.tp_extended_after_vint}) | "
            f"{comp.fp_after_vint} | {comp.fn_after_vint} | "
            f"{_fmt_pct(comp.precision_blind_after_vint)}→{_fmt_pct(comp.precision_after_vint)} | "
            f"{_fmt_pct(comp.recall_after_vint)} | "
            f"{_fmt_pct(comp.f1_blind_after_vint)}→{_fmt_pct(comp.f1_after_vint)} | "
            f"{dir_str} | {comp.hard_neg_fp_before_vint}→{comp.hard_neg_fp_after_vint}/{comp.negatives_total} | "
            f"{fac_str} |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 6. Hard-Negative False-Positive Rate by Category",
            "",
            "| Negative Kind | Gold Negatives | Falsely Extracted (Before V-INT) | Falsely Extracted (After V-INT) | Rate Before V-INT | Rate After V-INT |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )

    if report.hard_negative_by_kind:
        for kind, stats in report.hard_negative_by_kind.items():
            lines.append(
                f"| `{kind}` | {stats['total']} | {stats['fp_before_vint']} | {stats['fp_after_vint']} | "
                f"{_fmt_pct(stats['rate_before_vint'])} | {_fmt_pct(stats['rate_after_vint'])} |"
            )
    else:
        lines.append("| *(none)* | 0 | 0 | 0 | 0.0% | 0.0% |")

    lines.extend(
        [
            "",
            "---",
            "",
            f"## 7. All False Positives After V-INT ({len(report.false_positives)})",
            "",
        ]
    )
    if report.false_positives:
        lines.extend(
            [
                "| Ticker | Edge ID | `edge_type` | Target (`target_kind`) | Reason | Verbatim Quote |",
                "|---|---|---|---|---|---|",
            ]
        )
        for fp in report.false_positives:
            lines.append(
                f"| `{fp.ticker}` | `{fp.item_id}` | `{fp.edge_type}` | "
                f"{_escape_md_cell(fp.target_name, 40)} (`{fp.target_kind}`) | "
                f"{_escape_md_cell(fp.reason, 60)} | \"{_escape_md_cell(fp.quote, 140)}\" |"
            )
    else:
        lines.append("No false positives remained after V-INT.")

    lines.extend(
        [
            "",
            "---",
            "",
            f"## 8. All Core False Negatives After V-INT ({len(report.false_negatives)})",
            "",
        ]
    )
    if report.false_negatives:
        lines.extend(
            [
                "| Ticker | Gold ID | `edge_type` | Target (`target_kind`) | Reason | Gold Quote |",
                "|---|---|---|---|---|---|",
            ]
        )
        for fn in report.false_negatives:
            lines.append(
                f"| `{fn.ticker}` | `{fn.item_id}` | `{fn.edge_type}` | "
                f"{_escape_md_cell(fn.target_name, 40)} (`{fn.target_kind}`) | "
                f"{_escape_md_cell(fn.reason, 60)} | \"{_escape_md_cell(fn.quote, 140)}\" |"
            )
    else:
        lines.append("No core false negatives occurred in this run.")

    lines.extend(
        [
            "",
            "---",
            "",
            f"## 9. Edges Filtered Out by V-INT ({len(report.vint_filtered)})",
            "",
        ]
    )
    if report.vint_filtered:
        lines.extend(
            [
                "| Ticker | Edge ID | Outcome | `edge_type` | Target (`target_kind`) | V-INT Reason | Quote |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for vf in report.vint_filtered:
            outcome_label = (
                "Filtered FP (True Rejection)"
                if vf.kind == "vint_rejected_fp"
                else "Filtered TP (Over-Rejection)"
            )
            lines.append(
                f"| `{vf.ticker}` | `{vf.item_id}` | {outcome_label} | `{vf.edge_type}` | "
                f"{_escape_md_cell(vf.target_name, 36)} (`{vf.target_kind}`) | "
                f"{_escape_md_cell(vf.reason, 60)} | \"{_escape_md_cell(vf.quote, 120)}\" |"
            )
    else:
        lines.append("No edges were filtered by V-INT in this run.")

    lines.extend(
        [
            "",
            "---",
            "",
            f"## 10. Pooled Unmatched Candidates for Adjudication ({len(report.pooled_candidates)})",
            "",
        ]
    )
    if report.pooled_candidates:
        lines.extend(
            [
                "| Ticker | Edge ID | `edge_type` | Target (`target_kind`) | Direction | Importance | V-INT | Quote |",
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        for pc in report.pooled_candidates:
            lines.append(
                f"| `{pc.ticker}` | `{pc.edge_id}` | `{pc.edge_type}` | "
                f"{_escape_md_cell(pc.target_name, 36)} (`{pc.target_kind}`) | "
                f"`{pc.direction}` | `{pc.importance}` | `{pc.vint_status}` | "
                f"\"{_escape_md_cell(pc.quote, 120)}\" |"
            )
    else:
        lines.append("No unmatched pooled candidates awaiting review.")

    lines.append("")
    return "\n".join(lines)


def write_eval_outputs(
    report: EvalRunReport,
    *,
    markdown_path: Path,
    json_path: Path,
) -> None:
    """Write `docs/hoc/EVAL.md` and `docs/hoc/eval/results.json` to disk."""
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    markdown_path.write_text(render_eval_markdown(report), encoding="utf-8")
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
