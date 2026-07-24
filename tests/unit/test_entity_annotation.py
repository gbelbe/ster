"""Adding a configured annotation to an OWL entity.

The config panel's entity-metadata catalog offers predicates like rdfs:seeAlso and
dcterms:source on any class / property / individual. ``set_entity_annotation`` writes
one, dispatching to the storage each kind round-trips through: the generic
``.annotations`` bucket for classes and properties, and an object (IRI) or literal
property assertion for individuals.
"""

from __future__ import annotations

from pathlib import Path

from ster import store
from ster.domain.owl import remove_entity_annotation, set_entity_annotation

E = "https://ex.org/"
SEEALSO = "http://www.w3.org/2000/01/rdf-schema#seeAlso"
SOURCE = "http://purl.org/dc/terms/source"

TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <https://ex.org/> .

ex:Product a owl:Class .
ex:hasPart a owl:ObjectProperty .
ex:prod1   a owl:NamedIndividual, ex:Product .
"""


def _tax(tmp_path: Path):
    src = tmp_path / "o.ttl"
    src.write_text(TTL, encoding="utf-8")
    return store.load(src)


def test_set_entity_annotation_on_class_uses_annotations_bucket(tmp_path) -> None:
    tax = _tax(tmp_path)
    set_entity_annotation(tax, E + "Product", SEEALSO, E + "ref", is_iri=True)
    anns = tax.owl_classes[E + "Product"].annotations
    assert [(a.predicate, a.value, a.is_iri) for a in anns] == [(SEEALSO, E + "ref", True)]


def test_set_entity_annotation_on_property_uses_annotations_bucket(tmp_path) -> None:
    tax = _tax(tmp_path)
    set_entity_annotation(tax, E + "hasPart", SOURCE, "handbook", is_iri=False)
    anns = tax.owl_properties[E + "hasPart"].annotations
    assert [(a.predicate, a.value) for a in anns] == [(SOURCE, "handbook")]


def test_set_entity_annotation_iri_on_individual_is_a_property_value(tmp_path) -> None:
    tax = _tax(tmp_path)
    set_entity_annotation(tax, E + "prod1", SEEALSO, E + "ref", is_iri=True)
    assert (SEEALSO, E + "ref") in tax.owl_individuals[E + "prod1"].property_values


def test_set_entity_annotation_literal_on_individual_is_a_literal_value(tmp_path) -> None:
    tax = _tax(tmp_path)
    set_entity_annotation(tax, E + "prod1", SOURCE, "handbook", is_iri=False)
    triples = tax.owl_individuals[E + "prod1"].literal_values
    assert any(p == SOURCE and v == "handbook" for p, v, _dt in triples)


def test_set_entity_annotation_is_idempotent_and_guards_unknown(tmp_path) -> None:
    tax = _tax(tmp_path)
    set_entity_annotation(tax, E + "Product", SEEALSO, E + "ref", is_iri=True)
    set_entity_annotation(tax, E + "Product", SEEALSO, E + "ref", is_iri=True)  # no dup
    assert len(tax.owl_classes[E + "Product"].annotations) == 1
    set_entity_annotation(tax, E + "nope", SEEALSO, E + "ref", is_iri=True)  # unknown → no raise


def test_remove_entity_annotation_from_class(tmp_path) -> None:
    tax = _tax(tmp_path)
    set_entity_annotation(tax, E + "Product", SEEALSO, E + "ref", is_iri=True)
    remove_entity_annotation(tax, E + "Product", SEEALSO, E + "ref")
    assert tax.owl_classes[E + "Product"].annotations == []


def test_entity_set_annotation_command_applies(tmp_path) -> None:
    from ster.core.commands import EntityRemoveAnnotation, EntitySetAnnotation

    tax = _tax(tmp_path)
    EntitySetAnnotation(tmp_path / "o.ttl", E + "Product", SEEALSO, E + "ref", is_iri=True).apply(
        tax
    )
    assert any(a.value == E + "ref" for a in tax.owl_classes[E + "Product"].annotations)
    EntityRemoveAnnotation(tmp_path / "o.ttl", E + "Product", SEEALSO, E + "ref").apply(tax)
    assert tax.owl_classes[E + "Product"].annotations == []


# ── rendering: the per-entity Metadata section ────────────────────────────────


def _catalog():
    from ster.metadata_coverage import MetaProp

    return [MetaProp(SEEALSO, "rdfs:seeAlso  (IRI)"), MetaProp(SOURCE, "dcterms:source")]


def test_class_page_shows_add_cta_for_each_missing_configured_predicate(tmp_path) -> None:
    from ster.tui.detail import _fields_for

    tax = _tax(tmp_path)
    fields = _fields_for(tax, E + "Product", "en", entity_metadata_props=_catalog())
    ctas = [f for f in fields if f.meta.get("action") == "add_entity_annotation"]
    assert {f.meta["predicate"] for f in ctas} == {SEEALSO, SOURCE}
    assert "Metadata" in [
        f.display for f in fields if f.meta.get("type", "").startswith("separator")
    ]


def test_present_annotation_shows_value_row_and_no_cta_for_it(tmp_path) -> None:
    from ster.tui.detail import _fields_for

    tax = _tax(tmp_path)
    set_entity_annotation(tax, E + "Product", SEEALSO, E + "ref", is_iri=True)
    fields = _fields_for(tax, E + "Product", "en", entity_metadata_props=_catalog())
    # the existing value renders as an editable entity_annotation row …
    assert any(f.meta.get("type") == "entity_annotation" and f.value == E + "ref" for f in fields)
    # … and its predicate no longer has an add CTA (only the still-missing one does)
    ctas = [f.meta["predicate"] for f in fields if f.meta.get("action") == "add_entity_annotation"]
    assert ctas == [SOURCE]


def test_no_metadata_section_when_catalog_unconfigured(tmp_path) -> None:
    from ster.tui.detail import _fields_for

    tax = _tax(tmp_path)
    fields = _fields_for(tax, E + "Product", "en", entity_metadata_props=None)
    assert "Metadata" not in [
        f.display for f in fields if f.meta.get("type", "").startswith("separator")
    ]


def test_individual_page_shows_add_cta(tmp_path) -> None:
    from ster.tui.detail import _fields_for

    tax = _tax(tmp_path)
    fields = _fields_for(tax, E + "prod1", "en", entity_metadata_props=_catalog())
    ctas = {f.meta["predicate"] for f in fields if f.meta.get("action") == "add_entity_annotation"}
    assert ctas == {SEEALSO, SOURCE}


def test_add_entity_annotation_handler_adds_the_value(tmp_path) -> None:
    """Activating a '+ Add <predicate>' affordance on a class opens a value modal; submitting
    it writes the annotation onto the entity."""
    import asyncio

    from textual.widgets import Input

    from ster.tui.app import OntologyApp
    from ster.tui.detail_view import DetailRow

    async def scenario() -> None:
        src = tmp_path / "o.ttl"
        src.write_text(TTL, encoding="utf-8")
        app = OntologyApp(store.load(src), source="o.ttl", path=src)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._show(E + "Product")
            await pilot.pause()
            cta = next(
                r
                for r in app.query(DetailRow)
                if r.field.meta.get("action") == "add_entity_annotation"
                and r.field.meta.get("predicate") == SEEALSO
            )
            cta.focus()
            await pilot.press("enter")  # opens the value modal
            await pilot.pause()
            app.screen.query_one("#edit-input", Input).value = E + "ref"
            await pilot.press("enter")
            await pilot.pause()
            assert any(
                a.predicate == SEEALSO and a.value == E + "ref"
                for a in app.tax.owl_classes[E + "Product"].annotations
            )

    asyncio.run(scenario())


def test_entity_annotation_round_trips_through_store(tmp_path) -> None:
    """A class annotation set in memory survives a save + reload."""
    src = tmp_path / "o.ttl"
    src.write_text(TTL, encoding="utf-8")
    tax = store.load(src)
    set_entity_annotation(tax, E + "Product", SEEALSO, E + "ref", is_iri=True)
    store.save(tax, src)
    reloaded = store.load(src)
    anns = reloaded.owl_classes[E + "Product"].annotations
    assert any(a.predicate == SEEALSO and a.value == E + "ref" for a in anns)
