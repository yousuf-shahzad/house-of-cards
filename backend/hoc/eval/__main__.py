"""CLI entry point: `python -m hoc.eval [--live|--replay]`."""

from __future__ import annotations

import sys

from hoc.eval.runner import run_eval_cli

if __name__ == "__main__":
    sys.exit(run_eval_cli())
