#!/usr/bin/env bash
# Install git hooks for this repository.
# Run once after cloning: bash scripts/install-hooks.sh

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="$ROOT/.git/hooks"

ln -sf "$ROOT/scripts/pre-push.sh" "$HOOKS_DIR/pre-push"
chmod +x "$HOOKS_DIR/pre-push"

echo "✓ pre-push hook installed — git push will now require a passing CI run."
echo "  Run 'bash scripts/ci.sh' before pushing."
