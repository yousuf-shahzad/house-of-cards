"""Independent validation of 5-year historical 21-trading-day stress drops (FIX-63).

This script is completely standalone and uses ONLY the Python standard library.
It does NOT import anything from the application codebase (`hoc`).

If `validation/stress/data/yahoo_adj_close_5y.json` already exists on disk, it reproduces
all calculations deterministically offline from the saved snapshot. Pass `--fetch` to
refresh the snapshot from Yahoo Finance's v8 chart endpoint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
SNAPSHOT_PATH = DATA_DIR / "yahoo_adj_close_5y.json"
RESULTS_PATH = ROOT_DIR / "results.json"

SHOCK_WINDOW_DAYS = 21
HISTORY_YEARS = 5
YAHOO_URL_TEMPLATE = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=5y&interval=1d"
USER_AGENT = "Mozilla/5.0 (compatible; HoC-Stress-Validation/1.0)"

SECTOR_PROXIES: tuple[tuple[str, str, str], ...] = (
    ("information_technology", "XLK", "Technology Select Sector SPDR Fund"),
    ("financials", "XLF", "Financial Select Sector SPDR Fund"),
    ("health_care", "XLV", "Health Care Select Sector SPDR Fund"),
    ("consumer_discretionary", "XLY", "Consumer Discretionary Select Sector SPDR Fund"),
    ("communication_services", "XLC", "Communication Services Select Sector SPDR Fund"),
    ("industrials", "XLI", "Industrial Select Sector SPDR Fund"),
    ("consumer_staples", "XLP", "Consumer Staples Select Sector SPDR Fund"),
    ("energy", "XLE", "Energy Select Sector SPDR Fund"),
    ("utilities", "XLU", "Utilities Select Sector SPDR Fund"),
    ("real_estate", "XLRE", "Real Estate Select Sector SPDR Fund"),
    ("materials", "XLB", "Materials Select Sector SPDR Fund"),
)

PRIMARY_COUNTRY_PROXIES: tuple[tuple[str, str, str], ...] = (
    ("TW", "EWT", "iShares MSCI Taiwan ETF"),
    ("CN", "MCHI", "iShares MSCI China ETF"),
    ("JP", "EWJ", "iShares MSCI Japan ETF"),
    ("KR", "EWY", "iShares MSCI South Korea ETF"),
    ("US", "SPY", "SPDR S&P 500 ETF Trust"),
)

ADDITIONAL_COUNTRY_PROXIES: tuple[tuple[str, str, str], ...] = (
    ("NL", "EWN", "iShares MSCI Netherlands ETF"),
    ("DE", "EWG", "iShares MSCI Germany ETF"),
    ("GB", "EWU", "iShares MSCI United Kingdom ETF"),
    ("FR", "EWQ", "iShares MSCI France ETF"),
    ("CH", "EWL", "iShares MSCI Switzerland ETF"),
    ("CA", "EWC", "iShares MSCI Canada ETF"),
    ("AU", "EWA", "iShares MSCI Australia ETF"),
    ("IN", "INDA", "iShares MSCI India ETF"),
    ("IE", "EIRL", "iShares MSCI Ireland ETF"),
    ("IL", "EIS", "iShares MSCI Israel ETF"),
    ("HK", "EWH", "iShares MSCI Hong Kong ETF"),
    ("SG", "EWS", "iShares MSCI Singapore ETF"),
    ("SE", "EWD", "iShares MSCI Sweden ETF"),
    ("IT", "EWI", "iShares MSCI Italy ETF"),
    ("ES", "EWP", "iShares MSCI Spain ETF"),
    ("BR", "EWZ", "iShares MSCI Brazil ETF"),
    ("MX", "EWW", "iShares MSCI Mexico ETF"),
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_yahoo_series(ticker: str) -> dict[str, object]:
    url = YAHOO_URL_TEMPLATE.format(ticker=ticker)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    result_list = (payload.get("chart") or {}).get("result") or []
    if not result_list:
        raise ValueError(f"No chart result for {ticker}")
    result = result_list[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    adj_blocks = indicators.get("adjclose") or []
    quote_blocks = indicators.get("quote") or []
    adj_values = (adj_blocks[0].get("adjclose") if adj_blocks else None) or []
    close_values = (quote_blocks[0].get("close") if quote_blocks else None) or []

    by_date: dict[str, tuple[float, float | None]] = {}
    for idx, ts in enumerate(timestamps):
        if ts is None:
            continue
        adj = adj_values[idx] if idx < len(adj_values) else None
        raw_close = close_values[idx] if idx < len(close_values) else None
        price = adj if (adj is not None and adj > 0) else raw_close
        if price is None or price <= 0:
            continue
        day = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
        by_date[day] = (float(price), float(raw_close) if raw_close is not None and raw_close > 0 else None)

    dates = sorted(by_date.keys())
    return {
        "ticker": ticker,
        "url": url,
        "trading_days": len(dates),
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "dates": dates,
        "adj_close": [by_date[d][0] for d in dates],
        "close": [by_date[d][1] for d in dates],
    }


def compute_worst_window(
    dates: list[str],
    prices: list[float],
    window_days: int = SHOCK_WINDOW_DAYS,
) -> dict[str, object]:
    """Compute the worst `window_days`-trading-day return `prices[i + window_days] / prices[i] - 1`."""
    if len(prices) <= window_days:
        raise ValueError(f"Need more than {window_days} trading days, got {len(prices)}")

    worst_return: float | None = None
    worst_idx = -1
    for i in range(len(prices) - window_days):
        start_p = prices[i]
        end_p = prices[i + window_days]
        if start_p <= 0 or end_p <= 0:
            continue
        ret = (end_p / start_p) - 1.0
        if worst_return is None or ret < worst_return:
            worst_return = ret
            worst_idx = i

    if worst_return is None or worst_idx < 0:
        raise ValueError("No valid window found")

    drop = max(0.0, -worst_return)
    return {
        "window_days": window_days,
        "trading_days": len(prices),
        "series_start": dates[0],
        "series_end": dates[-1],
        "window_start": dates[worst_idx],
        "window_end": dates[worst_idx + window_days],
        "start_price": round(prices[worst_idx], 6),
        "end_price": round(prices[worst_idx + window_days], 6),
        "return": round(worst_return, 6),
        "drop": round(drop, 6),
        "drop_4dp": round(drop, 4),
        "drop_pct_1dp": round(drop * 100.0, 1),
        "drop_pct_2dp": round(drop * 100.0, 2),
    }


def load_or_fetch_snapshot(*, force_fetch: bool = False) -> dict[str, object]:
    all_tickers: list[str] = []
    for _, ticker, _ in (*SECTOR_PROXIES, *PRIMARY_COUNTRY_PROXIES, *ADDITIONAL_COUNTRY_PROXIES):
        if ticker not in all_tickers:
            all_tickers.append(ticker)

    if SNAPSHOT_PATH.exists() and not force_fetch:
        return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    series_by_ticker: dict[str, object] = {}
    for ticker in all_tickers:
        series_by_ticker[ticker] = fetch_yahoo_series(ticker)

    snapshot = {
        "source": "Yahoo Finance v8 Chart API (range=5y, interval=1d, daily adjusted close)",
        "url_template": YAHOO_URL_TEMPLATE,
        "window_days": SHOCK_WINDOW_DAYS,
        "history_years": HISTORY_YEARS,
        "tickers": series_by_ticker,
    }
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Refresh the Yahoo Finance 5y snapshot.")
    args = parser.parse_args(argv)

    snapshot = load_or_fetch_snapshot(force_fetch=args.fetch)
    tickers_data: dict[str, dict[str, object]] = snapshot["tickers"]  # type: ignore[assignment]

    def evaluate_group(entries: tuple[tuple[str, str, str], ...], kind: str) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for key, ticker, name in entries:
            item = tickers_data[ticker]
            dates = list(item["dates"])  # type: ignore[arg-type]
            adj_prices = list(item["adj_close"])  # type: ignore[arg-type]
            raw_closes = [
                float(c) if c is not None else float(adj_prices[idx])
                for idx, c in enumerate(item.get("close") or adj_prices)  # type: ignore[arg-type]
            ]
            adj_stats = compute_worst_window(dates, adj_prices, SHOCK_WINDOW_DAYS)
            close_stats = compute_worst_window(dates, raw_closes, SHOCK_WINDOW_DAYS)
            rows.append(
                {
                    "kind": kind,
                    "key": key,
                    "proxy": ticker,
                    "name": name,
                    "adj_close_worst_21d": adj_stats,
                    "unadjusted_close_worst_21d": {
                        "window_start": close_stats["window_start"],
                        "window_end": close_stats["window_end"],
                        "drop": close_stats["drop"],
                        "drop_pct_1dp": close_stats["drop_pct_1dp"],
                        "drop_pct_2dp": close_stats["drop_pct_2dp"],
                    },
                    "description": (
                        f"{ticker}'s worst month in the last 5 years: "
                        f"-{adj_stats['drop_pct_1dp']:.1f}% "
                        f"({adj_stats['window_start']} to {adj_stats['window_end']})"
                    ),
                }
            )
        return rows

    sectors = evaluate_group(SECTOR_PROXIES, "sector")
    primary_countries = evaluate_group(PRIMARY_COUNTRY_PROXIES, "country")
    additional_countries = evaluate_group(ADDITIONAL_COUNTRY_PROXIES, "country")

    results = {
        "snapshot_file": str(SNAPSHOT_PATH.relative_to(ROOT_DIR)),
        "snapshot_sha256": sha256_file(SNAPSHOT_PATH),
        "snapshot_bytes": SNAPSHOT_PATH.stat().st_size,
        "window_days": SHOCK_WINDOW_DAYS,
        "history_years": HISTORY_YEARS,
        "sectors": sectors,
        "primary_countries": primary_countries,
        "additional_countries": additional_countries,
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    print("=== FIX-63 Independent 5-Year Worst 21-Trading-Day Fall Check ===")
    print(f"Snapshot: {SNAPSHOT_PATH.name} ({results['snapshot_bytes']:,} bytes, sha256={results['snapshot_sha256'][:16]}...)")
    print()
    print("Sectors (11 SPDR ETFs):")
    print(f"{'Key':<26} {'ETF':<6} {'Drop (6dp)':>10} {'Drop (%)':>9} {'Window Start':<12} {'Window End':<12} {'Unadj (%)':>10}")
    for row in sectors:
        s = row["adj_close_worst_21d"]  # type: ignore[assignment]
        u = row["unadjusted_close_worst_21d"]  # type: ignore[assignment]
        print(
            f"{row['key']:<26} {row['proxy']:<6} {s['drop']:>10.6f} {s['drop_pct_2dp']:>8.2f}% "
            f"{s['window_start']:<12} {s['window_end']:<12} {u['drop_pct_2dp']:>9.2f}%"
        )
    print()
    print("Primary Countries (EWT, MCHI, EWJ, EWY, SPY):")
    for row in primary_countries:
        s = row["adj_close_worst_21d"]  # type: ignore[assignment]
        u = row["unadjusted_close_worst_21d"]  # type: ignore[assignment]
        print(
            f"{row['key']:<26} {row['proxy']:<6} {s['drop']:>10.6f} {s['drop_pct_2dp']:>8.2f}% "
            f"{s['window_start']:<12} {s['window_end']:<12} {u['drop_pct_2dp']:>9.2f}%"
        )
    print()
    print("Additional Countries (17 MSCI Country ETFs):")
    for row in additional_countries:
        s = row["adj_close_worst_21d"]  # type: ignore[assignment]
        u = row["unadjusted_close_worst_21d"]  # type: ignore[assignment]
        print(
            f"{row['key']:<26} {row['proxy']:<6} {s['drop']:>10.6f} {s['drop_pct_2dp']:>8.2f}% "
            f"{s['window_start']:<12} {s['window_end']:<12} {u['drop_pct_2dp']:>9.2f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
