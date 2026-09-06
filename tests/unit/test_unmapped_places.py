"""A place with no coordinates is still a place, and still counts.

An ontology can hold entities it deliberately will not plot: a store in the
Canaries when the map covers continental Europe, a grouping tier with no shape
of its own. ster used to drop them from /api/locate entirely, so they vanished
from the totals as well as the map — a country's store count silently excluded
the ones it could not draw, which makes the figure wrong rather than partial.

They now travel with the result, positioned or not. The map skips them when
drawing and includes them when counting.
"""

from __future__ import annotations

import pytest
import rdflib

from ster import geo_shapes

TTL = """\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wgs:  <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix ex:   <https://example.org/p#> .

ex:Place a owl:Class .
ex:Country a owl:Class ; rdfs:subClassOf ex:Place ; rdfs:label "Country"@en .
ex:Store a owl:Class ; rdfs:subClassOf ex:Place ; rdfs:label "Store"@en .
ex:within a owl:ObjectProperty ; rdfs:domain ex:Place ; rdfs:range ex:Place .

ex:spain a owl:NamedIndividual, ex:Country ; rdfs:label "Spain"@en ;
    wgs:lat "40.4" ; wgs:long "-3.7" .

ex:madrid a owl:NamedIndividual, ex:Store ; rdfs:label "Madrid"@en ;
    ex:within ex:spain ; wgs:lat "40.41" ; wgs:long "-3.70" .

# Real, counted, but deliberately not plotted — no coordinates at all.
ex:laspalmas a owl:NamedIndividual, ex:Store ; rdfs:label "Las Palmas"@en ;
    ex:within ex:spain ;
    rdfs:comment "Outside the mapped area, so no coordinates are asserted."@en .
"""

NS = "https://example.org/p#"


@pytest.fixture
def graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=TTL, format="turtle")
    return g


def test_an_unmapped_place_has_no_geometry(graph) -> None:
    """Precondition: this is exactly the entity that used to be dropped."""
    assert geo_shapes.geometry_of(graph, rdflib.URIRef(NS + "laspalmas")) is None


def test_it_still_knows_where_it_belongs(graph) -> None:
    """Its place in the hierarchy is independent of whether it can be drawn."""
    node = rdflib.URIRef(NS + "laspalmas")

    assert geo_shapes.place_parent(graph, node) == NS + "spain"
    assert geo_shapes.place_ancestors(graph, node) == [NS + "spain"]
    assert geo_shapes.place_level(graph, node) == 1


def test_the_api_keeps_it_rather_than_dropping_it() -> None:
    """The behaviour change: a record comes back, with no position."""
    from ster.api import _place_record

    g = rdflib.Graph()
    g.parse(data=TTL, format="turtle")
    rec = _place_record(g, NS + "laspalmas", True)

    assert rec is not None, "an unmapped place must still reach the client"
    assert rec["lat"] is None and rec["long"] is None
    assert rec["mapped"] is False
    assert rec["parent"] == NS + "spain"


def test_a_mapped_place_is_unchanged() -> None:
    from ster.api import _place_record

    g = rdflib.Graph()
    g.parse(data=TTL, format="turtle")
    rec = _place_record(g, NS + "madrid", True)

    assert rec["mapped"] is True
    assert rec["lat"] == pytest.approx(40.41, abs=0.01)


def test_the_page_draws_only_what_it_can_place() -> None:
    """Counting must not become plotting: a null coordinate would break Leaflet."""
    from ster import geo_map_html

    assert "p.lat !== null" in geo_map_html._PAGE or "mapped" in geo_map_html._PAGE
