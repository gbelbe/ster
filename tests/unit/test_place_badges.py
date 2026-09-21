"""Who operates here, shown on the shape itself.

A polygon says where something is; it does not say who is in it. When an
ontology links other entities to a place — a business unit to the country it
trades in, an operator to a region — and those entities carry a logo, the map
can show them on the shape.

Discovered, not configured: any entity that points at the place and has an
image qualifies, whatever the property is called. Places themselves never
qualify, because the drill-down already draws those.
"""

from __future__ import annotations

import pytest
import rdflib

from ster import geo_shapes

NS = "https://example.org/b#"

TTL = f"""\
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix geo:    <http://www.opengis.net/ont/geosparql#> .
@prefix wgs:    <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix ex:     <{NS}> .

ex:Place a owl:Class .
ex:Country a owl:Class ; rdfs:subClassOf ex:Place ; rdfs:label "Country"@en .
ex:Unit a owl:Class ; rdfs:label "Unit"@en .
ex:within a owl:ObjectProperty ; rdfs:domain ex:Place ; rdfs:range ex:Place .
ex:tradesIn a owl:ObjectProperty ; rdfs:domain ex:Unit ; rdfs:range ex:Country .

ex:france a owl:NamedIndividual, ex:Country ; rdfs:label "France"@en ;
    geo:asWKT "POLYGON((0 45, 5 45, 5 50, 0 50, 0 45))"^^geo:wktLiteral .
ex:spain a owl:NamedIndividual, ex:Country ; rdfs:label "Spain"@en ;
    wgs:lat "40" ; wgs:long "-3" .

ex:unitA a owl:NamedIndividual, ex:Unit ; rdfs:label "Unit A"@en ;
    ex:tradesIn ex:france ; schema:image <https://img.example.org/a.svg> .
ex:unitB a owl:NamedIndividual, ex:Unit ; rdfs:label "Unit B"@en ;
    ex:tradesIn ex:france ; schema:image <https://img.example.org/b.svg> .
ex:unitC a owl:NamedIndividual, ex:Unit ; rdfs:label "Unit C"@en ;
    ex:tradesIn ex:france .
"""


@pytest.fixture
def graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=TTL, format="turtle")
    return g


def _badges(graph, local):
    return geo_shapes.badges_of(graph, NS + local)


def test_entities_pointing_at_a_place_become_its_badges(graph) -> None:
    got = {b["uri"] for b in _badges(graph, "france")}

    assert got == {NS + "unitA", NS + "unitB"}


def test_a_badge_carries_what_the_map_needs_to_draw_it(graph) -> None:
    badge = next(b for b in _badges(graph, "france") if b["uri"] == NS + "unitA")

    assert badge["label"] == "Unit A"
    assert badge["image"] == "https://img.example.org/a.svg"


def test_an_entity_without_an_image_is_not_a_badge(graph) -> None:
    """There is nothing to draw for it, and a name alone would clutter the shape."""
    assert NS + "unitC" not in {b["uri"] for b in _badges(graph, "france")}


def test_a_place_is_never_a_badge_on_another_place(graph) -> None:
    """Countries already appear through the drill-down."""
    graph.add(
        (rdflib.URIRef(NS + "spain"), rdflib.URIRef(NS + "within"), rdflib.URIRef(NS + "france"))
    )
    graph.add(
        (
            rdflib.URIRef(NS + "spain"),
            rdflib.URIRef("https://schema.org/image"),
            rdflib.URIRef("https://img.example.org/es.svg"),
        )
    )

    assert NS + "spain" not in {b["uri"] for b in _badges(graph, "france")}


def test_badges_are_stable_in_order(graph) -> None:
    """The map lays them out side by side; a shifting order would jitter."""
    assert [b["uri"] for b in _badges(graph, "france")] == sorted(
        b["uri"] for b in _badges(graph, "france")
    )


def test_a_place_nothing_points_at_has_none(graph) -> None:
    assert _badges(graph, "spain") == []


def test_the_map_spreads_them_rather_than_stacking(graph) -> None:
    """All of them must be visible, so they are offset in screen pixels — which
    keeps them apart at every zoom, unlike a geographic offset."""
    from ster import geo_map_html

    page = geo_map_html._PAGE

    assert "badge" in page
    assert "divIcon" in page


def test_the_whole_row_is_one_marker() -> None:
    """Why one marker and not one per logo.

    A marker each, nudged apart by a few degrees, collides the moment the scale
    changes — the offsets are geographic and the icons are not. One marker
    holding a flex row lets the browser space them in *pixels*, so several units
    on one country stay side by side however far out you zoom.
    """
    from ster import geo_map_html

    page = geo_map_html._PAGE

    assert "display:flex" in page.split(".badge-row")[1][:80]
    # Anchored on the block's own centre. That used to be `size / 2` because the
    # row was one logo tall; it wraps onto a second row now, so the height is
    # computed and a marker anchored on `size` would hang half out of its shape.
    assert "iconAnchor: [width / 2, height / 2]" in page


def test_badges_reach_the_client() -> None:
    """Every field the server adds must be copied onto the point explicitly —
    `facets` was missed exactly this way and the filter menu never appeared."""
    from ster import geo_map_html

    assert "badges:found.badges" in geo_map_html._PAGE
    assert "badges:p.badges" in geo_map_html._PAGE


def test_only_a_shape_carries_them() -> None:
    """A bare point is already the thing itself; badges belong on an area."""
    from ster import geo_map_html

    assert "p.shape && (p.badges || []).length" in geo_map_html._PAGE


def test_the_row_is_measured_against_the_shape_on_screen() -> None:
    """A fixed size cannot fit both Cyprus and Ukraine.

    The shape's pixel width is what decides whether three logos sit inside it,
    and that changes with every zoom — so the row is measured in container
    points, not in degrees, and re-measured when the zoom changes.
    """
    from ster import geo_map_html

    page = geo_map_html._PAGE

    assert "function badgeSize" in page
    assert "latLngToContainerPoint" in page
    assert "addBadges(badgeVisible)" in page, "not re-measured on zoom"


def test_sizes_stay_within_a_narrow_band() -> None:
    """So a mark on a small country and a large one read as the same thing."""
    from ster import geo_map_html

    page = geo_map_html._PAGE

    assert "const BADGE_MIN = 11;" in page
    assert "const BADGE_MAX = 22;" in page
    assert "Math.min(size, BADGE_MAX)" in page


def test_a_shape_too_small_shows_none_rather_than_spilling_over() -> None:
    """Below the floor the logos would cover ground outside the country, which
    reads as a claim about somewhere it does not operate."""
    from ster import geo_map_html

    assert "size < BADGE_MIN ? 0" in geo_map_html._PAGE
    assert "if (!size) return null;" in geo_map_html._PAGE
