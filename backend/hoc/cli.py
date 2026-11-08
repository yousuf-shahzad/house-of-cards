"""Command line: `python -m hoc.cli analyse --example us-core-tilt` / `analyse IVV=40 QQQ=60` / `warm`.

Owner: package f (Bekarys's Claude). Prints the analysis summary (top exposures, coverage, sources).
"""

from __future__ import annotations

import argparse
import sys

from hoc.config import Settings
from hoc.contract import AnalysisResponse, EtfHoldings, HocError, PortfolioItem, PortfolioRequest, Sector
from hoc.examples import EXAMPLES
from hoc.service import EtfService


def pct(weight: float) -> str:
    return f"{weight * 100:.2f}%"


def find_example(example_id: str):
    for example in EXAMPLES:
        if example.id == example_id:
            return example
    raise ValueError(f"unknown example {example_id!r}; choose from {', '.join(e.id for e in EXAMPLES)}")


def build_request(example_id: str | None, pairs: list[str]) -> PortfolioRequest:
    """--example, or TICKER=percent pairs (the CLI is a user-input boundary, so percent -> fraction here)."""
    if bool(example_id) == bool(pairs):
        raise ValueError("give either --example or TICKER=percent pairs, not both or neither")
    if example_id:
        items = find_example(example_id).holdings
    else:
        items = []
        for pair in pairs:
            ticker, sep, percent = pair.partition("=")
            try:
                if not sep or not ticker:
                    raise ValueError
                items.append((ticker, float(percent) / 100))
            except ValueError:
                raise ValueError(f"bad pair {pair!r}; expected TICKER=percent, e.g. IVV=40") from None
    return PortfolioRequest(holdings=[PortfolioItem(ticker=t, allocation=a) for t, a in items])


def summary(result: AnalysisResponse, top: int = 20) -> str:
    cov = result.coverage
    lines = [f"House of Cards analysis (as of {result.as_of_date}, method {result.method_version})", "",
             "ETFs:"]
    for etf in result.etfs:
        lines.append(f"  {etf.ticker:<8} {pct(etf.allocation):>8}  {etf.status:<11} {etf.source or '-':<12} "
                     f"as of {etf.as_of or '-'}  {etf.holdings_count} holdings")
    lines += ["", (f"Coverage: covered {pct(cov.covered_weight)}, excluded {pct(cov.excluded_weight)}, "
                  f"missing {pct(cov.missing_allocation)}, unexplained {pct(cov.unexplained_weight)}"), "",
              f"Top {min(top, len(result.exposures))} company exposures:"]
    for exp in result.exposures[:top]:
        lines.append(f"  {exp.rank:>3}. {exp.company_name[:40]:<40} {pct(exp.exposure):>8}  in {exp.etf_count} ETF(s)")
    con = result.concentration
    lines += ["", (f"Concentration: top10 {pct(con.top10)}, HHI {con.hhi:.4f}, "
                  f"effective companies {con.effective_companies:.1f}, {con.distinct_companies} companies")]
    if result.gaps:
        lines += ["", f"Data gaps ({len(result.gaps)}):"]
        lines += [f"  [{gap.severity}] {gap.message}" for gap in result.gaps]
    if result.attributions:
        lines += ["", "Sources:"] + [f"  {a.text}" for a in result.attributions]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hoc", description="House of Cards ETF look-through")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("analyse", help="analyse an example or TICKER=percent pairs")
    run.add_argument("--example", help="example id, e.g. us-core-tilt")
    run.add_argument("pairs", nargs="*", help="TICKER=percent, e.g. IVV=40 QQQ=60")
    run.add_argument("--json", action="store_true", help="print the full AnalysisResponse JSON")
    warm = sub.add_parser("warm", help="prefetch reference data and example ETFs into the cache")
    warm.add_argument("--example", default="us-core-tilt")
    from hoc.eval import build_eval_arg_parser, run_eval_from_args

    build_eval_arg_parser(sub.add_parser(
        "eval", help="score dependency extraction against the held-out answer key (offline replay by default)",
        description="House of Cards v3 unseen-data evaluation (E-RUN). --replay (default) scores the recorded "
                    "predictions offline with no network or Gemini calls; --live re-extracts the 10 held-out "
                    "10-Ks (needs GEMINI_API_KEY and HOC_SEC_CONTACT) and records them."))
    args = parser.parse_args(argv)
    if args.command == "eval":
        return run_eval_from_args(args)

    try:
        if args.command == "warm":
            tickers = [ticker for ticker, _ in find_example(args.example).holdings]
        else:
            request = build_request(args.example, args.pairs)
    except ValueError as exc:
        parser.error(str(exc))

    service = EtfService.from_settings(Settings.from_env())
    if args.command == "warm":
        # Loading an ETF fetches its holdings, the reference files and per-stock sector data, all cached.
        failed = 0
        for ticker, etf in service._load_many(tickers).items():
            if isinstance(etf, EtfHoldings):
                known = sum(h.weight for h in etf.holdings if h.sector != Sector.unknown)
                print(f"{ticker:<8} ok    {etf.source} as of {etf.as_of}, {len(etf.holdings)} holdings, "
                      f"company sectors for {pct(known)} of weight (basis {etf.sector_basis})")
            else:
                failed += 1
                print(f"{ticker:<8} {etf.status}  {etf.message}")
        return 1 if failed else 0

    try:
        result = service.analyse(request)
    except HocError as exc:
        print(f"error {exc.code}: {exc.message}", file=sys.stderr)
        return 1
    print(result.model_dump_json(indent=2) if args.json else summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
