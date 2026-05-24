#!/usr/bin/env bash
# Git pre-push hook — blocks push when CI has not passed recently.
#
# Install once after cloning:
#   bash scripts/install-hooks.sh
#
# The sentinel file .ci-passed is written by scripts/ci.sh on success.
# It expires after 60 minutes.

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
SENTINEL="$ROOT/.ci-passed"

if [[ ! -f "$SENTINEL" ]]; then
    cat >&2 <<'MSG'
╔══════════════════════════════════════════════════════════════╗
║  PUSH BLOCKED — CI has not been run                         ║
║                                                              ║
║  Run the local CI gate first:                               ║
║    bash scripts/ci.sh           (full: 3.11 / 3.12 / 3.13)  ║
║    bash scripts/ci.sh --fast    (current Python only)        ║
╚══════════════════════════════════════════════════════════════╝
MSG
    exit 1
fi

AGE=$(python3 -c "
import os, time
mtime = os.path.getmtime('$SENTINEL')
print(int(time.time() - mtime))
" 2>/dev/null || echo 9999)

if [[ "$AGE" -gt 3600 ]]; then
    MINS=$(( AGE / 60 ))
    cat >&2 <<MSG
╔══════════════════════════════════════════════════════════════╗
║  PUSH BLOCKED — CI result is stale (${MINS} min ago)
║                                                              ║
║  Re-run the CI gate before pushing:                         ║
║    bash scripts/ci.sh           (full: 3.11 / 3.12 / 3.13)  ║
║    bash scripts/ci.sh --fast    (current Python only)        ║
╚══════════════════════════════════════════════════════════════╝
MSG
    exit 1
fi

exit 0
