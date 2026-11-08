"""Independent validation of House of Cards (QQQ vs XLK overlap & dependency links vs 3y price history).

This script is completely standalone and uses ONLY the Python standard library.
It does NOT import anything from the application codebase.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import random
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
RESULTS_PATH = ROOT_DIR / "results.json"

SOURCES = {
    "xlk_ssga_xlsx": {
        "file": "xlk_ssga_2026-11-05.xlsx",
        "issuer": "State Street Global Advisors (SPDR)",
        "url": "https://www.ssga.com/us/en/intermediary/etfs/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xlk.xlsx",
        "as_of_date": "2026-11-05",
    },
    "qqq_invesco_json": {
        "file": "qqq_invesco_2026-11-05.json",
        "issuer": "Invesco",
        "url": "https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/46090E103/holdings/fund?idType=cusip&productType=ETF",
        "as_of_date": "2026-11-05",
    },
    "qqq_sec_nport_xml": {
        "file": "qqq_sec_nport_2026-06-30.xml",
        "issuer": "SEC EDGAR (Invesco QQQ Trust Form N-PORT)",
        "url": "https://www.sec.gov/Archives/edgar/data/1067839/000106783926000030/primary_doc.xml",
        "as_of_date": "2026-06-30",
        "filed_date": "2026-08-28",
    },
    "app_export_json": {
        "file": "app_qqq_xlk_export.json",
        "issuer": "App output under test (/api/analysis and /api/dependencies for QQQ + XLK)",
        "url": "http://127.0.0.1:8000/api/dependencies",
        "as_of_date": "2026-11-05",
    },
    "yahoo_prices_json": {
        "file": "yahoo_adj_close_3y.json",
        "issuer": "Yahoo Finance v8 Chart API (daily adjusted close)",
        "url": "https://query1.finance.yahoo.com/v8/finance/chart/{TICKER}?range=3y&interval=1d",
        "as_of_date": "2026-11-06",
    },
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_xlsx_rows(xlsx_bytes: bytes) -> list[list[str]]:
    """Parse the first worksheet of an .xlsx file using only Python stdlib."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zf:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss_root.findall(f".//{ns}si"):
                texts = [t.text or "" for t in si.findall(f".//{ns}t")]
                shared_strings.append("".join(texts))
        sheet_root = ET.fromstring(zf.read("xl/worksheets/sheet1.xml"))
        rows: list[list[str]] = []
        for row_el in sheet_root.findall(f".//{ns}row"):
            vals: list[str] = []
            for cell_el in row_el.findall(f"{ns}c"):
                cell_type = cell_el.attrib.get("t")
                val_el = cell_el.find(f"{ns}v")
                raw_val = val_el.text if val_el is not None and val_el.text is not None else ""
                if cell_type == "s" and raw_val != "":
                    raw_val = shared_strings[int(raw_val)]
                vals.append(raw_val)
            rows.append(vals)
        return rows


def issuer_key_from_cusip(cusip: str, fallback: str) -> str:
    """Group multiple share classes of the same company by 6-character CUSIP issuer prefix."""
    cleaned = cusip.strip()
    if len(cleaned) == 9:
        return f"CUSIP6:{cleaned[:6]}"
    return f"ID:{fallback.strip().upper()}"


def load_xlk_ssga(path: Path) -> tuple[dict[str, float], dict[str, dict[str, str]], str]:
    rows = parse_xlsx_rows(path.read_bytes())
    as_of_label = rows[2][1].strip() if len(rows) > 2 and len(rows[2]) > 1 else ""
    weights: dict[str, float] = defaultdict(float)
    meta: dict[str, dict[str, str]] = {}
    for row in rows[4:]:
        if len(row) < 5:
            continue
        name, ticker, cusip, _sedol, weight_str = (
            row[0].strip(),
            row[1].strip(),
            row[2].strip(),
            row[3].strip(),
            row[4].strip(),
        )
        if not name or not ticker or not weight_str:
            continue
        try:
            weight = float(weight_str) / 100.0
        except ValueError:
            continue
        # Exclude cash/currency lines if present
        if ticker.upper() in ("USD", "CASH") or "CASH" in name.upper():
            continue
        key = issuer_key_from_cusip(cusip, ticker)
        weights[key] += weight
        if key not in meta:
            meta[key] = {"ticker": ticker, "name": name, "cusip": cusip}
    return dict(weights), meta, as_of_label


