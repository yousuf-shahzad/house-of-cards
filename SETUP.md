# Setup notes

Repo setup log for the hackathon, done 2026-11-06.

## Done

- Repo comes from the agent-board template (`README.md`, `AGENTS.md`, `tools/board`, `.claude/` hooks).
- `gh` is logged in as `yousuf-shahzad`. `origin` is `yousuf-shahzad/hackathon-test`.
- Created the `board` label (it did not exist in the repo).
- Created issue **#1 "Message Board"** from `.github/ISSUE_TEMPLATE/message-board.md` and pinned it. It is #1, so `BOARD_ISSUE` needs no override.
- Posted a first message and confirmed `tools/board post` and `read` work.

## Still to do (needs the team)

1. **Team logins in `AGENTS.md`**: the `@login1..4` placeholders are unfilled. Add the real GitHub logins and names.
2. **Owner table in `AGENTS.md`**: empty. Fill it in at kickoff (area, owner login, folders).
3. **Invite teammates** as collaborators on the repo (Settings > Collaborators).
4. **Each teammate** runs `gh auth login`, then `tools/board whoami`.
5. **Team lead**: not yet named. Only the lead reassigns work (`AGENTS.md` section 2).

## Gotchas

- The `SessionStart` hook printed "board unreachable" before the issue existed. That is expected on a fresh repo, so run `tools/board unread` again.
- In Claude Code, keep one background `tools/board wait` running and re-arm it after each wake.
- `.board/` holds local read cursors and is gitignored. Do not commit it.
- On Windows, run `tools/board` through Git Bash. The hooks are `.sh` files.
- With many agents on one account, use `tools/board wait --interval 60` to stay under the GitHub rate limit.
- Workflow reminder: branch `<issue#>-<slug>`, stage only your own files, PR with `Closes #N`, and `git fetch` and rebase before pushing.
