# House of Cards backend

FastAPI service that fetches **real** ETF holdings, normalises them, resolves the same company across
ETFs, and computes look-through exposure, overlap and concentration with deterministic Python.
Contract and definitions: [`docs/hoc/CONTRACT.md`](../docs/hoc/CONTRACT.md). Plan: [`docs/hoc/PLAN.md`](../docs/hoc/PLAN.md).

## Run

Needs [uv](https://docs.astral.sh/uv/) (macOS: `brew install uv`; Windows: `winget install astral-sh.uv`).
uv installs Python 3.12 for you.

```bash
cd backend
uv sync                      # create .venv from uv.lock
uv run pytest                # offline tests (network is blocked in tests)
uv run uvicorn hoc.api.app:app --reload --host 127.0.0.1 --port 8000
```

Live smoke tests against the real sources: `HOC_LIVE=1 uv run pytest -m live`.
Configuration is via environment variables; see [`.env.example`](.env.example). No secrets are needed.
SEC EDGAR requires a contact in the User-Agent: set `HOC_SEC_CONTACT="Your Name you@example.com"`.

## Layout

| Path | Owner | Responsibility |
|---|---|---|
| `hoc/contract/` | lead (frozen) | Pydantic models, units, error codes: the only cross-layer import |
| `hoc/sources/base.py` | lead (frozen) | `SourceAdapter` / `ReferenceProvider` protocols |
| `hoc/sources/registry.py` | lead | Fallback order, records every attempt |
| `hoc/sources/tickerinside/`, `sec_nport/`, `ishares/` | a, b, c | One adapter per real source |
| `hoc/sources/fake.py` | lead | Synthetic fixtures for tests only |
| `hoc/core/` | d | Cached HTTP and disk cache (`.cache/`, gitignored) |
| `hoc/normalise/`, `hoc/identity/` | d | Raw -> normalised holdings, security/company identity |
| `hoc/portfolio/` | e | Pure maths: validation, exposure, overlap, concentration, sectors, coverage |
| `hoc/service.py`, `hoc/api/`, `hoc/examples.py`, `hoc/cli.py` | f | Wiring, HTTP routes, example portfolios, CLI |
| `hoc/graph/` | future | Corporate dependency graph plugs in after identity |

Data rules: no financial data is hardcoded or committed. Real holdings are fetched at runtime and
cached locally; synthetic data lives only in `tests/fixtures/synthetic/` and is labelled.
TickerInside data is CC BY 4.0: its `cite_as` attribution is carried through to the UI.
