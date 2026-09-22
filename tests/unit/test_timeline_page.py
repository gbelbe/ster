"""The timeline page served at GET /timeline, and the data route behind it.

Mirrors the map's own tests: the page is open and embeds its token, the API
route resolves URIs server-side, and the page's inline script must actually
parse — the trap `test_map_page_syntax` documents applies identically here,
since this is also a few hundred lines of JavaScript inside a Python string.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from ster.api import SSEBroadcaster, create_app
from ster.model import Label, LabelType, RDFClass, Taxonomy
from ster.timeline_html import DEFAULT_TIMELINE_QUERY, render_timeline_html
from tests._rendered_page import main_inline_script

NS = "https://example.org/onto#"
TOKEN = "test-token"


def _taxonomy() -> Taxonomy:
    t = Taxonomy()
    t.namespace_bindings[""] = NS
    t.owl_classes[NS + "Event"] = RDFClass(
        uri=NS + "Event", labels=[Label(lang="en", value="Event", type=LabelType.PREF)]
    )
    return t


def _client() -> TestClient:
    app = create_app(_taxonomy(), TOKEN, SSEBroadcaster(), save_fn=lambda _t: None)
    return TestClient(app)


def test_timeline_route_returns_html() -> None:
    response = _client().get("/timeline")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_timeline_route_loads_without_a_token() -> None:
    """Same as /viz and /map: the page is open, its API calls carry the token."""
    assert _client().get("/timeline").status_code == 200


def test_timeline_route_renders_the_supplied_query() -> None:
    response = _client().get("/timeline", params={"q": "SELECT ?s WHERE { ?s ?p ?o }"})
    assert "SELECT ?s WHERE" in response.text


def test_timeline_starts_with_provenance_and_annotations_hidden() -> None:
    page = _client().get("/timeline").text
    assert 'id="toggle-auxiliary">Provenance &amp; annotations</button>' in page
    assert "state.showAuxiliary || !i.auxiliary" in page


def test_provenance_moments_carry_their_own_colour() -> None:
    """The class the server flags must reach an item, and the stylesheet must paint it."""
    page = _client().get("/timeline").text
    assert "item.provenance ? ' provenance' : ''" in page
    assert ".vis-item.provenance{" in page


def test_the_controls_are_in_english() -> None:
    """They were hard-coded French, never a locale — one button was already English."""
    page = _client().get("/timeline").text
    assert '<html lang="en">' in page
    for label in (">Fit to data<", ">Query<", ">Run<", ">Timeline<"):
        assert label in page, label
    for gone in ("Tout voir", "Requête", "Relancer", "Frise temporelle"):
        assert gone not in page, gone


def test_the_query_box_opens_on_a_single_click() -> None:
    """Toggling a class, because the box is hidden by the stylesheet: reading
    style.display back gives "" on the first click, so a read-and-flip handler
    wrote back the state it was already in and the button looked dead."""
    page = _client().get("/timeline").text
    assert "#qbox.open{display:block}" in page
    assert "el('qbox').classList.toggle('open')" in page


def test_lane_filters_are_chosen_not_hidden() -> None:
    """The map's model: picking a lane narrows to it, and every lane stays on
    screen so the pick can be undone. Building the strip from what is *left*
    after filtering is what made a clicked lane's own button disappear."""
    page = _client().get("/timeline").text
    assert "state.chosen" in page
    assert "state.hidden" not in page
    # the strip is built from everything the auxiliary switch admits, not from
    # what survives the lane filter
    assert "admitted().forEach(function (item) {" in page
    assert "clear filters" in page


def test_the_default_query_asks_for_temporal_datatypes() -> None:
    assert "xsd:date" in DEFAULT_TIMELINE_QUERY
    assert "xsd:gYear" in DEFAULT_TIMELINE_QUERY


def test_api_timeline_needs_a_token() -> None:
    assert _client().post("/api/timeline", json={"uris": []}).status_code in (401, 403)


def test_api_timeline_returns_items_lanes_and_span() -> None:
    body = _client().post(
        "/api/timeline",
        json={"uris": []},
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert body.status_code == 200
    payload = body.json()
    assert set(payload) == {"items", "lanes", "span"}


def _inline_script(page: str) -> str:
    return main_inline_script(page, "timeline")


def test_the_timeline_page_script_parses(tmp_path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; the syntax check needs a JS parser")
    script = tmp_path / "page.js"
    script.write_text(_inline_script(render_timeline_html(DEFAULT_TIMELINE_QUERY, "tok")))
    done = subprocess.run(  # noqa: S603
        [node, "--check", str(script)], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, f"the timeline page's script does not parse:\n{done.stderr}"


def test_the_app_layer_script_parses(tmp_path) -> None:
    """The asset itself, so a broken edit fails before it reaches a page."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; the syntax check needs a JS parser")
    from importlib.resources import files

    script = tmp_path / "app.js"
    script.write_text((files("ster") / "assets" / "timeline_app.js").read_text(encoding="utf-8"))
    done = subprocess.run(  # noqa: S603
        [node, "--check", str(script)], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, f"timeline_app.js does not parse:\n{done.stderr}"
