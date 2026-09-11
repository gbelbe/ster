"""Which view the graph page opens on, and in what order the tabs sit.

A file with both an ontology and a scheme is an ontology that happens to carry
a scheme, so that is the half to open on. The page used to choose the taxonomy
whenever one existed at all — `hasTax ? 'taxonomy' : 'relations'` — so an OWL
ontology with a single SKOS scheme in it opened on the smaller half of itself.

The data-view keys are unchanged on purpose: "relations" is wired through
graph_app.js and the .view-relations CSS, so renaming it is a refactor rather
than a relabel. These tests read the keys, and the labels separately, so a
future rename fails here loudly instead of silently swapping the tabs.
"""

from __future__ import annotations

import re


def _page() -> str:
    from ster.viz_vowl import _html_template

    for name in dir(_html_template):
        value = getattr(_html_template, name)
        if isinstance(value, str) and 'id="view-tabs"' in value:
            return value
    raise AssertionError("no template string carrying the tab bar")


def _tab_order(page: str) -> list[str]:
    return re.findall(r'<button class="vt-btn" data-view="([a-z]+)"', page)


def _tab_labels(page: str) -> list[str]:
    return re.findall(r'<button class="vt-btn" data-view="[a-z]+">([^<]+)</button>', page)


def test_the_ontology_tab_comes_first():
    assert _tab_order(_page())[0] == "relations"


def test_the_taxonomy_tab_comes_second():
    assert _tab_order(_page())[1] == "taxonomy"


def test_the_tabs_read_ontology_then_taxonomy():
    """ "Relations" described the edges, not the thing. And "Taxonomie" was the
    one French word in an English interface."""
    assert _tab_labels(_page()) == ["Ontology", "Taxonomy"]


def test_a_file_with_both_opens_on_the_ontology():
    """The regression: hasTax won whenever a scheme existed at all."""
    page = _page()

    assert "var initial=hasRel?'relations':'taxonomy';" in page
    assert "hasTax?'taxonomy'" not in page


def test_a_scheme_only_file_still_opens_on_the_taxonomy():
    """hasRel is false when the ontology half is empty, so the ternary falls
    through — a SKOS-only file is unaffected by the change."""
    page = _page()
    match = re.search(r"var initial=(\w+)\?'(\w+)':'(\w+)';", page)

    assert match is not None
    condition, when_true, when_false = match.groups()
    assert (condition, when_true, when_false) == ("hasRel", "relations", "taxonomy")
