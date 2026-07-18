"""Phase 1 rendering (Option B): puns merge in the live tree, pure projects don't move.

The Ontology / Taxonomy sections stay. A pun (skos:Concept + owl:Class) renders
with the promoted glyph in the Taxonomy spine, and its OWL subclasses are bridged
in under it — so it appears once (in the taxonomy), never duplicated in the
Ontology section. A pure class with no concept twin stays in the Ontology section.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from rich.style import Style
from textual.widgets import Tree

from ster import store
from ster.tui import data, detail
from ster.tui.app import OntologyApp

E = "https://ex.org/"

MIXED = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://ex.org/> .

ex:scheme a skos:ConceptScheme ; skos:hasTopConcept ex:Animal .
ex:Animal a skos:Concept, owl:Class ; skos:topConceptOf ex:scheme ; skos:inScheme ex:scheme .
ex:Mammal a skos:Concept ; skos:broader ex:Animal ; skos:inScheme ex:scheme .
ex:Dog    a owl:Class ; rdfs:subClassOf ex:Animal .
ex:Cat    a owl:Class .
ex:rex    a owl:NamedIndividual, ex:Dog .
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


def _mixed_app(tmp_path) -> OntologyApp:
    src = tmp_path / "mixed.ttl"
    src.write_text(MIXED, encoding="utf-8")
    return OntologyApp(store.load(src), source="mixed.ttl")


def _section_of(tree: Tree, node) -> str | None:
    """The section (Ontology/Taxonomy) a node lives under: walk up to the child of root."""
    while node.parent is not None and node.parent is not tree.root:
        node = node.parent
    return node.data


def test_pun_renders_with_the_promoted_glyph(tmp_path) -> None:
    async def scenario() -> None:
        app = _mixed_app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            label = tree.render_label(app._uri_nodes[E + "Animal"], Style(), Style()).plain
            assert label[2:].startswith(data.ICON["promoted"])  # ◉, not the plain concept glyph

    _run(scenario)


def test_pun_owl_subclass_bridges_under_the_pun(tmp_path) -> None:
    """The pun's OWL subclass (Dog) hangs under it in the taxonomy spine, with its
    individual (rex) nested under Dog — the SKOS→OWL bridge, rendered."""

    async def scenario() -> None:
        app = _mixed_app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            pun = app._uri_nodes[E + "Animal"]
            child_uris = {c.data for c in pun.children}
            assert E + "Dog" in child_uris  # OWL subclass bridged in
            assert E + "Mammal" in child_uris  # narrower concept also present
            dog = app._uri_nodes[E + "Dog"]
            assert E + "rex" in {c.data for c in dog.children}  # individual under the class

    _run(scenario)


def test_pun_appears_only_in_the_taxonomy_not_duplicated_in_ontology(tmp_path) -> None:
    async def scenario() -> None:
        app = _mixed_app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            # the pun and its bridged subclass live under Taxonomy …
            assert _section_of(tree, app._uri_nodes[E + "Animal"]) == detail.TAXONOMY_URI
            assert _section_of(tree, app._uri_nodes[E + "Dog"]) == detail.TAXONOMY_URI
            # … and the pun is not also sitting in the Ontology section
            ont = next(n for n in tree.root.children if n.data == detail.OVERVIEW_URI)
            assert E + "Animal" not in _descendant_uris(ont)

    _run(scenario)


def test_pure_class_with_no_concept_twin_stays_in_ontology(tmp_path) -> None:
    async def scenario() -> None:
        app = _mixed_app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            assert _section_of(tree, app._uri_nodes[E + "Cat"]) == detail.OVERVIEW_URI

    _run(scenario)


def test_promoting_a_concept_re_renders_it_as_a_pun(tmp_path) -> None:
    """End-to-end: the 'promote' action on a plain concept applies the command and the
    node re-renders with the ◉ pun glyph (and now offers the pun menu)."""
    from ster.nav.logic import DetailField
    from ster.tui import edits

    async def scenario() -> None:
        src = tmp_path / "mixed.ttl"
        src.write_text(MIXED, encoding="utf-8")
        app = OntologyApp(store.load(src), source="mixed.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            tree = app.query_one("#tree", Tree)
            before = tree.render_label(app._uri_nodes[E + "Mammal"], Style(), Style()).plain
            assert before[2:].startswith(data.ICON["concept"])  # ○ to start

            app._detail_uri = E + "Mammal"  # select it, then run the menu action
            app._run_field_action(
                DetailField(
                    "ctx", "", "", editable=False, meta={"type": "action", "action": "promote"}
                )
            )
            await pilot.pause()

            assert app.tax.node_type(E + "Mammal") == "promoted"
            after = tree.render_label(app._uri_nodes[E + "Mammal"], Style(), Style()).plain
            assert after[2:].startswith(data.ICON["promoted"])  # ◉ now
            assert "demote" in {
                a for _, a in edits.context_actions(edits.menu_kind(app.tax, E + "Mammal"))
            }

    _run(scenario)


def test_bulk_tag_individuals_from_a_concept_applies_dct_subject(tmp_path) -> None:
    """End-to-end: 'Tag individuals…' on a concept opens the checklist; ticking an
    individual and confirming adds dct:subject → that concept."""
    from textual.widgets import SelectionList

    from ster.nav.logic import DetailField
    from ster.operations import DCT_SUBJECT
    from ster.tui.multi_picker_modal import MultiPickerModal

    async def scenario() -> None:
        src = tmp_path / "mixed.ttl"
        src.write_text(MIXED, encoding="utf-8")
        app = OntologyApp(store.load(src), source="mixed.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._detail_uri = E + "Mammal"  # tag individuals with the Mammal concept
            app._run_field_action(
                DetailField(
                    "ctx",
                    "",
                    "",
                    editable=False,
                    meta={"type": "action", "action": "tag_individuals"},
                )
            )
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, MultiPickerModal)  # the checklist opened
            sel = app.screen.query_one(SelectionList)
            sel.select(sel.get_option_at_index(0))  # tick the only individual (rex)
            await pilot.pause()
            app.screen.action_confirm()
            for _ in range(20):
                await pilot.pause()
            assert (DCT_SUBJECT, E + "Mammal") in app.tax.owl_individuals[E + "rex"].property_values

    _run(scenario)


NO_CONCEPTS = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix ex: <https://ex.org/> .

ex:Product a owl:Class .
ex:prod1   a owl:NamedIndividual, ex:Product .
"""