def load_qqq_invesco(path: Path) -> tuple[dict[str, float], dict[str, dict[str, object]], str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    as_of = str(payload.get("effectiveDate", ""))
    weights: dict[str, float] = defaultdict(float)
    meta: dict[str, dict[str, object]] = {}
    for h in payload.get("holdings", []):
        sec_type = h.get("securityTypeCode")
        if sec_type not in ("COM", "ADR", "DRNY"):
            continue
        pct = h.get("percentageOfTotalNetAssets")
        if pct is None:
            continue
        weight = float(pct) / 100.0
        ticker = str(h.get("ticker") or "").strip()
        name = str(h.get("issuerName") or "").strip()
        cusip = str(h.get("cusip") or "").strip()
        key = issuer_key_from_cusip(cusip, ticker or name)
        weights[key] += weight
        if key not in meta:
            meta[key] = {"ticker": ticker, "tickers": [ticker], "name": name, "cusip": cusip}
        else:
            tickers_list = list(meta[key].get("tickers", []))  # type: ignore[arg-type]
            if ticker and ticker not in tickers_list:
                tickers_list.append(ticker)
                meta[key]["tickers"] = tickers_list
    return dict(weights), meta, as_of


def load_qqq_nport(path: Path) -> tuple[dict[str, float], dict[str, dict[str, str]], str]:
    root = ET.fromstring(path.read_bytes())
    ns = {"n": "http://www.sec.gov/edgar/nport"}
    rep_date = root.findtext(".//n:repPdDate", default="", namespaces=ns)
    weights: dict[str, float] = defaultdict(float)
    meta: dict[str, dict[str, str]] = {}
    for inv in root.findall(".//n:invstOrSec", ns):
        asset_cat = (inv.findtext("n:assetCat", default="", namespaces=ns) or "").strip()
        if asset_cat != "EC":
            continue
        cusip = (inv.findtext("n:cusip", default="", namespaces=ns) or "").strip()
        name = (inv.findtext("n:name", default="", namespaces=ns) or "").strip()
        pct_str = (inv.findtext("n:pctVal", default="0", namespaces=ns) or "0").strip()
        weight = float(pct_str) / 100.0
        key = issuer_key_from_cusip(cusip, name)
        weights[key] += weight
        if key not in meta:
            meta[key] = {"name": name, "cusip": cusip}
    return dict(weights), meta, rep_date


def compute_overlap(
    weights_a: dict[str, float],
    meta_a: dict[str, dict[str, object]],
    weights_b: dict[str, float],
    meta_b: dict[str, dict[str, str]],
) -> dict[str, object]:
    shared_keys = sorted(
        set(weights_a.keys()) & set(weights_b.keys()),
        key=lambda k: min(weights_a[k], weights_b[k]),
        reverse=True,
    )
    total_overlap = sum(min(weights_a[k], weights_b[k]) for k in shared_keys)
    rows = []
    for k in shared_keys:
        wa = weights_a[k]
        wb = weights_b[k]
        mw = min(wa, wb)
        rows.append(
            {
                "issuer_key": k,
                "ticker": meta_b[k].get("ticker") or meta_a[k].get("ticker", ""),
                "company_name": meta_a[k].get("name") or meta_b[k].get("name", ""),
                "weight_qqq": round(wa, 6),
                "weight_xlk": round(wb, 6),
                "min_weight": round(mw, 6),
            }
        )
    return {
        "shared_companies": len(shared_keys),
        "weighted_overlap": round(total_overlap, 6),
        "weighted_overlap_pct": round(total_overlap * 100.0, 2),
        "top_shared": rows[:15],
        "all_shared": rows,
    }


def ols_residuals(y: list[float], x_cols: list[list[float]]) -> list[float]:
    """Compute OLS residuals y - X * beta_hat (with intercept) using Gauss-Jordan elimination."""
    n = len(y)
    x_mat = [[1.0] + [col[i] for col in x_cols] for i in range(n)]
    k = len(x_mat[0])
    xtx = [[sum(x_mat[i][r] * x_mat[i][c] for i in range(n)) for c in range(k)] for r in range(k)]
    xty = [sum(x_mat[i][r] * y[i] for i in range(n)) for r in range(k)]
    aug = [xtx[r][:] + [xty[r]] for r in range(k)]
    for col in range(k):
        piv = max(range(col, k), key=lambda r: abs(aug[r][col]))
        aug[col], aug[piv] = aug[piv], aug[col]
        div = aug[col][col]
        for c in range(col, k + 1):
            aug[col][c] /= div
        for r in range(k):
            if r != col:
                factor = aug[r][col]
                for c in range(col, k + 1):
                    aug[r][c] -= factor * aug[col][c]
    beta = [aug[r][k] for r in range(k)]
    return [y[i] - sum(x_mat[i][c] * beta[c] for c in range(k)) for i in range(n)]


def pearson_corr(x: list[float], y: list[float]) -> float:
    n = len(x)
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    den = math.sqrt(sum((x[i] - mx) ** 2 for i in range(n)) * sum((y[i] - my) ** 2 for i in range(n)))
    return num / den if den > 0.0 else 0.0


def zscore_series(x: list[float]) -> list[float]:
    n = len(x)
    m = sum(x) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in x) / n)
    if sd == 0.0:
        return [0.0] * n
    return [(v - m) / sd for v in x]


