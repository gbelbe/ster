#!/usr/bin/env bash
# Everything the agent app has: Python (unittest, no dependency beyond the server's own) and JavaScript (node's built-in runner).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tests -p "test_*.py"
node --test tests/*.test.js
for f in agent_app/static/*.js; do node --check "$f"; done
