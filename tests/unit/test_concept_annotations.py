"""A concept must keep the predicates ster does not model.

Every other entity type already does. `_parse_class`, `_parse_property` and
`_parse_scheme` each pass a generic bucket to `_dispatch_predicates`, whose own
docstring says it captures "every descriptive predicate the structured fields
don't model, so it round-trips"; individuals use property_values/literal_values.
`_parse_concept` was the one loader that passed no bucket, so opening and saving
a file silently deleted every unmodelled predicate on a skos:Concept —
coordinates, GeoSPARQL geometry, and any project-specific fact.

That is data loss with no error and no warning: ster is an editor, and the file
comes back shorter than it went in.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import rdflib

from ster import store
from ster.model import Concept, OntologyAnnotation

NS = "https://example.org/t#"
GEO_WKT = "http://www.opengis.net/ont/geosparql#asWKT"
WGS_LAT = "http://www.w3.org/2003/01/geo/wgs84_pos#lat"

TTL = f"""\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix wgs:  <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix geo:  <http://www.opengis.net/ont/geosparql#> .
@prefix dct:  <http://purl.org/dc/terms/> .
@prefix ex:   <{NS}> .

ex:S a skos:ConceptScheme ; skos:prefLabel "Scheme"@en .
ex:City a skos:Concept ; skos:prefLabel "City"@en ; skos:inScheme ex:S ;
    wgs:lat "47.28" ; wgs:long "-2.21" ;
    geo:asWKT "POINT(-2.21 47.28)"^^geo:wktLiteral ;
    ex:population "300000" ;
    dct:source <https://example.org/registry> .