def bootstrap_diff_ci(
    vals_a: list[float],
    vals_b: list[float],
    rng: random.Random,
    n_boot: int = 10000,
) -> tuple[float, float]:
    na, nb = len(vals_a), len(vals_b)
    diffs: list[float] = []
    for _ in range(n_boot):
        ma = sum(vals_a[rng.randrange(na)] for _ in range(na)) / na
        mb = sum(vals_b[rng.randrange(nb)] for _ in range(nb)) / nb
        diffs.append(ma - mb)
    diffs.sort()
    lo = diffs[int(0.025 * n_boot)]
    hi = diffs[int(0.975 * n_boot)]
    return lo, hi


def permutation_pvalue(
    vals_a: list[float],
    vals_b: list[float],
    rng: random.Random,
    n_perm: int = 10000,
) -> float:
    na, nb = len(vals_a), len(vals_b)
    obs = (sum(vals_a) / na) - (sum(vals_b) / nb)
    pooled = vals_a + vals_b
    extreme = 0
    for _ in range(n_perm):
        rng.shuffle(pooled)
        ma = sum(pooled[:na]) / na
        mb = sum(pooled[na:]) / nb
        if abs(ma - mb) >= abs(obs) - 1e-12:
            extreme += 1
    return (extreme + 1) / (n_perm + 1)


