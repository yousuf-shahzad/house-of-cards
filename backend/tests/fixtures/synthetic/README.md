# SYNTHETIC TEST DATA: NOT REAL HOLDINGS

Everything in this folder is invented for automated tests. None of it describes a real fund,
company or security, and none of it may be used as application data.

- ETF tickers and company symbols start with `ZZ` (or use the fictional `9999.TW` listing).
- CIKs start with `999`, LEIs with `9999`, ISINs with `ZZ`: they cannot collide with real ones.
- `source` is always `"fake"`.

| File | What it exercises |
|---|---|
| `raw/ZZAAA.json` | Two share classes of one company (ZZBET.A / ZZBET.B, same CIK), a cash line, fresh issuer date |
| `raw/ZZBBB.json` | A futures line (derivative), an unmatched name-only line, a stale N-PORT-style date, a fund-reported sector breakdown |
| `raw/ZZCCC.json` | An ADR-style alias pair (ZZEPS here vs local `9999.TW` in ZZBBB), an ISIN-only line, a duplicate line to merge |
| `reference.json` | Synthetic reference data (names, CIKs, sectors) for the symbols above |

Real holdings are fetched at runtime by the source adapters and cached in the gitignored `backend/.cache/`.
