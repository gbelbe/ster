"""The primitives every visualisation asks of an entity.

One definition each, so a second view costs no third copy — and so a fix lands
once. The vendoring helper is here too: "download a library once into
~/.cache/ster and inline it" is a rule about how ster ships pages, not about any
one library.
"""

from __future__ import annotations

import rdflib

from ster import viz_shared

NS = "https://example.org/v#"

TURTLE = f"""
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex:   <{NS}> .

ex:Thing  a owl:Class ; rdfs:label "Thing" .
ex:Widget a owl:Class ; rdfs:subClassOf ex:Thing ; rdfs:label "Widget" .
ex:Shiny  a owl:Class ; rdfs:label "Shiny" .

ex:a a owl:NamedIndividual, ex:Thing, ex:Widget, ex:Shiny ;
     skos:prefLabel "Preferred" ; rdfs:label "Fallback" .
ex:b a owl:NamedIndividual ; rdfs:label "Plain" .
ex:c a owl:NamedIndividual ; ex:mentions ex:b .
"""


def _graph() -> rdflib.Graph:
    return rdflib.Graph().parse(data=TURTLE, format="turtle")


def test_skos_preferred_label_wins_over_rdfs() -> None:
    assert viz_shared.label_of(_graph(), rdflib.URIRef(NS + "a")) == "Preferred"


def test_an_unlabelled_node_falls_back_to_the_uri_tail() -> None:
    assert viz_shared.label_of(_graph(), rdflib.URIRef(NS + "zzz")) == "zzz"


def test_local_name_handles_both_separators() -> None:
    assert viz_shared.local_name("https://ex.org/a#b") == "b"
    assert viz_shared.local_name("https://ex.org/a/b") == "b"
    assert viz_shared.local_name("bare") == "bare"


def test_a_cell_is_a_uri_only_when_it_looks_like_one() -> None:
    assert viz_shared.is_uri("https://ex.org/a")
    assert viz_shared.is_uri("urn:x:1")
    assert not viz_shared.is_uri("Widget")
    assert not viz_shared.is_uri("")


def test_an_implied_class_is_dropped_but_a_parallel_one_is_kept() -> None:
    """Widget implies Thing, so Thing goes; Shiny is another axis, so it stays."""
    types = viz_shared.most_specific_types(_graph(), rdflib.URIRef(NS + "a"))
    assert types == sorted([NS + "Shiny", NS + "Widget"])


def test_reach_is_inward_and_bounded() -> None:
    graph = _graph()
    seen = viz_shared.reachable_inward(graph, rdflib.URIRef(NS + "b"), lambda _g, _n: True, depth=1)
    assert NS + "b" in seen and NS + "c" in seen


def test_reach_of_zero_depth_is_the_node_itself() -> None:
    graph = _graph()
    assert viz_shared.reachable_inward(
        graph, rdflib.URIRef(NS + "b"), lambda _g, _n: True, depth=0
    ) == [NS + "b"]


# ── vendoring ─────────────────────────────────────────────────────────────────


def test_a_cached_asset_is_read_without_a_download(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    monkeypatch.setattr(viz_shared, "ster_cache_dir", lambda: tmp_path)
    (tmp_path / "lib.js").write_text("console.log(1)", encoding="utf-8")
    assert viz_shared.vendored("lib.js", "https://example.invalid/lib.js") == "console.log(1)"


def test_an_unreachable_asset_yields_none_rather_than_raising(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    """The page falls back to a CDN tag: absent beats a stack trace."""
    monkeypatch.setattr(viz_shared, "ster_cache_dir", lambda: tmp_path)
    assert viz_shared.vendored("absent.js", "https://example.invalid/absent.js") is None
