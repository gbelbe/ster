"""Drilling a place hierarchy that the ontology defines, not the code.

The map shows one level at a time — a continent, then its countries, then their
cities — and descends when you click. Which levels exist, what they are called
and what contains what all come from the data, so adding a level to an ontology
adds one to the map with no change here. These tests pin that: the fixture below
is a four-level hierarchy, and one of them inserts a fifth.
"""

from __future__ import annotations

import pytest
import rdflib

from ster import geo_shapes

NS = "https://example.org/p#"
BOX = "POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))"

TTL = f"""\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix geo:  <http://www.opengis.net/ont/geosparql#> .
@prefix wgs:  <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix ex:   <{NS}> .

# The levels are *sibling* classes naming a tier, not a chain of subclasses: a
# country is not a kind of continent. Nesting lives in ex:within.
ex:Place a owl:Class ; rdfs:label "Place"@en .
ex:Continent a owl:Class ; rdfs:label "Continent"@en ; rdfs:subClassOf ex:Place .
ex:Country a owl:Class ; rdfs:label "Country"@en ; rdfs:subClassOf ex:Place .
ex:City a owl:Class ; rdfs:label "City"@en ; rdfs:subClassOf ex:Place .
ex:Shop a owl:Class ; rdfs:label "Shop"@en ; rdfs:subClassOf ex:Place .
ex:within a owl:ObjectProperty ; rdfs:label "within area"@en ;
    rdfs:domain ex:Place ; rdfs:range ex:Place .
ex:turnover a owl:DatatypeProperty ; rdfs:label "turnover"@en .
ex:founded a owl:DatatypeProperty ; rdfs:label "founded"@en .

ex:Euro a owl:NamedIndividual, ex:Continent ; rdfs:label "Euro"@en ;
    geo:asWKT "{BOX}"^^geo:wktLiteral .
ex:Gaul a owl:NamedIndividual, ex:Country ; rdfs:label "Gaul"@en ; ex:within ex:Euro ;
    geo:asWKT "POLYGON((1 1, 5 1, 5 5, 1 5, 1 1))"^^geo:wktLiteral .
ex:Lutetia a owl:NamedIndividual, ex:City ; rdfs:label "Lutetia"@en ; ex:within ex:Gaul ;
    wgs:lat "3.0" ; wgs:long "3.0" .
ex:Forum a owl:NamedIndividual, ex:Shop ; rdfs:label "Forum"@en ; ex:within ex:Lutetia ;
    wgs:lat "3.1" ; wgs:long "3.1" ;
    ex:turnover "1000"^^xsd:decimal ;
    ex:founded "1200" .
"""


@pytest.fixture
def graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=TTL, format="turtle")
    return g


def _n(local: str) -> rdflib.URIRef:
    return rdflib.URIRef(NS + local)


# ── where a place sits ────────────────────────────────────────────────────────


def test_the_level_is_the_depth_of_the_containment_chain(graph):
    """Not the class tree: the level classes are siblings, so subclass depth is
    the same for all of them and would put every place on one level."""
    depths = {
        name: geo_shapes.place_level(graph, _n(name))
        for name in ("Euro", "Gaul", "Lutetia", "Forum")
    }

    assert depths == {"Euro": 0, "Gaul": 1, "Lutetia": 2, "Forum": 3}


def test_the_level_is_named_by_the_entity_class(graph):
    assert geo_shapes.place_type(graph, _n("Gaul")) == "Country"
    assert geo_shapes.place_type(graph, _n("Forum")) == "Shop"


def test_ancestors_come_back_nearest_first(graph):
    assert geo_shapes.place_ancestors(graph, _n("Forum")) == [
        NS + "Lutetia",
        NS + "Gaul",
        NS + "Euro",
    ]


def test_the_top_of_the_chain_has_no_ancestors(graph):
    assert geo_shapes.place_ancestors(graph, _n("Euro")) == []


