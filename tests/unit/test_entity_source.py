"""One entity's Turtle: what the source pane reads.

The rule these tests hold: the pane shows the entity's *own* statements and then,
clearly separated and bounded, the statements that point at it. Both halves earn
their place — without the first there is nothing to read, and without the second
the pane cannot answer "what is this thing part of", because that fact is never
written on the thing itself.
"""

from __future__ import annotations

import rdflib

from ster.entity_source import MAX_INCOMING, entity_source

NS = "https://example.org/e#"

_PREFIXES = (
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    "@prefix owl:  <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .\n"
    f"@prefix ex:   <{NS}> .\n"
)


def _graph(turtle: str) -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(data=_PREFIXES + turtle, format="turtle")
    return graph


def test_the_entitys_own_statements_are_the_body() -> None:
    graph = _graph('ex:thing a owl:Class ; rdfs:label "Thing" .')
    source = entity_source(graph, NS + "thing")
    assert "ex:thing a owl:Class" in source.text
    assert '"Thing"' in source.text


def test_the_file_s_own_prefixes_are_used() -> None:
    """Not a wall of full IRIs: the pane has to read like the file it came from."""
    graph = _graph('ex:thing a owl:Class ; rdfs:label "Thing" .')
    text = entity_source(graph, NS + "thing").text
    assert f"@prefix ex: <{NS}>" in text
    assert f"<{NS}thing>" not in text


def test_blank_nodes_are_followed() -> None:
    """A blank node has no name, so stopping at it would print `[ ]` and lose the content."""
    graph = _graph("ex:thing rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:p ] .")
    text = entity_source(graph, NS + "thing").text
    assert "owl:Restriction" in text
    assert "owl:onProperty" in text


def test_what_points_at_the_entity_is_shown_and_marked() -> None:
    graph = _graph(
        "ex:thing a owl:Class .\n"
        "ex:dossier rdfs:seeAlso ex:thing .\n"
        "ex:other rdfs:seeAlso ex:thing ."
    )
    source = entity_source(graph, NS + "thing")
    assert source.incoming == 2
    assert "ex:dossier" in source.text
    assert "2 statements point here" in source.text


def test_the_entitys_own_block_is_the_focus_range() -> None:
    """So the pane can mark it: the inbound half below is context, not this subject."""
    graph = _graph("ex:thing a owl:Class .\nex:other rdfs:seeAlso ex:thing .")
    source = entity_source(graph, NS + "thing")
    lines = source.text.splitlines()
    focused = [lines[n - 1] for n in sorted(source.focus_lines)]
    assert any("ex:thing a owl:Class" in line for line in focused)
    assert not any("ex:other" in line for line in focused)


def test_inbound_statements_are_capped_and_the_cap_says_so() -> None:
    """A hub entity is the object of thousands of triples; the pane must stay openable."""
    referrers = "\n".join(f"ex:r{n} rdfs:seeAlso ex:thing ." for n in range(MAX_INCOMING + 15))
    source = entity_source(_graph(f"ex:thing a owl:Class .\n{referrers}"), NS + "thing")
    assert source.incoming == MAX_INCOMING + 15
    assert source.omitted == 15
    assert "omitted" in source.text


def test_an_entity_the_graph_does_not_have_says_so() -> None:
    """An empty pane reads as a broken feature, not as an absent entity."""
    source = entity_source(_graph("ex:thing a owl:Class ."), NS + "missing")
    assert "not in the graph" in source.text


def test_an_entity_with_only_inbound_statements_still_reads() -> None:
    """A URI used but never described: the pane says that, instead of going blank."""
    source = entity_source(_graph("ex:other rdfs:seeAlso ex:thing ."), NS + "thing")
    assert "no statements of its own" in source.text
    assert "ex:other" in source.text


def test_the_entity_is_not_listed_among_its_own_referrers() -> None:
    """A self-reference is already in the body; repeating it below would read as a second fact."""
    source = entity_source(_graph("ex:thing rdfs:seeAlso ex:thing ."), NS + "thing")
    assert source.incoming == 0
