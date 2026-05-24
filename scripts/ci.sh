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

# ── 1. Ensure main dev deps are installed ─────────────────────────────────────
step "Install deps (main env)"
uv sync --extra html --extra api --extra dev --quiet
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

# ── 3. Type check ─────────────────────────────────────────────────────────────
step "Type check (mypy)"
uv run mypy ster/ && ok "mypy"

# ── 4. Security ───────────────────────────────────────────────────────────────
step "Security — bandit"
uv run bandit -r ster/ -c pyproject.toml -q && ok "bandit"

step "Security — pip-audit"
uv run pip-audit --ignore-vuln CVE-2026-3219 --ignore-vuln CVE-2026-6357 --skip-editable \
  && ok "pip-audit"

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
    --extra html --extra api --extra dev --quiet
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
uv sync --extra html --extra api --extra dev --quiet

# Write sentinel so the pre-push hook knows CI has passed
date -u +"%Y-%m-%dT%H:%M:%SZ" > "$SENTINEL"

echo -e "\n${GREEN}══════════════════════════════════════════"
echo -e "  All checks passed — ready to push  ✓"
echo -e "══════════════════════════════════════════${NC}"
