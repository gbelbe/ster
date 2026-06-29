"""Pure view-model adapter tests for the New-TUI (``ster.tui.data``).

No Textual needed — these exercise the taxonomy→view-model functions directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ster import store
from ster.tui import data

DEMO = Path(__file__).resolve().parents[2] / "ster" / "tui" / "demo.ttl"
ZOO = "https://example.org/zoo/"


@pytest.fixture
def tax():
    return store.load(DEMO)


def test_class_hierarchy(tax):
    assert data.class_roots(tax) == [ZOO + "Animal", ZOO + "Person"]
    assert data.subclasses(tax, ZOO + "Animal") == [ZOO + "Bird", ZOO + "Mammal"]
    assert data.subclasses(tax, ZOO + "Mammal") == [ZOO + "Cat", ZOO + "Dog"]


def test_individuals_nest_under_their_class(tax):
    assert data.individuals_of(tax, ZOO + "Dog") == [ZOO + "Rex"]
    assert data.individuals_of(tax, ZOO + "Person") == [ZOO + "Alice"]


def test_properties_listed_and_sorted(tax):
    assert data.properties(tax) == [ZOO + "hasAge", ZOO + "hasOwner"]


def test_property_groups_always_lists_the_three_owl_groups_with_local(tax):
    """The three OWL groups always appear in a fixed order; demo's object/datatype
    properties land under their group's Local list."""
    groups = data.property_groups(tax)
    by_title = {title: (local, ext) for title, local, ext in groups}
    assert [title for title, _, _ in groups][:3] == [
        "Object Properties",
        "Datatype Properties",
        "Annotation Properties",
    ]
    assert by_title["Object Properties"][0] == [ZOO + "hasOwner"]  # Local
    assert by_title["Datatype Properties"][0] == [ZOO + "hasAge"]
    assert by_title["Object Properties"][1] == []  # no External


def test_property_groups_surface_used_but_undeclared_ontology_predicates(tax):
    """Predicates used on the ontology header but never declared (here demo's
    rdfs:label / dcterms:title / dcterms:description) appear under Annotation ›
    External, label-sorted, and never under Local."""
    annotation = next(
        local_ext for t, *local_ext in data.property_groups(tax) if t == "Annotation Properties"
    )
    local, external = annotation
    assert local == []  # none declared locally
    assert external == [  # used-but-undeclared, label-sorted (description, label, title)
        "http://purl.org/dc/terms/description",
        "http://www.w3.org/2000/01/rdf-schema#label",
        "http://purl.org/dc/terms/title",
    ]


def test_property_groups_external_excludes_declared_predicates(tax):
    """A predicate that IS declared locally is not duplicated into External."""
    from ster.model import Label, OWLProperty

    # dcterms:title is used on the header AND now declared locally → Local only.
    title_uri = "http://purl.org/dc/terms/title"
    tax.owl_properties[title_uri] = OWLProperty(
        uri=title_uri, prop_type="AnnotationProperty", labels=[Label("en", "title")]
    )
    annotation = next(le for t, *le in data.property_groups(tax) if t == "Annotation Properties")
    local, external = annotation
    assert title_uri in local
    assert title_uri not in external  # not duplicated


def test_property_groups_unrecognised_external_predicate_is_untyped(tax):
    """A used-but-undeclared predicate that isn't a known annotation property falls
    under Untyped › External."""
    from ster.model import OntologyAnnotation

    weird = "https://vocab.example/x#widget"
    tax.ontology_annotations.append(OntologyAnnotation(weird, "v", is_iri=True))
    untyped = next(le for t, *le in data.property_groups(tax) if t == "Untyped Properties")
    local, external = untyped
    assert local == []
    assert weird in external


def test_search_rows_cover_every_entity(tax):
    labels = {label for label, _uri, _kind in data.search_rows(tax)}
    assert {"Dog", "Eagle", "Rex", "has owner"} <= labels
    assert len(data.search_rows(tax)) == 12  # 7 classes + 3 individuals + 2 properties


def test_label_and_kind(tax):
    assert data.label_of(tax, ZOO + "Dog") == "Dog"
    assert data.kind_of(tax, ZOO + "Dog") == "class"
    assert data.kind_of(tax, ZOO + "Rex") == "individual"
    assert data.kind_of(tax, ZOO + "hasOwner") == "property"
    assert data.label_of(tax, ZOO + "Unknown") == "Unknown"  # fallback to local name


# Detail rendering moved to ster.tui.detail.render_detail — see test_tui_detail.py.
