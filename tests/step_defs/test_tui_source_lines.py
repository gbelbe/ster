"""BDD step defs for line numbers and prefix files in the source pane
(tests/features/tui/source_pane_lines_and_prefixes.feature).

Each ``When`` opens the real app on the two files, selects the entity, presses
``r`` and keeps the pane's parts and their side columns for the ``Then`` steps.
"""

from __future__ import annotations

import asyncio

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import store
from ster.tui.app import OntologyApp
from ster.tui.source_view import SourceView

pytestmark = pytest.mark.tui

scenarios("../features/tui/source_pane_lines_and_prefixes.feature")

NS = "https://example.org/agri#"
_HEAD = (
    "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    f"@prefix ex: <{NS}> .\n"
)


@pytest.fixture
def ctx(tmp_path) -> dict:
    return {"tmp_path": tmp_path}


def _write(ctx: dict, name: str, body_line: int, body: str) -> None:
    """Write *body* so that it starts on line *body_line*, after the prefixes."""
    padding = "\n" * (body_line - 1 - _HEAD.count("\n"))
    path = ctx["tmp_path"] / name
    path.write_text(_HEAD + padding + body, encoding="utf-8")
    ctx.setdefault("files", []).append(path)


@given(
    parsers.parse('a main file "{name}" whose statement about "{curie}" starts on line {line:d}')
)
def given_main(ctx, name, curie, line):
    _write(ctx, name, line, f"{curie} a skos:Concept .\n")


@given(
    parsers.parse(
        'a read-only context file "{name}" whose statement pointing to "{curie}" starts on line {line:d}'
    )
)
def given_context(ctx, name, curie, line):
    _write(ctx, name, line, f"ex:Elsewhere rdfs:seeAlso {curie} .\n")


def _open(ctx: dict, curie: str, *, copy: bool = False) -> None:
    main, *context = ctx["files"]
    app = OntologyApp(store.load(main, context=context), source=str(main))

    async def scenario() -> None:
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            app._show(NS + curie.split(":", 1)[1])
            await pilot.press("r")
            await pilot.pause()
            view = app.query_one("#source", SourceView)
            ctx["parts"] = list(zip(view.parts, view.asides, strict=True))
            if copy:
                view.focus()
                await pilot.pause()
                ctx["copied"] = app._focused_copy_value() or ""

    asyncio.run(scenario())


@when(parsers.parse('I select "{curie}" and open the source pane'))
def when_open(ctx, curie):
    _open(ctx, curie)


@when(parsers.parse('I select "{curie}", open the source pane and copy'))
def when_open_and_copy(ctx, curie):
    _open(ctx, curie, copy=True)


def _block_marks(ctx: dict, file: str) -> dict[str, str]:
    """``{first token: line mark}`` for the first Turtle block after the *file* label."""
    after_label = False
    for (kind, text), (left, _right) in ctx["parts"]:
        if kind == "file":
            after_label = text == file
        elif kind == "turtle" and after_label:
            marks = zip(text.splitlines(), left.splitlines() or [""], strict=False)
            return {line.split()[0]: mark for line, mark in marks if mark}
    raise AssertionError(f"no block for {file}")


def _prefix_notes(ctx: dict) -> list[tuple[str, str]]:
    (_, text), (_, right) = next(p for p in ctx["parts"] if p[0][0] == "turtle")
    return list(zip(text.splitlines(), right.splitlines(), strict=True))


@then(parsers.parse('the "{file}" block marks "{curie}" with "{mark}"'))
def then_marks(ctx, file, curie, mark):
    assert _block_marks(ctx, file).get(curie) == mark


@then(parsers.parse('the first prefix is "{prefix}", used by "{files}"'))
def then_first_prefix(ctx, prefix, files):
    line, note = _prefix_notes(ctx)[0]
    assert line.split()[1] == prefix
    assert note == f"← {files}"


@then(parsers.parse('the prefix "{prefix}" is used by "{files}"'))
def then_prefix_used_by(ctx, prefix, files):
    notes = {line.split()[1]: note for line, note in _prefix_notes(ctx)}
    assert notes[prefix] == f"← {files}"


@then("the clipboard holds no line number and no file note")
def then_clean_copy(ctx):
    assert "L4" not in ctx["copied"] and "L5" not in ctx["copied"]
    assert "←" not in ctx["copied"]
