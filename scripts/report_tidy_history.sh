#!/usr/bin/env bash
# Report on this repo's Tidy First / craftsmanship commit history.
# See CRAFTSMANSHIP.md's "Don't let the exemption become the rule" — run
# this periodically, don't just trust the ratchet exists.
#
# Usage: scripts/report_tidy_history.sh
set -euo pipefail

TIDY_COUNT=$(git log --grep='^tidy(' --oneline | wc -l | tr -d ' ')
CHAR_COUNT=$(git log --grep='^test(characterize):' --oneline | wc -l | tr -d ' ')
EXEMPT_COUNT=$(git log --grep='^Tidy-Exempt:' --oneline | wc -l | tr -d ' ')

echo "── Tidy First discipline ──────────────────────────────"
echo "tidy(...) commits:           $TIDY_COUNT"
echo "test(characterize) commits:  $CHAR_COUNT"
echo "Tidy-Exempt: commits:        $EXEMPT_COUNT"
if [[ $((TIDY_COUNT + CHAR_COUNT + EXEMPT_COUNT)) -gt 0 ]]; then
  TOTAL=$((TIDY_COUNT + CHAR_COUNT + EXEMPT_COUNT))
  EXEMPT_PCT=$((EXEMPT_COUNT * 100 / TOTAL))
  echo "exemption rate:              ${EXEMPT_PCT}%"
  if [[ $EXEMPT_PCT -gt 40 ]]; then
    echo "  ⚠ exemptions are a large share — worth asking why, per"
    echo "    CRAFTSMANSHIP.md's 'Don't let the exemption become the rule'"
  fi
fi

echo
echo "── Tidyings by type ────────────────────────────────────"
git log --pretty=format:'%s' --grep='^tidy(' \
  | sed -E 's/^tidy\(([a-z0-9-]+)\):.*/\1/' \
  | sort | uniq -c | sort -rn

echo
echo "── Cited sources (Tidy-Source: trailer) ────────────────"
git log --grep='^Tidy-Source:' --pretty=format:'%b' \
  | (grep '^Tidy-Source:' || true) \
  | sed -E 's/^Tidy-Source:[[:space:]]*//' \
  | sort | uniq -c | sort -rn
