"""BDD step definitions for the New-TUI ontology browser (ster.tui)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from ster import store
from ster.model import Concept, ConceptScheme, Definition, Label, LabelType, Taxonomy
from ster.tui.app import OntologyApp

scenarios("../features/tui/new_tui.feature")

DEMO = Path(__file__).resolve().parents[1].parent / "ster" / "tui" / "demo.ttl"
ZOO = "https://example.org/zoo/"
SKOS_NS = "https://example.org/skos/"

PLACEHOLDER = "Select a class"


@pytest.fixture
def ctx():
    return {}


# ── session helper: open the app, run an action, capture end-state ──────────────


def _session(ctx, action: Callable[..., Awaitable[None]] | None = None) -> None:
    async def scenario() -> None:
        app = OntologyApp(ctx["taxonomy"], source="demo")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            if action is not None:
                await action(app, pilot)
                for _ in range(3):
                    await pilot.pause()
            ctx["nodes"] = set(app._uri_nodes)
            ctx["parent_data"] = {
                u: (n.parent.data if n.parent else None) for u, n in app._uri_nodes.items()
            }
            ctx["visible"] = {u: (n.line >= 0) for u, n in app._uri_nodes.items()}
            ctx["detail"] = app._detail_text

    asyncio.run(scenario())


# ── Given ───────────────────────────────────────────────────────────────────--


@given("the zoo ontology is open in the New-TUI")
def given_zoo_open(ctx):
    ctx["taxonomy"] = store.load(DEMO)
    _session(ctx)  # capture the initial tree


@given(
    parsers.parse('a SKOS scheme "{scheme}" with concepts "{a}" and "{b}" is open in the New-TUI')
)
def given_skos_open(ctx, scheme, a, b):
    t = Taxonomy()
    s = ConceptScheme(uri=SKOS_NS + scheme, labels=[Label(lang="en", value=scheme)])
    t.schemes[s.uri] = s
    for name, defn in ((a, "A small feline."), (b, "A loyal dog.")):
        c = Concept(
            uri=SKOS_NS + name,
            top_concept_of=s.uri,
            labels=[Label(lang="en", value=name, type=LabelType.PREF)],
            definitions=[Definition(lang="en", value=defn)],
        )
        t.concepts[c.uri] = c
        s.top_concepts.append(c.uri)
    ctx["taxonomy"] = t
    _session(ctx)


# ── When ──────────────────────────────────────────────────────────────────────


@when(parsers.parse('I move the cursor down to the class "{name}"'))
def when_cursor_down_to(ctx, name):
    target = ZOO + name

    async def act(app, pilot):
        for _ in range(20):
            node = app.query_one("#tree").cursor_node
            if node is not None and node.data == target:
                break
            await pilot.press("down")
            await pilot.pause()

    _session(ctx, act)


@when(parsers.parse('I search for "{query}"'))
def when_search(ctx, query):
    async def act(app, pilot):
        if query.startswith("http"):  # a URI → exercise jump_to directly (incl. not-found)
            app.jump_to(query)
        else:  # a term → drive the fuzzy command palette end-to-end
            await pilot.press("slash")
            await pilot.pause()
            await pilot.press(*query)
            for _ in range(3):
                await pilot.pause()
            await pilot.press("enter")

    _session(ctx, act)


@when(parsers.parse('I select the class "{name}"'))
def when_select_class(ctx, name):
    async def act(app, pilot):
        app.jump_to(ZOO + name)

    _session(ctx, act)


@when("I expand the whole tree")
def when_expand_all(ctx):
    async def act(app, pilot):
        await pilot.press("e")

    _session(ctx, act)


@when("I step right into the detail panel, down a row, then left back to the tree")
def when_arrow_navigate(ctx):
    from textual.widgets import Tree

    from ster.tui.detail_view import DetailRow

    async def act(app, pilot):
        app.jump_to(ZOO + "Person")  # populate the detail pane
        await pilot.pause()
        app.query_one("#tree", Tree).focus()
        await pilot.pause()
        await pilot.press("right")  # tree → detail
        await pilot.pause()
        await pilot.press("down")  # next row
        await pilot.pause()
        ctx["row_focused"] = isinstance(app.focused, DetailRow)
        await pilot.press("left")  # detail → tree
        await pilot.pause()
        ctx["tree_focused"] = app.focused is app.query_one("#tree", Tree)

    _session(ctx, act)


@when(parsers.parse('I run "ster new-tui" on the zoo ontology'))
def when_run_cli(ctx):
    from typer.testing import CliRunner

    from ster.cli import app as cli_app

    with patch("ster.tui.launch") as launch:
        result = CliRunner().invoke(cli_app, ["new-tui", str(DEMO)])
    ctx["cli_result"] = result
    ctx["launch"] = launch


@when('I choose "New-TUI" in the home-screen menu')
def when_choose_menu(ctx):
    from ster.cli import _NEW_TUI_SENTINEL, _dispatch_menu_action

    with patch("ster.tui.launch") as launch:
        ctx["handled"] = _dispatch_menu_action(_NEW_TUI_SENTINEL, [DEMO])
    ctx["launch"] = launch


# ── Then ──────────────────────────────────────────────────────────────────────


@when("I press up from the top of the tree")
def when_wrap_up(ctx):
    from textual.widgets import Tree

    async def act(app, pilot):
        tree = app.query_one("#tree", Tree)
        tree.focus()
        tree.cursor_line = 0
        await pilot.pause()
        await pilot.press("up")  # at the top → wraps to the last node
        await pilot.pause()
        ctx["wrapped_line"] = tree.cursor_line
        ctx["last_line"] = len(tree._tree_lines) - 1

    _session(ctx, act)


@then("the tree cursor lands on the last node")
def then_cursor_on_last(ctx):
    assert ctx["wrapped_line"] == ctx["last_line"] > 0


@then("a detail row was focused along the way")
def then_row_focused(ctx):
    assert ctx["row_focused"]


@then("the tree is focused at the end")
def then_tree_focused(ctx):
    assert ctx["tree_focused"]


@then(parsers.parse('the tree contains the class "{name}"'))
def then_tree_has_class(ctx, name):
    assert ZOO + name in ctx["nodes"]


@then(parsers.parse('the tree contains the property "{label}"'))
def then_tree_has_property(ctx, label):  # noqa: ARG001
    assert ZOO + "hasOwner" in ctx["nodes"]


@then(parsers.parse('the individual "{ind}" is nested under the class "{cls}"'))
def then_individual_nested(ctx, ind, cls):
    assert ctx["parent_data"][ZOO + ind] == ZOO + cls


@then(parsers.parse('the detail panel shows "{text}"'))
def then_detail_shows(ctx, text):
    assert text in ctx["detail"]


@then(parsers.parse('the detail panel shows its owner "{owner}"'))
def then_detail_owner(ctx, owner):
    assert owner in ctx["detail"]


@then(parsers.parse('the detail panel shows the parent "{parent}"'))
def then_detail_parent(ctx, parent):
    assert parent in ctx["detail"]


@then(parsers.parse('the detail panel shows the comment "{comment}"'))
def then_detail_comment(ctx, comment):
    assert comment in ctx["detail"]


@then(parsers.parse('the class "{name}" is visible in the tree'))
def then_class_visible(ctx, name):
    assert ctx["visible"][ZOO + name]


@then("the detail panel still shows the placeholder")
def then_detail_placeholder(ctx):
    assert PLACEHOLDER in ctx["detail"]


@then(parsers.parse('the tree contains the scheme "{scheme}"'))
def then_tree_has_scheme(ctx, scheme):
    assert SKOS_NS + scheme in ctx["nodes"]


@then(parsers.parse('selecting the concept "{name}" shows its definition "{defn}"'))
def then_concept_definition(ctx, name, defn):
    async def act(app, pilot):
        app.jump_to(SKOS_NS + name)

    _session(ctx, act)
    assert defn in ctx["detail"]


@then("the browser is launched with that ontology")
def then_cli_launched(ctx):
    assert ctx["cli_result"].exit_code == 0, ctx["cli_result"].output
    ctx["launch"].assert_called_once()
    (taxonomy,), kwargs = ctx["launch"].call_args
    assert kwargs.get("source") == "demo.ttl"
    assert taxonomy.owl_classes


@then("the browser is launched with the selected files")
def then_menu_launched(ctx):
    assert ctx["handled"] is True
    ctx["launch"].assert_called_once()
