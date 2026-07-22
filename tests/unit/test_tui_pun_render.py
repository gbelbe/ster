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


def test_pun_appears_in_both_the_spine_and_the_ontology_pane(tmp_path) -> None:
    """A pun is both a concept and a class, so it shows in both panes: on the SKOS spine
    (with its bridged subclass) *and* in the Ontology pane as a class."""

    async def scenario() -> None:
        app = _mixed_app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            tree = app.query_one("#tree", Tree)  # unified pane holds the SKOS spine + puns
            ont_tree = app.query_one("#ont-tree", Tree)  # ontology pane holds the OWL classes
            tax_sec = next(n for n in tree.root.children if n.data == detail.TAXONOMY_URI)
            ont_sec = next(n for n in ont_tree.root.children if n.data == detail.OVERVIEW_URI)
            # the pun and its bridged subclass hang on the SKOS spine …
            assert E + "Animal" in _descendant_uris(tax_sec)
            assert E + "Dog" in _descendant_uris(tax_sec)
            # … and the pun now also appears in the Ontology pane (promote → shown in ontology)
            assert E + "Animal" in _descendant_uris(ont_sec)

    _run(scenario)


def test_pure_class_with_no_concept_twin_stays_in_ontology(tmp_path) -> None:
    async def scenario() -> None:
        app = _mixed_app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            tree = app.query_one("#ont-tree", Tree)  # a pure class lives in the ontology pane
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
            # Promote now asks *how* — choose "Create a new class (pun, same URI)".
            assert app.screen.__class__.__name__ == "ChoiceModal"
            await pilot.click("#opt-pun")
            for _ in range(3):
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


# ── foaf:focus link (concept → existing class) ────────────────────────────────

_NO_CLASS = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://ex.org/> .
ex:scheme a skos:ConceptScheme ; skos:hasTopConcept ex:Mammal .
ex:Mammal a skos:Concept ; skos:topConceptOf ex:scheme ; skos:inScheme ex:scheme .
"""


def test_linked_concept_shows_the_classes_individuals_nested(tmp_path) -> None:
    """A concept foaf:focus-linked to a class surfaces that class's individuals under it,
    and renders with the linked (◎) glyph."""

    async def scenario() -> None:
        app = _mixed_app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.tax.concepts[E + "Mammal"].focus = E + "Dog"  # Dog owns individual rex
            app._rebuild_main_tree()
            await pilot.pause()
            mammal = app._uri_nodes[E + "Mammal"]
            assert E + "rex" in {c.data for c in mammal.children}  # the class's individual surfaced
            label = app.query_one("#tree", Tree).render_label(mammal, Style(), Style()).plain
            assert label[2:].startswith(data.ICON["linked"])  # ◎

    _run(scenario)


def test_promote_link_flow_sets_the_foaf_focus(tmp_path) -> None:
    """Promote → 'Link to an existing class' → pick a class → the concept gains foaf:focus."""
    from ster.nav.logic import DetailField

    async def scenario() -> None:
        src = tmp_path / "mixed.ttl"
        src.write_text(MIXED, encoding="utf-8")
        app = OntologyApp(store.load(src), source="mixed.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._detail_uri = E + "Mammal"
            app._run_field_action(
                DetailField("ctx", "", "", editable=False, meta={"action": "promote"})
            )
            await pilot.pause()
            assert app.screen.__class__.__name__ == "ChoiceModal"
            await pilot.click("#opt-link")  # choose the foaf:focus path
            await pilot.pause()
            assert app.screen.__class__.__name__ == "PickerModal"
            app.screen.dismiss(E + "Dog")  # pick the existing class Dog
            for _ in range(3):
                await pilot.pause()
            assert app.tax.concepts[E + "Mammal"].focus == E + "Dog"
            assert app.tax.node_type(E + "Mammal") == "linked"

    _run(scenario)


def test_promote_link_with_no_classes_warns_instead_of_an_empty_picker(tmp_path) -> None:
    async def scenario() -> None:
        src = tmp_path / "notax.ttl"
        src.write_text(_NO_CLASS, encoding="utf-8")
        app = OntologyApp(store.load(src), source="notax.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            notes: list = []
            app.notify = lambda msg, **k: notes.append((msg, k.get("severity")))  # type: ignore[method-assign]
            app._link_concept_to_class(E + "Mammal", src)
            await pilot.pause()
            assert app.screen.__class__.__name__ != "PickerModal"  # no empty picker
            assert any("Add a class" in m for m, _ in notes)

    _run(scenario)


def test_unlink_action_removes_the_focus(tmp_path) -> None:
    from ster.nav.logic import DetailField

    async def scenario() -> None:
        src = tmp_path / "mixed.ttl"
        src.write_text(MIXED, encoding="utf-8")
        app = OntologyApp(store.load(src), source="mixed.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.tax.concepts[E + "Mammal"].focus = E + "Dog"
            app._rebuild_main_tree()
            await pilot.pause()
            app._detail_uri = E + "Mammal"
            app._run_field_action(
                DetailField("ctx", "", "", editable=False, meta={"action": "unlink"})
            )
            for _ in range(3):
                await pilot.pause()
            assert app.tax.concepts[E + "Mammal"].focus is None
            assert app.tax.node_type(E + "Mammal") == "concept"

    _run(scenario)


def test_tagged_individuals_cluster_under_the_concept_and_drop_on_untag(tmp_path) -> None:
    """An individual tagged with a concept (dct:subject) appears nested under it, and
    disappears again when untagged."""
    from ster.operations import DCT_SUBJECT

    async def scenario() -> None:
        app = _mixed_app(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.tax.owl_individuals[E + "rex"].property_values.append((DCT_SUBJECT, E + "Mammal"))
            app._rebuild_main_tree()
            await pilot.pause()
            assert E + "rex" in {c.data for c in app._uri_nodes[E + "Mammal"].children}

            app.tax.owl_individuals[E + "rex"].property_values.remove((DCT_SUBJECT, E + "Mammal"))
            app._rebuild_main_tree()
            await pilot.pause()
            assert E + "rex" not in {c.data for c in app._uri_nodes[E + "Mammal"].children}

    _run(scenario)