def run_part1_overlap() -> dict[str, object]:
    xlk_path = DATA_DIR / SOURCES["xlk_ssga_xlsx"]["file"]
    qqq_inv_path = DATA_DIR / SOURCES["qqq_invesco_json"]["file"]
    qqq_nport_path = DATA_DIR / SOURCES["qqq_sec_nport_xml"]["file"]
    app_exp_path = DATA_DIR / SOURCES["app_export_json"]["file"]

    xlk_w, xlk_meta, xlk_as_of_label = load_xlk_ssga(xlk_path)
    qqq_inv_w, qqq_inv_meta, qqq_inv_as_of = load_qqq_invesco(qqq_inv_path)
    qqq_np_w, qqq_np_meta, qqq_np_as_of = load_qqq_nport(qqq_nport_path)
    app_export = json.loads(app_exp_path.read_text(encoding="utf-8"))

    direct_issuer_overlap = compute_overlap(qqq_inv_w, qqq_inv_meta, xlk_w, xlk_meta)
    nport_matched_overlap = compute_overlap(qqq_np_w, qqq_np_meta, xlk_w, xlk_meta)

    # Check dual-class Alphabet merging in QQQ
    goog_key = "CUSIP6:02079K"
    alphabet_merge_check = {
        "issuer_key": goog_key,
        "qqq_invesco_combined_weight": round(qqq_inv_w.get(goog_key, 0.0), 6),
        "qqq_nport_combined_weight": round(qqq_np_w.get(goog_key, 0.0), 6),
        "in_xlk": goog_key in xlk_w,
        "note": "Alphabet Class A (GOOGL, 02079K305) and Class C (GOOG, 02079K107) merge under 6-digit issuer CUSIP 02079K; XLK classifies Alphabet under Communication Services (XLC) so XLK weight is 0.",
    }

    # Decompose the +1.33 pp gap between 2026-11-05 direct Invesco QQQ and 2026-06-30 SEC N-PORT QQQ
    direct_by_key = {r["issuer_key"]: r for r in direct_issuer_overlap["all_shared"]}  # type: ignore[index]
    nport_by_key = {r["issuer_key"]: r for r in nport_matched_overlap["all_shared"]}  # type: ignore[index]
    drift_rows = []
    for k in sorted(set(direct_by_key.keys()) | set(nport_by_key.keys())):
        d_min = float(direct_by_key.get(k, {}).get("min_weight", 0.0))
        n_min = float(nport_by_key.get(k, {}).get("min_weight", 0.0))
        delta = d_min - n_min
        drift_rows.append(
            {
                "issuer_key": k,
                "ticker": direct_by_key.get(k, nport_by_key.get(k, {})).get("ticker", ""),
                "company_name": direct_by_key.get(k, nport_by_key.get(k, {})).get("company_name", ""),
                "qqq_2026_06_30": round(float(nport_by_key.get(k, {}).get("weight_qqq", 0.0)), 6),
                "qqq_2026_11_05": round(float(direct_by_key.get(k, {}).get("weight_qqq", 0.0)), 6),
                "xlk_2026_11_05": round(float(direct_by_key.get(k, {}).get("weight_xlk", 0.0)), 6),
                "min_2026_06_30": round(n_min, 6),
                "min_2026_11_05": round(d_min, 6),
                "overlap_delta": round(delta, 6),
            }
        )
    drift_rows.sort(key=lambda r: abs(float(r["overlap_delta"])), reverse=True)

    app_overlap_val = float(app_export["app_overlap"]["weighted_overlap"])
    app_shared_cnt = int(app_export["app_overlap"]["shared_companies"])

    return {
        "files": {
            "xlk_ssga": {
                **SOURCES["xlk_ssga_xlsx"],
                "as_of_header": xlk_as_of_label,
                "sha256": sha256_file(xlk_path),
                "bytes": xlk_path.stat().st_size,
                "equity_company_count": len(xlk_w),
                "equity_weight_sum": round(sum(xlk_w.values()), 6),
            },
            "qqq_invesco_current": {
                **SOURCES["qqq_invesco_json"],
                "effective_date": qqq_inv_as_of,
                "sha256": sha256_file(qqq_inv_path),
                "bytes": qqq_inv_path.stat().st_size,
                "equity_company_count": len(qqq_inv_w),
                "equity_weight_sum": round(sum(qqq_inv_w.values()), 6),
            },
            "qqq_sec_nport": {
                **SOURCES["qqq_sec_nport_xml"],
                "rep_pd_date": qqq_np_as_of,
                "sha256": sha256_file(qqq_nport_path),
                "bytes": qqq_nport_path.stat().st_size,
                "equity_company_count": len(qqq_np_w),
                "equity_weight_sum": round(sum(qqq_np_w.values()), 6),
            },
        },
        "app_reported": {
            "shared_companies": app_shared_cnt,
            "weighted_overlap": app_overlap_val,
            "weighted_overlap_pct": round(app_overlap_val * 100.0, 2),
            "qqq_as_of": "2026-06-30",
            "xlk_as_of": "2026-11-05",
        },
        "independent_nport_2026_06_30_vs_xlk_2026_11_05": {
            "shared_companies": nport_matched_overlap["shared_companies"],
            "weighted_overlap": nport_matched_overlap["weighted_overlap"],
            "weighted_overlap_pct": nport_matched_overlap["weighted_overlap_pct"],
            "abs_diff_vs_app": round(abs(float(nport_matched_overlap["weighted_overlap"]) - app_overlap_val), 6),
            "top_shared": nport_matched_overlap["top_shared"],
        },
        "independent_direct_invesco_2026_11_05_vs_xlk_2026_11_05": {
            "shared_companies": direct_issuer_overlap["shared_companies"],
            "weighted_overlap": direct_issuer_overlap["weighted_overlap"],
            "weighted_overlap_pct": direct_issuer_overlap["weighted_overlap_pct"],
            "diff_vs_app": round(float(direct_issuer_overlap["weighted_overlap"]) - app_overlap_val, 6),
            "diff_vs_app_pct_points": round((float(direct_issuer_overlap["weighted_overlap"]) - app_overlap_val) * 100.0, 2),
            "top_shared": direct_issuer_overlap["top_shared"],
        },
        "alphabet_share_class_merge": alphabet_merge_check,
        "top_date_drift_contributors": drift_rows[:10],
    }


