"""Unit tests for ster.metadata_coverage (pure — no TUI)."""

from __future__ import annotations

from ster import metadata_coverage as mc
from ster.model import (
    Label,
    OntologyAnnotation,
    OWLIndividual,
    OWLProperty,
    RDFClass,
    Taxonomy,
)

_SEE_ALSO = "http://www.w3.org/2000/01/rdf-schema#seeAlso"
_SOURCE = "http://purl.org/dc/terms/source"
_PREFLABEL = mc.SKOS_PREFLABEL


def test_entity_predicates_merges_structured_and_generic() -> None:
    cls = RDFClass(
        uri="x",
        labels=[Label("en", "X")],
        annotations=[OntologyAnnotation(_SEE_ALSO, "y", is_iri=True)],
    )
    assert mc.entity_predicates(cls) == {mc.RDFS_LABEL, _SEE_ALSO}


def test_is_labelled_accepts_rdfs_label_or_skos_preflabel() -> None:
    assert mc.is_labelled(RDFClass(uri="a", labels=[Label("en", "A")]))  # rdfs:label
    # skos:prefLabel on a class lives in the generic annotation bucket
    pref = RDFClass(uri="b", annotations=[OntologyAnnotation(_PREFLABEL, "B")])
    assert mc.is_labelled(pref)
    # and on an individual, in its literal assertions
    ind = OWLIndividual(uri="c", literal_values=[(_PREFLABEL, "C", "@en")])
    assert mc.is_labelled(ind)
    assert not mc.is_labelled(RDFClass(uri="d"))  # neither → not labelled


def test_ontology_metadata_pct_is_fraction_of_catalog_present() -> None:
    tax = Taxonomy()
    tax.ontology_annotations = [
        OntologyAnnotation("http://purl.org/dc/terms/title", "t"),
        OntologyAnnotation("http://purl.org/dc/terms/creator", "c"),
    ]
    catalog = [
        ("http://purl.org/dc/terms/title", "title"),
        ("http://purl.org/dc/terms/creator", "creator"),
        ("http://purl.org/dc/terms/license", "license"),
        ("http://purl.org/dc/terms/modified", "modified"),
    ]
    assert mc.ontology_metadata_pct(tax, catalog) == 50  # 2 of 4 present
    assert mc.ontology_metadata_pct(tax, []) is None  # nothing configured


def test_entity_metadata_pct_is_average_per_entity_fill() -> None:
    tax = Taxonomy()
    tax.owl_classes["a"] = RDFClass(
        uri="a", annotations=[OntologyAnnotation(_SEE_ALSO, "r", is_iri=True)]
    )  # 1 of 2 → 0.5
    tax.owl_properties["p"] = OWLProperty(
        uri="p",
        annotations=[
            OntologyAnnotation(_SEE_ALSO, "r", is_iri=True),
            OntologyAnnotation(_SOURCE, "s", is_iri=True),
        ],
    )  # 2 of 2 → 1.0
    catalog = [(_SEE_ALSO, "seeAlso"), (_SOURCE, "source")]
    assert mc.entity_metadata_pct(tax, catalog) == 75  # mean(0.5, 1.0) = 0.75
    assert mc.entity_metadata_pct(tax, []) is None  # nothing configured
    assert mc.entity_metadata_pct(Taxonomy(), catalog) is None  # no entities


def test_overview_coverage_bundles_both_percentages() -> None:
    tax = Taxonomy()
    tax.owl_classes["a"] = RDFClass(uri="a", annotations=[OntologyAnnotation(_SOURCE, "s")])
    cov = mc.overview_coverage(tax, [], [(_SOURCE, "source")])
    assert cov == {"ontology_pct": None, "entity_pct": 100}
