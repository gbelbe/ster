"""The timeline page served at GET /timeline, and the data route behind it.

Mirrors the map's own tests: the page is open and embeds its token, the API
route resolves URIs server-side, and the page's inline script must actually
parse — the trap `test_map_page_syntax` documents applies identically here,
since this is also a few hundred lines of JavaScript inside a Python string.
"""

from __future__ import annotations

import shutil
import subprocess
from http import HTTPStatus

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
    assert response.status_code == HTTPStatus.OK
    assert "text/html" in response.headers["content-type"]


def test_timeline_route_loads_without_a_token() -> None:
    """Same as /viz and /map: the page is open, its API calls carry the token."""
    assert _client().get("/timeline").status_code == HTTPStatus.OK


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
    assert body.status_code == HTTPStatus.OK
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


def _app_js() -> str:
    from importlib.resources import files

    return (files("ster") / "assets" / "timeline_app.js").read_text(encoding="utf-8")


def test_date_only_events_are_drawn_as_points_and_periods_as_boxes() -> None:
    """vis-timeline's own item types carry the distinction: a period is a
    `range` box, a single date a `point` — a dot at the date with its label
    starting there, where a `box` hung its connecting line from the middle."""
    js = _app_js()
    assert "type: i.end ? 'range' : 'point'" in js
    assert "'box'" not in js


def test_date_only_events_have_no_border_or_background() -> None:
    page = _client().get("/timeline").text
    # Declared after the instant/provenance colours so it wins on equal specificity.
    point_rule = ".vis-item.vis-point{background:transparent;border:none}"
    assert point_rule in page
    assert page.index(point_rule) > page.index(".vis-item.provenance{")


def test_the_dot_keeps_the_colour_of_its_kind() -> None:
    page = _client().get("/timeline").text
    assert ".vis-item.vis-dot.instant{" in page
    assert ".vis-item.vis-dot.provenance{" in page


def test_a_period_too_narrow_for_its_label_shows_it_beside_the_box() -> None:
    """The overflow is vis-timeline's own mode for text wider than its item, so
    stacking reserves the label's room; the margin moves it past the right edge."""
    page = _client().get("/timeline").text
    assert ".vis-item.vis-range.beside .vis-item-overflow{overflow:visible}" in page
    assert ".vis-item.vis-range.beside .vis-item-content{margin-left:100%}" in page


# ── after/before: rejected early, and never reflected unescaped ──────────────


def test_an_after_value_that_is_not_date_shaped_is_rejected() -> None:
    """Caught at the API boundary before it ever reaches the rendered page —
    the CodeQL/SonarQube-flagged sink this pair of tests exists to close."""
    response = _client().get("/timeline", params={"after": "</script><script>alert(1)</script>"})

    assert response.status_code == HTTPStatus.BAD_REQUEST


def test_a_valid_after_value_is_accepted_and_embedded() -> None:
    page = _client().get("/timeline", params={"after": "2025-01-01"}).text

    assert '"after": "2025-01-01"' in page


def test_a_valid_before_value_is_accepted_and_embedded() -> None:
    page = _client().get("/timeline", params={"before": "2025-01-01"}).text

    assert '"before": "2025-01-01"' in page


@pytest.mark.parametrize(
    "value",
    [
        "2025",
        "2025-06",
        "2025-06-01",
        "2025-06-01T10:00",
        "2025-06-01T10:00+01:00",
        "2025-06-01T10:00.5Z",
        "2025-06-01T10:00:00.5Z",
        "2025-06-01T10:00:00-01:00",
    ],
)
def test_every_shape_time_shapes_recognises_is_accepted(value: str) -> None:
    """One shape per xsd:gYear/gYearMonth/date/dateTime — see
    time_shapes.TEMPORAL_DATATYPES, which this validation exists to mirror."""
    assert _client().get("/timeline", params={"before": value}).status_code == HTTPStatus.OK