# Mapping from app company keys / names in app_qqq_xlk_export.json to US-listed stock / ADR tickers
COMPANY_TO_US_TICKER: dict[str, str] = {
    "CIK:0000320193": "AAPL",
    "CIK:0001045810": "NVDA",
    "CIK:0000789019": "MSFT",
    "CIK:0000723125": "MU",
    "CIK:0000002488": "AMD",
    "CIK:0001730168": "AVGO",
    "CIK:0001652044": "GOOGL",
    "CIK:0000050863": "INTC",
    "CIK:0000858877": "CSCO",
    "CIK:0000006951": "AMAT",
    "CIK:0000707549": "LRCX",
    "CIK:0001321655": "PLTR",
    "CIK:0001327567": "PANW",
    "CIK:0000866374": "FLEX",
    "ALIAS:TSMC": "TSM",
    "ALIAS:ASML": "ASML",
    "SYM:2303.TW": "UMC",
    "Fabrinet": "FN",
    "GLOBALFOUNDRIES Inc.": "GFS",
    "Sony": "SONY",
    "Flextronics International, Ltd.": "FLEX",
}

SEMI_TICKERS = {
    "AMD", "ASML", "AVGO", "FN", "GFS", "INTC", "LRCX", "MU", "NVDA", "TSM", "UMC",
    "AMAT", "TXN", "ADI", "KLAC", "QCOM", "MRVL", "SNPS", "CDNS", "NXPI", "MPWR",
}
TECH_TICKERS = {
    "AAPL", "FLEX", "GOOGL", "MSFT", "PANW", "SONY",
    "CSCO", "PLTR", "CRWD", "ADBE", "INTU",
}


def resolve_us_ticker(company_key: str | None, company_name: str | None) -> str | None:
    if company_key and company_key in COMPANY_TO_US_TICKER:
        return COMPANY_TO_US_TICKER[company_key]
    if company_name and company_name in COMPANY_TO_US_TICKER:
        return COMPANY_TO_US_TICKER[company_name]
    return None


