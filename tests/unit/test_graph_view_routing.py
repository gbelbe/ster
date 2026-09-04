"""Routing: which tabs a rendered graph page carries, driven by taxonomy content.

The Python side never branches the HTML structure per content type — the tab
bar and #treemap container are always emitted (see docs on `_HTML_TEMPLATE`);
only the injected `window.__STER_GRAPH__` payload varies, and a small inline
bootstrap script (in the template) decides visibility at runtime from it. These
tests assert on that payload, which is the only thing that actually differs.
"""

from __future__ import annotations

from ster.model import Concept, ConceptScheme, Label, LabelType, RDFClass, Taxonomy
from ster.viz_vowl import render_vowl_html

NS = "https://example.org/onto#"


def _skos_only() -> Taxonomy:
    t = Taxonomy()
    scheme_uri, root_uri = NS + "Scheme", NS + "Root"
    t.concepts[root_uri] = Concept(uri=root_uri, labels=[Label("en", "Root", LabelType.PREF)])
    t.schemes[scheme_uri] = ConceptScheme(
        uri=scheme_uri, labels=[Label("en", "Scheme", LabelType.PREF)], top_concepts=[root_uri]
    )
    return t


def _owl_only() -> Taxonomy:
    t = Taxonomy()
    t.owl_classes[NS + "Cls"] = RDFClass(uri=NS + "Cls", labels=[Label("en", "Cls")])
    return t


def _mixed() -> Taxonomy:
    t = _skos_only()
    t.owl_classes[NS + "Cls"] = RDFClass(uri=NS + "Cls", labels=[Label("en", "Cls")])
    return t


# ── tab bar / treemap container are always present in the DOM ────────────────


def test_view_tabs_markup_always_present():
    for tax in (_skos_only(), _owl_only(), _mixed()):
        html = render_vowl_html(tax, file_path=None)
        assert 'id="view-tabs"' in html
        assert 'id="treemap"' in html


# ── taxonomy payload presence drives tab visibility ───────────────────────────


def test_owl_only_has_no_taxonomy_payload():
    html = render_vowl_html(_owl_only(), file_path=None)
    assert '"taxonomy":' not in html
    # Relations content (the pre-existing Cytoscape behaviour) is unaffected.
    assert '"type": "class"' in html


def test_skos_only_has_taxonomy_payload_and_relations_graph():
    html = render_vowl_html(_skos_only(), file_path=None)
    assert '"taxonomy":' in html
    # The existing Cytoscape graph still renders the SKOS content too — the tab
    # is additive, not a replacement.
    assert '"type": "concept"' in html or '"type": "topconcept"' in html
    assert '"type": "scheme"' in html


def test_mixed_has_taxonomy_payload_and_owl_relations():
    html = render_vowl_html(_mixed(), file_path=None)
    assert '"taxonomy":' in html
    assert '"type": "class"' in html
    assert '"type": "concept"' in html or '"type": "topconcept"' in html


def test_empty_taxonomy_has_no_taxonomy_payload():
    html = render_vowl_html(Taxonomy(), file_path=None)
    assert '"taxonomy":' not in html
