"""Step definitions for features/cli/sparql_endpoint.feature."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from typer.testing import CliRunner

from ster import sparql_endpoint as ep
from ster import store
from ster.cli import _endpoint as cli_endpoint
from ster.cli import app
from ster.cli._exit import ExitCode
from ster.tui.app import OntologyApp
from tests._fake_endpoint import DEAD_ENDPOINT, TTL, FakeEndpoint

scenarios("../features/cli/sparql_endpoint.feature")

_runner = CliRunner()
MORE = b'@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n@prefix ex: <https://example.org/e#> .\nex:Yurt a skos:Concept ; skos:prefLabel "Yurt"@en .\n'


@pytest.fixture
def ctx(tmp_path, monkeypatch) -> dict[str, Any]:
    monkeypatch.setattr(ep, "_CONFIG_FILE", tmp_path / "endpoint.json")
    state: dict[str, Any] = {"servers": []}
    yield state
    for server in state["servers"]:
        server.close()


@given("a SPARQL endpoint that holds two concepts")  # noqa: V103
def endpoint_with_two_concepts(ctx):
    ctx["server"] = FakeEndpoint()
    ctx["servers"].append(ctx["server"])
    ctx["url"] = ctx["server"].url


@given("the endpoint is down")  # noqa: V103
def endpoint_down(ctx):
    ctx["url"] = DEAD_ENDPOINT


def _show(ctx, *extra: str) -> None:
    ctx["result"] = _runner.invoke(app, ["show", "--endpoint", ctx["url"], "--plain", *extra])


@when("I print the endpoint's tree")  # noqa: V103
def print_tree(ctx):
    _show(ctx)


@when(parsers.parse('I print the endpoint\'s tree for the named graph "{graph}"'))  # noqa: V103
def print_named(ctx, graph):
    _show(ctx, "--graph", graph)


@when("I print the endpoint's tree for my own CONSTRUCT query")  # noqa: V103
def print_own_query(ctx):
    ctx["own"] = "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"
    _show(ctx, "--query", ctx["own"])


@when(parsers.parse("I print the endpoint's tree with a row limit of {limit:d}"))  # noqa: V103
def print_limited(ctx, limit):
    ctx["limit"] = limit
    _show(ctx, "--limit", str(limit))


@then(parsers.parse('the tree shows the concept "{label}"'))  # noqa: V103
def tree_shows(ctx, label):
    assert label in ctx["result"].output


@then("the endpoint was asked for a CONSTRUCT of the default graph")  # noqa: V103
def asked_default(ctx):
    sent = ctx["server"].requests[0]["query"]
    assert sent.startswith("CONSTRUCT") and "GRAPH" not in sent


@then("the endpoint was asked for that named graph")  # noqa: V103
def asked_named(ctx):
    assert "GRAPH <https://example.org/graphs/arch>" in ctx["server"].requests[0]["query"]


@then("the endpoint received my query unchanged")  # noqa: V103
def received_own(ctx):
    assert ctx["server"].requests[0]["query"] == ctx["own"]


@then(parsers.parse("the endpoint was asked for at most {limit:d} rows"))  # noqa: V103
def asked_limit(ctx, limit):
    assert ctx["server"].requests[0]["query"].endswith(f"LIMIT {limit}")


@then("I am told the row limit was reached")  # noqa: V103
def told_truncated(ctx):
    assert "Row limit" in ctx["result"].output


@then("the command fails and says the endpoint could not be reached")  # noqa: V103
def failed_unreachable(ctx):
    assert ctx["result"].exit_code == ExitCode.FILE
    assert "Could not reach" in ctx["result"].output


# ── the viewer ────────────────────────────────────────────────────────────────


def _open_viewer(ctx, steps) -> None:
    """Run the app on the endpoint's loader and call *steps(app, pilot)* once it is up."""
    snapshots = [ep.load(ep.EndpointSource(ctx["url"]))]
    ctx["loads"] = 0

    def loader(_progress):
        ctx["loads"] += 1
        if ctx["loads"] == 1:
            return snapshots[0].taxonomy, None
        return store.taxonomy_from_bytes(TTL + MORE), None

    app_ = OntologyApp(None, source=ctx["url"], progressive_startup=True, loader=loader)

    async def scenario():
        async with app_.run_test(size=(100, 30)) as pilot:
            for _ in range(200):
                if app_._loaded_successfully and app_._browser_ready:
                    break
                await pilot.pause(0.05)
            await steps(app_, pilot)

    asyncio.run(scenario())
    ctx["app"] = app_


@when("I open the endpoint in the viewer")  # noqa: V103
def open_viewer(ctx, monkeypatch):
    notes: list[str] = []
    monkeypatch.setattr(OntologyApp, "notify", lambda _s, msg, **_kw: notes.append(str(msg)))
    ctx["notes"] = notes

    async def steps(app_, _pilot):
        ctx["service"] = app_._service
        app_._apply_command(object())

    _open_viewer(ctx, steps)


@then("editing is refused as read-only")  # noqa: V103
def refused(ctx):
    assert ctx["service"] is None
    assert any("read-only" in n.lower() for n in ctx["notes"])


@when("the endpoint then holds a third concept and I press re-fetch")  # noqa: V103
def refetch(ctx, monkeypatch):
    monkeypatch.setattr(OntologyApp, "notify", lambda *_a, **_k: None)

    async def steps(app_, pilot):
        app_.action_refetch()
        for _ in range(200):
            if "https://example.org/e#Yurt" in app_.tax.concepts:
                break
            await pilot.pause(0.05)

    _open_viewer(ctx, steps)


@then("the viewer shows the third concept")  # noqa: V103
def shows_third(ctx):
    assert "https://example.org/e#Yurt" in ctx["app"].tax.concepts


# ── the home menu ─────────────────────────────────────────────────────────────


@when("I choose the endpoint entry in the home menu and answer its questions")  # noqa: V103
def home_menu(ctx, monkeypatch):
    launched: list[ep.EndpointSource] = []
    answers = [ctx["url"], "graph", "https://example.org/graphs/arch", "40", ""]
    monkeypatch.setattr("ster.ask.text", lambda *_a, **_k: answers.pop(0))
    monkeypatch.setattr("ster.cli._viewer._is_interactive_terminal", lambda: True)
    monkeypatch.setattr(
        "ster.tui.launch_endpoint", lambda source, lang="en": launched.append(source)
    )
    cli_endpoint.run_endpoint_interactive()
    ctx["launched"] = launched


@then("the viewer opens on that endpoint with the answers I gave")  # noqa: V103
def opened_with_answers(ctx):
    source = ctx["launched"][0]
    assert (source.url, source.graph, source.limit) == (
        ctx["url"],
        "https://example.org/graphs/arch",
        40,
    )
