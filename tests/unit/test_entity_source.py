"""One entity's Turtle: what the source pane reads.

The rule these tests hold: the pane shows the entity's *own* statements and then,
separately and bounded, the statements that point at it — each half split into
one block per file, so the reader can tell what their file says from what a
read-only context file adds. A block holds only statements that are really in a
file; everything ster says about them (headings, counts, notes) is the pane's
job, drawn in its own style, and never appears inside the Turtle.
"""

from __future__ import annotations

import rdflib

from ster import store
from ster.entity_source import MAX_INCOMING, entity_source

NS = "https://example.org/e#"

_PREFIXES = (
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    "@prefix owl:  <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .\n"
    "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
    f"@prefix ex:   <{NS}> .\n"
)


def _graph(turtle: str) -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(data=_PREFIXES + turtle, format="turtle")
    return graph


def _session(tmp_path, main_body: str, *contexts: tuple[str, str]):
    """Load *main_body* as vocab.ttl with (name, body) context files, as the TUI does."""
    main = tmp_path / "vocab.ttl"
    main.write_text(_PREFIXES + main_body, encoding="utf-8")
    paths = []
    for name, body in contexts:
        path = tmp_path / name
        path.write_text(_PREFIXES + body, encoding="utf-8")
        paths.append(path)
    tax = store.load(main, context=paths)
    return store.full_graph_rdflib(tax), store.provenance(tax)


def _names(blocks) -> list[str]:
    return [block.file.name for block in blocks]


# ── what counts as the entity's source ───────────────────────────────────────


def test_the_entitys_own_statements_are_the_body() -> None:
    source = entity_source(_graph('ex:thing a owl:Class ; rdfs:label "Thing" .'), NS + "thing")
    [block] = source.own
    assert "ex:thing a owl:Class" in block.turtle
    assert '"Thing"' in block.turtle


def test_the_file_s_own_prefixes_are_used() -> None:
    """Not a wall of full IRIs: the pane has to read like the file it came from."""
    text = entity_source(_graph('ex:thing a owl:Class ; rdfs:label "Thing" .'), NS + "thing").text
    assert f"@prefix ex: <{NS}>" in text
    assert f"<{NS}thing>" not in text


def test_blank_nodes_are_followed() -> None:
    """A blank node has no name, so stopping at it would print `[ ]` and lose the content."""
    graph = _graph("ex:thing rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:p ] .")
    text = entity_source(graph, NS + "thing").text
    assert "owl:Restriction" in text
    assert "owl:onProperty" in text


def test_what_points_at_the_entity_is_its_own_part() -> None:
    graph = _graph(
        "ex:thing a owl:Class .\nex:dossier rdfs:seeAlso ex:thing .\nex:other rdfs:seeAlso ex:thing ."
    )
    source = entity_source(graph, NS + "thing")
    assert source.incoming == 2
    assert "ex:dossier" in source.pointing[0].turtle
    assert "ex:dossier" not in source.own[0].turtle


def test_inbound_statements_are_capped_and_the_cap_is_counted() -> None:
    """A hub entity is the object of thousands of triples; the pane must stay openable."""
    referrers = "\n".join(f"ex:r{n} rdfs:seeAlso ex:thing ." for n in range(MAX_INCOMING + 15))
    source = entity_source(_graph(f"ex:thing a owl:Class .\n{referrers}"), NS + "thing")
    assert source.incoming == MAX_INCOMING + 15
    assert source.omitted == 15


def test_an_unknown_entity_has_no_turtle_at_all() -> None:
    """The pane says "not in the graph" in its own style; the Turtle stays empty."""
    source = entity_source(_graph("ex:thing a owl:Class ."), NS + "missing")
    assert (source.own, source.pointing, source.text) == ((), (), "")


def test_an_entity_with_only_inbound_statements_has_an_empty_own_part() -> None:
    source = entity_source(_graph("ex:other rdfs:seeAlso ex:thing ."), NS + "thing")
    assert source.own == ()
    assert "ex:other" in source.pointing[0].turtle


def test_the_entity_is_not_listed_among_its_own_referrers() -> None:
    """A self-reference is already in the body; repeating it below would read as a second fact."""
    source = entity_source(_graph("ex:thing rdfs:seeAlso ex:thing ."), NS + "thing")
    assert source.incoming == 0


# ── one block per file ───────────────────────────────────────────────────────


def test_own_statements_are_grouped_by_file(tmp_path) -> None:
    graph, prov = _session(
        tmp_path,
        'ex:Farm a skos:Concept ; skos:prefLabel "Farm"@en .\n',
        ("labels.ttl", 'ex:Farm skos:prefLabel "Ferme"@fr .\n'),
    )
    source = entity_source(graph, NS + "Farm", provenance=prov)

    assert _names(source.own) == ["vocab.ttl", "labels.ttl"]
    assert '"Farm"@en' in source.own[0].turtle and '"Ferme"@fr' not in source.own[0].turtle
    assert '"Ferme"@fr' in source.own[1].turtle and '"Farm"@en' not in source.own[1].turtle


