#!/usr/bin/env bash
# Local CI — same checks as .github/workflows/ci.yml, driven by prek.
# Run this before every push; it must be fully green before shipping.
#
# Static checks run via prek (.pre-commit-config.yaml) — the exact hooks the
# GitHub 'checks' job runs. Tests run on the current Python only (fast); GitHub
# Actions runs the full 3.11 / 3.12 / 3.13 matrix on every PR.
#
# Usage:
#   scripts/ci.sh            # full gate: prek + eslint + pip-audit + tests + diff-cover
#   scripts/ci.sh --fast     # skip the patch-coverage gate (quick dev check)
#   scripts/ci.sh --fix      # let prek's hooks auto-fix, then re-run to verify

set -euo pipefail

SENTINEL=".ci-passed"
# Remove any stale sentinel at the start so a partial run never leaves it valid
rm -f "$SENTINEL"

FAST=0
FIX=0
for arg in "$@"; do
  case "$arg" in
    --fast) FAST=1 ;;
    --fix)  FIX=1  ;;
  esac
done

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
PASS="${GREEN}✓${NC}"; FAIL="${RED}✗${NC}"

step() { echo -e "\n${CYAN}── $1 ──${NC}"; }
ok()   { echo -e "${PASS} $1"; }
warn() { echo -e "${YELLOW}⚠ $1${NC}"; }

# ── 0. Pre-flight: ghost deletion check ──────────────────────────────────────
# Tracked files deleted locally but not staged still exist in git.
# GitHub CI clones from git and sees them; local pytest skips missing files.
# This divergence is a common source of "passes locally, fails on GitHub".
step "Pre-flight: ghost deletions"
DELETED_UNSTAGED=$(git ls-files --deleted 2>/dev/null || true)
if [[ -n "$DELETED_UNSTAGED" ]]; then
  echo -e "${FAIL} Tracked files deleted locally but not staged — GitHub CI will clone them:"
  while IFS= read -r f; do echo "  D $f"; done <<< "$DELETED_UNSTAGED"
  echo -e "  Fix: git add -u  (or: git rm \$file)"
  exit 1
fi
ok "no ghost deletions"

# ── 1. Ensure main dev deps are installed ─────────────────────────────────────
step "Install deps (main env)"
uv sync --extra dev --quiet
ok "deps synced (Python $(uv run python --version | awk '{print $2}'))"

# ── 2. Static checks via prek ─────────────────────────────────────────────────
# One runner for ruff (lint+format, incl. S security rules and C90 complexity),
# mypy, import-linter, the complexity ratchet and file hygiene — defined once in
# .pre-commit-config.yaml and shared with the GitHub 'checks' job.
PREK="prek"
command -v prek >/dev/null 2>&1 || PREK="uv tool run prek"
step "Static checks (prek run --all-files)"
if [[ $FIX -eq 1 ]]; then
  $PREK run --all-files || true   # --fix: let hooks autofix; re-run to verify
  ok "prek (autofix applied — re-run without --fix to verify)"
else
  $PREK run --all-files
  ok "prek checks (ruff · format · mypy · import-linter · ratchet)"
fi

# ── 2b. JavaScript lint & syntax ──────────────────────────────────────────────
step "JS lint (eslint + node --check)"
if command -v npm >/dev/null 2>&1; then
  if [[ ! -d node_modules ]]; then
    npm ci --no-audit --no-fund >/dev/null 2>&1 || npm install --no-audit --no-fund >/dev/null 2>&1
  fi
  npx --no-install eslint .
  ok "eslint"
  for f in ster/assets/*.js kai-extension/*.js; do node --check "$f"; done
  ok "node --check"
else
  warn "npm not found — skipping JS lint (CI installs Node)"
fi

# ── 3. Security — pip-audit (dependency CVEs) ────────────────────────────────
step "Security — pip-audit"
uv run pip-audit --skip-editable
ok "pip-audit"

# ── 4. Tests (single Python version locally) ─────────────────────────────────
# Local CI runs the current interpreter only — fast feedback. GitHub Actions
# runs the *full* 3.11 / 3.12 / 3.13 matrix on every PR, so support for all
# three versions is still enforced there before merge.
#   -n auto → one worker per CPU core. Safe now that SPARQL parsing is
#             serialised (sparql_query._SPARQL_LOCK) — the rdflib parser
#             thread-safety flake that previously blocked xdist is fixed.
#   --fast  → skip coverage entirely (tracing ~doubles runtime); the full gate
#             keeps it for the diff-cover patch-coverage check.
step "Tests (current Python $(uv run python --version | awk '{print $2}'))"
if [[ $FAST -eq 1 ]]; then
  uv run pytest tests/ -q --tb=short -n auto
  ok "pytest (fast, no coverage)"
else
  uv run pytest tests/ -q --tb=short -n auto \
    --cov=ster --cov-report=term-missing --cov-report=xml
  ok "pytest"
fi

# ── 5. Patch coverage gate (diff-cover vs origin/main) — full mode only ───────
# Mirrors the CI 'diff-cover' step: changed lines must be ≥ 90% covered.
if [[ $FAST -eq 0 ]]; then
  step "Patch coverage (diff-cover vs origin/main)"
  if git rev-parse --verify --quiet origin/main >/dev/null; then
    uv run diff-cover coverage.xml --compare-branch origin/main --fail-under 90
    ok "patch coverage ≥ 90%"
  else
    warn "origin/main not found — skipping patch coverage (run: git fetch origin main)"
  fi
fi

# Write sentinel so the pre-push hook knows CI has passed
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$SENTINEL"

echo -e "\n${GREEN}══════════════════════════════════════════"
echo -e "  All checks passed — ready to push  ✓"
echo -e "══════════════════════════════════════════${NC}"
