"""BDD step definitions for tests/features/io/publish_versioning.feature."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/io/publish_versioning.feature")


# ── helpers ─────────────────────────────────────────────────────────────────


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _minimal_taxonomy(uri: str = "https://ex.org/onto") -> object:
    from ster.model import Label, LabelType, RDFClass, Taxonomy

    t = Taxonomy()
    t.ontology_uri = uri
    t.namespace_bindings[""] = uri + "#"
    t.owl_classes[uri + "#Animal"] = RDFClass(
        uri=uri + "#Animal",
        labels=[Label(lang="en", value="Animal", type=LabelType.PREF)],
    )
    return t


def _init_repo(repo: Path) -> Path:
    """Create a git repo containing a committed onto.ttl; return the source path."""
    from ster.store import taxonomy_to_graph

    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")
    src = repo / "onto.ttl"
    src.write_text(taxonomy_to_graph(_minimal_taxonomy()).serialize(format="turtle"))
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return src


@pytest.fixture
def ctx(tmp_path: Path) -> dict:
    return {"repo": tmp_path / "repo"}


# ── given ───────────────────────────────────────────────────────────────────


@given("an ontology repo with no ontology tags")
def given_repo_no_tags(ctx: dict) -> None:
    ctx["src"] = _init_repo(ctx["repo"])


@given(parsers.parse('an ontology repo already tagged "{tag}"'))
def given_repo_tagged(ctx: dict, tag: str) -> None:
    src = _init_repo(ctx["repo"])
    _git(ctx["repo"], "tag", tag)
    ctx["src"] = src


@given("an ontology repo with a remote and no ontology tags")
def given_repo_with_remote(ctx: dict) -> None:
    src = _init_repo(ctx["repo"])
    remote = ctx["repo"].parent / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], capture_output=True)
    _git(ctx["repo"], "remote", "add", "origin", str(remote))
    branch = _git(ctx["repo"], "branch", "--show-current").stdout.strip()
    _git(ctx["repo"], "push", "-u", "origin", branch)
    ctx["src"] = src
    ctx["remote"] = remote


# ── when ────────────────────────────────────────────────────────────────────


@when(parsers.parse('I perform a stable release with bump "{bump}"'))
def when_perform_release(ctx: dict, bump: str) -> None:
    from ster.git.manager import GitManager
    from ster.publish import perform_stable_release

    git = GitManager(ctx["src"])
    ctx["result"] = perform_stable_release(ctx["src"], ctx["repo"] / "ontology", bump, git)


# ── then ────────────────────────────────────────────────────────────────────


@then(parsers.parse('the release version is "{version}"'))
def then_release_version(ctx: dict, version: str) -> None:
    assert ctx["result"].version == version


@then(parsers.parse('the tag "{tag}" exists in the repo'))
def then_tag_exists(ctx: dict, tag: str) -> None:
    out = _git(ctx["repo"], "tag", "--list").stdout.split()
    assert tag in out


@then(parsers.parse('the source file contains owl:versionInfo "{value}"'))
def then_source_contains_version(ctx: dict, value: str) -> None:
    assert value in ctx["src"].read_text()


@then(parsers.parse('a commit "{message}" exists in the repo'))
def then_commit_exists(ctx: dict, message: str) -> None:
    log = _git(ctx["repo"], "log", "--oneline").stdout
    assert message in log


@then(parsers.parse('the tag "{tag}" exists in the remote'))
def then_tag_in_remote(ctx: dict, tag: str) -> None:
    out = _git(ctx["remote"], "tag", "--list").stdout.split()
    assert tag in out
