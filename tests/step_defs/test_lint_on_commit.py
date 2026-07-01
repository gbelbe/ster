"""BDD step definitions for tests/features/ci/lint_on_commit.feature."""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import given, scenarios, then, when
from semanticlint.checks.base import Severity

from ster.plugins.semanticlint.runner import lint_files, load_config, run_pre_commit_lint

scenarios("../features/ci/lint_on_commit.feature")

_VALID_SKOS = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex:   <http://example.org/> .

ex:Scheme a skos:ConceptScheme ;
    skos:hasTopConcept ex:C1 .
ex:C1 a skos:Concept ;
    skos:inScheme ex:Scheme ;
    skos:topConceptOf ex:Scheme ;
    skos:prefLabel "Concept One"@en ;
    skos:definition "The first concept."@en .
"""

_SKOS_ERROR = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex:   <http://example.org/> .

ex:Scheme a skos:ConceptScheme .
ex:C1 a skos:Concept ;
    skos:inScheme ex:Scheme ;
    skos:prefLabel "Concept One"@en ;
    skos:prefLabel "Also Concept One"@en .
"""

_SKOS_WARNING = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex:   <http://example.org/> .

ex:Scheme a skos:ConceptScheme .
ex:C1 a skos:Concept ; skos:inScheme ex:Scheme .
"""


# ── Givens ────────────────────────────────────────────────────────────────────


@given("a valid SKOS taxonomy file with no violations", target_fixture="taxonomy_path")
def valid_skos_file(tmp_path: Path) -> Path:
    p = tmp_path / "vocab.ttl"
    p.write_text(_VALID_SKOS, encoding="utf-8")
    return p


@given("a taxonomy file with SKOS errors", target_fixture="taxonomy_path")
def skos_error_file(tmp_path: Path) -> Path:
    p = tmp_path / "vocab.ttl"
    p.write_text(_SKOS_ERROR, encoding="utf-8")
    return p


@given("a taxonomy file with SKOS warnings only", target_fixture="taxonomy_path")
def skos_warning_file(tmp_path: Path) -> Path:
    p = tmp_path / "vocab.ttl"
    p.write_text(_SKOS_WARNING, encoding="utf-8")
    return p


@given("a repo directory", target_fixture="repo_dir")
def plain_repo_dir(tmp_path: Path) -> Path:
    return tmp_path


@given(
    "a repo directory with onto-ci.yml setting fail_on to warning",
    target_fixture="repo_dir",
)
def repo_dir_with_warning_config(tmp_path: Path) -> Path:
    (tmp_path / "onto-ci.yml").write_text("fail_on: warning\n", encoding="utf-8")
    return tmp_path


# ── Whens ─────────────────────────────────────────────────────────────────────


@when("the user runs the pre-commit lint check", target_fixture="lint_result")
def run_check(taxonomy_path: Path, repo_dir: Path):
    cfg, fail_on = load_config(repo_dir)
    violations = lint_files([taxonomy_path], cfg)
    blocked = False
    from ster.plugins.semanticlint.runner import has_blocking_violations

    blocked = has_blocking_violations(violations, fail_on)
    return {"violations": violations, "blocked": blocked, "proceeded": not blocked}


@when(
    "the user runs the pre-commit lint check and declines to proceed",
    target_fixture="lint_result",
)
def run_check_declined(taxonomy_path: Path, repo_dir: Path):
    proceeded = run_pre_commit_lint(taxonomy_path, repo_dir, confirm_fn=lambda _: False)
    return {"proceeded": proceeded}


@when(
    "the user runs the pre-commit lint check and confirms to proceed",
    target_fixture="lint_result",
)
def run_check_confirmed(taxonomy_path: Path, repo_dir: Path):
    proceeded = run_pre_commit_lint(taxonomy_path, repo_dir, confirm_fn=lambda _: True)
    cfg, fail_on = load_config(repo_dir)
    violations = lint_files([taxonomy_path], cfg)
    return {"violations": violations, "proceeded": proceeded}


# ── Thens ─────────────────────────────────────────────────────────────────────


@then("the lint result shows no violations")
def no_violations(lint_result: dict) -> None:
    assert lint_result["violations"] == [], (
        f"Expected no violations, got {[v.check_id for v in lint_result['violations']]}"
    )


@then("the lint result shows errors")
def has_errors(lint_result: dict) -> None:
    assert any(v.severity == Severity.ERROR for v in lint_result["violations"]), (
        "Expected at least one ERROR violation"
    )


@then("the lint result shows warnings")
def has_warnings(lint_result: dict) -> None:
    assert any(v.severity == Severity.WARNING for v in lint_result["violations"]), (
        "Expected at least one WARNING violation"
    )


@then("the commit is blocked")
def commit_blocked(lint_result: dict) -> None:
    assert lint_result["blocked"] is True, "Expected commit to be blocked"


@then("the commit is not blocked")
def commit_not_blocked(lint_result: dict) -> None:
    assert lint_result.get("blocked", False) is False, "Expected commit NOT to be blocked"


@then("the pre-commit check returns False")
def check_returns_false(lint_result: dict) -> None:
    assert lint_result["proceeded"] is False, "Expected run_pre_commit_lint to return False"


@then("the pre-commit check returns True")
def check_returns_true(lint_result: dict) -> None:
    assert lint_result["proceeded"] is True, "Expected run_pre_commit_lint to return True"
