"""BDD step defs for the source pane's per-file blocks (tests/features/tui/source_pane_by_file.feature).

Each ``When`` opens the real app on a main file plus (usually) one read-only
context file, selects the entity, presses ``r``, and keeps what the pane drew —
its ``parts``, a flat list of ``(kind, text)`` — for the ``Then`` steps.
"""

from __future__ import annotations

import asyncio

import pytest
import rdflib
from pytest_bdd import given, parsers, scenarios, then, when

from ster import store
from ster.tui.app import OntologyApp
from ster.tui.source_view import SourceView

pytestmark = pytest.mark.tui

scenarios("../features/tui/source_pane_by_file.feature")

NS = "https://example.org/agri#"
_HEAD = f"@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n@prefix ex: <{NS}> .\n"
_PHRASES = {
    "the English label": '"Agriculture"@en',
    "the French label": '"Agriculture"@fr',
}


@pytest.fixture
def ctx(tmp_path) -> dict:
    return {"tmp_path": tmp_path, "load_context": True}


def _write(ctx: dict, name: str, body: str) -> None:
    path = ctx["tmp_path"] / name
    path.write_text(_HEAD + body, encoding="utf-8")
    ctx[name] = path


def _expected(phrase: str) -> str:
    return _PHRASES.get(phrase, phrase)


def _blocks(parts: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """``{part heading: [(file name, turtle), ...]}`` from the pane's flat parts."""
    parts_by_heading: dict[str, list[tuple[str, str]]] = {}
    heading = file = ""
    for kind, text in parts:
        if kind == "heading":
            heading = text.lower()
            parts_by_heading[heading] = []
        elif kind == "file":
            file = text
        elif kind == "turtle":
            parts_by_heading[heading].append((file, text))
    return parts_by_heading


def _part(ctx: dict, name: str) -> list[tuple[str, str]]:
    key = "point" if "point" in name else name
    return next(blocks for heading, blocks in _blocks(ctx["parts"]).items() if key in heading)


# ── Given ────────────────────────────────────────────────────────────────────


@given(parsers.parse('a main file "{name}" defining the concept "{concept}" with an English label'))
def given_main(ctx, name, concept):
    ctx["main_body"] = f'{concept} a skos:Concept ; skos:prefLabel "Agriculture"@en .\n'
    ctx["main"] = name


@given(parsers.parse('a read-only context file "{name}" adding a French label to "{concept}"'))
def given_context(ctx, name, concept):
    ctx["context_body"] = f'{concept} skos:prefLabel "Agriculture"@fr .\n'
    ctx["context"] = name


@given(
    parsers.parse(
        '"{main_ref}" in "{main}" and "{ctx_ref}" in "{context}" both point to "{concept}"'
    )
)
def given_referrers(ctx, main_ref, main, ctx_ref, context, concept):
    ctx["main_body"] += f"{main_ref} a skos:Concept ; skos:related {concept} .\n"
    ctx["context_body"] += f"{ctx_ref} a skos:Concept ; skos:related {concept} .\n"


@given(parsers.parse('only the main file "{name}" is loaded'))
def given_only_main(ctx, name):
    ctx["load_context"] = False


@given(parsers.parse('"{name}" also asserts the English label of "{concept}"'))
def given_shared_label(ctx, name, concept):
    ctx["context_body"] += f'{concept} skos:prefLabel "Agriculture"@en .\n'


# ── When ─────────────────────────────────────────────────────────────────────


def _open(ctx: dict, curie: str, *, copy: bool = False) -> None:
    _write(ctx, ctx["main"], ctx["main_body"])
    _write(ctx, ctx["context"], ctx["context_body"])
    context = [ctx[ctx["context"]]] if ctx["load_context"] else []
    tax = store.load(ctx[ctx["main"]], context=context)
    app = OntologyApp(tax, source=str(ctx[ctx["main"]]))
    uri = NS + curie.split(":", 1)[1]

    async def scenario() -> None:
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            app._show(uri)
            await pilot.press("r")
            await pilot.pause()
            view = app.query_one("#source", SourceView)
            ctx["parts"] = list(view.parts)
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


# ── Then ─────────────────────────────────────────────────────────────────────


@then(parsers.parse('the "{part}" part has a block for "{file}" holding {what}'))
def then_part_block_holding(ctx, part, file, what):
    ctx["last_part"] = part
    blocks = dict(_part(ctx, part))
    assert file in blocks, f"no {file} block in {part}: {list(blocks)}"
    assert _expected(what.strip('"')) in blocks[file]


@then(parsers.parse('it has a block for "{file}" holding {what}'))
def then_same_part_block_holding(ctx, file, what):
    blocks = dict(_part(ctx, ctx["last_part"]))
    assert file in blocks, f"no {file} block: {list(blocks)}"
    assert _expected(what.strip('"')) in blocks[file]


@then(parsers.parse('the "{part}" part is a single block, named "{file}"'))
def then_single_block(ctx, part, file):
    assert [name for name, _ in _part(ctx, part)] == [file]


@then(parsers.parse('within each part the "{first}" block comes before the "{second}" block'))
def then_order(ctx, first, second):
    for heading, blocks in _blocks(ctx["parts"]).items():
        if heading == "prefixes":
            continue  # shared by every file, so it names none
        names = [name for name, _ in blocks]
        assert names.index(first) < names.index(second)


@then(parsers.parse('the English label appears only in the "{file}" block'))
def then_label_only_in(ctx, file):
    holders = [
        name for name, turtle in _part(ctx, "own statements") if '"Agriculture"@en' in turtle
    ]
    assert holders == [file]


@then("no Turtle block contains a part heading, a file name or a count")
def then_turtle_is_clean(ctx):
    labels = [text for kind, text in ctx["parts"] if kind in ("heading", "file")]
    for kind, text in ctx["parts"]:
        if kind == "turtle":
            assert not any(label in text for label in labels)
            assert "point here" not in text and "points here" not in text


def _turtle_texts(ctx) -> list[str]:
    return [text for kind, text in ctx["parts"] if kind == "turtle"]


@then("the prefixes are shown once, above every block")
def then_prefixes_once(ctx):
    prefixes, *blocks = _turtle_texts(ctx)
    assert "@prefix skos:" in prefixes
    assert not any("@prefix" in block for block in blocks)


@then("every block parses as Turtle with those prefixes")
def then_turtle_parses(ctx):
    prefixes, *blocks = _turtle_texts(ctx)
    for block in blocks:
        rdflib.Graph().parse(data=f"{prefixes}\n{block}", format="turtle")


@then("the clipboard holds every Turtle block and none of the headings")
def then_copied(ctx):
    for kind, text in ctx["parts"]:
        if kind == "turtle":
            assert text in ctx["copied"]
        else:
            assert text not in ctx["copied"]
