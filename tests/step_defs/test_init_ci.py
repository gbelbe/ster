"""BDD step definitions for tests/features/ci/init_ci.feature."""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when
from typer.testing import CliRunner

from ster.cli import app
from ster.init_ci import prompt_if_missing

scenarios("../features/ci/init_ci.feature")

runner = CliRunner()

_WORKFLOW = Path(".github") / "workflows" / "taxonomy-ci.yml"


# ── Givens ────────────────────────────────────────────────────────────────────


@given("an empty project directory", target_fixture="project_dir")
def empty_project_dir(tmp_path: Path) -> Path:
    return tmp_path


@given(parsers.parse('a project with an existing "taxonomy-ci.yml"'), target_fixture="project_dir")
def project_with_existing_workflow(tmp_path: Path) -> Path:
    wf = tmp_path / _WORKFLOW
    wf.parent.mkdir(parents=True)
    wf.write_text("name: Existing CI\n", encoding="utf-8")
    return tmp_path


@given(
    "a git project directory with ontology files but no CI workflow at all",
    target_fixture="project_dir",
)
def git_project_no_ci(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / "vocab.ttl").write_text("", encoding="utf-8")
    return tmp_path


@given(
    "a git project directory with ontology files and an existing CI workflow",
    target_fixture="project_dir",
)
def git_project_existing_ci(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / "vocab.ttl").write_text("", encoding="utf-8")
    wf = tmp_path / ".github" / "workflows" / "ontology-ci.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("name: Ontology CI\n", encoding="utf-8")
    return tmp_path


@given("the user will confirm the CI prompt", target_fixture="ask_fn")
def user_confirms() -> object:
    return lambda _: True


@given("the user will decline the CI prompt", target_fixture="ask_fn")
def user_declines() -> object:
    return lambda _: False


# ── Whens ─────────────────────────────────────────────────────────────────────


@when(parsers.parse('I run "ster init-ci"'), target_fixture="result")
def run_init_ci(project_dir: Path):
    return runner.invoke(app, ["init-ci", str(project_dir)])


@when(parsers.parse('I run "ster init-ci --no-config"'), target_fixture="result")
def run_init_ci_no_config(project_dir: Path):
    return runner.invoke(app, ["init-ci", str(project_dir), "--no-config"])


@when(parsers.parse('I run "ster init-ci --force"'), target_fixture="result")
def run_init_ci_force(project_dir: Path):
    return runner.invoke(app, ["init-ci", str(project_dir), "--force"])


@when("ster checks for CI on startup", target_fixture="result")
def ster_checks_ci(project_dir: Path, ask_fn) -> bool:
    return prompt_if_missing(project_dir, ask_fn=ask_fn)


# ── Thens ─────────────────────────────────────────────────────────────────────


@then(parsers.parse('"{rel_path}" is created'))
def file_is_created(project_dir: Path, rel_path: str) -> None:
    assert (project_dir / rel_path).exists(), f"Expected {rel_path!r} to exist in {project_dir}"


@then(parsers.parse('"{rel_path}" does not exist'))
def file_does_not_exist(project_dir: Path, rel_path: str) -> None:
    assert not (project_dir / rel_path).exists(), f"Expected {rel_path!r} NOT to exist"


@then("the exit code is 0")
def exit_zero(result) -> None:
    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}.\n{result.output}"


@then(parsers.parse('the output contains "{text}"'))
def output_contains(result, text: str) -> None:
    assert text in result.output, f"Expected {text!r} in output:\n{result.output}"