def test_incoming_statements_are_grouped_by_file(tmp_path) -> None:
    graph, prov = _session(
        tmp_path,
        "ex:Farm a skos:Concept .\nex:Policy a skos:Concept ; skos:related ex:Farm .\n",
        ("labels.ttl", "ex:Field a skos:Concept ; skos:related ex:Farm .\n"),
    )
    source = entity_source(graph, NS + "Farm", provenance=prov)

    assert _names(source.pointing) == ["vocab.ttl", "labels.ttl"]
    assert "ex:Policy" in source.pointing[0].turtle
    assert "ex:Field" in source.pointing[1].turtle


def test_the_main_file_comes_first_then_context_files_in_load_order(tmp_path) -> None:
    graph, prov = _session(
        tmp_path,
        "ex:Farm a skos:Concept .\n",
        ("zeta.ttl", 'ex:Farm skos:altLabel "Z"@en .\n'),
        ("alpha.ttl", 'ex:Farm skos:altLabel "A"@en .\n'),
    )
    source = entity_source(graph, NS + "Farm", provenance=prov)

    assert _names(source.own) == ["vocab.ttl", "zeta.ttl", "alpha.ttl"]


def test_a_single_file_session_still_names_its_file(tmp_path) -> None:
    graph, prov = _session(tmp_path, "ex:Farm a skos:Concept .\n")

    assert _names(entity_source(graph, NS + "Farm", provenance=prov).own) == ["vocab.ttl"]


def test_blank_node_statements_follow_the_statement_that_owns_them(tmp_path) -> None:
    """Merging re-mints blank nodes, so they cannot be looked up by identity."""
    graph, prov = _session(
        tmp_path,
        "ex:Farm a owl:Class .\n",
        ("rules.ttl", "ex:Farm rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:p ] .\n"),
    )
    source = entity_source(graph, NS + "Farm", provenance=prov)
    by_file = {block.file.name: block.turtle for block in source.own}

    assert "owl:Restriction" in by_file["rules.ttl"]
    assert "owl:Restriction" not in by_file["vocab.ttl"]


def test_prefixes_are_written_once_for_every_block(tmp_path) -> None:
    """Repeating them in each block buried the statements; one block reads better."""
    graph, prov = _session(
        tmp_path,
        "ex:Farm a skos:Concept .\nex:Policy a skos:Concept ; skos:related ex:Farm .\n",
        ("links.ttl", "ex:Elsewhere rdfs:seeAlso ex:Farm .\n"),
    )
    source = entity_source(graph, NS + "Farm", provenance=prov)

    assert not any("@prefix" in block.turtle for block in (*source.own, *source.pointing))
    assert source.prefixes.count("@prefix skos:") == 1
    assert "@prefix rdfs:" in source.prefixes  # only the pointing block uses it


def test_the_prefixes_are_only_those_the_blocks_use(tmp_path) -> None:
    graph, prov = _session(tmp_path, "ex:Farm a skos:Concept .\n")

    assert "@prefix owl:" not in entity_source(graph, NS + "Farm", provenance=prov).prefixes


def test_each_block_parses_with_the_shared_prefixes(tmp_path) -> None:
    graph, prov = _session(
        tmp_path,
        "ex:Farm a skos:Concept .\n",
        ("labels.ttl", 'ex:Farm rdfs:label "Farm" .\n'),
    )
    source = entity_source(graph, NS + "Farm", provenance=prov)

    for block in source.own:
        rdflib.Graph().parse(data=f"{source.prefixes}\n{block.turtle}", format="turtle")


def test_copying_the_whole_pane_still_parses(tmp_path) -> None:
    """The copied text leads with the prefixes, so it is one valid document."""
    graph, prov = _session(
        tmp_path,
        "ex:Farm a skos:Concept .\n",
        ("labels.ttl", 'ex:Farm rdfs:label "Farm" .\n'),
    )
    text = entity_source(graph, NS + "Farm", provenance=prov).text

    assert text.startswith("@prefix")
    rdflib.Graph().parse(data=text, format="turtle")


def test_blocks_hold_only_file_statements_no_ster_notes(tmp_path) -> None:
    referrers = "".join(f"ex:r{n} skos:related ex:Farm .\n" for n in range(MAX_INCOMING + 5))
    graph, prov = _session(tmp_path, "ex:Farm a skos:Concept .\n" + referrers)
    source = entity_source(graph, NS + "Farm", provenance=prov)

    assert not any(line.lstrip().startswith("#") for line in source.text.splitlines())


