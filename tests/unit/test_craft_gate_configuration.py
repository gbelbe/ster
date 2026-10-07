from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_local_ci_enforces_mutation_and_local_craftcov_reports() -> None:
    ci = (ROOT / "scripts" / "ci.sh").read_text()

    for required in (
        "mutmut run",
        "check_mutation_ratchet.py",
        "craftcov_pr_comment.py",
        "--format sarif",
        "--fast",
    ):
        assert required in ci


def test_mutmut_is_a_default_dependency_and_configured_for_ster() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text()

    assert '"mutmut>=' in pyproject
    assert "[tool.mutmut]" in pyproject
    assert 'source_paths = ["ster"]' in pyproject
    assert 'cache_invalidation_files = ["tests/**/*.py", "conftest.py"]' in pyproject
    assert 'on_dependency_change = "rerun"' in pyproject


def test_github_ci_keeps_mutation_and_reporting_jobs() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    for required in (
        "mutation-ratchet:",
        "mutmut run",
        "check_mutation_ratchet.py",
        "craftcov-pr-comment:",
        "craftcov-sarif:",
        "hashFiles('**/*.py', 'pyproject.toml', 'uv.lock')",
        "Force fresh mutation campaign",
        "github.base_ref || 'main'",
    ):
        assert required in workflow


def test_local_ci_supports_a_fresh_mutation_campaign() -> None:
    ci = (ROOT / "scripts" / "ci.sh").read_text()

    assert "--fresh" in ci
    assert "rm -rf mutants" in ci
