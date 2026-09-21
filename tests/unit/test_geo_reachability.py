"""What a file, and a node inside it, can put on a map.

Two questions the TUI has to answer before opening the map at all. Whether the
file holds any geography — opening an empty map on a vocabulary that has none
tells the reader nothing and looks broken. And whether the selected entity has
any of its own, directly or through what it is linked to, because a brand
carries no coordinates and its stores carry them all.

Both are answered from the graph, with no vocabulary named: coordinates are
W3C Basic Geo or a GeoSPARQL geometry, and the walk follows object properties
without caring what they mean.
"""

from __future__ import annotations

import rdflib

from ster.geo_shapes import anything_located, located_from

NS = "https://ex.org/geo#"


def _graph(turtle: str) -> rdflib.Graph:
    return rdflib.Graph().parse(
        data="""
@prefix ex:   <https://ex.org/geo#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wgs:  <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix geo:  <http://www.opengis.net/ont/geosparql#> .
"""
        + turtle,
        format="turtle",
    )


# ── does the file hold any geography at all ───────────────────────────────────


def test_a_file_with_no_coordinates_is_reported_as_unmappable():
    """The case that matters: a taxonomy of concepts and nothing placeable."""
    graph = _graph("""
ex:Fruit  rdfs:label "Fruit" .
ex:Apple  rdfs:subClassOf ex:Fruit .
""")

    assert anything_located(graph) is False


def test_a_single_point_makes_the_file_mappable():
    graph = _graph("ex:Shop wgs:lat 48.11 ; wgs:long -1.68 .")

    assert anything_located(graph) is True


def test_a_shape_counts_as_much_as_a_point():
    """A file of regions carries WKT and no lat/long. Reading only points would
    call an atlas unmappable."""
    graph = _graph('ex:Region geo:asWKT "POLYGON((0 0,1 0,1 1,0 0))"^^geo:wktLiteral .')

    assert anything_located(graph) is True


# ── what a node reaches ───────────────────────────────────────────────────────


def test_a_located_node_reaches_itself():
    graph = _graph("ex:Shop wgs:lat 48.11 ; wgs:long -1.68 .")

    assert located_from(graph, rdflib.URIRef(NS + "Shop")) == [NS + "Shop"]


def test_a_class_reaches_its_located_individuals():
    graph = _graph("""
ex:Store  rdfs:label "Store" .
ex:shop-1 a ex:Store ; wgs:lat 48.11 ; wgs:long -1.68 .
ex:shop-2 a ex:Store ; wgs:lat 47.90 ; wgs:long -2.10 .
""")

    assert sorted(located_from(graph, rdflib.URIRef(NS + "Store"))) == [
        NS + "shop-1",
        NS + "shop-2",
    ]


def test_a_brand_reaches_its_stores_through_the_unit_between_them():
    """The case the request was really about: pressing m on a brand, which holds
    no coordinates and is two hops from everything that does."""
    graph = _graph("""
ex:Castorama  rdfs:label "Castorama" .
ex:bu-fr      ex:partOfBrand ex:Castorama .
ex:shop-1     ex:operatedBy ex:bu-fr ; wgs:lat 48.11 ; wgs:long -1.68 .
ex:shop-2     ex:operatedBy ex:bu-fr ; wgs:lat 47.90 ; wgs:long -2.10 .
""")

    assert sorted(located_from(graph, rdflib.URIRef(NS + "Castorama"))) == [
        NS + "shop-1",
        NS + "shop-2",
    ]


def test_a_node_linked_to_nothing_placeable_reaches_nothing():
    graph = _graph("""
ex:prefLabel  rdfs:label "preferred label" .
ex:Shop       wgs:lat 48.11 ; wgs:long -1.68 .
""")

    assert located_from(graph, rdflib.URIRef(NS + "prefLabel")) == []


def test_the_walk_is_bounded():
    """A chain longer than the depth must not drag the far end in — otherwise
    every node in a connected file reaches every point in it, and the focus
    means nothing. The chain points inward, which is the direction walked."""
    graph = _graph("""
ex:b ex:under ex:a .
ex:c ex:under ex:b .
ex:d ex:under ex:c .
ex:e ex:under ex:d ; wgs:lat 48.11 ; wgs:long -1.68 .
""")

    assert located_from(graph, rdflib.URIRef(NS + "a"), depth=2) == []
    assert located_from(graph, rdflib.URIRef(NS + "a"), depth=4) == [NS + "e"]


def test_links_are_followed_inward_only():
    """Outward walks climb to a shared parent and come back down a sibling's
    branch: Castorama reached Brico Depot's stores through Kingfisher, 1,324 of
    1,509 placeable entities for a brand that has 228."""
    graph = _graph("""
ex:Castorama  ex:ownedBy ex:Kingfisher .
ex:BricoDepot ex:ownedBy ex:Kingfisher .
ex:their-shop ex:operatedBy ex:BricoDepot ; wgs:lat 40.0 ; wgs:long 3.0 .
ex:our-shop   ex:operatedBy ex:Castorama  ; wgs:lat 48.0 ; wgs:long 2.0 .
""")

    assert located_from(graph, rdflib.URIRef(NS + "Castorama")) == [NS + "our-shop"]


def test_a_peer_link_is_not_followed():
    """competesWith is symmetric: it says these two are rivals, not that one is
    inside the other. Following it turned Weldom France's shops into every
    rival's shop in France — 846 for a chain that has 266."""
    graph = _graph("""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
ex:competesWith a owl:SymmetricProperty .
ex:ours   ex:competesWith ex:theirs .
ex:theirs ex:competesWith ex:ours .
ex:our-shop   ex:operatedBy ex:ours   ; wgs:lat 48.0 ; wgs:long 2.0 .
ex:their-shop ex:operatedBy ex:theirs ; wgs:lat 40.0 ; wgs:long 3.0 .
""")

    assert located_from(graph, rdflib.URIRef(NS + "ours")) == [NS + "our-shop"]


def test_a_container_maps_itself_and_what_is_inside_it():
    """A region carries an outline, so an early return would map the outline and
    none of the shops in it."""
    graph = _graph("""
ex:Region geo:asWKT "POLYGON((0 0,1 0,1 1,0 0))"^^geo:wktLiteral .
ex:shop-1 ex:locatedIn ex:Region ; wgs:lat 48.11 ; wgs:long -1.68 .
""")

    assert located_from(graph, rdflib.URIRef(NS + "Region")) == [
        NS + "Region",
        NS + "shop-1",
    ]


def test_a_literal_neighbour_is_not_followed():
    """Only URIs are walked; a label is not a step towards anything."""
    graph = _graph("""
ex:Thing rdfs:label "Thing" .
ex:Shop  wgs:lat 48.11 ; wgs:long -1.68 .
""")

    assert located_from(graph, rdflib.URIRef(NS + "Thing")) == []
