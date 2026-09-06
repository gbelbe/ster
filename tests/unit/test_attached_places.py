"""A thing with a location need not be a place.

Most ontologies model geography as a containment chain — continent, country,
region, city — and then hang something else off the end of it. A store, a
warehouse, a building, a sensor: none of those is a *kind of* city, and forcing
them under the geographic class to get them on a map is modelling for the
tool's convenience rather than for the truth.

They say so with a property instead: `Store --locatedIn--> City`. ster reads the
domain and range to find it — the range is inside the containment tree, the
domain is not — so the leaf joins the hierarchy without pretending to be a place.

Both shapes work. An ontology that does subclass its stores under Place is
unaffected; this is an additional way in, not a replacement.
"""

from __future__ import annotations

import pytest
import rdflib

from ster import geo_shapes

NS = "https://example.org/a#"

ATTACHED = f"""\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wgs:  <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix ex:   <{NS}> .

ex:Place a owl:Class ; rdfs:label "Place"@en .
ex:Country a owl:Class ; rdfs:subClassOf ex:Place ; rdfs:label "Country"@en .
ex:City a owl:Class ; rdfs:subClassOf ex:Place ; rdfs:label "City"@en .

# Not a place. A thing that has one.
ex:Store a owl:Class ; rdfs:label "Store"@en .
ex:Warehouse a owl:Class ; rdfs:label "Warehouse"@en .

ex:within a owl:ObjectProperty ; rdfs:domain ex:Place ; rdfs:range ex:Place .
ex:locatedIn a owl:ObjectProperty ; rdfs:domain ex:Store ; rdfs:range ex:City .
ex:sitsIn a owl:ObjectProperty ; rdfs:domain ex:Warehouse ; rdfs:range ex:City .

ex:france a owl:NamedIndividual, ex:Country ; rdfs:label "France"@en ;
    wgs:lat "46.7" ; wgs:long "1.7" .
ex:lyon a owl:NamedIndividual, ex:City ; rdfs:label "Lyon"@en ;
    ex:within ex:france ; wgs:lat "45.76" ; wgs:long "4.84" .
ex:shop a owl:NamedIndividual, ex:Store ; rdfs:label "Shop"@en ;
    ex:locatedIn ex:lyon ; wgs:lat "45.75" ; wgs:long "4.85" .
ex:depot a owl:NamedIndividual, ex:Warehouse ; rdfs:label "Depot"@en ;
    ex:sitsIn ex:lyon ; wgs:lat "45.77" ; wgs:long "4.83" .
"""


@pytest.fixture
def graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=ATTACHED, format="turtle")
    return g


def test_a_store_that_is_not_a_place_still_finds_its_city(graph) -> None:
    assert geo_shapes.place_parent(graph, rdflib.URIRef(NS + "shop")) == NS + "lyon"


def test_it_sits_one_level_below_the_place_it_names(graph) -> None:
    node = rdflib.URIRef(NS + "shop")

    assert geo_shapes.place_level(graph, node) == 2  # country 0, city 1, store 2
    assert geo_shapes.place_ancestors(graph, node) == [NS + "lyon", NS + "france"]


def test_the_level_is_named_by_its_own_class(graph) -> None:
    """It joins the hierarchy without being renamed a place."""
    assert geo_shapes.place_type(graph, rdflib.URIRef(NS + "shop")) == "Store"


def test_any_such_property_works_not_just_one_spelling(graph) -> None:
    """`sitsIn` is discovered the same way `locatedIn` is — by domain and range."""
    assert geo_shapes.place_parent(graph, rdflib.URIRef(NS + "depot")) == NS + "lyon"
    assert geo_shapes.place_type(graph, rdflib.URIRef(NS + "depot")) == "Warehouse"


def test_containment_is_still_only_the_geographic_property(graph) -> None:
    """Attachment must not be mistaken for the drill-down itself."""
    assert geo_shapes._declared_containment(graph) == (NS + "within",)


def test_a_property_between_two_non_places_is_not_attachment(graph) -> None:
    """Only a property *into* the hierarchy attaches; others are facets."""
    graph.add(
        (
            rdflib.URIRef(NS + "supplies"),
            rdflib.RDF.type,
            rdflib.URIRef("http://www.w3.org/2002/07/owl#ObjectProperty"),
        )
    )
    graph.add((rdflib.URIRef(NS + "supplies"), rdflib.RDFS.domain, rdflib.URIRef(NS + "Warehouse")))
    graph.add((rdflib.URIRef(NS + "supplies"), rdflib.RDFS.range, rdflib.URIRef(NS + "Store")))

    assert NS + "supplies" not in geo_shapes.attachment_predicates(graph)


def test_the_subclass_shape_still_works() -> None:
    """The other way round: a store modelled *as* a place is unaffected."""
    g = rdflib.Graph()
    g.parse(
        data=ATTACHED.replace(
            'ex:Store a owl:Class ; rdfs:label "Store"@en .',
            'ex:Store a owl:Class ; rdfs:subClassOf ex:Place ; rdfs:label "Store"@en .',
        ),
        format="turtle",
    )

    assert geo_shapes.place_parent(g, rdflib.URIRef(NS + "shop")) == NS + "lyon"


def test_a_relation_to_a_place_is_not_a_location(graph) -> None:
    """The distinction that stops phantom nodes appearing under every country.

    A business unit names the country it trades in. That points into the
    hierarchy exactly as `locatedIn` does, but a unit is not anywhere — it has
    no coordinates — so treating it as a location would hang one unmapped node
    under each country and inflate every count above it.
    """
    OWL = "http://www.w3.org/2002/07/owl#"
    for triple in (
        (NS + "BusinessUnit", str(rdflib.RDF.type), OWL + "Class"),
        (NS + "operatesIn", str(rdflib.RDF.type), OWL + "ObjectProperty"),
    ):
        graph.add(tuple(rdflib.URIRef(t) for t in triple))
    graph.add(
        (rdflib.URIRef(NS + "operatesIn"), rdflib.RDFS.domain, rdflib.URIRef(NS + "BusinessUnit"))
    )
    graph.add((rdflib.URIRef(NS + "operatesIn"), rdflib.RDFS.range, rdflib.URIRef(NS + "Country")))
    graph.add((rdflib.URIRef(NS + "unit1"), rdflib.RDF.type, rdflib.URIRef(NS + "BusinessUnit")))
    graph.add(
        (
            rdflib.URIRef(NS + "unit1"),
            rdflib.URIRef(NS + "operatesIn"),
            rdflib.URIRef(NS + "france"),
        )
    )
    graph.__dict__.pop("_ster_attachment", None)  # the cache predates these triples

    assert NS + "operatesIn" not in geo_shapes.attachment_predicates(graph)
    assert geo_shapes.place_parent(graph, rdflib.URIRef(NS + "unit1")) is None
