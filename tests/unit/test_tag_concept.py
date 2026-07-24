"""Tag an individual with a concept (dct:subject → concept) — the clustering link.

SKOS's core use: index an instance with a concept without touching its class.
A "Tag with concept…" action on an individual picks a concept and adds a
``dct:subject`` link; the tag then renders on the individual with the concept's
label (not a raw URI), so its themes are visible.
"""

from __future__ import annotations

from pathlib import Path

from ster import store
from ster.core.commands import OwlSetIndividualValue
from ster.nav.logic import build_individual_detail
from ster.tui import edits

E = "https://ex.org/"

TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix ex: <https://ex.org/> .

ex:scheme  a skos:ConceptScheme ; skos:hasTopConcept ex:Outdoor .
ex:Outdoor a skos:Concept ; skos:prefLabel "Outdoor"@en ; skos:topConceptOf ex:scheme .
ex:Product a owl:Class .
ex:prod1   a owl:NamedIndividual, ex:Product ; dct:subject ex:Outdoor .
ex:prod2   a owl:NamedIndividual, ex:Product .
ex:prod3   a owl:NamedIndividual, ex:Product .
"""


def _tax(tmp_path: Path):
    src = tmp_path / "o.ttl"
    src.write_text(TTL, encoding="utf-8")
    return store.load(src)


def test_tag_concept_is_a_concept_picker_action() -> None:
    assert edits.PICKER_ACTIONS["tag_concept"][1] == "concept"


def test_tag_concept_builds_a_dct_subject_value_command(tmp_path) -> None:
    cmd = edits.relation_command("tag_concept", E + "prod1", tmp_path / "o.ttl", E + "Outdoor")
    assert isinstance(cmd, OwlSetIndividualValue)
    assert cmd.ind_uri == E + "prod1"
    assert cmd.prop_uri == edits.DCT_SUBJECT
    assert cmd.new_val_uri == E + "Outdoor"


def test_individual_menu_offers_tag_with_concept() -> None:
    actions = {a for _label, a in edits.context_actions("individual")}
    assert "tag_concept" in actions


def test_tagging_adds_a_dct_subject_link(tmp_path) -> None:
    tax = _tax(tmp_path)
    # start from an untagged product, then apply the tag command
    tax.owl_individuals[E + "prod1"].property_values.clear()
    OwlSetIndividualValue(tmp_path / "o.ttl", E + "prod1", edits.DCT_SUBJECT, E + "Outdoor").apply(
        tax
    )
    assert (edits.DCT_SUBJECT, E + "Outdoor") in tax.owl_individuals[E + "prod1"].property_values


def test_tagged_concept_shows_its_label_not_a_raw_uri(tmp_path) -> None:
    """The dct:subject → concept value renders with the concept's prefLabel, marked with a
    tag icon and navigable to the concept."""
    tax = _tax(tmp_path)
    fields = build_individual_detail(tax, E + "prod1", "en")
    subject_rows = [f for f in fields if f.meta.get("val_uri") == E + "Outdoor"]
    assert subject_rows, "the dct:subject tag should appear as a value row"
    assert subject_rows[0].value == "Outdoor"  # concept label, not the URI
    assert subject_rows[0].meta.get("nav") is True  # navigable to the concept
    assert subject_rows[0].display.startswith("🏷")  # tagged with the tag icon


# ── bulk tagging ──────────────────────────────────────────────────────────────


def test_tag_individual_op_is_idempotent_and_guards(tmp_path) -> None:
    from ster.operations import DCT_SUBJECT, tag_individual_with_concept

    tax = _tax(tmp_path)
    tag_individual_with_concept(tax, E + "prod2", E + "Outdoor")
    tag_individual_with_concept(tax, E + "prod2", E + "Outdoor")  # idempotent
    assert tax.owl_individuals[E + "prod2"].property_values == [(DCT_SUBJECT, E + "Outdoor")]
    tag_individual_with_concept(tax, E + "nope", E + "Outdoor")  # unknown individual → no-op
    tag_individual_with_concept(tax, E + "prod2", E + "Product")  # not a concept → no-op
    assert tax.owl_individuals[E + "prod2"].property_values == [(DCT_SUBJECT, E + "Outdoor")]


def test_tag_individuals_command_tags_every_selected_individual(tmp_path) -> None:
    from ster.core.commands import TagIndividuals
    from ster.operations import DCT_SUBJECT

    tax = _tax(tmp_path)
    TagIndividuals(tmp_path / "o.ttl", (E + "prod2", E + "prod3"), E + "Outdoor").apply(tax)
    for u in (E + "prod2", E + "prod3"):
        assert (DCT_SUBJECT, E + "Outdoor") in tax.owl_individuals[u].property_values


def test_concept_and_pun_menus_offer_bulk_tag_individuals() -> None:
    assert "tag_individuals" in {a for _, a in edits.context_actions("concept")}
    assert "tag_individuals" in {a for _, a in edits.context_actions("promoted")}


def test_object_value_row_menu_offers_go_to_the_target(tmp_path) -> None:
    """The Edit/Delete submenu on a navigable object-property value (here a dct:subject tag)
    also offers "Go to «target»", which navigates to that entity — generic for any object
    property, not just tags."""
    import asyncio

    from ster.tui.app import OntologyApp
    from ster.tui.context_menu import ContextMenu
    from ster.tui.detail_view import DetailRow

    async def scenario() -> None:
        src = tmp_path / "o.ttl"
        src.write_text(TTL, encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(E + "prod1")  # the tagged individual
            await pilot.pause()
            tag = next(
                r for r in app.query(DetailRow) if r.field.meta.get("val_uri") == E + "Outdoor"
            )
            app.on_detail_row_menu_requested(
                DetailRow.MenuRequested(tag.field, tag.delete_field, (0, 0))
            )
            await pilot.pause()
            actions = [a for _, a in app.query_one("#ctx-menu", ContextMenu)._items]
            assert actions == ["row_edit", "row_delete", "row_goto"]
            app.on_context_menu_chosen(ContextMenu.Chosen("row_goto"))
            await pilot.pause()
            assert app._detail_uri == E + "Outdoor"  # navigated to the concept

    asyncio.run(scenario())
