"""Unit tests for the layer-agnostic rename front: rename_kind,
count_uri_references, and rename_entity_uri.

These dispatch to the SKOS-specialized primitives (rename_uri /
count_concept_uri_references) and the OWL-specialized primitives
(rename_owl_uri / count_owl_uri_references) depending on which layer(s)
own the URI. A node promoted to both layers is handled in both.
"""

from __future__ import annotations

import pytest

from ster.exceptions import ConceptNotFoundError, URIAlreadyExistsError
from ster.model import (
    Concept,
    Label,
    LabelType,
    OWLIndividual,
    OWLProperty,
    RDFClass,
    Taxonomy,
)
from ster.operations import (
    count_concept_uri_references,
    count_owl_uri_references,
    count_uri_references,
    rename_entity_uri,
    rename_kind,
)

NS = "https://example.org/onto#"


def uri(name: str) -> str:
    return NS + name


def _concept(name: str) -> Concept:
    return Concept(uri=uri(name), labels=[Label("en", name, LabelType.PREF)])


# ── rename_kind ─────────────────────────────────────────────────────────────


def test_rename_kind_concept():
    t = Taxonomy()
    t.concepts[uri("Dog")] = _concept("Dog")
    assert rename_kind(t, uri("Dog")) == "concept"


def test_rename_kind_class():
    t = Taxonomy()
    t.owl_classes[uri("Dog")] = RDFClass(uri=uri("Dog"))
    assert rename_kind(t, uri("Dog")) == "class"


def test_rename_kind_individual():
    t = Taxonomy()
    t.owl_individuals[uri("Rex")] = OWLIndividual(uri=uri("Rex"))
    assert rename_kind(t, uri("Rex")) == "individual"


def test_rename_kind_property():
    t = Taxonomy()
    t.owl_properties[uri("knows")] = OWLProperty(uri=uri("knows"))
    assert rename_kind(t, uri("knows")) == "property"


def test_rename_kind_promoted():
    t = Taxonomy()
    t.concepts[uri("Dog")] = _concept("Dog")
    t.owl_classes[uri("Dog")] = RDFClass(uri=uri("Dog"))
    assert rename_kind(t, uri("Dog")) == "promoted"


# ── count_uri_references routing ──────────────────────────────────────────────


def test_count_uri_references_routes_to_concept():
    t = Taxonomy()
    t.concepts[uri("Animal")] = _concept("Animal")
    t.concepts[uri("Dog")] = _concept("Dog")
    t.concepts[uri("Dog")].broader.append(uri("Animal"))
    assert count_uri_references(t, uri("Animal")) == count_concept_uri_references(
        t, uri("Animal")
    )


def test_count_uri_references_routes_to_owl():
    t = Taxonomy()
    t.owl_classes[uri("Animal")] = RDFClass(uri=uri("Animal"))
    t.owl_classes[uri("Dog")] = RDFClass(uri=uri("Dog"), sub_class_of=[uri("Animal")])
    assert count_uri_references(t, uri("Animal")) == count_owl_uri_references(t, uri("Animal"))


def test_count_uri_references_promoted_sums_both_layers():
    t = Taxonomy()
    t.concepts[uri("Animal")] = _concept("Animal")
    t.concepts[uri("Dog")] = _concept("Dog")
    t.concepts[uri("Dog")].broader.append(uri("Animal"))
    t.owl_classes[uri("Animal")] = RDFClass(uri=uri("Animal"))
    t.owl_classes[uri("Pet")] = RDFClass(uri=uri("Pet"), sub_class_of=[uri("Animal")])
    total = count_uri_references(t, uri("Animal"))
    assert total == count_concept_uri_references(t, uri("Animal")) + count_owl_uri_references(
        t, uri("Animal")
    )


# ── rename_entity_uri dispatch ────────────────────────────────────────────────


def test_rename_entity_uri_renames_concept_and_propagates_match():
    t = Taxonomy()
    t.concepts[uri("Cat")] = _concept("Cat")
    t.concepts[uri("Dog")] = _concept("Dog")
    t.concepts[uri("Dog")].exact_match.append(uri("Cat"))
    rename_entity_uri(t, uri("Cat"), uri("Feline"))
    assert uri("Feline") in t.concepts
    assert uri("Cat") not in t.concepts
    assert uri("Feline") in t.concepts[uri("Dog")].exact_match


def test_rename_entity_uri_renames_owl_property():
    t = Taxonomy()
    t.owl_properties[uri("hasMaster")] = OWLProperty(uri=uri("hasMaster"))
    rename_entity_uri(t, uri("hasMaster"), uri("ownedBy"))
    assert uri("ownedBy") in t.owl_properties
    assert uri("hasMaster") not in t.owl_properties


def test_rename_entity_uri_renames_promoted_in_both_layers():
    t = Taxonomy()
    t.concepts[uri("Animal")] = _concept("Animal")
    t.concepts[uri("Dog")] = _concept("Dog")
    t.concepts[uri("Dog")].broader.append(uri("Animal"))
    t.owl_classes[uri("Animal")] = RDFClass(uri=uri("Animal"))
    t.owl_classes[uri("Pet")] = RDFClass(uri=uri("Pet"), sub_class_of=[uri("Animal")])
    rename_entity_uri(t, uri("Animal"), uri("Creature"))
    assert uri("Creature") in t.concepts
    assert uri("Creature") in t.owl_classes
    assert uri("Animal") not in t.concepts
    assert uri("Animal") not in t.owl_classes
    assert uri("Creature") in t.concepts[uri("Dog")].broader
    assert uri("Creature") in t.owl_classes[uri("Pet")].sub_class_of


def test_rename_entity_uri_raises_on_collision_in_concept_layer():
    t = Taxonomy()
    t.concepts[uri("Cat")] = _concept("Cat")
    t.concepts[uri("Dog")] = _concept("Dog")
    with pytest.raises(URIAlreadyExistsError):
        rename_entity_uri(t, uri("Cat"), uri("Dog"))


def test_rename_entity_uri_raises_on_collision_in_owl_layer():
    t = Taxonomy()
    t.owl_classes[uri("Cat")] = RDFClass(uri=uri("Cat"))
    t.owl_individuals[uri("Rex")] = OWLIndividual(uri=uri("Rex"))
    with pytest.raises(URIAlreadyExistsError):
        rename_entity_uri(t, uri("Cat"), uri("Rex"))


def test_rename_entity_uri_unknown_uri_raises():
    t = Taxonomy()
    t.concepts[uri("Dog")] = _concept("Dog")
    with pytest.raises(ConceptNotFoundError):
        # new URI is free, but the old URI exists in no layer
        rename_entity_uri(t, uri("Ghost"), uri("Phantom"))