"""


@pytest.fixture
def saved(tmp_path) -> Path:
    path = tmp_path / "o.ttl"
    path.write_text(TTL, encoding="utf-8")
    store.save(store.load(path), path)
    return path


def _graph(path: Path) -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(str(path), format="turtle")
    return graph


def _predicates(path: Path, local: str) -> set[str]:
    return {str(p) for p in _graph(path).predicates(rdflib.URIRef(NS + local), None)}


# ── the loss ──────────────────────────────────────────────────────────────────


def test_coordinates_on_a_concept_survive_a_save(saved):
    """The reported symptom: a mapped concept came back unplaceable."""
    assert WGS_LAT in _predicates(saved, "City")


def test_a_geosparql_geometry_on_a_concept_survives_a_save(saved):
    assert GEO_WKT in _predicates(saved, "City")


def test_a_project_specific_predicate_survives_a_save(saved):
    assert NS + "population" in _predicates(saved, "City")


def test_an_iri_valued_predicate_survives_a_save(saved):
    """IRI objects must come back as IRIs, not as strings that look like them."""
    graph = _graph(saved)
    value = graph.value(
        rdflib.URIRef(NS + "City"), rdflib.URIRef("http://purl.org/dc/terms/source")
    )

    assert isinstance(value, rdflib.URIRef)
    assert str(value) == "https://example.org/registry"


def test_the_typed_literal_keeps_its_datatype(saved):
    graph = _graph(saved)
    value = graph.value(rdflib.URIRef(NS + "City"), rdflib.URIRef(GEO_WKT))

    assert value.datatype is not None
    assert "wktLiteral" in str(value.datatype)


def test_the_annotations_reach_the_model(tmp_path):
    path = tmp_path / "o.ttl"
    path.write_text(TTL, encoding="utf-8")

    concept = store.load(path).concepts[NS + "City"]

    assert {a.predicate for a in concept.annotations} >= {WGS_LAT, GEO_WKT, NS + "population"}


# ── what must NOT be captured ─────────────────────────────────────────────────


def test_modelled_predicates_do_not_also_become_annotations(tmp_path):
    """prefLabel has a structured home; capturing it twice would duplicate it."""
    path = tmp_path / "o.ttl"
    path.write_text(TTL, encoding="utf-8")

    concept = store.load(path).concepts[NS + "City"]

    assert not [a for a in concept.annotations if a.predicate.endswith("prefLabel")]


def test_in_scheme_is_not_captured(tmp_path):
    """Regression trap: inScheme is *derived* on save from topConceptOf or the
    broader chain. Capturing it as an annotation writes it a second time, and a
    concept later moved to another scheme would keep asserting the old one."""
    path = tmp_path / "o.ttl"
    path.write_text(TTL, encoding="utf-8")

    concept = store.load(path).concepts[NS + "City"]

    assert not [a for a in concept.annotations if a.predicate.endswith("inScheme")]


def test_a_saved_concept_states_its_scheme_exactly_once(saved):
    graph = _graph(saved)
    schemes = list(
        graph.objects(
            rdflib.URIRef(NS + "City"),
            rdflib.URIRef("http://www.w3.org/2004/02/skos/core#inScheme"),
        )
    )

    assert len(schemes) == 1


def test_rdf_type_is_not_captured(tmp_path):
    path = tmp_path / "o.ttl"
    path.write_text(TTL, encoding="utf-8")

    concept = store.load(path).concepts[NS + "City"]

    assert not [a for a in concept.annotations if a.predicate.endswith("#type")]


def test_a_moved_concept_does_not_resurrect_its_old_scheme(tmp_path):
    """The concrete harm the inScheme trap would cause."""
    path = tmp_path / "o.ttl"
    path.write_text(
        TTL + '\nex:Other a skos:ConceptScheme ; skos:prefLabel "Other"@en .\n',
        encoding="utf-8",
    )
    tax = store.load(path)
    tax.concepts[NS + "City"].top_concept_of = NS + "Other"
    store.save(tax, path)

    graph = _graph(path)
    schemes = {
        str(s)
        for s in graph.objects(
            rdflib.URIRef(NS + "City"),
            rdflib.URIRef("http://www.w3.org/2004/02/skos/core#inScheme"),
        )
    }

    assert schemes == {NS + "Other"}


# ── the round trip is stable ──────────────────────────────────────────────────


def test_saving_twice_does_not_duplicate_anything(saved):
    """An annotation written back must not be re-captured and re-emitted."""
    first = sorted(_predicates(saved, "City"))
    store.save(store.load(saved), saved)

    assert sorted(_predicates(saved, "City")) == first


def test_a_concept_with_nothing_extra_gains_no_annotations(tmp_path):
    path = tmp_path / "plain.ttl"
    path.write_text(
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        f"@prefix ex: <{NS}> .\n"
        'ex:S a skos:ConceptScheme ; skos:prefLabel "S"@en .\n'
        'ex:C a skos:Concept ; skos:prefLabel "C"@en ; skos:inScheme ex:S .\n',
        encoding="utf-8",
    )

    assert store.load(path).concepts[NS + "C"].annotations == []


def test_a_bare_concept_defaults_to_no_annotations():
    assert Concept(uri=NS + "X").annotations == []


def test_an_annotation_added_in_the_model_is_written(tmp_path):
    path = tmp_path / "o.ttl"
    path.write_text(TTL, encoding="utf-8")
    tax = store.load(path)
    tax.concepts[NS + "City"].annotations.append(
        OntologyAnnotation(predicate=NS + "addedLater", value="yes")
    )
    store.save(tax, path)

    assert NS + "addedLater" in _predicates(path, "City")


# ── the boundary of this fix ──────────────────────────────────────────────────
#
# There used to be a test here recording that a bare node referenced by a
# concept was still lost — GeoSPARQL's Feature -> hasGeometry -> Geometry -> WKT
# shape, where the middle node is not a concept, class, individual, property or
# scheme. Its docstring said: "If this test starts failing, that gap has been
# closed — delete it."
#
# Taxonomy.residue closed it. Every triple the model cannot describe is now
# carried verbatim, so the geometry node survives with the link that points at
# it. tests/unit/test_round_trip_fidelity.py is where that is asserted now.


def test_geometry_attached_directly_to_a_concept_survives(tmp_path):
    """The form that is safe today, and what the demo therefore uses."""
    path = tmp_path / "direct.ttl"
    path.write_text(
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        "@prefix geo:  <http://www.opengis.net/ont/geosparql#> .\n"
        f"@prefix ex: <{NS}> .\n"
        'ex:S a skos:ConceptScheme ; skos:prefLabel "S"@en .\n'
        'ex:C a skos:Concept ; skos:prefLabel "C"@en ; skos:inScheme ex:S ;\n'
        '    geo:asWKT "POINT(1 2)"^^geo:wktLiteral .\n',
        encoding="utf-8",
    )
    store.save(store.load(path), path)

    assert GEO_WKT in _predicates(path, "C")
