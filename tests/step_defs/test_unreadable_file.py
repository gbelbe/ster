"""Step definitions for the unreadable-file guard."""

from __future__ import annotations

import asyncio

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from typer.testing import CliRunner

from ster import store
from ster.cli import app as cli_app
from ster.tui.app import OntologyApp
from ster.tui.unreadable_modal import UnreadableModal

scenarios("../features/io/unreadable_file.feature")

NS = "https://example.com/business-capability/"

CAPABILITIES = f"""\
@prefix ex: <{NS}> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
ex:one a ex:BusinessCapability ; skos:prefLabel "Collect Supplier Information" .
ex:two a ex:BusinessCapability ; skos:prefLabel "Calculate Costs" .
ex:three a ex:BusinessCapability ; skos:prefLabel "Manage Treasury" .
"""

NORMAL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://example.org/t#> .
ex:Tent a skos:Concept ; skos:prefLabel "Tent"@en .
"""

_runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    monkeypatch.setenv("STER_NO_CACHE", "1")


@pytest.fixture(autouse=True)
def _scan_on_open_off():
    """The guard must fire on its own, not through the semanticlint plugin."""
    from ster.plugins.semanticlint import config

    config.set_feature("check_on_open", False)


@pytest.fixture
def ctx(tmp_path):
    return {"tmp_path": tmp_path}


def _open_browser(ctx, path, press=None, settle=2):
    """Run the app to first paint, optionally press a modal button, and record what happened."""

    async def scenario():
        app = OntologyApp(store.load(path), source=path.name, path=path)
        async with app.run_test(size=(120, 40)) as pilot:
            for _ in range(settle):
                await pilot.pause()
            ctx["modal_text"] = _modal_text(app)
            if press is not None:
                app.screen.query_one(f"#{press}").press()
                for _ in range(10):
                    await pilot.pause()
            ctx["screen"] = app.screen
            ctx["tax"] = app.tax

    asyncio.run(scenario())


def _modal_text(app):
    from textual.widgets import Static

    if not isinstance(app.screen, UnreadableModal):
        return ""
    return " ".join(str(node.render()) for node in app.screen.query(Static))


# ──────────────────────────── given ──────────────────────────────────────────


@given('a capability file whose subjects are all typed "ex:BusinessCapability"')
def given_capability_file(ctx):
    path = ctx["tmp_path"] / "business_capabilities.ttl"
    path.write_text(CAPABILITIES, encoding="utf-8")
    ctx["path"] = path
    ctx["before"] = path.read_text(encoding="utf-8")


@given("that type is never declared as a class")
def given_type_undeclared(ctx):
    assert "a owl:Class" not in ctx["path"].read_text(encoding="utf-8")


@given("an empty Turtle file")
def given_empty_file(ctx):
    path = ctx["tmp_path"] / "empty.ttl"
    path.write_text("", encoding="utf-8")
    ctx["path"] = path


@given("a normal SKOS taxonomy file")
def given_normal_file(ctx):
    path = ctx["tmp_path"] / "gear.ttl"
    path.write_text(NORMAL, encoding="utf-8")
    ctx["path"] = path


@given("the unreadable-file modal is open on the capability file")
def given_modal_open(ctx):
    ctx["modal_expected"] = True


# ──────────────────────────── when ───────────────────────────────────────────


@when("I open the capability file in the browser")
@when("I open the empty file in the browser")
@when("I open the normal file in the browser")
def when_open(ctx):
    _open_browser(ctx, ctx["path"])


@when("I choose to declare the missing types")
def when_declare(ctx):
    _open_browser(ctx, ctx["path"], press=UnreadableModal.DECLARE)


@when("I choose to open the file anyway")
def when_open_anyway(ctx):
    _open_browser(ctx, ctx["path"], press=UnreadableModal.OPEN)


@when(parsers.parse('I run "{command}" on the capability file'))
def when_cli(ctx, command):
    args = [*command.split(), str(ctx["path"])]
    ctx["result"] = _runner.invoke(cli_app, args)


# ──────────────────────────── then ───────────────────────────────────────────


@then("the tree is not shown")
def then_tree_hidden(ctx):
    assert isinstance(ctx["screen"], UnreadableModal)


@then("I am told that no entity was recognised")
def then_told_nothing_recognised(ctx):
    assert "recognised no entity" in ctx["modal_text"]


@then(parsers.parse('I am told "{qname}" is used {count:d} times and never declared'))
def then_told_type_count(ctx, qname, count):
    local = qname.split(":", 1)[1]
    assert f"{count} ×  {NS}{local}" in ctx["modal_text"]


@then("the declaration is written through the service")
def then_declaration_written(ctx):
    assert "a owl:Class ." in ctx["path"].read_text(encoding="utf-8")


@then(parsers.parse("the browser shows {count:d} individuals"))
def then_browser_shows_individuals(ctx, count):
    assert len(ctx["tax"].owl_individuals) == count


@then("the browser opens with an empty tree")
def then_browser_empty(ctx):
    assert not isinstance(ctx["screen"], UnreadableModal)
    assert not ctx["tax"].owl_individuals


@then("the file on disk is unchanged")
def then_file_unchanged(ctx):
    assert ctx["path"].read_text(encoding="utf-8") == ctx["before"]


@then("I am told the file contains no triples")
def then_told_no_triples(ctx):
    assert "no triples" in ctx["modal_text"]


@then("no fix is offered")
def then_no_fix(ctx):
    assert not ctx["screen"].query(f"#{UnreadableModal.DECLARE}")


@then(parsers.parse('the output names "{qname}"'))
def then_output_names(ctx, qname):
    assert qname.split(":", 1)[1] in ctx["result"].output


@then("the output prints the declaration to add")
def then_output_declaration(ctx):
    assert "a owl:Class ." in ctx["result"].output


@then("the exit code is not zero")
def then_exit_non_zero(ctx):
    assert ctx["result"].exit_code != 0


@then("no unreadable-file modal appears")
def then_no_modal(ctx):
    assert not isinstance(ctx["screen"], UnreadableModal)
