# Opt-in live smoke tests (T1)

From `backend/`:

```sh
HOC_LIVE=1 uv run pytest tests/live -m live -v
```

Without `HOC_LIVE=1`, the shared test setup skips every test here and blocks
external sockets. These tests use production `CachedHttpClient` / `DiskCache`;
core HTTP/cache must be implemented before running them live.

The cache defaults to `backend/.cache/` (gitignored). Set `HOC_LIVE_CACHE_DIR`
to an existing private cache directory to reuse another run's downloads. The
parent test fixture's temporary cache is deliberately overridden here so repeat
runs honour source TTLs. Never commit cache files or issuer downloads.

N-PORT additionally needs `HOC_SEC_CONTACT` set to the operator's real contact.
A missing contact skips only that case; transport, parsing and assertion failures
are failures. Its 180-day disclosure bound accommodates reporting lag, whereas
iShares must disclose within seven days. Reported raw weights allow five percent
for rounding and non-equity lines; the adapter must retain those lines for the
normaliser to exclude, rather than silently renormalising equity to 100 percent.

The offline test first warms IVV using the same cache, then sets `HOC_OFFLINE=1`
and recreates the client and adapter while socket connections fail immediately.
It compares holdings, disclosure and retrieval timestamps with the warmed data.

The iShares tests also run the real normaliser without optional reference
enrichment and verify cash/non-equity exclusions and preserved weights.
The example test calls EtfService.from_settings and checks complete loading,
coverage reconciliation and exposure totals. It needs package a reference data.
The TickerInside adapter smoke is added when package a lands. Their implementation stubs are not silently skipped by these tests.
