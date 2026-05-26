#!/usr/bin/env bash
# Release pipeline: version bump → changelog → commit → tag → push → PyPI.
#
# Usage:
#   bash scripts/release.sh 0.4.7
#
# Before running:
#   1. Write RELEASE_NOTES.md (bullet points for the changelog)
#   2. Run: bash scripts/ci.sh    (gate must be green)
#
# RELEASE_ROOT can be overridden in tests to avoid requiring a real git repo.

set -euo pipefail

ROOT="${RELEASE_ROOT:-$(git rev-parse --show-toplevel)}"
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'

die() { printf "${RED}✗ BLOCKED — %s${NC}\n" "$1" >&2; exit 1; }
ok()  { printf "${GREEN}✓ %s${NC}\n" "$1"; }
step(){ printf "\n${CYAN}── %s ──${NC}\n" "$1"; }

# ── 1. Version argument ────────────────────────────────────────────────────────
if [[ $# -ne 1 ]]; then
    printf "Usage: %s <version>  (e.g. 0.4.7)\n" "$0" >&2
    exit 1
fi
VERSION="${1#v}"   # strip leading 'v' if present
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    die "Invalid version '$VERSION' — expected X.Y.Z"
fi

# ── 2. CI sentinel ─────────────────────────────────────────────────────────────
SENTINEL="$ROOT/.ci-passed"
if [[ ! -f "$SENTINEL" ]]; then
    die "CI has not been run. Run: bash scripts/ci.sh"
fi
AGE=$(python3 -c "import os,time; print(int(time.time()-os.path.getmtime('$SENTINEL')))" 2>/dev/null || echo 9999)
if [[ "$AGE" -gt 3600 ]]; then
    MINS=$(( AGE / 60 ))
    die "CI result is stale (${MINS} min ago). Re-run: bash scripts/ci.sh"
fi
ok "CI gate is green"

# ── 3. RELEASE_NOTES.md ────────────────────────────────────────────────────────
NOTES="$ROOT/RELEASE_NOTES.md"
if [[ ! -f "$NOTES" ]]; then
    die "RELEASE_NOTES.md not found. Create it with bullet-point release notes."
fi
if [[ ! -s "$NOTES" ]] || ! grep -qE '[^[:space:]]' "$NOTES"; then
    die "RELEASE_NOTES.md is empty. Add release notes before publishing."
fi
ok "RELEASE_NOTES.md found"

# ── 4. Clean working tree (skip when RELEASE_ROOT overridden in tests) ─────────
if [[ -z "${RELEASE_ROOT:-}" ]]; then
    if ! git -C "$ROOT" diff --quiet HEAD 2>/dev/null; then
        die "Working tree has uncommitted changes. Commit or stash them first."
    fi
    ok "Working tree is clean"
fi

# ── 5. Bump version + update changelog ────────────────────────────────────────
step "Version bump"
uv run python "$ROOT/scripts/bump_version.py" "$VERSION" --notes "$NOTES"

# ── 6. Commit + tag ────────────────────────────────────────────────────────────
step "Commit and tag"
if [[ -z "${RELEASE_ROOT:-}" ]]; then
    git -C "$ROOT" add pyproject.toml README.md
    git -C "$ROOT" commit -m "chore(release): v${VERSION}"
    git -C "$ROOT" tag "v${VERSION}"
    ok "Committed and tagged v${VERSION}"
fi

# ── 7. Push ────────────────────────────────────────────────────────────────────
if [[ -z "${RELEASE_ROOT:-}" ]]; then
    step "Push to GitHub"
    git -C "$ROOT" push
    git -C "$ROOT" push origin "v${VERSION}"
    ok "Pushed v${VERSION} to GitHub"
fi

# ── 8. Build + publish ─────────────────────────────────────────────────────────
if [[ -z "${RELEASE_ROOT:-}" ]]; then
    step "Build"
    (cd "$ROOT" && uv build)
    ok "Built dist/ster-${VERSION}*"

    step "Publish to PyPI"
    twine upload "$ROOT/dist/ster-${VERSION}"*
    ok "Published ster ${VERSION} to PyPI"
fi

# ── 9. Cleanup ────────────────────────────────────────────────────────────────
rm -f "$NOTES"
ok "Cleaned up RELEASE_NOTES.md"

printf "\n${GREEN}══════════════════════════════════════════\n"
printf "  Released ster v%s  ✓\n" "$VERSION"
printf "══════════════════════════════════════════${NC}\n"
