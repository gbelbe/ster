"""Unit tests for the semanticdiff CLI wiring."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from semanticdiff.cli import app
from tests._ontology_repo import ONTOLOGY, RepoBuilder

runner = CliRunner()

CLASS_A = "ex:A a owl:Class ."
CLASS_AB = "ex:A a owl:Class . ex:B a owl:Class ."
REPO_FLAG = "--repo"
LOG = "log"


def test_log_command_accepts_rev_range(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="first")
    ontology_repo.tag("v0.1")
    ontology_repo.commit(ttl=CLASS_AB, message="second")
    ontology_repo.tag("v0.2")

    result = runner.invoke(app, [LOG, "v0.1..v0.2", REPO_FLAG, str(ontology_repo.path)])

    assert result.exit_code == 0
    assert "ex:B" in result.stdout


def test_log_defaults_to_head(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="first")

    result = runner.invoke(app, [LOG, REPO_FLAG, str(ontology_repo.path)])

    assert result.exit_code == 0
    assert "ex:A" in result.stdout


def test_log_text_option_shows_the_raw_hunk(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="first")

    result = runner.invoke(app, [LOG, REPO_FLAG, str(ontology_repo.path), "--text"])

    assert "diff --git" in result.stdout


def test_show_command_filters_to_one_entity(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_AB, message="first")

    result = runner.invoke(app, ["show", "ex:B", REPO_FLAG, str(ontology_repo.path)])

    assert result.exit_code == 0
    assert "ex:B" in result.stdout


def test_show_command_requires_a_uri(ontology_repo: RepoBuilder) -> None:
    assert runner.invoke(app, ["show", REPO_FLAG, str(ontology_repo.path)]).exit_code != 0


def test_ontology_file_is_autodetected_when_the_repo_holds_one(
    ontology_repo: RepoBuilder,
) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="first")

    result = runner.invoke(app, [LOG, REPO_FLAG, str(ontology_repo.path)])

    assert result.exit_code == 0
    assert ONTOLOGY in result.stdout


def test_explicit_file_option_overrides_autodetection(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, files={"other.ttl": "# empty"}, message="two files")

    result = runner.invoke(app, [LOG, REPO_FLAG, str(ontology_repo.path), "--file", ONTOLOGY])

    assert result.exit_code == 0
    assert "ex:A" in result.stdout


def test_ambiguous_ontology_file_is_reported(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, files={"other.ttl": "# empty"}, message="two files")

    result = runner.invoke(app, [LOG, REPO_FLAG, str(ontology_repo.path)])

    assert result.exit_code != 0
    assert "--file" in result.stdout


def test_repo_without_an_rdf_file_is_reported(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(files={"README.md": "hello"}, message="no ontology")

    result = runner.invoke(app, [LOG, REPO_FLAG, str(ontology_repo.path)])

    assert result.exit_code != 0
    assert "no RDF file" in result.stdout


def test_missing_repo_exits_nonzero(tmp_path: Path) -> None:
    assert runner.invoke(app, [LOG, REPO_FLAG, str(tmp_path / "nope")]).exit_code != 0


def test_unknown_revision_exits_nonzero(ontology_repo: RepoBuilder) -> None:
    ontology_repo.commit(ttl=CLASS_A, message="first")

    result = runner.invoke(app, [LOG, "v9.9..HEAD", REPO_FLAG, str(ontology_repo.path)])

    assert result.exit_code != 0
    assert "v9.9" in result.stdout
