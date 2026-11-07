#!/usr/bin/env bash
# UserPromptSubmit: surface board posts that arrived since the last check. Silent when none. Never fails.
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0
# Same identity as the agent's own tools/board calls, so they share one read cursor consistently.
export BOARD_AGENT="${BOARD_AGENT:-Claude}"
out="$(tools/board unread 2>/dev/null)" || exit 0
[ -n "$out" ] && printf 'New board posts (issue #%s):\n%s\n' "${BOARD_ISSUE:-1}" "$out"
exit 0
