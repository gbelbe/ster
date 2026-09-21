#!/usr/bin/env bash
# Install git hooks for this repository (driven by prek).
# Run once after cloning: bash scripts/install-hooks.sh
#
# prek (https://prek.j178.dev) is a fast, drop-in pre-commit replacement.
# It reads .pre-commit-config.yaml and installs both hook types declared in
# `default_install_hook_types`:
#   • pre-commit → ruff, format, mypy, import-linter and file hygiene
#   • pre-push   → verifies the full local CI gate passed within the last hour

set -euo pipefail

# Resolve a prek runner: prefer an installed binary, else fall back to `uv tool`.
if command -v prek >/dev/null 2>&1; then
  PREK=(prek)
elif command -v uv >/dev/null 2>&1; then
  PREK=(uv tool run prek)
else
  echo "✗ prek not found and uv is unavailable." >&2
  echo "  Install prek with:  uv tool install prek   (or see https://prek.j178.dev)" >&2
  exit 1
fi

"${PREK[@]}" install --install-hooks

echo "✓ git hooks installed via prek (pre-commit + pre-push)."
echo "  Static checks run on commit; push requires a fresh full local CI pass."
echo "  Run the full local gate any time with:  bash scripts/ci.sh"
