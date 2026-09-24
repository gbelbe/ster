"""Step definitions for running ster from scripts (tests/features/cli/scripting.feature).

Each run goes through the real entry point, ``ster.cli.main``, with the exit
code and stderr captured — what a CI job would see.
"""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from typer.testing import CliRunner

import ster.cli
from ster import ask

scenarios("../features/cli/scripting.feature")

GOOD = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://example.org/x#> .
ex:S a skos:ConceptScheme ; skos:prefLabel "Scheme"@en ; skos:hasTopConcept ex:A .
ex:A a skos:Concept ; skos:prefLabel "A"@en ; skos:inScheme ex:S ; skos:topConceptOf ex:S .
"""


@pytest.fixture
def ctx(tmp_path, monkeypatch) -> dict:
    monkeypatch.setattr("ster.cli._state.session_file", None)
    monkeypatch.setattr("ster.cli._file_picker._load_session", lambda: None)
    monkeypatch.setattr("ster.cli._file_picker._save_session", lambda path: None)
    return {"tmp_path": tmp_path, "monkeypatch": monkeypatch}


def _write(ctx: dict, body: str) -> None:
    ctx["file"] = ctx["tmp_path"] / "t.ttl"
    ctx["file"].write_text(body, encoding="utf-8")


def _run(ctx: dict, capsys, *argv: str) -> None:
    ctx["monkeypatch"].setattr("sys.argv", ["ster", *argv])
    try:
        ster.cli.main()
        ctx["code"] = 0
    except SystemExit as exited:
        ctx["code"] = int(exited.code or 0)
    ctx["err"] = capsys.readouterr().err


@given("a valid taxonomy file")
def given_valid(ctx):
    _write(ctx, GOOD)


@given("a taxonomy file with a concept that has no label")
def given_issues(ctx):
    _write(ctx, GOOD + "ex:B a skos:Concept ; skos:inScheme ex:S ; skos:broader ex:A .\n")


@given("a file that is not valid Turtle")
def given_broken(ctx):
    _write(ctx, "@prefix ex: <https://e/> .\nex:a ex:b .\n")


@given("a folder holding one taxonomy file")
def given_folder(ctx):
    _write(ctx, GOOD)
    ctx["monkeypatch"].chdir(ctx["tmp_path"])


@given("ster will hit an unexpected error")
def given_crash(ctx):
    def boom(*_args, **_kwargs):
        raise RuntimeError("something nobody planned for")

    ctx["monkeypatch"].setattr("ster.cli._commands_edit._validate_concept_issues", boom)


@when(parsers.parse('a script runs "ster validate --file" on it'))
def when_validate(ctx, capsys):
    _run(ctx, capsys, "validate", "--file", str(ctx["file"]))


@when(parsers.parse('a script runs "ster validate --file" on a file that does not exist'))
def when_validate_missing(ctx, capsys):
    _run(ctx, capsys, "validate", "--file", str(ctx["tmp_path"] / "nowhere.ttl"))


@when(parsers.parse('a script with no terminal runs "ster validate" there'))
def when_no_terminal(ctx, capsys):
    ctx["monkeypatch"].setattr(ask, "has_terminal", lambda: False)
    _run(ctx, capsys, "validate")


@then(parsers.parse("ster exits with code {code:d}"))
def then_code(ctx, code):
    assert ctx["code"] == code, ctx["err"]


@then("the error names the question and says to pass --file")
def then_names_question(ctx):
    assert "Use this file for this session?" in ctx["err"]
    assert "--file" in ctx["err"]


@then("the error is one line that mentions STER_DEBUG=1")
def then_one_line(ctx):
    assert "Traceback" not in ctx["err"]
    assert "STER_DEBUG=1" in ctx["err"]


@then("every command's --help has an Examples section")
def then_examples():
    app = ster.cli._app.app
    for command in app.registered_commands:
        result = CliRunner().invoke(app, [command.name, "--help"])
        assert "Examples" in result.output, command.name
