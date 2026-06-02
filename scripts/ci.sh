#!/usr/bin/env bash
# Local CI — mirrors .github/workflows/ci.yml exactly.
# Run this before every push; it must be fully green before shipping.
#
# Usage:
#   scripts/ci.sh            # full run (lint + types + security + tests on 3.11/3.12/3.13)
#   scripts/ci.sh --fast     # skip multi-version matrix, run only current Python
#   scripts/ci.sh --fix      # auto-fix lint/format before checking

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

# ── 2. Lint ───────────────────────────────────────────────────────────────────
step "Lint (ruff check)"
if [[ $FIX -eq 1 ]]; then
  uv run ruff check --fix . && ok "ruff check --fix applied"
else
  uv run ruff check . && ok "ruff check"
fi

step "Format (ruff format)"
if [[ $FIX -eq 1 ]]; then
  uv run ruff format . && ok "ruff format applied"
else
  uv run ruff format --check . && ok "ruff format"
fi

# ── 2b. JavaScript lint & syntax ──────────────────────────────────────────────
step "JS lint (eslint + node --check)"
if command -v npm >/dev/null 2>&1; then
  if [[ ! -d node_modules ]]; then
    npm ci --no-audit --no-fund >/dev/null 2>&1 || npm install --no-audit --no-fund >/dev/null 2>&1
  fi
  npx --no-install eslint . && ok "eslint"
  for f in ster/assets/*.js kai-extension/*.js; do node --check "$f"; done && ok "node --check"
else
  warn "npm not found — skipping JS lint (CI installs Node)"
fi

# ── 3. Type check ─────────────────────────────────────────────────────────────
step "Type check (mypy)"
# --no-incremental: prevents stale cache masking errors that GitHub CI (cold run) would catch
uv run mypy ster/ --no-incremental && ok "mypy"

# ── 4. Security ───────────────────────────────────────────────────────────────
step "Security — bandit"
uv run bandit -r ster/ -c pyproject.toml -q && ok "bandit"

step "Security — pip-audit"
uv run pip-audit --ignore-vuln CVE-2026-3219 --ignore-vuln CVE-2026-6357 --skip-editable \
  && ok "pip-audit"

# ── 4c. Complexity ratchet (vs origin/main) ──────────────────────────────────
# Mirrors the CI 'complexity' job: no function may grow worse past 10.
step "Complexity ratchet (vs origin/main)"
if git rev-parse --verify --quiet origin/main >/dev/null; then
  uv run python scripts/check_complexity_ratchet.py --base origin/main \
    && ok "complexity ratchet"
else
  warn "origin/main not found — skipping complexity ratchet (run: git fetch origin main)"
fi
# ── 4b. Import contracts (dependency isolation) ──────────────────────────────
step "Import contracts (import-linter)"
uv run lint-imports && ok "import contracts"

# ── 5. Tests (per Python version, isolated envs) ─────────────────────────────
run_tests_for() {
  local PY="$1"
  local VENV=".venv-ci-${PY//./}"   # e.g. .venv-ci-311

  if ! uv python find "$PY" &>/dev/null; then
    warn "Python $PY not found — skipping (install with: uv python install $PY)"
    return 0
  fi

  step "Tests (Python $PY)"
  UV_PROJECT_ENVIRONMENT="$VENV" uv sync --python "$PY" \
    --extra dev --quiet
  UV_PROJECT_ENVIRONMENT="$VENV" uv run --python "$PY" pytest tests/ -q \
    --tb=short \
    --cov=ster \
    --cov-report=term-missing \
    --cov-report=xml
  ok "pytest Python $PY"
}

if [[ $FAST -eq 1 ]]; then
  step "Tests (current Python — fast mode)"
  uv run pytest tests/ -q --tb=short --cov=ster --cov-report=term-missing
  ok "pytest (fast)"
else
  for PY in 3.11 3.12 3.13; do
    run_tests_for "$PY"
  done
fi

# ── Restore main venv ─────────────────────────────────────────────────────────
uv sync --extra dev --quiet

# ── Patch coverage gate (diff-cover vs origin/main) — full mode only ──────────
# Mirrors the CI 'diff-cover' step: changed lines must be ≥ 90% covered.
if [[ $FAST -eq 0 ]]; then
  step "Patch coverage (diff-cover vs origin/main)"
  if git rev-parse --verify --quiet origin/main >/dev/null; then
    uv run diff-cover coverage.xml --compare-branch origin/main --fail-under 90 \
      && ok "patch coverage ≥ 90%"
  else
    warn "origin/main not found — skipping patch coverage (run: git fetch origin main)"
  fi
fi

# Write sentinel so the pre-push hook knows CI has passed
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$SENTINEL"

echo -e "\n${GREEN}══════════════════════════════════════════"
echo -e "  All checks passed — ready to push  ✓"
echo -e "══════════════════════════════════════════${NC}"
