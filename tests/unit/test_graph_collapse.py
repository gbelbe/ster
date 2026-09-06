"""Individuals are counted, not drawn, until you ask for them.

A file of a thousand shops opened with 1,993 nodes, of which 1,968 were
individuals: 98.7% of the graph and 98.5% of the payload, resent on every
refresh tick and laid out by a force algorithm whose cost grows far faster than
linearly in that number. Nobody opens a graph view to read a thousand identical
dots.

So above a threshold the graph carries classes only, each saying how many
individuals it holds, and a class hands its own over when asked. Below the
threshold nothing changes — a small ontology is legible whole, and collapsing it
would only hide things.
"""

from __future__ import annotations

import rdflib

from ster import store
from ster.viz_vowl import (
    CLASS_EXPAND_LIMIT,
    INDIVIDUAL_COLLAPSE_LIMIT,
    build_vowl_graph,
    class_individuals,
    collapse_individuals,
)

NS = "https://example.org/g#"


def _taxonomy(count: int, tmp_path):
    """An ontology with *count* individuals across two classes."""
    graph = rdflib.Graph()
    ttl = [
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        f"@prefix ex: <{NS}> .",
        'ex:Shop a owl:Class ; rdfs:label "Shop"@en .',
        'ex:Town a owl:Class ; rdfs:label "Town"@en .',
    ]
    for i in range(count):
        cls = "Shop" if i % 2 == 0 else "Town"
        ttl.append(f'ex:n{i} a owl:NamedIndividual, ex:{cls} ; rdfs:label "N{i}"@en .')
    path = tmp_path / "g.ttl"
    path.write_text("\n".join(ttl))
    graph.parse(str(path))  # fail loudly here rather than inside ster
    return store.load(str(path))


def test_a_small_ontology_is_left_whole(tmp_path) -> None:
    """Collapsing four individuals would hide things and save nothing."""
    graph = build_vowl_graph(_taxonomy(4, tmp_path))
    before = len(graph["nodes"])

    collapse_individuals(graph, limit=150)

    assert len(graph["nodes"]) == before
    assert "collapsed" not in graph


def test_above_the_threshold_only_classes_are_drawn(tmp_path) -> None:
    graph = collapse_individuals(build_vowl_graph(_taxonomy(200, tmp_path)), limit=150)

    assert {n["type"] for n in graph["nodes"]} == {"class"}
    assert graph["collapsed"] == 200


def test_a_class_says_how_many_it_holds(tmp_path) -> None:
    """The count is what makes the collapse legible rather than a silent gap."""
    graph = collapse_individuals(build_vowl_graph(_taxonomy(200, tmp_path)), limit=150)
    counts = {n["label"]: n.get("individualCount") for n in graph["nodes"]}

    assert counts["Shop"] == 100
    assert counts["Town"] == 100


def test_no_edge_is_left_pointing_at_something_that_is_gone(tmp_path) -> None:
    """A dangling edge is what makes a graph library throw rather than draw."""
    graph = collapse_individuals(build_vowl_graph(_taxonomy(200, tmp_path)), limit=150)
    ids = {n["id"] for n in graph["nodes"]}

    assert all(e["source"] in ids and e["target"] in ids for e in graph["edges"])


def test_a_class_hands_over_its_own_individuals(tmp_path) -> None:
    taxonomy = _taxonomy(200, tmp_path)

    payload = class_individuals(taxonomy, NS + "Shop")

    assert payload["total"] == 100
    assert {n["type"] for n in payload["nodes"]} == {"individual"}
    assert all(e["target"] == NS + "Shop" for e in payload["edges"])


def test_a_huge_class_is_capped_and_says_so(tmp_path) -> None:
    """Expanding a thousand-member class would reintroduce the freeze one click
    later, so it is capped — and reports the total it did not send."""
    taxonomy = _taxonomy(2 * CLASS_EXPAND_LIMIT + 40, tmp_path)

    payload = class_individuals(taxonomy, NS + "Shop")

    assert payload["total"] == CLASS_EXPAND_LIMIT + 20
    assert payload["shown"] == CLASS_EXPAND_LIMIT
    assert len(payload["nodes"]) == CLASS_EXPAND_LIMIT


def test_asking_for_a_class_with_no_individuals_is_not_an_error(tmp_path) -> None:
    payload = class_individuals(_taxonomy(4, tmp_path), NS + "Nothing")

    assert payload == {"nodes": [], "edges": [], "total": 0, "shown": 0}


# ── the served page, not just the JSON endpoint ───────────────────────────────
#
# Root cause of the regression below: #159 collapsed /api/graph, but the Graph
# view never asks that endpoint for its first payload. api_server serves a page
# built by render_vowl_html, which embeds the graph inline — uncollapsed. On a
# 1,027-shop file that page was 1,265 KB carrying all 1,968 individuals, so the
# freeze the collapse was written to prevent happened before the endpoint was
# ever called.
#
# Collapsing is only safe where the page can get the individuals back, and it
# gets them from /api/class-individuals. A live page carries an api_token; an
# offline export has none and must keep drawing them, or they become
# unreachable. That is the same signal _offline_banner already switches on.


def _served_page(tmp_path, count: int, *, api_token: str) -> str:
    from ster.viz_vowl import render_vowl_html

    taxonomy = _taxonomy(count, tmp_path)
    return render_vowl_html(taxonomy, tmp_path / "g.ttl", api_token=api_token)


def _individuals_in(page: str) -> int:
    return page.count('"type": "individual"') + page.count('"type":"individual"')


def test_the_served_page_collapses_individuals_regression(tmp_path) -> None:
    page = _served_page(tmp_path, INDIVIDUAL_COLLAPSE_LIMIT + 50, api_token="live-token")

    assert _individuals_in(page) == 0


def test_the_served_page_still_says_how_many_each_class_holds(tmp_path) -> None:
    page = _served_page(tmp_path, INDIVIDUAL_COLLAPSE_LIMIT + 50, api_token="live-token")

    assert "individualCount" in page


def test_an_offline_export_keeps_its_individuals(tmp_path) -> None:
    """No API to expand against, so collapsing would put them out of reach."""
    page = _served_page(tmp_path, INDIVIDUAL_COLLAPSE_LIMIT + 50, api_token="")

    assert _individuals_in(page) > 0


def test_a_small_ontology_is_left_whole_on_the_page_too(tmp_path) -> None:
    page = _served_page(tmp_path, 10, api_token="live-token")

    assert _individuals_in(page) == 10