def run_part2_dependencies_vs_prices() -> dict[str, object]:
    app_exp_path = DATA_DIR / SOURCES["app_export_json"]["file"]
    prices_path = DATA_DIR / SOURCES["yahoo_prices_json"]["file"]

    app_export = json.loads(app_exp_path.read_text(encoding="utf-8"))
    price_data = json.loads(prices_path.read_text(encoding="utf-8"))

    dates: list[str] = price_data["dates"]
    adj_close: dict[str, list[float]] = price_data["adj_close"]

    # Extract unique directed US-listed pairs from exported app company edges
    seen_pairs: dict[tuple[str, str], dict[str, object]] = {}
    excluded_non_us_or_private: list[dict[str, str]] = []
    for edge in app_export["app_company_edges"]:
        s_ticker = resolve_us_ticker(edge.get("source_company_key"), edge.get("source_company_name"))
        t_ticker = resolve_us_ticker(edge.get("target_key"), edge.get("target_name"))
        if s_ticker and t_ticker and s_ticker in adj_close and t_ticker in adj_close and s_ticker != t_ticker:
            pair_key = (s_ticker, t_ticker)
            score = float((edge.get("importance") or {}).get("score", 0.0))
            if pair_key not in seen_pairs or score > float(seen_pairs[pair_key]["importance_score"]):
                seen_pairs[pair_key] = {
                    "source_ticker": s_ticker,
                    "source_name": edge.get("source_company_name"),
                    "target_ticker": t_ticker,
                    "target_name": edge.get("target_name"),
                    "edge_type": edge.get("edge_type"),
                    "importance_tier": (edge.get("importance") or {}).get("tier"),
                    "importance_score": score,
                    "filing_accession": (edge.get("filing") or {}).get("accession"),
                    "filing_date": (edge.get("filing") or {}).get("filed"),
                }
        else:
            excluded_non_us_or_private.append(
                {
                    "source_name": str(edge.get("source_company_name")),
                    "target_name": str(edge.get("target_name")),
                    "edge_type": str(edge.get("edge_type")),
                }
            )

    linked_pairs = list(seen_pairs.values())
    linked_unordered = {tuple(sorted((str(p["source_ticker"]), str(p["target_ticker"])))) for p in linked_pairs}

    # Compute daily simple returns
    returns: dict[str, list[float]] = {}
    for t, series in adj_close.items():
        returns[t] = [(series[i] / series[i - 1]) - 1.0 for i in range(1, len(series))]

    stock_tickers = sorted(SEMI_TICKERS | TECH_TICKERS)
    res_2f = {t: ols_residuals(returns[t], [returns["SPY"], returns["XLK"]]) for t in stock_tickers}
    res_3f = {t: ols_residuals(returns[t], [returns["SPY"], returns["XLK"], returns["SOXX"]]) for t in stock_tickers}

    # Build matched same-sector control pairs (no predicted link in the app)
    analysed_sources = {
        resolve_us_ticker(c.get("company_key"), c.get("company_name"))
        for c in app_export["app_analysed_companies"]
    } - {None}

    control_pairs: list[tuple[str, str, str]] = []
    for i, a in enumerate(stock_tickers):
        for b in stock_tickers[i + 1 :]:
            if (a, b) in linked_unordered:
                continue
            if a not in analysed_sources and b not in analysed_sources:
                continue
            if a in SEMI_TICKERS and b in SEMI_TICKERS:
                control_pairs.append((a, b, "semiconductor"))
            elif a in TECH_TICKERS and b in TECH_TICKERS:
                control_pairs.append((a, b, "technology"))

    rng = random.Random(20261108)

    def evaluate_model(res_map: dict[str, list[float]], model_label: str) -> dict[str, object]:
        z_map = {t: zscore_series(res_map[t]) for t in stock_tickers}

        pair_rows = []
        linked_corrs: list[float] = []
        linked_event_hit_rates: list[float] = []
        linked_event_signed_z: list[float] = []

        for p in linked_pairs:
            s = str(p["source_ticker"])
            t = str(p["target_ticker"])
            c = pearson_corr(res_map[s], res_map[t])
            linked_corrs.append(c)

            shock_days = [idx for idx, zval in enumerate(z_map[t]) if abs(zval) > 2.0]
            same_sign = sum(1 for idx in shock_days if (z_map[s][idx] * z_map[t][idx]) > 0.0)
            hit_rate = same_sign / len(shock_days) if shock_days else 0.5
            signed_z = (
                sum((1.0 if z_map[t][idx] > 0 else -1.0) * z_map[s][idx] for idx in shock_days) / len(shock_days)
                if shock_days
                else 0.0
            )
            linked_event_hit_rates.append(hit_rate)
            linked_event_signed_z.append(signed_z)

            pair_rows.append(
                {
                    **p,
                    "residual_corr": round(c, 4),
                    "target_shock_days": len(shock_days),
                    "event_same_sign_rate": round(hit_rate, 4),
                    "event_signed_source_z": round(signed_z, 4),
                }
            )

        ctrl_corrs: list[float] = []
        ctrl_event_hit_rates: list[float] = []
        ctrl_event_signed_z: list[float] = []
        for a, b, _subsec in control_pairs:
            c = pearson_corr(res_map[a], res_map[b])
            ctrl_corrs.append(c)
            shock_days = [idx for idx, zval in enumerate(z_map[b]) if abs(zval) > 2.0]
            same_sign = sum(1 for idx in shock_days if (z_map[a][idx] * z_map[b][idx]) > 0.0)
            hit_rate = same_sign / len(shock_days) if shock_days else 0.5
            signed_z = (
                sum((1.0 if z_map[b][idx] > 0 else -1.0) * z_map[a][idx] for idx in shock_days) / len(shock_days)
                if shock_days
                else 0.0
            )
            ctrl_event_hit_rates.append(hit_rate)
            ctrl_event_signed_z.append(signed_z)

        corr_ci = bootstrap_diff_ci(linked_corrs, ctrl_corrs, rng)
        corr_p = permutation_pvalue(linked_corrs, ctrl_corrs, rng)

        hit_ci = bootstrap_diff_ci(linked_event_hit_rates, ctrl_event_hit_rates, rng)
        hit_p = permutation_pvalue(linked_event_hit_rates, ctrl_event_hit_rates, rng)

        sz_ci = bootstrap_diff_ci(linked_event_signed_z, ctrl_event_signed_z, rng)
        sz_p = permutation_pvalue(linked_event_signed_z, ctrl_event_signed_z, rng)

        return {
            "model": model_label,
            "n_linked_pairs": len(linked_corrs),
            "n_control_pairs": len(ctrl_corrs),
            "residual_correlation": {
                "linked_mean": round(sum(linked_corrs) / len(linked_corrs), 4),
                "linked_median": round(sorted(linked_corrs)[len(linked_corrs) // 2], 4),
                "control_mean": round(sum(ctrl_corrs) / len(ctrl_corrs), 4),
                "control_median": round(sorted(ctrl_corrs)[len(ctrl_corrs) // 2], 4),
                "diff_mean": round((sum(linked_corrs) / len(linked_corrs)) - (sum(ctrl_corrs) / len(ctrl_corrs)), 4),
                "bootstrap_95_ci": [round(corr_ci[0], 4), round(corr_ci[1], 4)],
                "permutation_p_value": round(corr_p, 4),
            },
            "event_study_target_abs_z_gt_2": {
                "linked_same_sign_rate": round(sum(linked_event_hit_rates) / len(linked_event_hit_rates), 4),
                "control_same_sign_rate": round(sum(ctrl_event_hit_rates) / len(ctrl_event_hit_rates), 4),
                "diff_same_sign_rate": round(
                    (sum(linked_event_hit_rates) / len(linked_event_hit_rates))
                    - (sum(ctrl_event_hit_rates) / len(ctrl_event_hit_rates)),
                    4,
                ),
                "same_sign_bootstrap_95_ci": [round(hit_ci[0], 4), round(hit_ci[1], 4)],
                "same_sign_permutation_p_value": round(hit_p, 4),
                "linked_mean_signed_source_z": round(sum(linked_event_signed_z) / len(linked_event_signed_z), 4),
                "control_mean_signed_source_z": round(sum(ctrl_event_signed_z) / len(ctrl_event_signed_z), 4),
                "diff_signed_source_z": round(
                    (sum(linked_event_signed_z) / len(linked_event_signed_z))
                    - (sum(ctrl_event_signed_z) / len(ctrl_event_signed_z)),
                    4,
                ),
                "signed_z_bootstrap_95_ci": [round(sz_ci[0], 4), round(sz_ci[1], 4)],
                "signed_z_permutation_p_value": round(sz_p, 4),
            },
            "pair_details": pair_rows,
        }

    eval_3f = evaluate_model(res_3f, "SPY + XLK + SOXX (market + tech + semiconductor factors)")
    eval_2f = evaluate_model(res_2f, "SPY + XLK (market + broad tech factor)")

    return {
        "files": {
            "app_export": {
                **SOURCES["app_export_json"],
                "sha256": sha256_file(app_exp_path),
                "bytes": app_exp_path.stat().st_size,
            },
            "yahoo_prices": {
                **SOURCES["yahoo_prices_json"],
                "sha256": sha256_file(prices_path),
                "bytes": prices_path.stat().st_size,
                "start_date": dates[0],
                "end_date": dates[-1],
                "trading_days": len(dates),
                "return_days": len(dates) - 1,
                "ticker_count": len(adj_close),
            },
        },
        "hypothesis_summary": {
            "total_app_company_edges": len(app_export["app_company_edges"]),
            "unique_us_listed_pairs_tested": len(linked_pairs),
            "matched_same_sector_control_pairs": len(control_pairs),
            "excluded_non_us_or_private_edges_count": len(excluded_non_us_or_private),
        },
        "three_factor_model_spy_xlk_soxx": eval_3f,
        "two_factor_model_spy_xlk": eval_2f,
    }


def main() -> None:
    part1 = run_part1_overlap()
    part2 = run_part2_dependencies_vs_prices()

    results = {
        "validation_date": "2026-11-08",
        "part1_qqq_xlk_overlap": part1,
        "part2_dependencies_vs_price_history": part2,
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    p1_np = part1["independent_nport_2026_06_30_vs_xlk_2026_11_05"]  # type: ignore[index]
    p1_dir = part1["independent_direct_invesco_2026_11_05_vs_xlk_2026_11_05"]  # type: ignore[index]
    p2_3f = part2["three_factor_model_spy_xlk_soxx"]  # type: ignore[index]
    p2_2f = part2["two_factor_model_spy_xlk"]  # type: ignore[index]

    print("=== PART 1: QQQ vs XLK OVERLAP ===")
    print(f"App reported (QQQ 2026-06-30 N-PORT vs XLK 2026-11-05): {part1['app_reported']['weighted_overlap']} ({part1['app_reported']['weighted_overlap_pct']}%) | {part1['app_reported']['shared_companies']} shared companies")  # type: ignore[index]
    print(f"Independent N-PORT (2026-06-30) vs SSGA XLK (2026-11-05): {p1_np['weighted_overlap']} ({p1_np['weighted_overlap_pct']}%) | {p1_np['shared_companies']} shared | abs_diff={p1_np['abs_diff_vs_app']}")  # type: ignore[index]
    print(f"Independent Direct Invesco (2026-11-05) vs SSGA XLK (2026-11-05): {p1_dir['weighted_overlap']} ({p1_dir['weighted_overlap_pct']}%) | {p1_dir['shared_companies']} shared | diff={p1_dir['diff_vs_app']:+.6f} ({p1_dir['diff_vs_app_pct_points']:+.2f} pp)")  # type: ignore[index]

    print("\n=== PART 2: DEPENDENCIES vs 3Y PRICE HISTORY (2023-11-07 to 2026-11-06, N=752 return days) ===")
    rc3 = p2_3f["residual_correlation"]  # type: ignore[index]
    ev3 = p2_3f["event_study_target_abs_z_gt_2"]  # type: ignore[index]
    print(f"[3-Factor SPY+XLK+SOXX] Linked r_res={rc3['linked_mean']:+.4f} (n={p2_3f['n_linked_pairs']}) vs Control={rc3['control_mean']:+.4f} (n={p2_3f['n_control_pairs']}) | diff={rc3['diff_mean']:+.4f}, 95% CI={rc3['bootstrap_95_ci']}, perm p={rc3['permutation_p_value']}")  # type: ignore[index]
    print(f"[3-Factor Event |z|>2]  Linked sign-match={ev3['linked_same_sign_rate']:.4f} vs Control={ev3['control_same_sign_rate']:.4f} | diff={ev3['diff_same_sign_rate']:+.4f}, 95% CI={ev3['same_sign_bootstrap_95_ci']}, perm p={ev3['same_sign_permutation_p_value']}")  # type: ignore[index]
    rc2 = p2_2f["residual_correlation"]  # type: ignore[index]
    ev2 = p2_2f["event_study_target_abs_z_gt_2"]  # type: ignore[index]
    print(f"[2-Factor SPY+XLK]      Linked r_res={rc2['linked_mean']:+.4f} vs Control={rc2['control_mean']:+.4f} | diff={rc2['diff_mean']:+.4f}, 95% CI={rc2['bootstrap_95_ci']}, perm p={rc2['permutation_p_value']}")  # type: ignore[index]
    print(f"[2-Factor Event |z|>2]  Linked sign-match={ev2['linked_same_sign_rate']:.4f} vs Control={ev2['control_same_sign_rate']:.4f} | diff={ev2['diff_same_sign_rate']:+.4f}, 95% CI={ev2['same_sign_bootstrap_95_ci']}, perm p={ev2['same_sign_permutation_p_value']}")  # type: ignore[index]


if __name__ == "__main__":
    main()
