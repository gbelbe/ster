#!/usr/bin/env bash
# Claude Code PreToolUse hook — blocks git push when CI has not passed recently.
#
# Reads the tool call JSON from stdin.
# Exits 2 (blocking) when a git push is attempted without a fresh CI run.
# Exits 0 (allow) for all other commands.
#
# The sentinel file .ci-passed is written by scripts/ci.sh on success.
# It expires after 60 minutes to guard against stale results.

set -euo pipefail

INPUT=$(cat)
COMMAND=$(python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('command', ''))
except Exception:
    print('')
" <<< "$INPUT" 2>/dev/null || true)

# Only intercept git push commands
if ! printf '%s' "$COMMAND" | grep -qE '^\s*git\s+push'; then
    exit 0
fi

SENTINEL=".ci-passed"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SENTINEL_PATH="$ROOT/$SENTINEL"

if [[ ! -f "$SENTINEL_PATH" ]]; then
    cat >&2 <<'MSG'
╔══════════════════════════════════════════════════════════════╗
║  PUSH BLOCKED — CI has not been run                         ║
║                                                              ║
║  Run the local CI gate first:                               ║
║    /ci          (full: 3.11 / 3.12 / 3.13)                  ║
║    /ci --fast   (current Python only, quick check)          ║
║                                                              ║
║  Or directly:  bash scripts/ci.sh                           ║
╚══════════════════════════════════════════════════════════════╝
MSG
    exit 2
fi

# Check age using Python (cross-platform: works on macOS and Linux)
AGE=$(python3 -c "
import os, time, sys
mtime = os.path.getmtime('$SENTINEL_PATH')
print(int(time.time() - mtime))
" 2>/dev/null || echo 9999)

if [[ "$AGE" -gt 3600 ]]; then
    MINS=$(( AGE / 60 ))
    cat >&2 <<MSG
╔══════════════════════════════════════════════════════════════╗
║  PUSH BLOCKED — CI result is stale (${MINS} min ago)
║                                                              ║
║  Re-run the CI gate before pushing:                         ║
║    /ci          (full: 3.11 / 3.12 / 3.13)                  ║
║    /ci --fast   (current Python only, quick check)          ║
╚══════════════════════════════════════════════════════════════╝
MSG
    exit 2
fi

exit 0
