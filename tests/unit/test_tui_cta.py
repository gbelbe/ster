"""Empty-section call-to-action leaves: a "＋ Add …" nudge shown only while a section
(Ontology / Taxonomy / a property type) is empty, hidden once it has content."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from textual.widgets import Tree

from ster import store
from ster.tui.app import OntologyApp, _parse_cta

DEMOMIX = Path(__file__).resolve().parents[2] / "ster" / "tui" / "mixed-gear-demo.ttl"

EMPTY = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix ex: <https://ex.org/> .
ex: a owl:Ontology .
"""


@pytest.fixture(autouse=True)
def _isolate_prefs(tmp_path, monkeypatch):
    from ster import api_server
    from ster.nav import prefs

    monkeypatch.setattr(prefs, "_prefs_path", lambda: tmp_path / "prefs.json")
    monkeypatch.setattr(api_server, "_SERVER_CONFIG_FILE", tmp_path / "server_config.json")
    monkeypatch.setattr(api_server, "_TOKEN_FILE", tmp_path / "api_token")


def _run(scenario: Callable[..., Awaitable[None]]) -> None:
    asyncio.run(scenario())


def _cta_actions(tree: Tree) -> list[str]:
    """Every call-to-action action reachable in *tree*."""
    out: list[str] = []
    stack = list(tree.root.children)
    while stack:
        node = stack.pop()
        action = _parse_cta(node.data)
        if action is not None:
            out.append(action)
        stack.extend(node.children)
    return out


def test_empty_sections_show_add_call_to_actions(tmp_path) -> None:
    async def scenario() -> None:
        src = tmp_path / "empty.ttl"
        src.write_text(EMPTY, encoding="utf-8")
        app = OntologyApp(store.load(src), source="empty.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # CTAs now span the two main panes: 'add_scheme' in the unified pane,
            # 'create_owl_class' in the ontology pane.
            main = set(_cta_actions(app.query_one("#tree", Tree))) | set(
                _cta_actions(app.query_one("#ont-tree", Tree))
            )
            props = set(_cta_actions(app.query_one("#prop-tree", Tree)))
            assert "create_owl_class" in main  # empty Ontology
            assert "add_scheme" in main  # empty Taxonomy
            assert props == {
                "create_object_property",
                "create_datatype_property",
                "create_annotation_property",
            }  # each empty property type

    _run(scenario)


def test_populated_sections_hide_their_call_to_action() -> None:
    """The mixed demo has classes + a scheme (but no properties): main-pane CTAs gone,
    property-type CTAs present."""

    async def scenario() -> None:
        app = OntologyApp(store.load(DEMOMIX), source="mixed-gear-demo.ttl")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            main = set(_cta_actions(app.query_one("#tree", Tree))) | set(
                _cta_actions(app.query_one("#ont-tree", Tree))
            )
            props = set(_cta_actions(app.query_one("#prop-tree", Tree)))
            assert "create_owl_class" not in main  # has classes
            assert "add_scheme" not in main  # has a scheme
            assert "create_object_property" in props  # no properties yet → still nudged

    _run(scenario)


def test_run_cta_dispatches_property_and_class_creates(tmp_path) -> None:
    from unittest.mock import patch

    from ster.tui import detail

    async def scenario() -> None:
        src = tmp_path / "empty.ttl"
        src.write_text(EMPTY, encoding="utf-8")
        app = OntologyApp(store.load(src), source="empty.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            with patch.object(app, "_open_property_create") as opc:
                app._run_cta("create_object_property")
            opc.assert_called_once_with("ObjectProperty")  # property create, no entity target

            with patch.object(app, "_run_field_action") as rfa:
                app._run_cta("create_owl_class")
            assert app._detail_uri == detail.OVERVIEW_URI  # anchored on the section
            assert rfa.call_args[0][0].meta["action"] == "create_owl_class"

            with patch.object(app, "_run_field_action") as rfa:
                app._run_cta("add_scheme")
            assert app._detail_uri == detail.TAXONOMY_URI

    _run(scenario)
