"""The JavaScript toolchain (ESLint + node --check) is configured and wired
into both the local CI script and the GitHub Actions workflow."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_package_json_declares_eslint():
    pkg = json.loads((ROOT / "package.json").read_text())
    dev = pkg.get("devDependencies", {})
    assert "eslint" in dev


def test_eslint_flat_config_exists():
    assert (ROOT / "eslint.config.js").is_file()


def test_node_modules_is_gitignored():
    assert "node_modules" in (ROOT / ".gitignore").read_text()


def test_ci_workflow_has_js_job():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "eslint" in ci
    assert "node --check" in ci
    assert "setup-node" in ci
    # The publish gate waits on the js job too.
    assert "needs: [lint, js, typecheck, security, test]" in ci


def test_local_ci_script_runs_js_checks():
    sh = (ROOT / "scripts/ci.sh").read_text()
    assert "eslint" in sh
    assert "node --check" in sh


def test_browser_assets_pass_eslint():
    """Functional check — runs the real linter when it is installed locally.

    Skips when Node / the local eslint install are unavailable (the dedicated
    GitHub Actions `js` job enforces this in CI)."""
    if not shutil.which("node"):
        pytest.skip("node not available")
    eslint = ROOT / "node_modules" / ".bin" / "eslint"
    if not eslint.exists():
        pytest.skip("eslint not installed (run `npm ci`)")
    proc = subprocess.run(
        [str(eslint), "."], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
