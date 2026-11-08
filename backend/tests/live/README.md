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
coverage reconciliation and exposure totals. It uses the production TickerInside reference data.
The TickerInside XLK smoke checks disclosure freshness, attribution/licence,
reference identifiers, sector weights and derivative exclusion. Source failures
are not silently skipped by these tests.

## v3 cache-only replay

After warming the demo's holdings, filings and dependency extraction cache, run:

```sh
HOC_LIVE=1 HOC_LIVE_CACHE_DIR=/path/to/backend/.cache uv run pytest tests/live/test_v3_cache.py -v
```

These two tests force offline reads (including expired HTTP cache entries), remove
Gemini keys, and fail on any attempted Gemini call or external socket connection.
A cache miss fails visibly; these tests never warm the cache or spend Gemini quota.
`HOC_LIVE_CACHE_DIR` defaults to this checkout's `backend/.cache`, so a separate
worktree usually needs the original checkout's cache path. No cache data is committed.
The filings reader requires a contact string even offline; if `HOC_SEC_CONTACT`
is absent, these tests use an offline-only placeholder that cannot reach the network.

The Compare test checks that swapping the us-core-tilt allocations for IVV 40%,
QQQ 10%, VTV 30%, EEM 20% lowers `dep.ALIAS:TSMC`, with a consistent negative delta.
The dependency replay checks that all 15 company runs finish with cached or known
unavailable-filing statuses, every returned edge has importance and interpretation,
flagged edges are capped at medium, and all five coverage buckets sum to one
within 1e-6. Empty or incomplete caches fail instead of passing vacuously.
Exact edge counts and exposure percentages are not pinned because cache contents
and holdings dates differ between operators. JUnit properties record the observed
TSMC values, edge count and coverage total when `--junitxml=...` is supplied.
