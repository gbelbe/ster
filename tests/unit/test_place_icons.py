"""A place that carries a picture is drawn as that picture, not as a dot.

A dot says a thing is somewhere. It cannot say *what* the thing is, so a map of
a thousand shops is a thousand identical marks. When the ontology already states
what something looks like — any of the image predicates ster reads — the map can
honour that instead.

Nothing here knows what a shop is, or what any particular mark means. The
ontology decides; ster only reads the picture and draws it.
"""

from __future__ import annotations

import rdflib

from ster import geo_shapes

NS = "https://example.org/i#"

TTL = f"""\
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix foaf:   <http://xmlns.com/foaf/0.1/> .
@prefix wgs:    <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix ex:     <{NS}> .

ex:Place a owl:Class .
ex:Shop  a owl:Class ; rdfs:label "Shop"@en .
ex:within a owl:ObjectProperty ; rdfs:domain ex:Place ; rdfs:range ex:Place .

ex:withMark a owl:NamedIndividual, ex:Shop ; rdfs:label "With a mark"@en ;
    wgs:lat "48.85" ; wgs:long "2.35" ;
    schema:image <data:image/svg+xml,%3Csvg/%3E> .

ex:withFoaf a owl:NamedIndividual, ex:Shop ; rdfs:label "Depicted"@en ;
    wgs:lat "48.86" ; wgs:long "2.36" ;
    foaf:depiction <https://img.example.org/f.svg> .

ex:plain a owl:NamedIndividual, ex:Shop ; rdfs:label "No mark"@en ;
    wgs:lat "48.87" ; wgs:long "2.37" .
"""


def _graph() -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(data=TTL, format="turtle")
    return graph


def test_a_place_offers_the_picture_the_ontology_gave_it() -> None:
    graph = _graph()

    assert geo_shapes.image_of(graph, rdflib.URIRef(NS + "withMark")).startswith(
        "data:image/svg+xml,"
    )


def test_the_picture_may_come_from_any_vocabulary() -> None:
    """schema:image is not privileged; foaf:depiction says the same thing."""
    graph = _graph()

    assert geo_shapes.image_of(graph, rdflib.URIRef(NS + "withFoaf")) == (
        "https://img.example.org/f.svg"
    )


def test_a_place_with_no_picture_offers_nothing_rather_than_failing() -> None:
    graph = _graph()

    assert geo_shapes.image_of(graph, rdflib.URIRef(NS + "plain")) == ""


def test_the_map_draws_a_picture_instead_of_a_dot_when_there_is_one() -> None:
    """The branch must be reachable: a point with an icon, drawn as a marker."""
    from ster.geo_map_html import render_map_html

    js = render_map_html("", "")

    assert "only.icon" in js
    assert "L.divIcon" in js


def test_the_point_carries_its_icon_to_the_page() -> None:
    """The field-by-field copy is where such things get silently dropped."""
    from ster.geo_map_html import render_map_html

    js = render_map_html("", "")

    assert js.count("icon:found.icon") == 1
    assert js.count("icon:p.icon") == 1
