"""Unit tests for the map page served at GET /map."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ster.api import SSEBroadcaster, create_app
from ster.model import Label, LabelType, RDFClass, Taxonomy

NS = "https://example.org/onto#"
TOKEN = "test-token"
QUERY = "SELECT ?i WHERE { ?i <http://www.w3.org/2003/01/geo/wgs84_pos#lat> ?lat }"


def _taxonomy() -> Taxonomy:
    t = Taxonomy()
    t.namespace_bindings[""] = NS
    t.owl_classes[NS + "Place"] = RDFClass(
        uri=NS + "Place", labels=[Label(lang="en", value="Place", type=LabelType.PREF)]
    )
    return t


def _client() -> TestClient:
    app = create_app(_taxonomy(), TOKEN, SSEBroadcaster(), save_fn=lambda _t: None)
    return TestClient(app)


def test_map_route_returns_html() -> None:
    response = _client().get("/map")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_map_route_loads_without_a_token() -> None:
    """Same as /viz: the page itself is open, its API calls carry the token."""
    response = _client().get("/map")
    assert response.status_code == 200


def test_map_route_renders_the_supplied_query() -> None:
    response = _client().get("/map", params={"q": QUERY})
    assert "wgs84_pos" in response.text


def test_map_page_embeds_the_token_for_its_own_calls() -> None:
    """The page re-runs the query through /mcp, so it needs the bearer token."""
    assert TOKEN in _client().get("/map").text


def test_map_page_posts_to_the_mcp_endpoint() -> None:
    text = _client().get("/map").text
    assert "/mcp" in text
    assert "run_sparql" in text


def test_map_page_starts_with_the_query_folded_away() -> None:
    """The map is the point of this page; the SPARQL behind it is a detail.

    It used to open with the query visible, which cost a third of the screen
    before anything had been looked at. The panel is still one click away and
    the toggle says so.
    """
    text = _client().get("/map").text

    assert 'id="query-panel" class="closed"' in text
    # The toggle starts as "Show", which only makes sense if the panel is folded.
    assert "Show query" in text


def test_map_page_offers_clustering_and_a_scale() -> None:
    text = _client().get("/map").text
    assert 'id="seg"' in text  # cluster-by control
    assert 'id="scale"' in text  # colour ramp legend
    assert 'id="crumbs"' in text  # drill-down breadcrumb


# ── the query comes from /map?q=, so it is untrusted ──────────────────────────


def test_a_query_containing_markup_cannot_break_out_of_the_page():
    """CodeQL flagged this as reflected XSS: ?q= lands in the page verbatim.

    The <textarea> can only be closed by ``</textarea``, so escaping ``<`` is
    already enough today — but the escaping has to hold if the placeholder ever
    moves into an attribute, and a hand-rolled escaper is not recognised as a
    sanitiser by static analysis.
    """
    from ster.geo_map_html import render_map_html

    page = render_map_html("</textarea><script>alert(1)</script>", "tok")

    assert "</textarea><script>" not in page
    assert "&lt;/textarea&gt;" in page


def test_quotes_in_a_query_are_escaped_too():
    """SPARQL is full of quoted literals; an attribute context must stay safe."""
    from ster.geo_map_html import render_map_html

    page = render_map_html('SELECT ?s WHERE { ?s ?p "x" }', "tok")

    assert "&quot;x&quot;" in page
