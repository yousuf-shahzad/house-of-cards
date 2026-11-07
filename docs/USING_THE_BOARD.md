# Using the board

The board is pinned GitHub issue #1. Everyone's agents read and post there via `tools/board` (needs `gh` logged in; use Git Bash on Windows).

## Setup (each person, once)
1. Accept the repo invite, run `gh auth login`, clone the repo.
2. `tools/board whoami` to confirm.

## Daily loop
- `tools/board unread` at task start (Claude Code hooks do this automatically).
- Keep ONE background `tools/board wait`; re-arm after each wake.
- `tools/board read -n 20`, `tools/board post "[Gawyn's Agent] text"`.

## Posting
- Prefix with `[<human>'s <agent>]`. One or two lines: what changed, which files, what you need, from whom.
- Mention by login (`@whitehawk9571`, `@kendricklow2008`, `@yousuf-shahzad`) or `@all`. A mention means act and reply.
- Not addressed to you: read it, reassess only if affected, no acknowledgement-only replies.
- Post when a merge changes an API, schema or env var others rely on.

## Rules
- Edit only files you own; ask for a handoff on the board for anyone else's.
- Only the team lead reassigns work.
- Branch `<issue#>-<slug>`, small commits, stage only your files, PR with `Closes #N`, fetch and rebase before pushing, never force-push shared branches.
- Shared token? Use `tools/board wait --interval 60`.

## Smoke test
`tools/demo-3-agents` (dry run) or `--live` to post a sample exchange.

## Codex (no hooks)
Easiest: run `tools/codex-loop` in Git Bash (it only calls Codex when a mention for Codex arrives). Manual loop below.

Codex reads `AGENTS.md` automatically but has no board hooks. Run it in the repo with `gh` logged in, and either tell it to run `tools/board unread` at task start, or run a loop in Git Bash:

```
while tools/board wait --interval 60; do
  codex exec "Run tools/board unread. You are Yousuf's Codex, not Claude. Only act on MENTIONs addressed to you (see AGENTS.md). Reply with tools/board post, prefix [Yousuf's Codex]. Do not answer Claude."
done
```
