"""BDD step definitions for tests/features/ci/release.feature."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
import bump_version as bv  # noqa: E402

scenarios("../features/ci/release.feature")

_SCRIPT = Path(__file__).parents[2] / "scripts" / "release.sh"

_PYPROJECT_TMPL = '[project]\nname = "ster"\nversion = "{ver}"\n'
_README_TMPL = "# ster\n\n  v{ver}\n\nSome text.\n\n## Changelog\n\n### {ver}\n- Old feature\n"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def ctx(tmp_path: Path) -> dict[str, Any]:
    return {"root": tmp_path, "result": None}


# ── Givens ────────────────────────────────────────────────────────────────────


@given(parsers.parse('pyproject.toml has version "{ver}"'))
def pyproject_with_version(ver: str, ctx: dict[str, Any]) -> None:
    (ctx["root"] / "pyproject.toml").write_text(_PYPROJECT_TMPL.format(ver=ver))
    (ctx["root"] / "README.md").write_text(_README_TMPL.format(ver=ver))


@given(parsers.parse('README.md has banner line "  v{ver}"'))
def readme_with_banner(ver: str, ctx: dict[str, Any]) -> None:
    (ctx["root"] / "README.md").write_text(_README_TMPL.format(ver=ver))
    (ctx["root"] / "pyproject.toml").write_text(_PYPROJECT_TMPL.format(ver=ver))


@given('README.md has a "## Changelog" section with an existing entry')
def readme_with_changelog(ctx: dict[str, Any]) -> None:
    (ctx["root"] / "README.md").write_text(_README_TMPL.format(ver="0.4.6"))
    (ctx["root"] / "pyproject.toml").write_text(_PYPROJECT_TMPL.format(ver="0.4.6"))


@given('README.md has a "## Changelog" section with a "### 0.4.6" entry')
def readme_with_old_entry(ctx: dict[str, Any]) -> None:
    (ctx["root"] / "README.md").write_text(_README_TMPL.format(ver="0.4.6"))
    (ctx["root"] / "pyproject.toml").write_text(_PYPROJECT_TMPL.format(ver="0.4.6"))


@given(parsers.parse('RELEASE_NOTES.md contains "{content}"'))
def release_notes_with_content(content: str, ctx: dict[str, Any]) -> None:
    (ctx["root"] / "RELEASE_NOTES.md").write_text(content + "\n")


@given("RELEASE_NOTES.md does not exist")
def no_release_notes(ctx: dict[str, Any]) -> None:
    pass  # tmp_path is empty


@given("the CI sentinel file does not exist")
def no_sentinel(ctx: dict[str, Any]) -> None:
    pass


# ── Whens ─────────────────────────────────────────────────────────────────────


@when(parsers.parse('bump_version is called with "{ver}"'))
def call_bump_version(ver: str, ctx: dict[str, Any]) -> None:
    bv._update_pyproject(ver, root=ctx["root"])
    bv._update_readme(ver, root=ctx["root"])


@when(parsers.parse('bump_version is called with "{ver}" and the release notes'))
def call_bump_version_with_notes(ver: str, ctx: dict[str, Any]) -> None:
    bv._update_pyproject(ver, root=ctx["root"])
    bv._update_readme(ver, root=ctx["root"])
    bv._update_changelog(ver, ctx["root"] / "RELEASE_NOTES.md", root=ctx["root"])


@when("release.sh is run with a fresh CI sentinel")
def run_release_with_sentinel(ctx: dict[str, Any]) -> None:
    sentinel = ctx["root"] / ".ci-passed"
    sentinel.write_text("2026-05-26T10:00:00Z\n")
    env = {**os.environ, "RELEASE_ROOT": str(ctx["root"])}
    ctx["result"] = subprocess.run(
        ["bash", str(_SCRIPT), "0.4.7"],
        env=env,
        capture_output=True,
        text=True,
    )


@when("release.sh is run without RELEASE_NOTES.md check")
def run_release_no_notes(ctx: dict[str, Any]) -> None:
    env = {**os.environ, "RELEASE_ROOT": str(ctx["root"])}
    ctx["result"] = subprocess.run(
        ["bash", str(_SCRIPT), "0.4.7"],
        env=env,
        capture_output=True,
        text=True,
    )


# ── Thens ─────────────────────────────────────────────────────────────────────


@then(parsers.parse('pyproject.toml contains version "{ver}"'))
def pyproject_has_version(ver: str, ctx: dict[str, Any]) -> None:
    text = (ctx["root"] / "pyproject.toml").read_text()
    assert f'version = "{ver}"' in text


@then(parsers.parse('README.md contains banner line "  v{ver}"'))
def readme_has_banner(ver: str, ctx: dict[str, Any]) -> None:
    assert f"  v{ver}" in (ctx["root"] / "README.md").read_text()


@then(parsers.parse('README.md contains "{header}" immediately after "## Changelog"'))
def changelog_has_new_entry(header: str, ctx: dict[str, Any]) -> None:
    text = (ctx["root"] / "README.md").read_text()
    assert "## Changelog" in text
    assert header in text
    assert text.index("## Changelog") < text.index(header)


@then(parsers.parse('the entry contains "{content}"'))
def entry_contains_content(content: str, ctx: dict[str, Any]) -> None:
    assert content in (ctx["root"] / "README.md").read_text()


@then('README.md still contains the "### 0.4.6" entry below the new one')
def old_entry_preserved(ctx: dict[str, Any]) -> None:
    text = (ctx["root"] / "README.md").read_text()
    assert "### 0.4.6" in text
    assert "- Old feature" in text
    assert text.index("### 0.4.7") < text.index("### 0.4.6")


@then("the script exits with a non-zero code")
def exits_nonzero(ctx: dict[str, Any]) -> None:
    assert ctx["result"].returncode != 0


@then(parsers.parse('stderr contains "{msg}"'))
def stderr_contains(msg: str, ctx: dict[str, Any]) -> None:
    assert msg in ctx["result"].stderr, f"Expected '{msg}' in stderr:\n{ctx['result'].stderr}"
