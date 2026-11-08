"""Scan every sector and known-country shock for the sample portfolios against their top change ideas.

Standard library only (HTTP API only, no `hoc` imports):

    python docs/hoc/demo/scan_shocks.py
    python docs/hoc/demo/scan_shocks.py --base http://127.0.0.1:8000 --out docs/hoc/demo/failure-simulator.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

NOTIONAL_DOLLARS = 10_000.0

SECTOR_LABELS: dict[str, str] = {
    "information_technology": "Information Technology",
    "financials": "Financials",
    "health_care": "Health Care",
    "consumer_discretionary": "Consumer Discretionary",
    "communication_services": "Communication Services",
    "industrials": "Industrials",
    "consumer_staples": "Consumer Staples",
    "energy": "Energy",
    "utilities": "Utilities",
    "real_estate": "Real Estate",
    "materials": "Materials",
}


def http_json(
    base: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: float = 90.0,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fmt_dollars(val: float) -> str:
    return f"${round(val):,}"


def fmt_dollars_exact(val: float) -> str:
    return f"${val:,.2f}"


def fmt_pct(val: float) -> str:
    return f"{val * 100:.1f}%"


def fetch_ideas_with_retry(base: str, holdings: list[dict[str, Any]], timeout: float) -> list[dict[str, Any]]:
    resp = http_json(base, "POST", "/api/change-ideas", {"holdings": holdings}, timeout=timeout)
    for _ in range(8):
        if resp.get("ideas") and resp.get("ai_status") != "pending":
            break
        if resp.get("ideas") and resp.get("status") == "ok":
            break
        time.sleep(1.5)
        resp = http_json(base, "POST", "/api/change-ideas", {"holdings": holdings}, timeout=timeout)
    return resp.get("ideas", [])


def scan_all(base: str, timeout: float = 90.0) -> dict[str, Any]:
    examples_resp = http_json(base, "GET", "/api/examples", timeout=timeout)
    examples = examples_resp.get("examples", [])

    val_resp = http_json(
        base,
        "POST",
        "/api/valuation",
        {
            "rows": [
                {"ticker": "IVV", "shares": 5},
                {"ticker": "QQQ", "shares": 4},
                {"ticker": "XLK", "shares": 9},
                {"ticker": "EEM", "shares": 34},
            ]
        },
        timeout=timeout,
    )
    shares_total = float(val_resp["total_value"])
    shares_holdings = [
        {"ticker": r["ticker"], "allocation": r["allocation"]}
        for r in val_resp["rows"]
    ]

    portfolios: list[dict[str, Any]] = [
        {
            "id": "us-core-tilt-shares",
            "name": "US core with a tech tilt (default shares: 5 IVV, 4 QQQ, 9 XLK, 34 EEM)",
            "holdings": shares_holdings,
            "notional": shares_total,
            "mode_label": f"${shares_total:,.2f} valuation (shares mode)",
        },
    ]
    for ex in examples:
        holdings = [{"ticker": h["ticker"], "allocation": h["allocation"]} for h in ex["holdings"]]
        portfolios.append({
            "id": ex["id"],
            "name": f"{ex['name']} (% mode)",
            "holdings": holdings,
            "notional": NOTIONAL_DOLLARS,
            "mode_label": "$10,000 notional (% mode)",
        })

    portfolio_runs: list[dict[str, Any]] = []
    top1_rows: list[dict[str, Any]] = []
    all_idea_rows: list[dict[str, Any]] = []

    for pf in portfolios:
        holdings = pf["holdings"]
        notional = pf["notional"]
        try:
            analysis = http_json(base, "POST", "/api/analysis", {"holdings": holdings}, timeout=timeout)
            ideas = fetch_ideas_with_retry(base, holdings, timeout=timeout)
        except Exception as exc:
            print(f"Skipping {pf['id']}: {exc}", file=sys.stderr)
            continue
        if not ideas:
            continue

        sectors = [
            (s["sector"], SECTOR_LABELS.get(s["sector"], s["sector"]), float(s["weight"]))
            for s in analysis.get("sectors", [])
            if s.get("sector") != "unknown" and float(s.get("weight", 0.0)) >= 0.0005
        ]
        sectors.sort(key=lambda x: -x[2])

        by_country: dict[str, float] = {}
        for comp in analysis.get("exposures", []):
            code = (comp.get("country") or "").strip().upper()
            w = float(comp.get("exposure", 0.0))
            if code and w > 0:
                by_country[code] = by_country.get(code, 0.0) + w
        countries = [
            (code, code, w)
            for code, w in sorted(by_country.items(), key=lambda kv: (-kv[1], kv[0]))
            if w >= 0.0005
        ][:15]

        shocks: list[tuple[str, str, str, float]] = [
            *[("sector", key, label, w) for key, label, w in sectors],
            *[("country", code, label, w) for code, label, w in countries],
            ("supplier", "ALIAS:TSMC", "TSMC", 0.163),
        ]

        pf_rows: list[dict[str, Any]] = []
        for idea_idx, idea in enumerate(ideas):
            cand_holdings = [{"ticker": h["ticker"], "allocation": h["allocation"]} for h in idea["holdings"]]
            action_desc = (
                f"Swap {int(round(idea['add_fraction']*100))}% {idea['swap_from']} -> {idea['ticker']}"
                if idea.get("action") == "swap" and idea.get("swap_from")
                else f"Add {int(round(idea['add_fraction']*100))}% {idea['ticker']} ({idea['title']})"
            )
            # Run full shock list against the #1 idea; run major shocks (>= 2%) against secondary ideas
            idea_shocks = shocks if idea_idx == 0 else [s for s in shocks if s[3] >= 0.02]
            for kind, key, label, base_w in idea_shocks:
                payload: dict[str, Any] = {
                    "baseline": holdings,
                    "candidate": cand_holdings,
                    "shock": {"kind": kind, "key": key, "label": label},
                }
                if kind == "supplier":
                    payload["company_keys"] = [
                        "CIK:0000320193",
                        "CIK:0001045810",
                        "CIK:0000002488",
                        "ISIN:TW0002330008",
                    ]
                stress = http_json(
                    base,
                    "POST",
                    "/api/stress",
                    payload,
                    timeout=timeout,
                )
                b_side = stress["baseline"]
                c_side = stress["candidate"]
                basis = stress["basis"]
                b_loss = notional * float(b_side["loss_fraction"])
                c_loss = notional * float(c_side["loss_fraction"])
                b_after = notional - b_loss
                c_after = notional - c_loss
                saved_exact = b_loss - c_loss
                saved_whole = round(b_loss) - round(c_loss)

                row = {
                    "portfolio_id": pf["id"],
                    "portfolio_name": pf["name"],
                    "notional": notional,
                    "idea_rank": idea_idx + 1,
                    "idea_ticker": idea["ticker"],
                    "idea_title": idea["title"],
                    "idea_desc": action_desc,
                    "kind": kind,
                    "key": key,
                    "label": label,
                    "source": basis["source"],
                    "proxy": basis.get("proxy"),
                    "drop": float(basis["drop"]),
                    "window_start": basis.get("window_start"),
                    "window_end": basis.get("window_end"),
                    "base_affected": float(b_side["affected_weight"]),
                    "base_loss_frac": float(b_side["loss_fraction"]),
                    "base_before": notional,
                    "base_after": b_after,
                    "base_loss_dollars": b_loss,
                    "cand_affected": float(c_side["affected_weight"]),
                    "cand_loss_frac": float(c_side["loss_fraction"]),
                    "cand_after": c_after,
                    "cand_loss_dollars": c_loss,
                    "saved_dollars": saved_exact,
                    "saved_whole": saved_whole,
                }
                pf_rows.append(row)
                if pf["id"] in {"us-core-tilt", "global-core"}:
                    all_idea_rows.append(row)
                    if idea_idx == 0:
                        top1_rows.append(row)

        portfolio_runs.append({
            "portfolio": pf,
            "ideas": ideas,
            "rows": pf_rows,
        })

    top1_rows.sort(key=lambda r: (-r["saved_dollars"], r["portfolio_id"], r["kind"], r["key"]))
    all_idea_rows.sort(key=lambda r: (-r["saved_dollars"], r["portfolio_id"], r["kind"], r["key"]))
    return {
        "portfolio_runs": portfolio_runs,
        "top5_top1_idea": top1_rows[:5],
        "top5_all_ideas": all_idea_rows[:5],
    }


def render_markdown(results: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Failure Simulator — Demo Scenario Table (FIX-63)")
    lines.append("")
    lines.append(
        "Generated via `python docs/hoc/demo/scan_shocks.py` using only the HTTP API "
        "(`GET /api/examples`, `POST /api/analysis`, `POST /api/change-ideas`, `POST /api/valuation`, "
        "and `POST /api/stress`). Historical shocks use the proxy ETF's worst 21-trading-day fall over "
        "the last 5 years of daily adjusted closes; unmapped groups and suppliers use the simulated **20%** fall "
        "(`DEFAULT_SHOCK_DROP = 0.20`)."
    )
    lines.append("")
    lines.append("## 1. Top 5 Scenarios Where the New Mix Loses the Most Less (Against Each Sample's #1 Change Idea)")
    lines.append("")
    lines.append("| Rank | Sample Portfolio | #1 Change Idea | Shock (`kind:key`) | Basis (Proxy / Drop) | Your Portfolio (`Before -> After`) | Your New Mix (`Before -> After`) | Loss Reduction |")
    lines.append("|---:|---|---|---|---|---|---|---|")
    for idx, r in enumerate(results["top5_top1_idea"], 1):
        basis_str = (
            f"Historical `{r['proxy']}` −{fmt_pct(r['drop'])} ({r['window_start']} to {r['window_end']})"
            if r["source"] == "historical"
            else f"Simulated −{fmt_pct(r['drop'])}"
        )
        base_str = f"{fmt_dollars(r['base_before'])} → {fmt_dollars(r['base_after'])} (−{fmt_dollars(r['base_loss_dollars'])} / `{fmt_dollars_exact(r['base_loss_dollars'])}`)"
        cand_str = f"{fmt_dollars(r['base_before'])} → {fmt_dollars(r['cand_after'])} (−{fmt_dollars(r['cand_loss_dollars'])} / `{fmt_dollars_exact(r['cand_loss_dollars'])}`)"
        saved_str = f"**loses {fmt_dollars(r['saved_whole'])} less** (`${r['saved_dollars']:,.2f}`)"
        lines.append(
            f"| {idx} | {r['portfolio_name']} | {r['idea_desc']} | `{r['kind']}:{r['key']}` ({r['label']}) | {basis_str} | {base_str} | {cand_str} | {saved_str} |"
        )

    lines.append("")
    lines.append("## 2. Top 5 Scenarios Across All Returned Change Ideas (Both Sample Portfolios)")
    lines.append("")
    lines.append("| Rank | Sample Portfolio | Change Idea | Shock (`kind:key`) | Basis (Proxy / Drop) | Your Portfolio (`Before -> After`) | Your New Mix (`Before -> After`) | Loss Reduction |")
    lines.append("|---:|---|---|---|---|---|---|---|")
    for idx, r in enumerate(results["top5_all_ideas"], 1):
        basis_str = (
            f"Historical `{r['proxy']}` −{fmt_pct(r['drop'])} ({r['window_start']} to {r['window_end']})"
            if r["source"] == "historical"
            else f"Simulated −{fmt_pct(r['drop'])}"
        )
        base_str = f"{fmt_dollars(r['base_before'])} → {fmt_dollars(r['base_after'])} (−{fmt_dollars(r['base_loss_dollars'])} / `{fmt_dollars_exact(r['base_loss_dollars'])}`)"
        cand_str = f"{fmt_dollars(r['base_before'])} → {fmt_dollars(r['cand_after'])} (−{fmt_dollars(r['cand_loss_dollars'])} / `{fmt_dollars_exact(r['cand_loss_dollars'])}`)"
        saved_str = f"**loses {fmt_dollars(r['saved_whole'])} less** (`${r['saved_dollars']:,.2f}`)"
        lines.append(
            f"| {idx} | {r['portfolio_name']} | {r['idea_desc']} | `{r['kind']}:{r['key']}` ({r['label']}) | {basis_str} | {base_str} | {cand_str} | {saved_str} |"
        )

    for run in results["portfolio_runs"]:
        pf = run["portfolio"]
        top1_rows = [r for r in run["rows"] if r["idea_rank"] == 1]
        top1_rows.sort(key=lambda r: (-r["saved_dollars"], r["kind"], r["key"]))
        if not top1_rows:
            continue
        lines.append("")
        lines.append(f"## 3. Full Sector & Country Scan — {pf['name']} ({pf['mode_label']})")
        lines.append("")
        lines.append(f"- **Top Change Idea**: {top1_rows[0]['idea_desc']}")
        lines.append("")
        lines.append("| Shock (`kind:key`) | Basis | Drop | Exposed (`Before -> After`) | Your Portfolio (`Before -> After`) | Your New Mix (`Before -> After`) | Delta |")
        lines.append("|---|---|---:|---|---|---|---|")
        for r in top1_rows:
            basis_tag = f"Historical (`{r['proxy']}`)" if r["source"] == "historical" else "Simulated"
            exp_str = f"{fmt_pct(r['base_affected'])} → {fmt_pct(r['cand_affected'])}"
            base_m = f"{fmt_dollars(r['base_before'])} → {fmt_dollars(r['base_after'])} (−{fmt_dollars(r['base_loss_dollars'])})"
            cand_m = f"{fmt_dollars(r['base_before'])} → {fmt_dollars(r['cand_after'])} (−{fmt_dollars(r['cand_loss_dollars'])})"
            if r["saved_whole"] > 0:
                delta_str = f"loses {fmt_dollars(r['saved_whole'])} less (`+${r['saved_dollars']:,.2f}`)"
            elif r["saved_whole"] < 0:
                delta_str = f"loses {fmt_dollars(abs(r['saved_whole']))} more (`-${abs(r['saved_dollars']):,.2f}`)"
            else:
                delta_str = f"same (`${r['saved_dollars']:+,.2f}`)"
            lines.append(
                f"| `{r['kind']}:{r['key']}` ({r['label']}) | {basis_tag} | −{fmt_pct(r['drop'])} | {exp_str} | {base_m} | {cand_m} | {delta_str} |"
            )

    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="Base URL of running House of Cards API")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--out", default="docs/hoc/demo/failure-simulator.md", help="Output markdown path")
    args = parser.parse_args(argv)

    results = scan_all(args.base, timeout=args.timeout)
    md = render_markdown(results)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"Wrote {out_path} ({len(md)} bytes)")
    for idx, r in enumerate(results["top5_top1_idea"], 1):
        print(
            f"  {idx}. [{r['portfolio_name']}] {r['idea_desc']} | {r['kind']}:{r['key']} "
            f"({r['source']} -{r['drop']*100:.1f}%): "
            f"{fmt_dollars(r['base_before'])} -> {fmt_dollars(r['base_after'])} (-{fmt_dollars(r['base_loss_dollars'])}) vs "
            f"{fmt_dollars(r['base_before'])} -> {fmt_dollars(r['cand_after'])} (-{fmt_dollars(r['cand_loss_dollars'])}) "
            f"[loses {fmt_dollars(r['saved_whole'])} less / ${r['saved_dollars']:,.2f}]"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
