#!/usr/bin/env bash
# Tidy First ratchet — see CRAFTSMANSHIP.md for the catalog and commit
# convention this checks the discipline of, not the content of.
#
# Fails when the commit range has no tidy(<type>): commit, no
# test(characterize): commit (the legacy-code prerequisite move — see
# CRAFTSMANSHIP.md's "Working with legacy code"), and no Tidy-Exempt:
# trailer. This only checks the *discipline* of recording one of these (or
# an explicit exemption) as its own commit, separate from the feature/fix —
# it cannot judge whether the right tidying was picked, or whether a commit
# tagged tidy(...) actually preserved behavior. That's on the author/reviewer.
#
# Usage:
#   scripts/check_tidy_ratchet.sh --base <ref> [--head <ref>]
#
# Examples:
#   scripts/check_tidy_ratchet.sh --base origin/main
#   scripts/check_tidy_ratchet.sh --base origin/master --head HEAD
set -euo pipefail

BASE=""
HEAD="HEAD"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) BASE="$2"; shift 2 ;;
    --head) HEAD="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$BASE" ]]; then
  echo "usage: $0 --base <ref> [--head <ref>]" >&2
  exit 2
fi

if ! git rev-parse --verify --quiet "$BASE" >/dev/null; then
  echo "⚠ tidy ratchet: '$BASE' not found locally — skipping (git fetch it first)" >&2
  exit 0
fi

RANGE="${BASE}..${HEAD}"
COMMITS="$(git log --format='%s%n%b%n===' "$RANGE" 2>/dev/null || true)"

# Nothing in range (e.g. base == head, or an empty/no-op push) — nothing to check.
[[ -z "$COMMITS" ]] && exit 0

if echo "$COMMITS" | grep -qE '^(tidy\([a-z0-9-]+\):|test\(characterize\):|Tidy-Exempt:)'; then
  exit 0
fi

cat >&2 <<MSG
✗ Tidy First ratchet: no tidy(<type>): commit, no test(characterize): commit,
  and no Tidy-Exempt: trailer found in ${RANGE}.

  Before the feature/fix commit, tidy the code you're about to touch (see
  CRAFTSMANSHIP.md for the catalog) and commit it on its own:
    tidy(<type>): <what and where>

  Touching untested (legacy) code? Pin its current behavior first:
    test(characterize): <what behavior is pinned>

  If nothing genuinely needed tidying, commit with a one-line explanation
  instead of skipping silently:
    Tidy-Exempt: <reason>
MSG
exit 1
