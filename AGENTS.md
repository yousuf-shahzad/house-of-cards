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

Fill this in at kickoff so every agent knows whose files are whose.

| Area | Owner (GitHub login) | Folders |
|---|---|---|
| | | |