def test_tag_with_no_concepts_guides_the_user_instead_of_an_empty_picker(tmp_path) -> None:
    """Tagging an individual when the file has no concepts must not open an empty picker —
    it points the user at creating a concept scheme first."""
    from ster.nav.logic import DetailField
    from ster.tui.picker_modal import PickerModal

    async def scenario() -> None:
        src = tmp_path / "no_concepts.ttl"
        src.write_text(NO_CONCEPTS, encoding="utf-8")
        app = OntologyApp(store.load(src), source="no_concepts.ttl", path=src)
        msgs: list = []
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.notify = lambda *a, **k: msgs.append((a, k))  # type: ignore[method-assign]
            app._detail_uri = E + "prod1"
            app._run_field_action(
                DetailField(
                    "ctx",
                    "",
                    "",
                    editable=False,
                    meta={"type": "action", "action": "tag_concept"},
                )
            )
            await pilot.pause()
            assert not isinstance(app.screen, PickerModal)  # no empty picker opened
            assert any("concept scheme" in str(a) for a, _ in msgs)  # actionable guidance shown

    _run(scenario)


def _descendant_uris(node) -> set:
    out: set = set()
    stack = list(node.children)
    while stack:
        n = stack.pop()
        out.add(n.data)
        stack.extend(n.children)
    return out
