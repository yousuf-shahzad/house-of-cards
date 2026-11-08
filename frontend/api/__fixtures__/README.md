# SYNTHETIC mock data: not real holdings

`synthetic-analysis.json` is an invented `AnalysisResponse` (ETFs `ZZAAA` 60% / `ZZBBB` 40%, companies
prefixed `ZZ`, `source: "fake"`) so the views can be built before the backend is running.

- It is served only when `VITE_API_MOCK=1`, and the UI must then show a visible **SYNTHETIC** banner
  (also whenever any ETF's `source` is `"fake"`).
- Its numbers reconcile (exposures sum to covered weight, contributions sum to exposure, etc.); the
  backend test `tests/test_contract.py::test_frontend_mock_fixture_matches_contract_and_reconciles`
  keeps it valid against the contract.
- Never use it as application data. Real numbers always come from `POST /api/analysis`.

## v2 mocks

- `synthetic-valuation.json`: a `ValuationResponse` (ZZAAA 100 sh, ZZBBB 40 sh with a stale price, ZZCCC pinned 20%).
- `synthetic-dependencies.json`: a finished `DependencyJob` (ZZ Alpha / ZZ Beta 10-Ks naming ZZ Epsilon as foundry, a Taiwan facility, an unnamed customer, metrics and insights).

Both are synthetic (`source: "fake"`, `example.invalid` URLs) and are validated by `backend/tests/test_contract_v2.py`.
