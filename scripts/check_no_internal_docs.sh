#!/usr/bin/env bash
# Guard against leaking internal/private docs into the public mirror.
#
# This project is developed in a private repository and mirrored to a public
# one. Anything tracked on `main` reaches the public repo, so internal-only
# material must never be committed there. This check fails the build if it
# finds any:
#
#   1. tracked file under an internal-only path   (docs/internal/, *.internal.md)
#   2. tracked file carrying the internal marker  (STER-INTERNAL-ONLY)
#
# Keep internal docs in docs/internal/ (gitignored) or on a private-only branch
# that is never pushed to the public remote.

set -euo pipefail

MARKER="STER-INTERNAL-ONLY"
status=0

# 1. No tracked files under internal-only paths.
internal_paths="$(git ls-files 'docs/internal/**' '**/*.internal.md' || true)"
if [ -n "$internal_paths" ]; then
  echo "::error::Internal-only files are tracked (must stay local / private-branch only):"
  echo "$internal_paths" | sed 's/^/  - /'
  status=1
fi

# 2. No tracked file carries the internal marker.
#    The allowlist holds files that legitimately *mention* the marker (this
#    script and the contribution guide), so they don't flag themselves.
marked="$(git grep -lIF "$MARKER" -- . \
  ':(exclude)scripts/check_no_internal_docs.sh' \
  ':(exclude)CONTRIBUTING.md' || true)"
if [ -n "$marked" ]; then
  echo "::error::Files marked ${MARKER} are tracked (must not reach the public mirror):"
  echo "$marked" | sed 's/^/  - /'
  status=1
fi

if [ "$status" -eq 0 ]; then
  echo "Leak scan: OK — no internal-only docs are tracked."
else
  echo ""
  echo "Move the offending content to docs/internal/ (gitignored) or a private-only branch."
fi
exit "$status"
