"""A renamed node keeps its remembered position — from the TUI and from the CLI."""

from __future__ import annotations

import asyncio
import json

import pytest

import ster.cli
from ster import graph_layout, store
from ster.core.commands import RenameEntity

TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://ex.org/r#> .
ex:Dog a owl:Class .
ex:S a skos:ConceptScheme ; skos:prefLabel "S"@en ; skos:hasTopConcept ex:Tent .
ex:Tent a skos:Concept ; skos:prefLabel "Tent"@en ; skos:inScheme ex:S ; skos:topConceptOf ex:S .
"""
NS = "https://ex.org/r#"


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setattr("ster.graph_layout._git_root", lambda cwd: None)
    path = tmp_path / "zoo.ttl"
    path.write_text(TTL, encoding="utf-8")
    tax = store.load(path)
    graph_layout.save_positions(
        path, graph_layout.ONTOLOGY_VIEW, {NS + "Dog": (5, 6), NS + "Tent": (7, 8)}, tax
    )
    return path


def _stored(path) -> dict:
    return json.loads(graph_layout.layout_path(path).read_text())[graph_layout.ONTOLOGY_VIEW]


def test_a_rename_in_the_tui_moves_the_position(source) -> None:
    from ster.tui.app import OntologyApp

    app = OntologyApp(store.load(source), source=str(source), path=source)

    async def scenario() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            result = app._service.execute(RenameEntity(source, NS + "Dog", NS + "Hound"))
            assert result.status == "ok"

    asyncio.run(scenario())
    assert _stored(source) == {NS + "Hound": [5, 6], NS + "Tent": [7, 8]}


def test_a_rename_from_the_cli_moves_the_position(source, monkeypatch) -> None:
    index = store.load(source).handle_index
    handle = next(h for h, uri in index.items() if uri == NS + "Tent")
    monkeypatch.setattr("sys.argv", ["ster", "rename", handle, "Shelter", "--file", str(source)])
    try:
        ster.cli.main()
    except SystemExit as exited:
        assert not exited.code
    stored = _stored(source)
    assert NS + "Tent" not in stored
    assert [7, 8] in stored.values()