@pytest.mark.parametrize("value", ["not-a-date", "2025/06/01", "2025-1-1", "'; DROP--"])
def test_a_garbled_before_value_is_rejected(value: str) -> None:
    assert (
        _client().get("/timeline", params={"before": value}).status_code == HTTPStatus.BAD_REQUEST
    )


def test_render_timeline_html_never_lets_a_bound_break_out_of_its_script_tag() -> None:
    """The API's regex guard is one caller. This is the sink itself: even a
    value that guard would never let through must not be able to close the
    inline `<script>` tag it is embedded in, so a second caller with no such
    guard cannot reopen the same reflected-XSS hole."""
    hostile = '"; </script><script>alert(document.cookie)</script>'
    page = render_timeline_html(DEFAULT_TIMELINE_QUERY, "tok", after=hostile)

    assert "</script><script>alert" not in page
    assert "\\u003c/script\\u003e" in page


def test_narrow_periods_are_rechecked_after_every_zoom() -> None:
    js = _app_js()
    assert "state.timeline.off('rangechanged', placeLabels)" in js
    assert "state.timeline.on('rangechanged', placeLabels)" in js
    assert "state.beside[item.id] ? ' beside' : ''" in js
    # Only periods can be narrow: a single date is a point with a free label.
    assert "if (!i.end) return;" in js


# ---- embed mode: the page without its own chrome, for showing inside another page ----------------


def _hidden_by_embed(html: str) -> list[str] | None:
    marker = '<style id="ster-embed">'
    if marker not in html:
        return None
    return html.split(marker, 1)[1].split("{display:none !important}", 1)[0].split(",")


def test_timeline_page_without_embed_carries_no_embed_style() -> None:
    assert _hidden_by_embed(_client().get("/timeline").text) is None


def test_timeline_embed_hides_the_pages_own_chrome() -> None:
    hidden = _hidden_by_embed(_client().get("/timeline", params={"embed": "1"}).text)
    assert hidden is not None
    assert {"header", "#qbox"} <= set(hidden)


def test_timeline_embed_leaves_the_frieze_itself_alone() -> None:
    hidden = _hidden_by_embed(_client().get("/timeline", params={"embed": "1"}).text) or []
    assert "#tl" not in hidden
    assert "#main" not in hidden


def test_timeline_embed_keeps_query_token_and_date_range() -> None:
    params = {
        "q": DEFAULT_TIMELINE_QUERY,
        "embed": "1",
        "after": "2025-01-01",
        "before": "2026-01-01",
    }
    text = _client().get("/timeline", params=params).text
    assert TOKEN in text
    assert "2025-01-01" in text
    assert "2026-01-01" in text


def test_timeline_embed_style_sits_in_the_head() -> None:
    text = _client().get("/timeline", params={"embed": "1"}).text
    assert text.index('id="ster-embed"') < text.index("</head>")


@pytest.mark.parametrize(
    ("value", "embedded"), [("1", True), ("true", True), ("0", False), ("false", False)]
)
def test_timeline_embed_flag_values(value: str, embedded: bool) -> None:
    text = _client().get("/timeline", params={"embed": value}).text
    assert (_hidden_by_embed(text) is not None) is embedded


def test_timeline_embed_rejects_a_value_that_is_not_a_boolean() -> None:
    assert (
        _client().get("/timeline", params={"embed": "maybe"}).status_code
        == HTTPStatus.UNPROCESSABLE_ENTITY
    )


def test_timeline_embed_does_not_loosen_the_date_validation() -> None:
    assert (
        _client().get("/timeline", params={"embed": "1", "after": "<script>"}).status_code
        == HTTPStatus.BAD_REQUEST
    )


def test_the_timeline_renderer_takes_embed_directly() -> None:
    assert _hidden_by_embed(render_timeline_html("SELECT 1", TOKEN, embed=True)) is not None
    assert _hidden_by_embed(render_timeline_html("SELECT 1", TOKEN)) is None