def test_a_containment_cycle_does_not_hang(graph):
    """Arbitrary RDF can say A is in B and B is in A."""
    graph.add((_n("Euro"), rdflib.URIRef(NS + "within"), _n("Forum")))

    chain = geo_shapes.place_ancestors(graph, _n("Forum"))

    # Stopping on the revisit, not grinding to the 32 cap: a repeated place in
    # the chain would mean the walk went round before something cut it off.
    assert len(chain) == len(set(chain))
    assert len(chain) < 32


# ── inserting a level ─────────────────────────────────────────────────────────


def test_a_new_level_needs_only_the_ontology(graph):
    """The claim, tested: declare a class, add individuals, re-point containment.

    Nothing in this test touches ster's code, and the level lands between the two
    it was inserted into with its own name.
    """
    graph.parse(
        data=f"""\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <{NS}> .
ex:Region a owl:Class ; rdfs:label "Region"@en ; rdfs:subClassOf ex:Place .
ex:Loire a owl:NamedIndividual, ex:Region ; rdfs:label "Loire"@en ; ex:within ex:Gaul .
""",
        format="turtle",
    )
    # the city moves into the new level rather than straight into the country
    graph.remove((_n("Lutetia"), rdflib.URIRef(NS + "within"), _n("Gaul")))
    graph.add((_n("Lutetia"), rdflib.URIRef(NS + "within"), _n("Loire")))

    assert geo_shapes.place_level(graph, _n("Loire")) == 2
    assert geo_shapes.place_type(graph, _n("Loire")) == "Region"
    assert geo_shapes.place_level(graph, _n("Lutetia")) == 3
    assert geo_shapes.place_level(graph, _n("Forum")) == 4
    assert NS + "Loire" in geo_shapes.place_ancestors(graph, _n("Forum"))


# ── figures ───────────────────────────────────────────────────────────────────


def test_a_declared_number_is_a_figure(graph):
    figures = geo_shapes.numeric_literals(graph, _n("Forum"))

    assert [(f["label"], f["value"]) for f in figures] == [("turnover", 1000.0)]


def test_a_year_stored_as_a_string_is_not_a_figure(graph):
    """Regression: "1200" parses as a number and was being added to turnover.

    A postcode or a product code would have been too. A figure has to be declared
    numeric, so the ontology decides what is a quantity.
    """
    labels = [f["label"] for f in geo_shapes.numeric_literals(graph, _n("Forum"))]

    assert "founded" not in labels


def test_coordinates_are_never_figures(graph):
    """They are already on the map, and a summed longitude means nothing."""
    labels = [f["label"].lower() for f in geo_shapes.numeric_literals(graph, _n("Lutetia"))]

    assert not {"lat", "long", "latitude", "longitude"} & set(labels)


def test_a_geometry_literal_is_never_a_figure(graph):
    labels = [f["label"] for f in geo_shapes.numeric_literals(graph, _n("Euro"))]

    assert labels == []


def test_a_figure_is_labelled_from_the_ontology(graph):
    """The property's rdfs:label, not the last segment of its URI."""
    figures = geo_shapes.numeric_literals(graph, _n("Forum"))

    assert figures[0]["label"] == "turnover"


def test_a_figure_falls_back_to_the_local_name(graph):
    """An undeclared property still shows something readable."""
    graph.add(
        (
            _n("Forum"),
            rdflib.URIRef(NS + "shelfMetres"),
            rdflib.Literal(42, datatype=rdflib.URIRef("http://www.w3.org/2001/XMLSchema#integer")),
        )
    )

    labels = [f["label"] for f in geo_shapes.numeric_literals(graph, _n("Forum"))]

    assert "shelfMetres" in labels


def test_the_containment_property_is_inferred_not_hard_coded(graph):
    """ster must not know one ontology's predicate name.

    A self-nesting object property — same domain as range — is what containment
    looks like when an ontology declares its own, so it is found rather than
    listed. The first version of this module named the demo's predicate outright.
    """
    assert NS + "within" in geo_shapes._declared_containment(graph)
