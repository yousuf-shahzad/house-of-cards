# Free Vercel deployment

The repository-root `vercel.json` builds the Vite frontend and FastAPI backend as
one Vercel Services project (currently beta). `/api/*` stays on the backend; the
root selects the frontend's `index.html`. Local `uvicorn hoc.api.app:app` and Vite
development retain the existing behavior.

## Project settings

- Import `yousuf-shahzad/hackathon-test` with repository root `.` and production
  branch `main`. Keep the Hobby plan; do not enable a Pro trial or paid resources.
- Use the root Services configuration, not a frontend-only Root Directory.
- Create one **private** Blob store and connect it to Production and Preview.
  Vercel supplies its storage credentials; never put them in source or client JS.
- A human adds `GEMINI_API_KEY` and `HOC_SEC_CONTACT` to the Vercel environment
  settings. The SEC contact identifies the app to EDGAR, for example
  `House of Cards contact@example.com`. Redeploy after setting them.
- Keep `VITE_API_MOCK` unset. A live deployment must not silently serve fixtures.
- `/api/health` is the health endpoint. Test a real portfolio, dependency scan,
  research follow-up, comparison, change ideas, and a simulator shock after deploy.

Hobby is for personal, non-commercial use and has usage limits. Hosting does not
include unlimited Gemini calls. The app uses the existing provider key/credits.
If free quotas are exhausted, availability can stop; this setup does not upgrade
the plan automatically.

## Serverless execution

`vercel_app.py` creates the regular API with startup warm-up disabled. Its service
subclass swaps scheduling and storage, preserving the public API contracts:

1. The submit route records a private, deterministic job pointer and publishes an
   opaque run reference to Vercel Queues. Identical submissions reuse the pointer.
2. A dispatch task queues one company task per selected holding. Each task awaits
   filing extraction and bounded company research before returning. There is no
   detached research thread after the function response.
3. Company checkpoints are independent immutable objects. Retried completed tasks
   reuse them. A serialized progress consumer updates the shared polling snapshot.
4. A final task resolves/merges links, scores them, computes the existing metrics
   and coverage, and runs synthesis. Additional research and AI change ideas also
   run as queued tasks.
5. A fresh API instance can read progress and finished results from Blob. A stale
   run becomes an explicit error after 30 minutes; retry creates a new generation
   and reuses underlying extraction caches. Queue delivery is at least once,
   rather than an exactly-once execution guarantee.

The Python service **must use `entrypoint: pyproject.toml`**. This makes the Python
builder discover both `[tool.vercel].entrypoint` and `[[tool.vercel.subscribers]]`
in a Services project. Selecting the web `.py` file directly builds only the API,
without the private queue subscriber. Confirm the queue-triggered function appears
in deployment output and that a submitted job reaches a terminal state.

Workers use a 180-second external-request budget and cap individual HTTP calls at
45 seconds, inside the Hobby function duration configured as 300 seconds. Provider
failures retain the pipeline's explicit missing/partial/error behavior. These
budgets are deployment-specific; the local runtime keeps its existing timeouts.

## Shared cache and free-quota usage

`HOC_CACHE_BACKEND=vercel` enables compressed private Blob cache objects. `/tmp`
is a disposable local accelerator. The local cache's metadata, source dates,
keys and verified-edge validation remain authoritative; remote data is not
renormalized or fabricated. Preview and production use separate prefixes.

Normalized ETF snapshots are shared for up to 24 hours and keyed by code revision,
ticker and source order. This avoids repeating identity/sector normalization on
each new function instance. Small per-security TickerInside HTTP files and raw
Gemini HTTP responses stay local: normalized holdings and typed AI caches already
preserve the useful results, without consuming thousands of duplicate Blob writes.
Extraction listings have a five-second in-memory TTL, invalidated by local writes.

Hobby Blob operation/storage allowances are finite. Periodically remove old
deployment/run prefixes from the private store after they are no longer needed.
Job messages expire after an hour; stored checkpoints are not automatically
deleted by queue expiration. Keep watch on the Vercel usage dashboard during demos.

## Verification

```powershell
cd backend
uv sync --extra vercel
uv run pytest tests/deployment tests/core tests/portfolio tests/api
```

The deployment tests use fake storage and a fake publisher, create fresh worker
objects for deliveries, compare final results with the existing local pipeline,
and exercise duplicate deliveries, interrupted publication, missing filings,
expiry/retry, private cache bytes and listing invalidation. They do not use a live
Gemini key or make network calls.

CLI deployment (Vercel CLI 65.12.1 was used for setup):

```powershell
vercel link --project house-of-cards --scope yousuf-shahzads-projects
vercel pull --environment preview
vercel deploy
# After verifying the preview and merging the PR:
vercel deploy --prod
```

Git integration should deploy `main` to production and create previews for feature
branches. Keep `.vercel/`, local environment files and tool installations ignored.

Official references: [Services](https://vercel.com/docs/services),
[FastAPI](https://vercel.com/docs/frameworks/backend/fastapi),
[Python Queues](https://vercel.com/docs/queues/python-sdk),
[private Blob](https://vercel.com/docs/vercel-blob/private-storage),
[Hobby limits](https://vercel.com/docs/plans/hobby).
