# House of Cards frontend

The UI for House of Cards: enter ETF tickers and allocations, and see the companies you really own. Built on [telos-boardui](https://github.com/yousuf-shahzad/telos-boardui) (React 19, TypeScript, Tailwind v4, [Board UI](https://www.boardui.com) components). Plan and rules: [`docs/hoc/PLAN.md`](../docs/hoc/PLAN.md).

## Run

Needs Node.js 22.12 or newer.

```sh
npm ci
npm run dev     # proxies the backend routes to 127.0.0.1:8000
npm run build   # type-checks and builds; must pass before merging
```

To build a page before the backend exists, use mock mode. It serves a synthetic fixture and shows a SYNTHETIC banner, and it is off by default:

```sh
VITE_API_MOCK=1 npm run dev                     # Git Bash, macOS, Linux
$env:VITE_API_MOCK = "1"; npm run dev           # PowerShell
```

## Adding to a page

Edit only your own folder, `app/pages/<key>/`. Its `index.tsx` default-exports the page, and `app/registry.tsx` (frozen) already lists it.

```tsx
import { useAnalysis } from "@/app/analysis";

export default function ExposuresPage() {
  const { analysis, status, stale, error, retry } = useAnalysis();
  // ...
}
```

| `status` | Meaning |
|---|---|
| `invalid` | The rows can't be sent yet; see `validation.issues`. No request is made. |
| `loading` | Waiting out the 400 ms debounce, or a request is in flight. |
| `ready` | `analysis` matches the current rows. |
| `error` | `error` is an `ApiError` with `code`, `message`, `status` and `details`. Offer `retry()`. |

`analysis` keeps the last good result while a newer one loads or fails, and `stale` is true when it no longer matches the rows. Dim it or label it rather than showing it as current.

## Rules

- **Fractions and percent:** API values are fractions of 1. Show them with `<Pct value={0.1234} />` or `formatPct`. Only `api/client.ts` converts input percent to a fraction.
- **Shared UI:** `app/ui/` has `Pct`, `EtfChip` and `AsOfBadge`.
- **Design:** follow the Board UI rules in [`AGENTS.md`](AGENTS.md).
- **Dependencies:** no new npm packages without asking Yousuf's Claude, who owns `package.json` and the lockfile.
- **Frozen files:** `api/types.ts` and `app/registry.tsx` change only through the lead.
- **New backend routes:** the Vite proxy lists routes explicitly, because a bare `/api` would also catch source files in `./api/`. Add any new top-level route to `vite.config.ts`.

## What's still here from TELOS

The app starts at `app/main.tsx`, so the old `main.tsx` and `suite/` are unrouted and not in the bundle. That includes the scripted assistant (`suite/assistant.tsx`) and sample data (`suite/model.ts`). Don't route them back: judges mark down mocked UIs.
