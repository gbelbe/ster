"""The exit codes a script or CI job can rely on, through the real entry point.

0 success · 1 problems found · 2 wrong usage (or a question with no terminal)
· 3 file missing / unreadable / unsavable · 4 not valid RDF · 5 unexpected.
Before, nearly every failure exited 1, so a CI step could not tell "the
ontology has issues" from "the path is wrong" from "ster crashed".
"""

from __future__ import annotations

from pathlib import Path

import pytest

import ster.cli
from ster import ask

GOOD = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://example.org/x#> .
ex:S a skos:ConceptScheme ; skos:prefLabel "Scheme"@en ; skos:hasTopConcept ex:A .
ex:A a skos:Concept ; skos:prefLabel "A"@en ; skos:inScheme ex:S ; skos:topConceptOf ex:S .
"""
# A concept with no prefLabel: a validation issue, not a broken file.
WITH_ISSUES = GOOD + "ex:B a skos:Concept ; skos:inScheme ex:S ; skos:broader ex:A .\n"


@pytest.fixture(autouse=True)
def _no_remembered_session(monkeypatch):
    """ster remembers the file it last used; each test starts without one."""
    monkeypatch.setattr("ster.cli._state.session_file", None)
    monkeypatch.setattr("ster.cli._file_picker._load_session", lambda: None)
    monkeypatch.setattr("ster.cli._file_picker._save_session", lambda path: None)


def _run(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr("sys.argv", ["ster", *argv])
    with pytest.raises(SystemExit) as exited:
        ster.cli.main()
        raise SystemExit(0)  # a command that returns normally succeeded
    return int(exited.value.code or 0)


def _file(tmp_path: Path, body: str, name: str = "t.ttl") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_a_clean_file_validates_with_exit_0(tmp_path, monkeypatch) -> None:
    assert _run(monkeypatch, "validate", "--file", str(_file(tmp_path, GOOD))) == 0


def test_validation_problems_exit_1(tmp_path, monkeypatch) -> None:
    assert _run(monkeypatch, "validate", "--file", str(_file(tmp_path, WITH_ISSUES))) == 1


def test_a_missing_file_exits_3(tmp_path, monkeypatch) -> None:
    assert _run(monkeypatch, "validate", "--file", str(tmp_path / "nowhere.ttl")) == 3


def test_a_folder_with_no_rdf_file_exits_3(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert _run(monkeypatch, "validate") == 3


def test_broken_turtle_exits_4(tmp_path, monkeypatch) -> None:
    broken = _file(tmp_path, "@prefix ex: <https://e/> .\nex:a ex:b .\n")
    assert _run(monkeypatch, "validate", "--file", str(broken)) == 4


def test_a_file_ster_cannot_model_exits_4(tmp_path, monkeypatch) -> None:
    """Valid RDF, but nothing typed as anything ster models."""
    untyped = _file(tmp_path, '<https://e/a> <https://e/p> "x" .\n', name="t.nt")
    assert _run(monkeypatch, "validate", "--file", str(untyped)) == 4


def test_an_unknown_concept_exits_2(tmp_path, monkeypatch) -> None:
    path = _file(tmp_path, GOOD)
    assert _run(monkeypatch, "label", "NOPE", "en", "x", "--file", str(path)) == 2


def test_a_save_that_fails_exits_3(tmp_path, monkeypatch) -> None:
    path = _file(tmp_path, GOOD)

    def refuse(*_args, **_kwargs):
        raise PermissionError("read-only file system")

    monkeypatch.setattr("ster.store.save", refuse)
    index = ster.store.load(path).handle_index
    handle = next(h for h, uri in index.items() if uri.endswith("#A"))  # the concept
    assert _run(monkeypatch, "label", handle, "fr", "Un", "--file", str(path)) == 3


def test_an_unknown_option_exits_2(tmp_path, monkeypatch) -> None:
    assert _run(monkeypatch, "validate", "--no-such-option") == 2


# ── nobody there to answer ──────────────────────────────────────────────────


def test_a_question_without_a_terminal_exits_2_and_says_what_to_pass(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(ask, "has_terminal", lambda: False)
    monkeypatch.chdir(tmp_path)
    _file(tmp_path, GOOD)  # one file: ster would ask "Use this file for this session?"

    assert _run(monkeypatch, "validate") == 2
    err = capsys.readouterr().err
    assert "Use this file for this session?" in err
    assert "no terminal" in err
    assert "--file" in err


def test_ci_never_stops_on_the_ci_workflow_nudge_regression(tmp_path, monkeypatch) -> None:
    """In a git repo without ster's CI workflow, ster offers to create one — but
    only to a person. Root cause: _resolve_file asked it before anything else,
    even with --file, so every command in CI would have stopped there with exit 2."""
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ask, "has_terminal", lambda: False)
    monkeypatch.setattr("ster.cli._state.ci_check_done", False)
    path = _file(tmp_path, GOOD)

    assert _run(monkeypatch, "validate", "--file", str(path)) == 0


# ── the unexpected ──────────────────────────────────────────────────────────


def _crash(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("something nobody planned for")

    monkeypatch.setattr("ster.cli._commands_edit._validate_concept_issues", boom)


def test_an_unexpected_error_prints_one_line_and_exits_5(tmp_path, monkeypatch, capsys) -> None:
    _crash(monkeypatch)
    code = _run(monkeypatch, "validate", "--file", str(_file(tmp_path, GOOD)))
    err = capsys.readouterr().err
    assert code == 5
    assert "something nobody planned for" in err
    assert "Traceback" not in err
    assert "STER_DEBUG=1" in err


def test_ster_debug_shows_the_full_traceback(tmp_path, monkeypatch) -> None:
    _crash(monkeypatch)
    monkeypatch.setenv("STER_DEBUG", "1")
    monkeypatch.setattr("sys.argv", ["ster", "validate", "--file", str(_file(tmp_path, GOOD))])
    with pytest.raises(RuntimeError, match="nobody planned"):
        ster.cli.main()
