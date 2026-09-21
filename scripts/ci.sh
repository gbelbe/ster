#!/usr/bin/env bash
# Local CI — same checks as .github/workflows/ci.yml, driven by prek.
# Run this before every push; it must be fully green before shipping.
#
# Static checks run via prek (.pre-commit-config.yaml) — the exact hooks the
# GitHub 'checks' job runs. Tests run on the current Python only (fast); GitHub
# Actions runs the 3.12 / 3.13 matrix on every PR.
#
# Usage:
#   scripts/ci.sh            # full gate: prek + eslint + npm/pip audit + tests + diff-cover
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

# ── 0b. Pre-flight: untracked Python files ───────────────────────────────────
# prek's --all-files means "all files git knows about" — an untracked .py file
# is invisible to it. Write a new module or test, run the gate, and every static
# check silently skips it; the moment it is committed, GitHub lints it for the
# first time and fails. Intent-to-add (git add -N) is enough to make prek see a
# file while leaving its contents unstaged.
#
# Scoped to the source trees on purpose: a developer's scratch script at the
# repo root is their own business and must not block the gate. Only files that
# would ship are checked.
step "Pre-flight: untracked Python files"
UNTRACKED_PY=$(git ls-files --others --exclude-standard -- 'ster/*.py' 'semanticdiff/*.py' 'tests/*.py' 'scripts/*.py' 2>/dev/null || true)
if [[ -n "$UNTRACKED_PY" ]]; then
  echo -e "${FAIL} Untracked .py files in the source tree — prek cannot see them, so GitHub lints them first:"
  while IFS= read -r f; do echo "  ? $f"; done <<< "$UNTRACKED_PY"
  echo -e "  Fix: git add -N \$file   (intent-to-add; contents stay unstaged)"
  exit 1
fi
ok "no untracked Python files"

# ── 0c. Pre-flight: stale prek stash patches ─────────────────────────────────
# prek stashes unstaged changes to ~/.cache/prek/patches/<id>.patch, restores
# them after the hooks, and does not always delete the patch afterwards. A
# leftover is replayed on the *next* run, in whatever repository runs next —
# the cache is global, so a patch abandoned by an unrelated project lands here.
# What you see is a commit that fails with "files were modified by this hook"
# and an index carrying changes you never made, which is a genuinely baffling
# half hour if you do not know to look here.
step "Pre-flight: stale prek stash patches"
PREK_PATCHES="${HOME}/.cache/prek/patches"
STALE=$(ls -1 "$PREK_PATCHES"/*.patch 2>/dev/null || true)
if [[ -n "$STALE" ]]; then
  echo -e "${FAIL} Leftover prek stash patches — these will be replayed into your working tree:"
  while IFS= read -r f; do echo "  $(basename "$f")  ($(wc -l < "$f" | tr -d ' ') lines)"; done <<< "$STALE"
  echo -e "  Inspect them first — they may hold work from an interrupted run:"
  echo -e "    cat $PREK_PATCHES/*.patch"
  echo -e "  Then clear them:  rm $PREK_PATCHES/*.patch"
  exit 1
fi
ok "no stale prek patches"

# ── 1. Ensure main dev deps are installed ─────────────────────────────────────
step "Install deps (main env)"
uv sync --extra dev --quiet
ok "deps synced (Python $(uv run python --version | awk '{print $2}'))"

# ── 2. Static checks via prek ─────────────────────────────────────────────────
# One runner for ruff (lint+format, incl. S security rules),
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
  ok "prek checks (ruff · format · mypy · import-linter)"
fi

# ── 2a. Complexity ratchet — run directly, exactly as CI does ────────────────
# Not through prek: the ratchet is diff-aware and needs a base to compare
# against, and prek has no way to pass one. CI skips it in its prek step for the
# same reason and invokes the script with the PR's base ref. Running it through
# prek locally compared against the wrong thing, so a change could pass here and
# still fail the PR.
step "Complexity ratchet (vs origin/main)"
if git rev-parse --verify --quiet origin/main >/dev/null; then
  uv run python scripts/check_complexity_ratchet.py --base origin/main
  uv run python scripts/check_complexity_ratchet.py --path semanticdiff --base origin/main
  ok "complexity ratchet"
else
  warn "origin/main not found — skipping ratchet (run: git fetch origin main)"
fi

# ── 2b. JavaScript lint & syntax ──────────────────────────────────────────────
# eslint needs node_modules, and node_modules needs the Node the project asks
# for. A machine on an older Node cannot install it — npm refuses with EBADENGINE
# — and the gate used to die there with an npx error, which reads like a lint
# failure and is not one. Missing tooling is a warning; a lint *finding* is still
# fatal. node --check needs no packages, so it runs either way and keeps the
# syntax guarantee on every shipped .js.
step "JS lint (eslint + node --check)"
if command -v node >/dev/null 2>&1; then
  for f in ster/assets/*.js kai-extension/*.js; do node --check "$f"; done
  ok "node --check ($(node --version))"
else
  warn "node not found — skipping JS syntax check (CI runs it)"
fi

if command -v npm >/dev/null 2>&1; then
  if [[ ! -d node_modules ]]; then
    npm ci --no-audit --no-fund >/dev/null 2>&1 || npm install --no-audit --no-fund >/dev/null 2>&1 || true
  fi
  if [[ -d node_modules ]]; then
    npx --no-install eslint .
    ok "eslint"
  else
    warn "node_modules unavailable (Node $(node --version 2>/dev/null || echo '?') — package.json wants $(node -p "require('./package.json').engines?.node || 'a newer Node'" 2>/dev/null))"
    warn "  skipping eslint locally; the GitHub 'Lint JS' job still runs it"
  fi
else
  warn "npm not found — skipping eslint (CI installs Node)"
fi

# ── 3. Security — dependency CVEs ───────────────────────────────────────────
step "Security — npm audit"
if command -v npm >/dev/null 2>&1 && [[ -d node_modules ]]; then
  npm audit --audit-level=high
  ok "npm audit"
else
  warn "node_modules unavailable — skipping npm audit (CI runs it)"
fi

step "Security — pip-audit"
uv run pip-audit --skip-editable
ok "pip-audit"

# ── 4. Tests (single Python version locally) ─────────────────────────────────
# Local CI runs the current interpreter only — fast feedback. GitHub Actions
# runs the 3.12 / 3.13 matrix on every PR, so support for both versions is
# still enforced there before merge.
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
    --cov=ster --cov=semanticdiff --cov-report=term-missing --cov-report=xml
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
