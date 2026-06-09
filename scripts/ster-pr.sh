#!/usr/bin/env bash
# ster-pr <N> — integrate a PUBLIC pull request through the PRIVATE repo.
#
# External contributions arrive on the public repo, but the private repo is the
# source of truth and runs the full gate (incl. internal org checks). This helper
# brings a public PR into private `main`, gates it, and prints the mirror commands.
# It never pushes for you — review the merge, then run the printed commands.
#
# Requires remotes: origin (private) and public. Usage: bash scripts/ster-pr.sh 42

set -euo pipefail

N="${1:-}"
if [ -z "$N" ]; then
  echo "usage: bash scripts/ster-pr.sh <public-PR-number>" >&2
  exit 2
fi

cd "$(git rev-parse --show-toplevel)"

if [ -n "$(git status --porcelain)" ]; then
  echo "error: working tree is not clean — commit or stash first." >&2
  exit 1
fi

echo "▶ Fetching public PR #${N} …"
git fetch public "refs/pull/${N}/head:pr-${N}"

echo "▶ Updating private main …"
git checkout main
git pull origin main

echo "▶ Merging pr-${N} into main (--no-ff, preserves authorship) …"
git merge --no-ff --no-edit "pr-${N}"

echo "▶ Running the full CI gate …"
bash scripts/ci.sh

cat <<EOF

✅ PR #${N} integrated into private main and gated.

Review the merge, then mirror it out:

    git push origin main      # private (source of truth)
    git push public main      # public  — auto-closes PR #${N}
    # or both at once:  git pushall main

Clean up the local branch afterwards:  git branch -D pr-${N}
EOF
