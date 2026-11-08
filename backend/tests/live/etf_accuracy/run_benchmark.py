"""Read-only, source-recording accuracy benchmark. No production maths in the oracle.

Run from the repository root: python backend/tests/live/etf_accuracy/run_benchmark.py
Network responses are archived once; reruns use the same bytes unless deleted explicitly.
The production API is exercised through TestClient, with only its HTTP input seam replaced.
"""
from __future__ import annotations

import csv
import hashlib
import io
import itertools
import json
import math
import re
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OUT = HERE / "artifacts"
RAW = OUT / "raw"
BASE = "https://tickerinside.com/api/v1/"
CASES = json.loads((HERE / "cases.json").read_text())["cases"]
TICKERS = sorted({t for c in CASES for t in c["weights"]})
PAIRS = sorted({tuple(sorted(p)) for c in CASES for p in itertools.combinations(c["weights"], 2)})
INDEX_CONTRACTS={"IXTZ6","IXAZ6","IXCZ6","IXPZ6","IXSZ6","IXRZ6","IXIZ6","IXDZ6","XARZ6"}
_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_semaphore = threading.Semaphore(4)
_manifest_lock = threading.Lock()


def save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch(url: str, *, headers=None) -> tuple[bytes, dict]:
    key = hashlib.sha256(url.encode()).hexdigest()
    with _locks[key]:
        body_path, meta_path = RAW / (key + ".body"), RAW / (key + ".json")
        if body_path.exists() and meta_path.exists():
            return body_path.read_bytes(), json.loads(meta_path.read_text())
        with _semaphore:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 HouseOfCards/accuracy-benchmark", **(headers or {})})
            try:
                response = urllib.request.urlopen(request, timeout=35)
                body = response.read()
                status = response.status
                content_type = response.headers.get("content-type", "")
            except urllib.error.HTTPError as exc:
                body, status, content_type = exc.read(), exc.code, "http-error"
            meta = {"url": url, "status": status, "fetched_at": datetime.now(UTC).isoformat(),
                    "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "content_type": content_type}
            RAW.mkdir(parents=True, exist_ok=True)
            body_path.write_bytes(body)
            save(meta_path, meta)
            if status >= 400:
                print("SOURCE_ERROR", status, url, flush=True)
            return body, meta


def get_json(url: str):
    body, meta = fetch(url)
    if meta["status"] != 200:
        raise RuntimeError(f"HTTP {meta['status']}: {url}")
    return json.loads(body)


def pct(values):
    return math.fsum(values)


def raw_weights(fund: dict) -> dict[str, Decimal]:
    # Listing-level oracle. Source symbols are not merged into company identities.
    # Unknown futures-like rows are separately audited rather than called companies.
    return {s.upper(): Decimal(str(w)) / 100 for s, w in fund["holdings"].items()}


def equity_weights(fund: dict) -> dict[str, Decimal]:
    # CME-style futures use a month letter followed by the contract year.
    # This manual scope rule excludes the explicitly identified index contracts;
    # it does not remove rows merely because the app omits them.
    return {s:w for s,w in raw_weights(fund).items() if s not in INDEX_CONTRACTS}


def overlap(a: dict[str, Decimal], b: dict[str, Decimal]) -> Decimal:
    return sum((min(a[k], b[k]) for k in a.keys() & b.keys()), Decimal(0))


def pearson(a, b):
    pairs = [(float(x), float(y)) for x, y in zip(a, b, strict=True) if x is not None and y is not None and math.isfinite(x) and math.isfinite(y)]
    if len(pairs) < 2:
        return None, len(pairs)
    x, y = zip(*pairs)
    mx, my = statistics.fmean(x), statistics.fmean(y)
    numerator = math.fsum((u-mx)*(v-my) for u,v in pairs)
    denominator = math.sqrt(math.fsum((u-mx)**2 for u in x) * math.fsum((v-my)**2 for v in y))
    return numerator/denominator if denominator else None, len(pairs)


def weekly_dates(end: str, n: int):
    last = date.fromisoformat(end)
    return [(last - timedelta(weeks=n-1-i)).isoformat() for i in range(n)]


def yahoo_weekly(ticker: str, end: str):
    # Independent price provider; daily adjusted closes are rolled to Friday weeks.
    end_date = date.fromisoformat(end)
    start = end_date - timedelta(weeks=160)
    p1 = int(datetime.combine(start, datetime.min.time(), UTC).timestamp())
    p2 = int(datetime.combine(end_date + timedelta(days=1), datetime.min.time(), UTC).timestamp())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={p1}&period2={p2}&interval=1d&events=div%2Csplits&includeAdjustedClose=true"
    data = get_json(url)
    chart = data["chart"]["result"][0]
    adjusted = chart["indicators"]["adjclose"][0]["adjclose"]
    closes = {}
    for ts, price in zip(chart["timestamp"], adjusted, strict=True):
        if price is None:
            continue
        day = datetime.fromtimestamp(ts, ZoneInfo("America/New_York")).date()
        friday = day + timedelta(days=(4-day.weekday()) % 7)
        if friday <= end_date:
            closes[friday.isoformat()] = float(price)
    dates = sorted(closes)
    returns = {dates[i]: closes[dates[i]]/closes[dates[i-1]]-1 for i in range(1, len(dates)) if (date.fromisoformat(dates[i])-date.fromisoformat(dates[i-1])).days == 7}
    return returns, url


def issuer_holdings(ticker: str):
    if ticker in {"IVV","EEM"}:
        product={"IVV":"239726/ishares-core-s-p-500-etf","EEM":"239637/ishares-msci-emerging-markets-etf"}[ticker]
        url=f"https://www.ishares.com/us/products/{product}/latest-holdings.csv"
        text=fetch(url)[0].decode("utf-8-sig")
        lines=text.splitlines()
        index=next(i for i,line in enumerate(lines) if line.startswith("Ticker,"))
        heading=list(csv.reader(lines[:index]))
        as_of=datetime.strptime(next(r[1] for r in heading if r and r[0]=="Fund Holdings as of"),"%b %d, %Y").date().isoformat()
        rows=list(csv.DictReader(io.StringIO("\n".join(lines[index:]))))
        def value(row):
            try:return Decimal(row.get("Market Value","").replace(",",""))
            except Exception:return Decimal(0)
        denominator=sum((value(r) for r in rows),Decimal(0))
        exchange_country={"Shanghai Stock Exchange":"CN","Shenzhen Stock Exchange":"CN","National Stock Exchange Of India":"IN","Hong Kong Exchanges And Clearing Ltd":"HK","Korea Exchange (Stock Market)":"KR","Korea Exchange (Kosdaq)":"KR","Taiwan Stock Exchange":"TW","XBSP":"BR","Saudi Stock Exchange":"SA","Johannesburg Stock Exchange":"ZA","Bolsa Mexicana De Valores":"MX","Bursa Malaysia":"MY","Stock Exchange Of Thailand":"TH","Warsaw Stock Exchange/Equities/Main Market":"PL","Istanbul Stock Exchange":"TR","Standard-Classica-Forts":"RU","Qatar Exchange":"QA","Athens Exchange S.A. Cash Market":"GR","Abu Dhabi Securities Exchange":"AE","Santiago Stock Exchange":"CL","Indonesia Stock Exchange":"ID","Philippine Stock Exchange Inc.":"PH","Dubai Financial Market":"AE","Kuwait Stock Exchange":"KW","Gretai Securities Market":"TW","Budapest Stock Exchange":"HU","Bolsa De Valores De Colombia":"CO","Prague Stock Exchange":"CZ","Egyptian Exchange":"EG","Bse Ltd":"IN","London Stock Exchange":"GB"}
        weights={}
        for row in rows:
            if row.get("Asset Class")!="Equity" or row.get("Type", "EQUITY")!="EQUITY":continue
            symbol=row["Ticker"].upper()
            if symbol in {"-",""}:continue
            country=exchange_country.get(row.get("Exchange",""))
            if country:symbol+="."+country
            symbol={"BRKB":"BRK.B","BRK B":"BRK.B","BFB":"BF.B","BF B":"BF.B"}.get(symbol,symbol)
            weights[symbol]=weights.get(symbol,Decimal(0))+value(row)/denominator
        return {"url":url,"date":as_of,"weights":weights,"weight_basis":"equity market value / sum of all published row market values","identifier_weights":{}}
    if ticker.startswith("XL"):
        import openpyxl
        url = f"https://www.ssga.com/us/en/individual/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-{ticker.lower()}.xlsx"
        body, meta = fetch(url)
        if meta["status"] != 200:
            raise RuntimeError(f"Issuer HTTP {meta['status']}")
        sheet = openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=True).active
        rows = list(sheet.values)
        header_index = next(i for i,row in enumerate(rows) if "Ticker" in row and any("Weight" in str(v) for v in row))
        headers = [str(v or "") for v in rows[header_index]]
        ticker_i = headers.index("Ticker")
        weight_i = next(i for i,v in enumerate(headers) if "Weight" in v)
        parsed = {}
        identifiers = {}
        identifier_i=headers.index("Identifier")
        for row in rows[header_index+1:]:
            symbol, weight = row[ticker_i], row[weight_i]
            if symbol and str(symbol).strip().upper() not in {"-","USD","CASH","CASH_USD"}|INDEX_CONTRACTS and isinstance(weight,(int,float)) and re.fullmatch(r"[A-Za-z0-9./ -]{1,18}",str(symbol)):
                symbol = str(symbol).strip().upper().replace("BRK/B","BRK.B").replace("BRK-B","BRK.B")
                parsed[symbol] = parsed.get(symbol,Decimal(0)) + Decimal(str(weight))/100
                identifier=str(row[identifier_i] or "").strip().upper()
                if identifier: identifiers[identifier]=identifiers.get(identifier,Decimal(0))+Decimal(str(weight))/100
        raw_date = next((v for row in rows[:header_index] for v in row if isinstance(v,datetime)),None)
        date_text = " ".join(str(v) for row in rows[:header_index] for v in row if v is not None)
        match=re.search(r"As of (\d{2}-[A-Za-z]{3}-\d{4})",date_text)
        as_of=raw_date.date().isoformat() if raw_date else datetime.strptime(match.group(1),"%d-%b-%Y").date().isoformat() if match else None
        return {"url":url,"date":as_of,"date_text":date_text,"weights":parsed,"identifier_weights":identifiers,"headers":headers}
    if ticker.startswith("V"):
        url = f"https://investor.vanguard.com/irr/funds/profile/{ticker}-AdditionalFundData"
        data = get_json(url)
        details = data["holdingDetails"]
        rows = details.get("equityHoldings",[])
        parsed = {}
        identifiers = {}
        for row in rows:
            symbol = str(row.get("ticker","")).strip().upper().replace("/",".").replace("BRK-B","BRK.B")
            text = str(row.get("marketValuePercentage","")).replace("%","").replace(",","").strip()
            if symbol and text and symbol not in INDEX_CONTRACTS:
                try:
                    parsed[symbol]=parsed.get(symbol,Decimal(0))+Decimal(text)/100
                    identifier=str(row.get("cusip") or row.get("securityId") or "").strip().upper()
                    if identifier:identifiers[identifier]=identifiers.get(identifier,Decimal(0))+Decimal(text)/100
                except Exception: pass
        ds = details.get("asOfDate","")
        as_of = datetime.strptime(ds,"%m/%d/%Y").date().isoformat() if ds else None
        return {"url":url,"date":as_of,"weights":parsed,"identifier_weights":identifiers,"holding_rows":len(rows)}
    return {"error":"Issuer source not implemented for this default ETF; independent issuer controls cover the 16 non-tech funds."}


