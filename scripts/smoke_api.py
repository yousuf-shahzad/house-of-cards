"""Smoke-check a running House of Cards API (standard library only).

    python scripts/smoke_api.py                       # http://127.0.0.1:8000
    python scripts/smoke_api.py --base http://host:8000 --timeout 90

Uses the first verified example portfolio and checks health, examples, analysis, compare, change ideas,
the failure simulator (POST /api/stress: sector, country, supplier, both portfolio sides) and the error
envelope. Prints one line per check; exit code 1 if any check fails. It only reads: no job is started.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable

Fetch = Callable[[str, str, dict | None], tuple[int, dict]]


def http_fetch(base: str, timeout: float) -> Fetch:
    def fetch(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(base.rstrip("/") + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    return fetch


def _loss_matches(side: dict, drop: float) -> bool:
    return abs(side["loss_fraction"] - side["affected_weight"] * drop) < 1e-6


def run_checks(fetch: Fetch) -> list[tuple[str, bool, str]]:
    """Each check is (name, passed, detail). Later checks are skipped (failed) if there's no example."""
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> bool:
        results.append((name, ok, detail))
        return ok

    status, body = fetch("GET", "/api/health", None)
    check("health", status == 200 and body.get("status") == "ok", f"HTTP {status}")

    status, body = fetch("GET", "/api/examples", None)
    verified = [e for e in body.get("examples", []) if e.get("verified")]
    if not check("examples", status == 200 and bool(verified), f"HTTP {status}, {len(verified)} verified"):
        return results
    holdings = [{"ticker": e["ticker"], "allocation": e["allocation"]} for e in verified[0]["holdings"]]
    other = verified[-1] if len(verified) > 1 else verified[0]
    candidate = [{"ticker": e["ticker"], "allocation": e["allocation"]} for e in other["holdings"]]

    status, body = fetch("POST", "/api/analysis", {"holdings": holdings})
    check("analysis", status == 200 and bool(body.get("exposures")), f"HTTP {status}")
    top_sector = max(body.get("sectors", []), key=lambda s: s.get("weight", 0), default={}).get("sector")
    country = next((c["country"] for c in body.get("exposures", []) if c.get("country")), "US")

    status, body = fetch("POST", "/api/compare", {"baseline": holdings, "candidate": candidate})
    check("compare", status == 200 and "concentration_deltas" in body, f"HTTP {status}")

    status, body = fetch("POST", "/api/change-ideas", {"holdings": holdings})
    check("change-ideas", status == 200 and "ideas" in body, f"HTTP {status}, {len(body.get('ideas', []))} ideas")

    shocks = [("stress sector", {"kind": "sector", "key": top_sector or "information_technology"}),
              ("stress country", {"kind": "country", "key": country}),
              ("stress supplier", {"kind": "supplier", "key": "ALIAS:TSMC", "label": "TSMC"})]
    for name, shock in shocks:
        request = {"baseline": holdings, "candidate": candidate, "shock": shock}
        if shock["kind"] == "supplier":
            request["company_keys"] = ["CIK:0001045810", "CIK:0000320193"]
        status, body = fetch("POST", "/api/stress", request)
        ok = status == 200 and body.get("candidate") is not None
        if ok:
            drop = body["basis"]["drop"]
            ok = 0 < drop <= 1 and _loss_matches(body["baseline"], drop) and _loss_matches(body["candidate"], drop)
            if shock["kind"] == "supplier":
                ok = ok and body["basis"]["source"] == "simulated"
        basis = body.get("basis", {})
        check(name, ok, f"HTTP {status}, {shock['key']}: {basis.get('source')} {basis.get('drop')} "
                        f"{basis.get('proxy') or ''}, loss {body.get('baseline', {}).get('loss_fraction')}")

    status, body = fetch("POST", "/api/stress", {"baseline": [{"ticker": "ZZZZQ", "allocation": 1}],
                                                 "shock": {"kind": "sector", "key": "energy"}})
    check("stress unknown ticker", status == 422 and body.get("error", {}).get("code") == "UNKNOWN_TICKER",
          f"HTTP {status}")
    status, body = fetch("GET", "/api/no-such-route", None)
    check("error envelope", status == 404 and body.get("error", {}).get("code") == "NOT_FOUND", f"HTTP {status}")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)
    results = run_checks(http_fetch(args.base, args.timeout))
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:22} {detail}")
    failed = sum(not ok for _, ok, _ in results)
    print(f"{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
