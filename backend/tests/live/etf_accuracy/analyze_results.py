"""Validate the benchmark's outputs and prepare compact, inspectable evidence.

No production math helpers are used to validate holdings arithmetic or correlations.
The optional extraction-cache inventory measures availability, not prediction quality.
"""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import subprocess
from datetime import date, datetime, UTC
from pathlib import Path

import numpy as np

from run_benchmark import CASES, HERE, OUT, RAW, ROOT, TICKERS, equity_weights, overlap, save


def load(name):
    return json.loads((OUT / f"{name}.json").read_text(encoding="utf-8"))


def csv_export(path, rows):
    fields = [k for k,v in rows[0].items() if not isinstance(v,(dict,list))]
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)


def main():
    portfolios,pairs=load("portfolio_results"),load("pair_results")
    funds,issuers,analyses=load("funds"),load("issuer_holdings"),load("app_analyses")
    inputs=load("frozen_manifest")
    checks=[]
    for row in portfolios:
        if row["status"]!=200:raise AssertionError(row)
        hhi_error=abs(row["hhi_system"]-row["hhi_manual_same_entities"])
        top10_error=abs(row["top10_system_pct"]-row["top10_manual_same_entities_pct"])
        assert row["max_listing_error_pp"]<1e-8, row
        assert row["max_company_arithmetic_error_pp"]<1e-8, row
        assert top10_error<1e-8 and hhi_error<1e-10, row
        checks.append({"case":row["case"],"listing_pass":True,"company_arithmetic_pass":True,"top10_error_pp":top10_error,"hhi_error":hhi_error})
    for row in pairs:
        assert abs(row["app_vs_manual_listing_error_pp"])<1e-8,row
        if row["tickerinside_overlap_pct"] is not None:assert abs(row["manual_vs_ti_rounding_delta_pp"])<=0.050001,row
        if row["ti_return_rounding_delta"] is not None:assert abs(row["ti_return_rounding_delta"])<=0.005001,row
        a,b=funds[row["a"]]["weekly"],funds[row["b"]]["weekly"]
        assert len(a)==len(b)==156
        independently= float(np.corrcoef(a,b)[0,1])
        assert abs(independently-row["manual_ti_return_corr"])<1e-12,row

    issuer_controls=[]
    for ticker in TICKERS:
        issuer=issuers[ticker]
        if not issuer.get("weights"):continue
        ti={k:float(v)*100 for k,v in equity_weights(funds[ticker]).items()}
        direct={k:100*float(v) for k,v in issuer["weights"].items()}
        same_date=issuer.get("date")==funds[ticker]["holdings_as_of"]
        keys=ti.keys()|direct.keys()
        diffs={k:direct.get(k,0)-ti.get(k,0) for k in keys}
        only_ti=[k for k in ti if k not in direct]
        only_issuer=[k for k in direct if k not in ti]
        max_error=max((abs(v) for v in diffs.values()),default=0)
        issuer_controls.append({"ticker":ticker,"ti_date":funds[ticker]["holdings_as_of"],"issuer_date":issuer.get("date"),"same_date":same_date,"ti_rows":len(ti),"issuer_rows":len(direct),"max_abs_weight_difference_pp":max_error,"sum_abs_difference_pp":math.fsum(abs(v) for v in diffs.values()),"missing_from_issuer":only_ti,"missing_from_ti":only_issuer,"url":issuer["url"]})
        # SSGA publishes six decimal places in percent; TickerInside retains four.
        if (ticker.startswith("XL") or ticker in {"IVV","EEM"}) and same_date:
            assert all(abs(ti.get(s,0))<=0.000051 for s in only_ti),(ticker,only_ti)
            assert all(abs(direct.get(s,0))<=0.000051 for s in only_issuer),(ticker,only_issuer)
            assert max_error<=0.000051,(ticker,max_error)

    by_pair={r["pair"]:r for r in pairs}
    cases=[]
    for case in CASES:
        ps=[by_pair["/".join(sorted(p))] for p in itertools.combinations(case["weights"],2)]
        p=next(r for r in portfolios if r["case"]==case["id"])
        cases.append({**case,"pair_count":len(ps),"overlap_min":min(x["app_company_overlap_pct"] for x in ps),"overlap_max":max(x["app_company_overlap_pct"] for x in ps),"rho_min":min(x["independent_yahoo_return_corr"] for x in ps),"rho_max":max(x["independent_yahoo_return_corr"] for x in ps),"top10_pct":p["top10_system_pct"],"hhi":p["hhi_system"],"effective_n":1/p["hhi_system"],"coverage_pct":p["coverage_pct"],"pairs":[x["pair"] for x in ps]})

    # Read a snapshot of the existing cache without running new extraction or writing it.
    from hoc.ai.verifier import PROMPT_VERSION
    from hoc.contract import AnalysisResponse
    from hoc.portfolio.compare import read_cached_extractions
    git_common=Path(subprocess.check_output(["git","rev-parse","--git-common-dir"],cwd=ROOT,text=True).strip())
    if not git_common.is_absolute():git_common=ROOT/git_common
    shared_cache=git_common.resolve().parent/"backend"/".cache"
    all_top={c["company_key"] for d in analyses.values() for c in d["exposures"][:15]}
    cache_snapshot=OUT/"dependency_cache_snapshot.json"
    if cache_snapshot.exists():
        cached=json.loads(cache_snapshot.read_text(encoding="utf-8"))["companies"]
    else:
        cached=read_cached_extractions(shared_cache,all_top,models=("gemini-3.8-flash","gemini-4-argon"),prompt_version=PROMPT_VERSION)
        save(cache_snapshot,{"sampled_at":datetime.now(UTC).isoformat(),"source_cache":str(shared_cache),"companies":{k:[e.model_dump(mode="json") for e in v] for k,v in cached.items()}})
    cache_inventory=[]
    for case in CASES:
        top=analyses[case["id"]]["exposures"][:15]
        known=[c for c in top if c["company_key"] in cached]
        with_edges=[c for c in known if cached[c["company_key"]]]
        cache_inventory.append({"case":case["id"],"top_companies":len(top),"top_company_weight_pct":100*math.fsum(c["exposure"] for c in top),"cached_companies":len(known),"cached_with_edges":len(with_edges),"portfolio_weight_with_cached_edges_pct":100*math.fsum(c["exposure"] for c in with_edges),"missing_names":[c["company_name"] for c in top if c["company_key"] not in cached]})

    age=[]
    today=date.fromisoformat(inputs["created_at"][:10])
    for ticker in TICKERS:
        f=funds[ticker]
        age.append({"ticker":ticker,"holdings_date":f["holdings_as_of"],"price_date":f.get("weeks_end"),"holdings_age_days":(today-date.fromisoformat(f["holdings_as_of"])).days,"source_layer":f.get("source_layer"),"issuer_date":issuers[ticker].get("date"),"technology_pct":(f.get("breakdown") or {}).get("sectors_pct",{}).get("information_technology",0)})

    # A hand-style worked example from one frozen portfolio.
    fa,fb=funds["XLF"],funds["VFH"]
    financial=analyses["nontech-01"]
    worked=[]
    for symbol in ["JPM","BRK.B","V","MA","BAC"]:
        x,y=float(fa["holdings"].get(symbol,0)),float(fb["holdings"].get(symbol,0))
        company=next(c for c in financial["exposures"] if symbol in c["symbols"])
        worked.append({"symbol":symbol,"xlf_weight_pct":x,"vfh_weight_pct":y,"manual_portfolio_pct":0.5*x+0.5*y,"app_company_pct":100*company["exposure"],"overlap_contribution_pct":min(x,y)})

    bridged=[]
    for c in analyses["default-global"]["exposures"]:
        terms={i["etf_ticker"]:i["weight_in_etf"]*100 for i in c["contributions"]}
        if terms.get("QQQ",0)>0 and terms.get("VXUS",0)>0 and len(c["symbols"])>1:
            bridged.append({"company":c["company_name"],"symbols":c["symbols"],"qqq_weight_pct":terms["QQQ"],"vxus_weight_pct":terms["VXUS"],"added_overlap_pp":min(terms["QQQ"],terms["VXUS"])})

    matched=[i for i in issuer_controls if i["same_date"] and (i["ticker"].startswith("XL") or i["ticker"] in {"IVV","EEM"})]
    summary={"generated_at":datetime.now(UTC).isoformat(),"baseline_commit":inputs["git_commit"],"portfolio_count":len(portfolios),"nontech_cases":10,"fund_count":len(TICKERS),"pair_count":len(pairs),"portfolio_checks":checks,"cases":cases,"issuer_controls":issuer_controls,"matched_issuer_funds":len(matched),"matched_issuer_rows":sum(x["ti_rows"] for x in matched),"max_matched_issuer_weight_error_pp":max(x["max_abs_weight_difference_pp"] for x in matched),"max_listing_error_pp":max(x["max_listing_error_pp"] for x in portfolios),"max_hhi_error":max(x["hhi_error"] for x in checks),"max_ti_rounding_overlap_pp":max(abs(x["manual_vs_ti_rounding_delta_pp"]) for x in pairs),"max_return_corr_delta":max(abs(x["independent_return_delta"]) for x in pairs),"max_ti_corr_rounding_delta":max(abs(x["ti_return_rounding_delta"]) for x in pairs),"weeks":156,"return_start":pairs[0]["returns_start"],"return_end":pairs[0]["returns_end"],"cache_inventory":cache_inventory,"fund_dates":age,"worked_financials":worked,"cross_listing_bridge":bridged,"scope_notes":["No production code or model was tuned on these portfolios.","Manual company arithmetic is conditional on the app's symbol-to-company memberships; it is not an independent audit of every identity.","Raw index-futures rows are explicitly excluded from the equity oracle, consistent with the app contract; source weights are not renormalised.","HHI is normalised to covered company holdings; company exposures and overlap are not renormalised.","Direct issuer comparisons use CUSIP/security identifiers for cross-fund matching; native tickers alone are not globally unique.","SSGA cash and unkeyed money-market rows are excluded, rather than falsely joining '-' to '-'.","Vanguard issuer files have a different holdings vintage from TickerInside. Their differences are descriptive, not app arithmetic failures.","No fresh LLM inference or new gold annotation was run on the 10 portfolios. Recorded extraction evaluation and cache availability are separate evidence."]}
    # Keep the public summary compact; raw issuer lists remain local source evidence.
    summary["issuer_controls"]=[{**{k:v for k,v in row.items() if not isinstance(v,list)},
        "missing_from_issuer_count":len(row["missing_from_issuer"]),
        "missing_from_ti_count":len(row["missing_from_ti"])} for row in issuer_controls]
    save(OUT/"summary.json",summary)
    for name,rows in [("pairs",pairs),("portfolios",portfolios),("fund-dates",age),("issuer-controls",issuer_controls),("cache-coverage",cache_inventory)]:csv_export(OUT/f"{name}.csv",rows)
    manifest=[json.loads(p.read_text()) for p in sorted(RAW.glob("*.json"))]
    save(OUT/"sources.json",manifest)
    csv_export(OUT/"sources.csv",manifest)
    print(json.dumps({k:summary[k] for k in ["portfolio_count","fund_count","pair_count","matched_issuer_funds","matched_issuer_rows","max_listing_error_pp","max_hhi_error","max_return_corr_delta"]},indent=2))
    print("CACHE",[(x['case'],x['cached_companies'],x['portfolio_weight_with_cached_edges_pct']) for x in cache_inventory])


if __name__=="__main__":main()