def test_the_inbound_cap_is_applied_before_grouping(tmp_path) -> None:
    main = "".join(f"ex:m{n} skos:related ex:Farm .\n" for n in range(MAX_INCOMING))
    context = "".join(f"ex:c{n} skos:related ex:Farm .\n" for n in range(10))
    graph, prov = _session(tmp_path, "ex:Farm a skos:Concept .\n" + main, ("more.ttl", context))
    source = entity_source(graph, NS + "Farm", provenance=prov)

    shown = sum(block.turtle.count("skos:related") for block in source.pointing)
    assert (source.incoming, source.omitted, shown) == (MAX_INCOMING + 10, 10, MAX_INCOMING)


# ── line numbers and which files use each prefix ────────────────────────────


def _locate(path, uri: str) -> list[int]:
    from ster.source_lines import SourceLines

    lines = SourceLines.from_file(path)
    return lines.starts(uri) if lines else []


def _gutter(block) -> dict[str, str]:
    """``{first token of a line: its line mark}`` for the lines that carry one."""
    return {
        text.split()[0]: mark
        for text, mark in zip(block.turtle.splitlines(), block.lines, strict=True)
        if mark
    }


def test_each_statement_is_marked_with_the_line_it_starts_on(tmp_path) -> None:
    # _PREFIXES is five lines, so the body starts on line 6.
    graph, prov = _session(
        tmp_path,
        'ex:Farm a skos:Concept ;\n    skos:prefLabel "Farm"@en .\nex:Policy skos:related ex:Farm .\n',
    )
    source = entity_source(graph, NS + "Farm", provenance=prov, locate=_locate)

    assert _gutter(source.own[0]) == {"ex:Farm": "L6"}
    assert _gutter(source.pointing[0]) == {"ex:Policy": "L8"}


def test_only_a_statement_s_first_line_is_marked(tmp_path) -> None:
    graph, prov = _session(
        tmp_path,
        'ex:Farm a skos:Concept ;\n    skos:prefLabel "Farm"@en ;\n    skos:notation "F" .\n',
    )
    [block] = entity_source(graph, NS + "Farm", provenance=prov, locate=_locate).own

    assert [mark for mark in block.lines if mark] == ["L6"]
    assert len(block.lines) == len(block.turtle.splitlines())


def test_a_subject_starting_several_statements_lists_each_line(tmp_path) -> None:
    graph, prov = _session(
        tmp_path,
        'ex:Farm a skos:Concept .\nex:Other a skos:Concept .\nex:Farm skos:notation "F" .\n',
    )
    [block] = entity_source(graph, NS + "Farm", provenance=prov, locate=_locate).own

    assert _gutter(block) == {"ex:Farm": "L6, L8"}


def test_lines_come_from_each_block_s_own_file(tmp_path) -> None:
    graph, prov = _session(
        tmp_path,
        "ex:Farm a skos:Concept .\n",
        ("labels.ttl", '\n\nex:Farm skos:altLabel "Ferme"@fr .\n'),
    )
    source = entity_source(graph, NS + "Farm", provenance=prov, locate=_locate)

    assert [_gutter(block) for block in source.own] == [{"ex:Farm": "L6"}, {"ex:Farm": "L8"}]


def test_without_a_locator_no_line_is_marked(tmp_path) -> None:
    graph, prov = _session(tmp_path, "ex:Farm a skos:Concept .\n")
    [block] = entity_source(graph, NS + "Farm", provenance=prov).own

    assert not any(block.lines)


def test_each_prefix_names_the_files_whose_blocks_use_it(tmp_path) -> None:
    graph, prov = _session(
        tmp_path,
        "ex:Farm a skos:Concept .\n",
        ("links.ttl", "ex:Elsewhere rdfs:seeAlso ex:Farm .\n"),
    )
    uses = dict(entity_source(graph, NS + "Farm", provenance=prov).prefix_uses)

    by_name = {line.split()[1]: files for line, files in uses.items()}
    assert by_name["ex:"] == ("vocab.ttl", "links.ttl")
    assert by_name["skos:"] == ("vocab.ttl",)
    assert by_name["rdfs:"] == ("links.ttl",)


def test_prefixes_are_sorted_most_shared_first_then_by_name(tmp_path) -> None:
    graph, prov = _session(
        tmp_path,
        "ex:Farm a skos:Concept .\n",
        ("links.ttl", "ex:Elsewhere rdfs:seeAlso ex:Farm .\n"),
    )
    source = entity_source(graph, NS + "Farm", provenance=prov)

    names = [line.split()[1] for line, _ in source.prefix_uses]
    assert names == ["ex:", "rdfs:", "skos:"]
    assert source.prefixes.splitlines() == [line for line, _ in source.prefix_uses]
