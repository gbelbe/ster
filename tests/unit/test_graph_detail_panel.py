"""The graph's detail panel renders everything the payload carries.

The builders have always emitted a scope note, schema:image / schema:video and
schema:url, and the panel quietly dropped all three — the data was computed,
serialised, and then never shown.
"""

from __future__ import annotations

import pytest

from ster.model import (
    Concept,
    ConceptScheme,
    Definition,
    Label,
    LabelType,
    OWLIndividual,
    RDFClass,
    Taxonomy,
)
from ster.viz import _detail_class, _detail_concept, _detail_individual
from ster.viz_vowl import _app_js

NS = "https://example.org/t#"


def _lbl(v: str) -> Label:
    return Label(lang="en", value=v, type=LabelType.PREF)


@pytest.fixture
def rich() -> Taxonomy:
    """A concept carrying every field the panel is meant to show."""
    tax = Taxonomy()
    tax.schemes[NS + "S"] = ConceptScheme(uri=NS + "S", labels=[_lbl("Scheme")])
    tax.concepts[NS + "Tent"] = Concept(
        uri=NS + "Tent",
        labels=[_lbl("Tent")],
        definitions=[Definition(lang="en", value="Portable shelter. See https://example.org/docs")],
        scope_notes=[Definition(lang="en", value="Camping equipment only.")],
        schema_images=["https://example.org/tent.jpg"],
        schema_videos=["https://example.org/pitch.mp4"],
        schema_urls=["https://example.org/buy"],
    )
    return tax


# ── the payload already carried these ─────────────────────────────────────────


def test_the_builder_emits_media_and_scope_note(rich):
    detail = _detail_concept(rich.concepts[NS + "Tent"], rich)

    assert detail["images"] == ["https://example.org/tent.jpg"]
    assert detail["videos"] == ["https://example.org/pitch.mp4"]
    assert detail["urls"] == ["https://example.org/buy"]
    assert detail["scopeNote"] == "Camping equipment only."


# ── the panel now renders them ────────────────────────────────────────────────


def test_panel_renders_images_and_videos():
    js = _app_js()

    assert "detailMediaNodes" in js
    assert "class:'dp-img'" in js.replace('"', "'")
    assert "class:'dp-video'" in js.replace('"', "'")


def test_panel_renders_a_links_section():
    assert "detailUrlsNodes" in _app_js()


def test_panel_renders_the_scope_note():
    assert "detailScopeNodes" in _app_js()


def test_every_new_section_is_shown_by_show_detail():
    """Writing a renderer is not enough — showDetail has to call it."""
    js = _app_js().replace(" ", "")

    for call in (
        "detailScopeNodes(det.scopeNote)",
        "detailMediaNodes(det.images,det.videos)",
        "detailUrlsNodes(det.urls)",
    ):
        assert call in js, call


# ── these values come from the loaded file, so they are untrusted ─────────────


def test_only_http_urls_become_links():
    """A javascript: URL in an ontology must not become a clickable script."""
    js = _app_js()

    assert "function safeUrl" in js
    assert "parsed.protocol==='http:'||parsed.protocol==='https:'" in js.replace(" ", "")


def test_external_links_cannot_reach_back_through_window_opener():
    assert "rel:'noopener noreferrer'" in _app_js().replace('"', "'")


def test_free_text_urls_are_linkified_not_left_bare():
    """A definition mentioning a URL should be clickable, still escaped."""
    js = _app_js()

    assert "function linkifyNodes" in js
    assert "linkifyNodes(det.description)" in js.replace(" ", "")


def test_a_broken_image_does_not_leave_a_torn_layout():
    """Ontology media is often an off-site URL that no longer resolves."""
    assert "image unavailable" in _app_js()


# ── embedding, not just linking ───────────────────────────────────────────────


def test_media_is_requested_without_a_referrer():
    """Regression: the picture never painted.

    Wikimedia — and most image CDNs — reject a request whose Referer is another
    origin. Without this the <img> is in the DOM, reports complete with
    naturalWidth 0, and the panel shows only the caption link.
    """
    js = _app_js().replace('"', "'")

    assert js.count("referrerpolicy:'no-referrer'") >= 2  # images and videos


