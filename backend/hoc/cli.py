"""Command line: `python -m hoc.cli analyse --example us-core-tilt` / `analyse IVV=40 QQQ=60` / `warm`.

Owner: package f (Bekarys's Claude). Prints the analysis summary (top exposures, coverage, sources).
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hoc", description="House of Cards ETF look-through")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("analyse", help="analyse an example or TICKER=percent pairs")
    run.add_argument("--example", help="example id, e.g. us-core-tilt")
    run.add_argument("pairs", nargs="*", help="TICKER=percent, e.g. IVV=40 QQQ=60")
    run.add_argument("--json", action="store_true", help="print the full AnalysisResponse JSON")
    warm = sub.add_parser("warm", help="prefetch reference data and example ETFs into the cache")
    warm.add_argument("--example", default="us-core-tilt")
    parser.parse_args(argv)
    raise NotImplementedError("package f: hoc.cli")


if __name__ == "__main__":
    sys.exit(main())
