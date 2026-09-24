"""Step definitions for the remembered graph layout
(tests/features/ui/graph_layout_memory.feature).

Driven through what the graph page itself uses — /api/layout on a real app —
plus the TaxonomyService for model changes, so a rename reaches the layout the
way it does in the TUI.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

from ster import graph_layout, store
from ster.api import SSEBroadcaster, create_app
from ster.core.adapters import StorePersistence
from ster.core.commands import OwlDeleteClass, OwlMoveClass, RenameEntity
from ster.core.service import TaxonomyService
from ster.workspace import TaxonomyWorkspace

scenarios("../features/ui/graph_layout_memory.feature")

NS = "https://ex.org/zoo#"
TOKEN = "t"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def ctx(tmp_path, monkeypatch) -> dict:
    monkeypatch.setattr("ster.graph_layout._git_root", lambda cwd: None)
    return {"source": tmp_path / "zoo.ttl"}


def _client(ctx: dict) -> TestClient:
    tax = store.load(ctx["source"])
    return TestClient(
        create_app(tax, TOKEN, SSEBroadcaster(), lambda t: None, file_path=ctx["source"])
    )


def _service(ctx: dict) -> TaxonomyService:
    workspace = TaxonomyWorkspace.from_taxonomy(store.load(ctx["source"]), ctx["source"])
    service = TaxonomyService(workspace, StorePersistence())
    service.add_rename_listener(graph_layout.rename_nodes)
    return service


@given(parsers.parse('an ontology with the classes "{a}", "{b}" and "{c}"'))
def given_ontology(ctx, a, b, c):
    lines = ["@prefix owl: <http://www.w3.org/2002/07/owl#> .", f"@prefix ex: <{NS}> ."]
    lines += [f"ex:{name} a owl:Class ." for name in (a, b, c)]
    Path(ctx["source"]).write_text("\n".join(lines) + "\n", encoding="utf-8")


@given(parsers.parse('I left "{name}" at {x:d}, {y:d} in the graph'))
@when(parsers.parse('I leave "{name}" at {x:d}, {y:d}'))
def leave(ctx, name, x, y):
    response = _client(ctx).put(
        "/api/layout", json={"positions": {NS + name: [x, y]}}, headers=AUTH
    )
    assert response.status_code == 200


@given("the layout file has been corrupted")
def given_corrupted(ctx):
    graph_layout.layout_path(ctx["source"]).write_text("{ <<<<<<< HEAD", encoding="utf-8")


@when("ster is reopened on the same project")
def when_reopened(ctx):
    pass  # every step builds a fresh app from the files on disk, as a restart does


@when(parsers.parse('"{name}" is deleted from the ontology'))
def when_deleted(ctx, name):
    assert (
        _service(ctx).execute(OwlDeleteClass(ctx["source"], NS + name, "keep_all")).status == "ok"
    )


@when("the graph saves any position")
def when_saves(ctx):
    leave(ctx, "Cat", 1, 1)


@when(parsers.parse('"{old}" is renamed to "{new}"'))
def when_renamed(ctx, old, new):
    assert _service(ctx).execute(RenameEntity(ctx["source"], NS + old, NS + new)).status == "ok"


@when(parsers.parse('"{child}" becomes a subclass of "{parent}"'))
def when_subclassed(ctx, child, parent):
    assert (
        _service(ctx).execute(OwlMoveClass(ctx["source"], NS + child, NS + parent)).status == "ok"
    )


@when("I reset the layout")
def when_reset(ctx):
    assert _client(ctx).delete("/api/layout", headers=AUTH).status_code == 200


@then(parsers.parse('the graph places "{name}" at {x:d}, {y:d}'))
def then_placed(ctx, name, x, y):
    positions = _client(ctx).get("/api/layout", headers=AUTH).json()["positions"]
    assert positions.get(NS + name) == [x, y]


@then(parsers.parse('the layout file no longer mentions "{name}"'))
def then_not_mentioned(ctx, name):
    assert NS + name not in graph_layout.layout_path(ctx["source"]).read_text()


@then("the graph has no remembered positions")
def then_nothing(ctx):
    assert _client(ctx).get("/api/layout", headers=AUTH).json() == {"positions": {}}
