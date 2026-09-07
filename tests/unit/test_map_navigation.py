"""The map's own half of the place drill — what the page is wired to do.

These assert on the served page's source. That is a weak instrument and it is
worth naming: three bugs in this feature passed a green suite and only appeared
on screen — the endpoint the page never called, an ancestor chain that broke at
an undrawn level, and groups keyed by a row index that grouping places do not
have. What is checked here is that the wiring exists and the traps stay closed;
whether it *renders* still needs a browser.
"""

from __future__ import annotations

from ster.geo_map_html import render_map_html


def _page() -> str:
    return render_map_html("SELECT * WHERE {?s ?p ?o}", "tok")


# ── the level drill ───────────────────────────────────────────────────────────


def test_the_page_asks_the_server_to_place_rows():
    """Regression: the page located rows itself with a wgs:lat/long query, so no
    geometry ever reached it and every polygon came back unmappable."""
    page = _page()

    assert "/api/locate" in page
    assert "locateOnServer" in page


def test_containment_comes_from_the_server_not_a_local_walk():
    """Regression: walking `parent` through the drawn points broke at a level
    that carries no geometry, so a place appeared to have no ancestors."""
    page = _page().replace(" ", "")

    assert "(p.ancestors||[]).includes(uri)" in page


def test_the_drill_skips_a_level_that_draws_nothing():
    """A grouping tier with no geometry must be stepped over, not landed on."""
    assert "function childLevel(" in _page()


def test_the_level_snaps_to_one_that_exists():
    """Regression: a missing level fell back to the deepest, so the map opened on
    individual stores instead of the continent."""
    assert "function snapLevel(" in _page()


def test_places_are_grouped_by_uri_not_row_index():
    """Regression: a place pulled in to group results has no row of its own, so
    keying on one collapsed every country into a single "null" group — five
    outlines drawn as one dot."""
    page = _page().replace(" ", "")

    assert "(p.uri||'row:'+p.row)" in page


def test_zoom_does_not_change_the_level():
    """It used to, and fitting the map to what you opened fires zoomend, which
    read as the reader zooming and undid the drill — clicking Europe could land
    on a city in another country."""
    page = _page()

    assert "map.on('zoomend'" in page
    assert "level =" not in page.split("map.on('zoomend'")[1].split("});")[0]


# ── what the panels show ──────────────────────────────────────────────────────


def test_navigation_is_a_top_strip_with_a_trail_and_chips():
    page = _page()

    assert 'id="nav"' in page
    assert "function drawNav(" in page
    assert 'class="chip' in page


def test_the_chips_list_siblings_rather_than_the_children_on_the_map():
    """The map already draws the children and they are clickable there.

    Listing them again as buttons put 70 shop chips above a map of 70 shops.
    The strip lists where you could go *sideways* instead, which is the one
    move the map cannot offer.
    """
    page = _page()

    assert "function siblingsOfFocus(" in page
    assert "siblingsOfFocus()" in page


def test_the_place_you_are_in_is_shown_as_pressed():
    page = _page()

    assert "aria-pressed" in page
    assert "p.uri === focus ? ' current'" in page


def test_a_bare_row_count_is_not_offered_as_a_measure():
    """With no measure chosen the total is a row count, and "rows 1" on a shop
    says nothing at all."""
    page = _page()

    assert "function measureLine(" in page
    assert "measureCol === null && total <= 1" in page


def test_it_opens_where_there_is_something_to_compare():
    """A single continent fills the screen and answers nothing.

    Opening on the broadest level meant opening on one shape. The first level
    holding two things is where a map starts being a map.
    """
    page = _page()

    assert "function openingLevel(" in page
    assert ">= 2) return lvl" in page


def test_the_opening_level_counts_only_what_can_be_drawn():
    """A level of three cities with no coordinates draws a blank map."""
    page = _page()
    body = page[page.index("function openingLevel(") :]

    assert "p.lat !== null && p.long !== null" in body[: body.index("\n}")]


def test_one_shape_still_beats_none():
    """When no level holds two, it falls back rather than showing nothing."""
    page = _page()
    body = page[page.index("function openingLevel(") :]

    assert "return levelsOf(pts)[0] ?? 0;" in body[: body.index("\n}") + 2]


def test_both_entry_points_use_the_opening_level():
    """The first draw and the All crumb must agree on where 'the top' is."""
    page = _page()

    assert "levelsOf(points)[0] ?? 0" not in page
    assert page.count("openingLevel(points)") == 2


def test_the_wait_is_visible_and_says_which_phase_it_is_in():
    """A blank grey panel for a second reads as broken.

    There are two waits — running the query, then placing what it returned — and
    naming which one you are in is the whole value. A spinner alone says only
    that something is happening.
    """
    page = _page()

    assert 'id="loading"' in page
    assert "running the query…" in page
    assert "placing ${rows.length} row" in page


def test_a_failed_query_does_not_leave_the_map_behind_a_veil():
    """The loader is cleared in a finally, not on the happy path."""
    page = _page()
    tail = page[page.index("async function run()") :]

    assert "} finally {" in tail
    assert "loading(null);" in tail


def test_stated_and_calculated_facts_are_separated():
    """A total the map computed must not read as something the file asserts."""
    page = _page()

    assert "calculated — not stated in the ontology" in page
    assert 'class="derived"' in page


def test_totals_exclude_the_place_itself():
    """Regression: a store's own turnover was labelled a total, which is a
    different claim from a sum over what it contains."""
    page = _page().replace(" ", "")

    assert "if(q===p||!descendsFrom(q,p.uri))continue;" in page


def test_geometry_never_appears_as_a_property():
    """It is already drawn; a WKT polygon in the box is a hundred stray numbers."""
    page = _page()

    assert "GEOM_DATATYPES" in page
    assert "COORD_PROPS" in page


def test_the_detail_box_collapses():
    """It shares the panel with navigation and must not crowd it out."""
    page = _page()

    assert "detailOpen" in page
    assert ".collapsed .body" in page


# ── media and links come from the file, so they are untrusted ─────────────────


def test_only_http_urls_become_links_or_sources():
    page = _page().replace(" ", "")

    assert "functionsafeUrl" in page
    assert "u.protocol==='http:'||u.protocol==='https:'" in page


def test_links_cannot_reach_back_through_window_opener():
    assert 'rel="noopener noreferrer"' in _page()


def test_media_is_requested_without_a_referrer():
    """Most image hosts refuse a request whose Referer is another origin."""
    assert _page().count('referrerpolicy="no-referrer"') >= 2


def test_a_dead_image_says_so():
    assert "image unavailable" in _page()


def test_a_wms_layer_uses_leaflets_wms_constructor():
    """L.tileLayer cannot serve WMS: the endpoint has no {z}/{x}/{y} to fill, and
    the layer names have to travel as request parameters."""
    page = _page()

    assert "L.tileLayer.wms(" in page
    assert "layers: spec.wmsLayers" in page