def test_the_failure_handler_is_bound_not_an_inline_attribute():
    """Regression: the fallback never ran.

    The panel is rebuilt with innerHTML on every selection, and an inline onerror
    attribute is also the first thing a future CSP would silently drop.
    """
    js = _app_js()

    assert "onerror=" not in js, "attach the handler with addEventListener instead"
    assert "addEventListener('error'" in js.replace('"', "'")


def test_an_image_that_already_failed_is_still_caught():
    """A cached failure fires no event, so the bound handler alone would miss it."""
    assert "img.complete&&img.naturalWidth===0" in _app_js().replace(" ", "")


def test_showdetail_wires_the_media_it_just_rendered():
    """Binding handlers is useless if the render path never calls it."""
    js = _app_js().replace(" ", "").replace("\n", "")
    assert "panelEl.replaceChildren(panel);wireMedia();" in js


# ── the OWL layer gets the same panel as the SKOS one ─────────────────────────


@pytest.fixture
def owl() -> Taxonomy:
    """A class and an individual carrying the same rich fields a concept would."""
    tax = Taxonomy()
    tax.owl_classes[NS + "Shelter"] = RDFClass(
        uri=NS + "Shelter",
        labels=[Label(lang="en", value="Shelter")],
        comments=[Definition(lang="en", value="Any shelter. Spec at https://example.org/spec")],
        schema_images=["https://example.org/shelter.jpg"],
        schema_videos=["https://example.org/shelter.mp4"],
        schema_urls=["https://example.org/buy-shelter"],
    )
    tax.owl_individuals[NS + "Tent1"] = OWLIndividual(
        uri=NS + "Tent1",
        labels=[Label(lang="en", value="Tent #1")],
        comments=[Definition(lang="en", value="A specific tent.")],
        schema_images=["https://example.org/tent1.jpg"],
        schema_urls=["https://example.org/buy-tent1"],
    )
    return tax


def test_an_owl_class_carries_media_into_the_payload(owl):
    detail = _detail_class(owl.owl_classes[NS + "Shelter"], owl)

    assert detail["images"] == ["https://example.org/shelter.jpg"]
    assert detail["videos"] == ["https://example.org/shelter.mp4"]
    assert detail["urls"] == ["https://example.org/buy-shelter"]


def test_an_owl_individual_carries_media_into_the_payload(owl):
    detail = _detail_individual(owl.owl_individuals[NS + "Tent1"], owl)

    assert detail["images"] == ["https://example.org/tent1.jpg"]
    assert detail["urls"] == ["https://example.org/buy-tent1"]


def test_urls_in_an_rdfs_comment_are_clickable_too():
    """OWL puts its prose in comments where SKOS uses a definition.

    Linkifying only the description left an rdfs:comment's URL dead, so the same
    text was clickable on a concept and inert on a class — the panel is shared, and
    the two layers should not differ in what it does with them.
    """
    assert "linkifyNodes(c.value)" in _app_js().replace(" ", "")


def test_the_panel_renders_media_for_every_node_type():
    """showDetail is shared, so one call site covers concept, class and individual."""
    js = _app_js().replace(" ", "")

    # a single, type-independent render path — not a SKOS-only branch
    assert js.count("detailMediaNodes(det.images,det.videos)") == 1
    assert "if(d.type==='concept')" not in js


# ── node labels ───────────────────────────────────────────────────────────────


def test_node_labels_are_dark_with_a_light_halo():
    """Regression: a label that wrapped past its node was white on white canvas.

    Dark text alone would be unreadable on the darker nodes, so the halo is what
    makes one colour work both inside the shape and outside it.
    """
    js = _app_js().replace(" ", "").replace('"', "'")

    assert "'color':'#0f172a'" in js
    assert "'text-outline-color':'#ffffff'" in js
    assert "'color':'white'" not in js
