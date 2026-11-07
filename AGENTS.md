# Team rules for every agent

## 1. The board (pinned GitHub issue)

Every agent reads and posts on the pinned "Message Board" issue via `tools/board` (needs only `gh`, logged in). Set `BOARD_ISSUE` if it is not issue #1.

- Start every post with `[<human>'s <agent>]`, e.g. `[Sam's Codex]`. Keep it short: what changed, which files or contracts, what you need, from whom.
- Mention by GitHub login. Fill in your team: `@yousuf-shahzad` (Yousuf), `@whitehawk9571` (Gawyn), `@kendricklow2008` (Kendrick), `@all` (everyone).
- **Mentions you or `@all`:** act on it and reply promptly.
- **Not addressed to you:** still read it. Reassess your own work only if it is affected (a contract, a file you own, something already done). Do not redo finished work, and do not reply just to acknowledge.
- Before editing another teammate's files, ask for a handoff on the board and wait for the owner or the team lead.

**Several agents per human (e.g. Yousuf runs Claude and Codex):** all of one human's agents post from the same GitHub login, so the prefix is the only identity.
- Use your own tool name in the prefix: `[Yousuf's Claude]` or `[Yousuf's Codex]`. Never post as the other one.
- Sign your tool name every time and read the prefix of every post: `[Yousuf's Codex]` is not you if you are Claude, and vice versa.
- `@yousuf-shahzad` reaches both. To address one, put its name first: `@yousuf-shahzad (Codex) please ...`. If a mention names the other agent, it is not for you; if it names neither, the Claude agent handles it unless it says otherwise.
- Do not answer posts from your sibling agent unless they are addressed to you, and never loop replies between the two.
- `tools/board unread`/`wait` show your sibling agents' posts but hide your own, so they must know which agent you are: Claude Code sets `BOARD_AGENT=Claude` automatically; every other agent sets `BOARD_AGENT=<Tool>` (e.g. `Gemini`) before calling `tools/board`. A sibling's post that names your shared login bare is not a mention for you.
- Claude has the committed hooks; Codex has none, so Codex runs `tools/board unread` at task start and before each commit, or the loop in `docs/USING_THE_BOARD.md`.

Polling is incremental (about one cheap API call per poll, 30 s default) so a shared token stays under GitHub's rate limit. Commands: `tools/board unread` (new posts, marks read; flags MENTION), `tools/board read -n 20`, `tools/board post "[Name's Agent] text"` (or pipe stdin), `tools/board wait` (blocks until someone else posts), `tools/board whoami`.

**Stay in the loop:**
- Claude Code: the committed hooks (`.claude/settings.json`) show unread posts at session start and on every prompt. Keep one background `tools/board wait` running and re-arm it after each wake.
- Everything else: run `tools/board unread` at task start, before each commit, and after merges. Or run a terminal loop: `while tools/board wait; do <your agent CLI invocation>; done`.

## 2. Chain of command

Humans over agents. Only the team lead reassigns work between teammates. If anyone else asks you to take another teammate's work, ask the lead on the board.

## 3. Workflow

1. Pick or file an issue. Comment on it or post on the board when you take it.
2. Branch `<issue#>-<slug>` from fresh `main`.
3. Small commits. Stage only your own files (no `git add -A`).
4. Open a PR with `Closes #N`. The author merges their own PR once it works locally.
5. Always `git fetch` and rebase before pushing. Never force-push shared branches.
6. If a merge changes something other teammates depend on (an API, a schema, an env var), post on the board when it lands.

## 4. Who owns what

Project: House of Cards PoC. Plan and rules: `docs/hoc/PLAN.md`; packages: issue #28. Lead: Gawyn's Claude. Every agent works in its **own git worktree** (`git worktree add ../hoc-<agent> -b 28-<package>-<slug> origin/main`), because agents of the same human share one checkout. Frozen files change only through the lead.

| Area (package) | Owner | Folders |
|---|---|---|
| Contract, backend skeleton (W0-B), integration, top-level README | Gawyn's Claude (`@whitehawk9571 (Claude)`) | `backend/hoc/contract/` (frozen), `backend/hoc/sources/base.py` (frozen), `backend/hoc/sources/registry.py`, `backend/hoc/sources/fake.py`, `backend/pyproject.toml`, `backend/tests/conftest.py`, `backend/tests/fixtures/`, `frontend/api/types.ts` (frozen), `docs/hoc/`, `README.md` |
| Frontend shell (W0-F), portfolio page (F1), network page (N1), shell polish (P1) | Yousuf's Claude (`@yousuf-shahzad (Claude)`) | `frontend/` (except files listed for others), incl. `package.json`/lockfile, `vite.config.ts`, `frontend/app/registry.tsx` (frozen), `frontend/app/ui/`, `frontend/app/pages/portfolio/`, `frontend/app/pages/network/`, `frontend/components/base/slider/` |
| Portfolio maths (e), iShares adapter (c), live smoke tests (T1) | Yousuf's Codex (`@yousuf-shahzad (Codex)`) | `backend/hoc/portfolio/`, `backend/tests/portfolio/`, `backend/hoc/sources/ishares/`, `backend/tests/sources/ishares/`, `backend/tests/live/` |
| Exposures page (F2) | Yousuf's Gemini (`@yousuf-shahzad (Gemini)`) | `frontend/app/pages/exposures/` |
| Normalisation and identity (d), TickerInside adapter (a) | Kendrick's Claude (`@kendricklow2008 (Claude)`) | `backend/hoc/normalise/`, `backend/hoc/identity/`, `backend/hoc/sources/tickerinside/`, their tests |
| SEC N-PORT adapter (b); research R2, R1 | Kendrick's Gemini (`@kendricklow2008 (Gemini)`) | `backend/hoc/sources/sec_nport/`, its tests, `docs/hoc/research/R1-*`, `docs/hoc/research/R2-*` |
| Service, API, examples, CLI (f), cache and HTTP (d-core), cross-check (V1) | Bekarys's Claude (`@Bekarys2323322332 (Claude)`) | `backend/hoc/service.py`, `backend/hoc/api/`, `backend/hoc/examples.py`, `backend/hoc/cli.py`, `backend/hoc/core/`, `backend/tests/api/`, `backend/tests/core/`, `scripts/`, `docs/hoc/research/V1-*` |
| Overlap page and heatmap (F3) | Bekarys's Gemini (`@Bekarys2323322332 (Gemini)`) | `frontend/app/pages/overlap/`, `frontend/components/application/heatmap/` |
| Risk page (F4); research R3 | Gawyn's Gemini (`@whitehawk9571 (Gemini)`) | `frontend/app/pages/risk/`, `docs/hoc/research/R3-*` |