def peer_pair(pair):
    a,b=pair
    url=BASE+"overlap?funds="+",".join(pair)
    body,meta=fetch(url)
    data=json.loads(body)
    if meta["status"]==200:return data
    # Follow the provider's published alternate endpoint; keep the original error.
    if data.get("reason")=="too_large":
        alternate=BASE+f"diversify?have={a}&try={b}"
        other=get_json(alternate)
        candidates=other.get("candidates",[])
        candidate=next((c for c in candidates if c.get("ticker")==b),candidates[0] if candidates else {})
        ov=candidate.get("overlap") or {}
        corr=candidate.get("correlation") or {}
        return {"original_error":data,"fallback_url":alternate,"fallback_response":other,
                "overlap":{"by_weight":ov.get("by_weight_pct"),"companies_in_both":ov.get("companies_in_both")},
                "correlation_3y":corr.get("weekly"),"weeks_used":corr.get("weeks")}
    return {"error":data,"url":url}


def collect():
    OUT.mkdir(parents=True,exist_ok=True)
    if not (OUT/"frozen_manifest.json").exists():
        save(OUT/"frozen_manifest.json", {"created_at":datetime.now(UTC).isoformat(),"git_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),"cases":CASES,"pairs":PAIRS,"selection":json.loads((HERE/"cases.json").read_text())["selection"]})
    funds={}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for ticker, data in zip(TICKERS,pool.map(lambda t:get_json(BASE+f"fund/{t.lower()}.json"),TICKERS),strict=True):
            funds[ticker]=data
            print("FUND",ticker,len(data.get("holdings",{})),data.get("holdings_as_of"),flush=True)
    save(OUT/"funds.json",funds)
    peers={}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for (a,b), data in zip(PAIRS,pool.map(peer_pair,PAIRS),strict=True):
            peers[f"{a}/{b}"]=data
    save(OUT/"tickerinside_pairs.json",peers)
    for path in ["securities.json","identifiers.json","methods.json"]:
        get_json(BASE+path)
    prices={}
    issuers={}
    for ticker in TICKERS:
        try:
            series,url=yahoo_weekly(ticker,funds[ticker]["weeks_end"])
            prices[ticker]={"weekly_returns":series,"url":url}
        except Exception as exc: prices[ticker]={"error":str(exc)}
        try:
            data=issuer_holdings(ticker)
            if "weights" in data: data["weights"]={k:float(v) for k,v in data["weights"].items()}
            if "identifier_weights" in data:data["identifier_weights"]={k:float(v) for k,v in data["identifier_weights"].items()}
            issuers[ticker]=data
        except Exception as exc: issuers[ticker]={"error":str(exc)}
        print("EXTERNAL",ticker,"prices",len(prices[ticker].get("weekly_returns",{})),"issuer",len(issuers[ticker].get("weights",{})),issuers[ticker].get("error",""),flush=True)
    save(OUT/"external_prices.json",prices)
    save(OUT/"issuer_holdings.json",issuers)


def measure():
    import httpx
    from fastapi.testclient import TestClient
    from hoc.api.app import create_app
    from hoc.config import Settings
    from hoc.core.http import CachedResponse
    from hoc.service import EtfService

    class RecordedInputs:
        def __init__(self, settings, cache): pass
        def get(self,url,*,source,ttl=None,headers=None,params=None):
            if not url.startswith(BASE): raise RuntimeError("Unrecorded source requested: "+url)
            if params: url += "?"+urllib.parse.urlencode(params)
            body,meta=fetch(url)
            return CachedResponse(url=url,status=meta["status"],content_type=meta["content_type"],body=body,fetched_at=datetime.fromisoformat(meta["fetched_at"]),from_cache=True)

    funds=json.loads((OUT/"funds.json").read_text())
    peers=json.loads((OUT/"tickerinside_pairs.json").read_text())
    prices=json.loads((OUT/"external_prices.json").read_text())
    issuers=json.loads((OUT/"issuer_holdings.json").read_text())
    settings=Settings(cache_dir=OUT/"app-cache",source_order=("tickerinside",),offline=False)
    with patch("hoc.core.http.CachedHttpClient",RecordedInputs):
        service=EtfService.from_settings(settings)
    app=create_app(service_factory=lambda:service,settings=settings,warm=False)
    analyses={}
    portfolio_rows=[]
    with TestClient(app) as client:
        for case in CASES:
            request={"holdings":[{"ticker":t,"allocation":w} for t,w in case["weights"].items()],"max_companies":20000}
            response=client.post("/api/analysis",json=request)
            data=response.json(); analyses[case["id"]]=data
            if response.status_code!=200:
                portfolio_rows.append({"case":case["id"],"status":response.status_code,"error":data});continue
            raw=defaultdict(Decimal)
            for ticker,allocation in case["weights"].items():
                for symbol,weight in equity_weights(funds[ticker]).items():raw[symbol]+=Decimal(str(allocation))*weight
            observed=defaultdict(float)
            conditional_expected=[]
            entity_errors=[]
            for company in data["exposures"]:
                expected=sum((raw[s] for s in company["symbols"]),Decimal(0))
                conditional_expected.append(float(expected))
                entity_errors.append(abs(float(expected)-company["exposure"]))
                for sec in company["securities"]:
                    observed[sec["symbol"]]+=sec["exposure"]
            differences={s:observed[s]-float(raw[s]) for s in raw.keys()|observed.keys()}
            denominator=sum(x for x in conditional_expected if x>0)
            excluded={t:{s:float(w)*100 for s,w in raw_weights(funds[t]).items() if s not in equity_weights(funds[t])} for t in case["weights"]}
            row={"case":case["id"],"group":case["group"],"status":200,"tickers":"/".join(case["weights"]),"companies":len(data["exposures"]),"coverage_pct":100*data["coverage"]["covered_weight"],"manual_equity_total_pct":100*float(sum(raw.values())),"max_listing_error_pp":100*max((abs(v) for v in differences.values()),default=0),"max_company_arithmetic_error_pp":100*max(entity_errors,default=0),"top10_system_pct":100*data["concentration"]["top10"],"top10_manual_same_entities_pct":100*sum(sorted(conditional_expected,reverse=True)[:10]),"hhi_system":data["concentration"]["hhi"],"hhi_manual_same_entities":sum((x/denominator)**2 for x in conditional_expected if x>0),"excluded_index_contracts":excluded,"listing_discrepancies":[{"symbol":s,"system_pct":100*observed[s],"raw_manual_pct":100*float(raw[s]),"difference_pp":100*differences[s]} for s in sorted(differences,key=lambda s:-abs(differences[s])) if abs(differences[s])>1e-8][:15]}
            portfolio_rows.append(row)
            print("SYSTEM",case["id"],row["max_listing_error_pp"],"pp",flush=True)
    save(OUT/"app_analyses.json",analyses)
    save(OUT/"portfolio_results.json",portfolio_rows)

    by_pair={}
    for analysis in analyses.values():
        for pair in analysis.get("overlap",{}).get("pairs",[]):by_pair[tuple(sorted((pair["etf_a"],pair["etf_b"])))]=pair
    pair_rows=[]
    for a,b in PAIRS:
        app_pair=by_pair.get((a,b),{})
        peer=peers[f"{a}/{b}"]
        manual=100*float(overlap(equity_weights(funds[a]),equity_weights(funds[b])))
        xa,xb=funds[a].get("weekly",[]),funds[b].get("weekly",[])
        end_a,end_b=funds[a].get("weeks_end"),funds[b].get("weeks_end")
        da=dict(zip(weekly_dates(end_a,len(xa)),xa,strict=True));db=dict(zip(weekly_dates(end_b,len(xb)),xb,strict=True))
        common=sorted(da.keys()&db.keys())[-156:]
        manual_r,n=pearson([da[d] for d in common],[db[d] for d in common])
        ya=prices[a].get("weekly_returns",{});yb=prices[b].get("weekly_returns",{})
        aligned=sorted(set(common)&ya.keys()&yb.keys())
        yahoo_r,yn=pearson([ya[d] for d in aligned],[yb[d] for d in aligned]) if aligned else (None,0)
        ai,bi=issuers[a],issuers[b]
        issuer_overlap=None
        if ai.get("identifier_weights") and bi.get("identifier_weights"):
            issuer_overlap=100*float(overlap({k:Decimal(str(v)) for k,v in ai["identifier_weights"].items()},{k:Decimal(str(v)) for k,v in bi["identifier_weights"].items()}))
        row={"pair":f"{a}/{b}","a":a,"b":b,"app_company_overlap_pct":100*app_pair.get("weighted_overlap",float("nan")),"app_listing_overlap_pct":100*app_pair.get("weighted_overlap_securities",float("nan")),"manual_listing_overlap_pct":manual,"tickerinside_overlap_pct":peer.get("overlap",{}).get("by_weight"),"tickerinside_shared_listings":peer.get("overlap",{}).get("companies_in_both"),"app_shared_companies":app_pair.get("shared_companies"),"app_shared_listings":app_pair.get("shared_securities"),"manual_listing_count":len(equity_weights(funds[a]).keys()&equity_weights(funds[b]).keys()),"tickerinside_return_corr":peer.get("correlation_3y"),"manual_ti_return_corr":manual_r,"manual_weeks":n,"independent_yahoo_return_corr":yahoo_r,"independent_weeks":yn,"returns_start":common[0] if common else None,"returns_end":common[-1] if common else None,"issuer_overlap_pct":issuer_overlap,"ti_date_a":funds[a].get("holdings_as_of"),"ti_date_b":funds[b].get("holdings_as_of"),"issuer_date_a":ai.get("date"),"issuer_date_b":bi.get("date"),"app_return_correlation":None,"app_return_correlation_status":"not_implemented"}
        row["app_vs_manual_listing_error_pp"]=row["app_listing_overlap_pct"]-manual
        row["app_vs_ti_company_delta_pp"]=row["app_company_overlap_pct"]-(row["tickerinside_overlap_pct"] or 0)
        row["manual_vs_ti_rounding_delta_pp"]=manual-(row["tickerinside_overlap_pct"] or 0)
        row["ti_return_rounding_delta"]=manual_r-row["tickerinside_return_corr"] if manual_r is not None and row["tickerinside_return_corr"] is not None else None
        row["independent_return_delta"]=yahoo_r-manual_r if yahoo_r is not None and manual_r is not None else None
        pair_rows.append(row)
    save(OUT/"pair_results.json",pair_rows)
    for name,rows in [("pairs",pair_rows),("portfolios",portfolio_rows)]:
        fields=[k for k,v in rows[0].items() if not isinstance(v,(list,dict))]
        with (OUT/f"{name}.csv").open("w",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");writer.writeheader();writer.writerows(rows)
    manifest=[json.loads(p.read_text()) for p in sorted(RAW.glob("*.json"))]
    save(OUT/"sources.json",manifest)
    print("COMPLETE",len(portfolio_rows),"portfolios",len(pair_rows),"pairs",len(manifest),"sources",flush=True)


if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("phase",choices=["collect","measure","all"],default="all",nargs="?")
    args=p.parse_args()
    if args.phase in {"collect","all"}:collect()
    if args.phase in {"measure","all"}:measure()
