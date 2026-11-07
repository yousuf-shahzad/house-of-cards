"""V1 numeric cross-check: our analysis vs TickerInside's own /lookthrough and /overlap answers.

A verification tool only: never imported by the app. Our numbers come from EtfService (the same path
as the API and CLI); this script only compares, it never re-implements the maths. TickerInside asks
for at most one fetch per nightly build, so their answers go through the cached HttpClient (24 h TTL).

Run (needs live sources, packages a and d):
    cd backend && uv run python ../scripts/crosscheck_tickerinside.py [--example us-core-tilt] [--output FILE]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import timedelta

from hoc.contract import AnalysisResponse

BASE = "https://tickerinside.com/api/v1"
TTL = timedelta(hours=24)
SOURCE = "tickerinside"
TOP = 20
ROUNDING_PP = 0.001
"""Their look-through weights have 3 decimals of a percent: anything under 0.001 pp is rounding."""


@dataclass
class Row:
    label: str
    theirs: float | None
    ours: float | None
    note: str = ""

    @property
    def diff(self) -> float | None:
        return None if self.theirs is None or self.ours is None else self.ours - self.theirs


@dataclass
class Report:
    example: str
    lookthrough_funds: list[str]
    skipped_funds: list[str]
    dates: list[tuple[str, str | None, str | None]]
    exposures: list[Row]
    coverage: list[Row]
    overlap: list[Row]
    notes: list[str] = field(default_factory=list)


def _get(http, path: str, params: dict[str, str]) -> tuple[int, dict]:
    response = http.get(f"{BASE}/{path}", source=SOURCE, ttl=TTL, params=params)
    return response.status, response.json()


def fetch_lookthrough(http, allocations: dict[str, float]) -> tuple[dict, list[str]]:
    """Ask for the whole portfolio; if it is too large, drop the largest fund files (sizes from the 400
    body) until the rest fits, and ask once more. Returns (answer, skipped tickers)."""

    def ask(funds: dict[str, float]) -> tuple[int, dict]:
        portfolio = ",".join(f"{t}:{a * 100:g}" for t, a in funds.items())
        return _get(http, "lookthrough", {"portfolio": portfolio, "top": "50"})

    status, body = ask(allocations)
    if status == 200:
        return body, []
    if status != 400 or body.get("reason") != "too_large":
        raise RuntimeError(f"lookthrough answered {status}: {body.get('message', body)}")
    sizes, limit = body["files"], body["limit"]["chars"]
    kept = dict(allocations)
    skipped = []
    for ticker in sorted(kept, key=lambda t: (-sizes.get(t, 0), t)):
        if sum(sizes.get(t, 0) for t in kept) <= limit or len(kept) == 1:
            break
        del kept[ticker]
        skipped.append(ticker)
    status, body = ask(kept)
    if status != 200:
        raise RuntimeError(f"lookthrough answered {status} without {skipped}: {body.get('message', body)}")
    return body, skipped


def compare(ours: AnalysisResponse, lookthrough: dict, skipped: list[str], overlap: dict,
            example: str = "") -> Report:
    funds = [e.ticker for e in ours.etfs if e.ticker not in skipped]
    by_symbol = {s: c for c in ours.exposures for s in c.symbols}
    scale = lookthrough["portfolio_value"] / 100  # their weight_pct is of the looked-through part
    their_dates = {**overlap.get("holdings_as_of", {}), **lookthrough.get("holdings_as_of", {})}
    report = Report(example=example, lookthrough_funds=funds, skipped_funds=skipped,
                    dates=[(e.ticker, str(e.as_of) if e.as_of else None, their_dates.get(e.ticker))
                           for e in ours.etfs],
                    exposures=[], coverage=[], overlap=[])
    stale = {t for t, a, b in report.dates if a and b and a != b}

    for company in lookthrough["companies"][:TOP]:
        ticker = company["ticker"]
        theirs = company["weight_pct"] * scale
        match = by_symbol.get(ticker)
        if match is None:
            report.exposures.append(Row(ticker, theirs, None, "not in our top companies (or keyed differently)"))
            continue
        ours_pct = 100 * sum(c.contribution for c in match.contributions if c.etf_ticker in funds)
        notes = []
        merged = [s for s in match.symbols if s != ticker]
        if merged:
            notes.append(f"we merge {'+'.join(sorted(match.symbols))} into one company ({match.company_key})")
        dated = sorted({c.etf_ticker for c in match.contributions if c.etf_ticker in stale})
        if dated:
            notes.append(f"holdings dates differ for {', '.join(dated)}")
        if not notes and abs(ours_pct - theirs) < ROUNDING_PP:
            notes.append("rounding")
        report.exposures.append(Row(ticker, theirs, ours_pct, "; ".join(notes)))

    cov = ours.coverage
    loaded = sum(e.allocation for e in ours.etfs if e.ticker in funds)
    covered_sub = sum(e.portfolio_covered_weight for e in ours.etfs if e.ticker in funds)
    report.coverage = [
        Row(f"share of {'+'.join(funds)} looked through (%)", lookthrough["looked_through_pct"],
            100 * covered_sub / loaded if loaded else None,
            "theirs counts every holdings line; we exclude cash, derivatives and FX"),
        Row("distinct companies (lookthrough funds)", lookthrough["distinct_companies"], None,
            "theirs counts tickers (GOOG and GOOGL are two); see ours below for the whole portfolio"),
        Row("our distinct companies / securities (whole portfolio)", None,
            ours.concentration.distinct_companies, f"{ours.concentration.distinct_securities} securities"),
        Row("our covered / excluded / missing (% of portfolio)", None, 100 * cov.covered_weight,
            f"excluded {100 * cov.excluded_weight:.4f}, missing {100 * cov.missing_allocation:.4f}, "
            f"unexplained {100 * cov.unexplained_weight:.4f}"),
    ]
    if lookthrough.get("top_10_weight_pct") is not None:
        ours_top10 = sorted((100 * sum(c.contribution for c in e.contributions if c.etf_ticker in funds)
                             for e in ours.exposures), reverse=True)[:10]
        report.coverage.append(Row("top-10 weight (% of the looked-through funds)", lookthrough["top_10_weight_pct"],
                                   sum(ours_top10) / scale if scale else None,
                                   "ours ranks merged companies, theirs ranks tickers"))

    pairs = {frozenset((p.etf_a, p.etf_b)): p for p in ours.overlap.pairs}
    theirs_pairs = overlap.get("pairs") or ([{"pair": overlap["pair"], **overlap["overlap"]}]
                                            if overlap.get("kind") == "pair" else [])
    for item in theirs_pairs:
        a, b = item["pair"]
        pair = pairs.get(frozenset((a, b)))
        if pair is None:
            report.overlap.append(Row(f"{a} / {b}", item.get("by_weight"), None, "pair not in our analysis"))
            continue
        notes = [(f"companies in both: theirs {item.get('companies_in_both')}, ours {pair.shared_companies} "
                 f"({pair.shared_securities} securities)"),
                 f"security level ours {100 * pair.weighted_overlap_securities:.2f}"]
        if {a, b} & stale:
            notes.append("holdings dates differ")
        report.overlap.append(Row(f"{a} / {b}", item.get("by_weight"), 100 * pair.weighted_overlap, "; ".join(notes)))

    report.notes = [
        ("Ours: fractions of the whole portfolio, never renormalised (cash and failed ETFs stay visible). "
        "Theirs: lookthrough weight_pct is of the funds looked through; scaled here by portfolio_value/100."),
        ("Overlap: both are the sum over shared holdings of the smaller weight. Ours merges share classes into "
        "companies (company level) and also gives the security level; theirs keys by ticker."),
    ]
    if skipped:
        report.notes.append(f"Lookthrough refused the whole portfolio (too large); {', '.join(skipped)} left out, "
                            "so exposures compare only the contributions of the other funds.")
    return report


def _fmt(value) -> str:
    if value is None:
        return "-"
    return f"{value:.4f}" if isinstance(value, float) else str(value)


def render(report: Report) -> str:
    out = [f"# V1 cross-check: {report.example or 'portfolio'} vs TickerInside", "",
           f"Lookthrough funds: {', '.join(report.lookthrough_funds)}"
           + (f" (left out: {', '.join(report.skipped_funds)})" if report.skipped_funds else ""), "",
           "## Holdings dates", "", "| ETF | ours | theirs |", "|---|---|---|"]
    out += [f"| {t} | {a or '-'} | {b or '-'} |" for t, a, b in report.dates]
    for title, rows, unit in (("Top exposures (% of portfolio)", report.exposures, "pp"),
                              ("Coverage", report.coverage, ""),
                              ("Pairwise overlap, by weight (%)", report.overlap, "pp")):
        out += ["", f"## {title}", "", f"| | theirs | ours | diff {unit} | why |", "|---|---:|---:|---:|---|"]
        out += [f"| {r.label} | {_fmt(r.theirs)} | {_fmt(r.ours)} | {_fmt(r.diff)} | {r.note} |" for r in rows]
    out += ["", "## Notes", ""] + [f"- {n}" for n in report.notes]
    out += ["", "Source: TickerInside (https://tickerinside.com/), CC BY 4.0. Measurement, not investment advice."]
    return "\n".join(out) + "\n"


def run(service, http, request, example: str = "") -> str:
    ours = service.analyse(request)
    lookthrough, skipped = fetch_lookthrough(http, {h.ticker: h.allocation for h in request.holdings})
    status, overlap = _get(http, "overlap", {"funds": ",".join(h.ticker for h in request.holdings)})
    if status != 200:
        raise RuntimeError(f"overlap answered {status}: {overlap.get('message', overlap)}")
    return render(compare(ours, lookthrough, skipped, overlap, example))


def main(argv: list[str] | None = None) -> int:
    from hoc.cli import build_request
    from hoc.config import Settings
    from hoc.core.cache import DiskCache
    from hoc.core.http import CachedHttpClient
    from hoc.service import EtfService

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--example", default="us-core-tilt")
    parser.add_argument("--output", help="also write the markdown table to this file")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    http = CachedHttpClient(settings, DiskCache(settings.cache_dir))
    text = run(EtfService.from_settings(settings), http, build_request(args.example, []), args.example)
    print(text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
