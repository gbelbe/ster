"""A file with coordinates and no hierarchy must still map cleanly.

Not every ontology has places inside places. When nothing nests, every entity
sits at one level with no parent and no ancestors, and the map is simply a set
of points — which is the common case for anyone who has only ever written
wgs:lat/long.

The bug this guards: `focus` was doing two jobs, naming both what the detail
panel describes *and* which branch the map is filtered to. Selecting a leaf set
it, so the map filtered itself down to that single point — on a flat file that
meant clicking any site hid the other four, with only "All" to get back.
"""

from __future__ import annotations

import pytest
import rdflib

from ster import geo_map_html, geo_shapes
from ster.api import _DEFAULT_MAP_QUERY

FLAT = """\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix wgs:  <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix ex:   <https://example.org/sites#> .

ex:Site a owl:Class ; rdfs:label "Site"@en .
ex:lille  a owl:NamedIndividual, ex:Site ; rdfs:label "Lille"@en  ; wgs:lat "50.63" ; wgs:long "3.06" .
ex:nantes a owl:NamedIndividual, ex:Site ; rdfs:label "Nantes"@en ; wgs:lat "47.22" ; wgs:long "-1.55" .
ex:nice   a owl:NamedIndividual, ex:Site ; rdfs:label "Nice"@en   ; wgs:lat "43.70" ; wgs:long "7.27" .
"""


@pytest.fixture
def flat() -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(data=FLAT, format="turtle")
    return graph


def test_the_default_query_maps_a_file_with_no_hierarchy(flat) -> None:
    rows = list(flat.query(_DEFAULT_MAP_QUERY))

    assert len(rows) == 3


def test_every_place_sits_at_one_level_with_no_parent(flat) -> None:
    """There is nothing to group by, and the map must not pretend otherwise."""
    nodes = [row[0] for row in flat.query(_DEFAULT_MAP_QUERY)]

    assert {geo_shapes.place_level(flat, n) for n in nodes} == {0}
    assert all(geo_shapes.place_parent(flat, n) is None for n in nodes)
    assert all(geo_shapes.place_ancestors(flat, n) == [] for n in nodes)


def test_a_flat_file_still_reports_its_class_as_the_level_name(flat) -> None:
    """The strip names what these things *are*, even with one level of them."""
    nodes = [row[0] for row in flat.query(_DEFAULT_MAP_QUERY)]

    assert {geo_shapes.place_type(flat, n) for n in nodes} == {"Site"}


# ── the page ──────────────────────────────────────────────────────────────────
# Source assertions: these catch a missing wire, never a rendering fault. Both
# shapes of file were also driven in a browser.


def test_the_page_separates_what_is_selected_from_what_is_drilled_into() -> None:
    page = geo_map_html._PAGE

    assert "let selected = null;" in page
    assert "const here = points.find(p => p.uri === selected);" in page


def test_selecting_a_leaf_does_not_move_the_drill_focus() -> None:
    """The whole bug in one line: a leaf must return before touching `focus`."""
    page = geo_map_html._PAGE

    assert page.count("// a leaf: select, do not descend") == 2, (
        "both the marker click and the chip click must take the leaf path"
    )


def test_a_new_result_clears_the_selection_as_well_as_the_focus() -> None:
    """A stale selection would describe an entity the new query never returned."""
    page = geo_map_html._PAGE

    assert "focus = null;\n    selected = null;" in page
