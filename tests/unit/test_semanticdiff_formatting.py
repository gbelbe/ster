"""Re-spelling a file is not a change to the ontology.

Turtle offers many ways to write the same graph: triples in any order, subjects
grouped with ``;``, objects with ``,``, ``a`` for rdf:type, prefixed names or
full URIs, shorthand literals. Git sees each of these as an edit, because git
compares bytes. semanticdiff must see none of them, because it compares graphs —
otherwise reformatting a file, or a serialiser changing its habits between
versions, would drown the real changes in noise.

Every case below asserts two things: that the two spellings really do differ as
text, and that semanticdiff reports nothing between them.
"""

from __future__ import annotations

from rdflib import Graph

from semanticdiff.changeset import compare
from semanticdiff.git_log import raw_diff
from semanticdiff.history import read_history
from tests._ontology_repo import ONTOLOGY, RepoBuilder

PREFIXES = """
@prefix ex:   <http://example.org/> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
"""


def turtle(body: str) -> Graph:
    graph = Graph()
    graph.parse(
        data=body if "@prefix" in body or "PREFIX" in body else PREFIXES + body, format="turtle"
    )
    return graph


def assert_same_meaning(before: str, after: str) -> None:
    """The two spellings differ as text, and not at all as a graph."""
    assert before != after, "the two spellings must actually differ, or this proves nothing"
    changes = compare(turtle(before), turtle(after))
    assert len(changes) == 0, f"re-spelling reported {[c.curie for c in changes]}"


# ── layout ────────────────────────────────────────────────────────────────────


def test_reordering_triples_is_not_a_change() -> None:
    assert_same_meaning(
        'ex:A a owl:Class . ex:B a owl:Class . ex:A rdfs:label "A"@en .',
        'ex:A rdfs:label "A"@en . ex:B a owl:Class . ex:A a owl:Class .',
    )


def test_indentation_and_blank_lines_are_not_a_change() -> None:
    assert_same_meaning(
        'ex:A a owl:Class ; rdfs:label "A"@en .',
        '\n\n   ex:A\n        a owl:Class ;\n        rdfs:label "A"@en\n   .\n\n',
    )


def test_comments_are_not_a_change() -> None:
    assert_same_meaning(
        "ex:A a owl:Class .",
        "# the top of the tree\nex:A a owl:Class .  # a comment here too\n",
    )


# ── turtle's shorthands ───────────────────────────────────────────────────────


def test_grouping_a_subject_with_a_semicolon_is_not_a_change() -> None:
    assert_same_meaning(
        'ex:A a owl:Class .\nex:A rdfs:label "A"@en .\nex:A rdfs:comment "c"@en .',
        'ex:A a owl:Class ; rdfs:label "A"@en ; rdfs:comment "c"@en .',
    )


def test_grouping_objects_with_a_comma_is_not_a_change() -> None:
    assert_same_meaning(
        "ex:A rdfs:subClassOf ex:B .\nex:A rdfs:subClassOf ex:C .",
        "ex:A rdfs:subClassOf ex:B, ex:C .",
    )


def test_a_keyword_and_rdf_type_are_not_a_change() -> None:
    assert_same_meaning("ex:A a owl:Class .", "ex:A rdf:type owl:Class .")


def test_full_uris_and_prefixed_names_are_not_a_change() -> None:
    assert_same_meaning(
        "ex:A a owl:Class .",
        "<http://example.org/A> a <http://www.w3.org/2002/07/owl#Class> .",
    )


def test_renaming_a_prefix_is_not_a_change() -> None:
    """The prefix is a spelling of the namespace, not part of the graph."""
    assert_same_meaning(
        "@prefix ex: <http://example.org/> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "ex:A a owl:Class .",
        "@prefix thing: <http://example.org/> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "thing:A a owl:Class .",
    )


def test_sparql_style_prefix_declarations_are_not_a_change() -> None:
    assert_same_meaning(
        "@prefix ex: <http://example.org/> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "ex:A a owl:Class .",
        "PREFIX ex: <http://example.org/>\n"
        "PREFIX owl: <http://www.w3.org/2002/07/owl#>\n"
        "ex:A a owl:Class .",
    )


# ── literals ──────────────────────────────────────────────────────────────────


def test_shorthand_and_typed_integers_are_not_a_change() -> None:
    assert_same_meaning(
        "ex:A ex:count 2 .",
        'ex:A ex:count "2"^^xsd:integer .',
    )


def test_triple_quoted_and_plain_strings_are_not_a_change() -> None:
    assert_same_meaning(
        'ex:A rdfs:label "hello"@en .',
        'ex:A rdfs:label """hello"""@en .',
    )


def test_boolean_shorthand_is_not_a_change() -> None:
    assert_same_meaning(
        "ex:A owl:deprecated true .",
        'ex:A owl:deprecated "true"^^xsd:boolean .',
    )


# ── blank nodes ───────────────────────────────────────────────────────────────


def test_blank_node_shorthand_and_labels_are_not_a_change() -> None:
    assert_same_meaning(
        "ex:A rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:p ] .",
        "ex:A rdfs:subClassOf _:r .\n_:r a owl:Restriction ; owl:onProperty ex:p .",
    )


def test_renaming_a_blank_node_label_is_not_a_change() -> None:
    assert_same_meaning(
        "ex:A rdfs:subClassOf _:one .\n_:one a owl:Restriction ; owl:onProperty ex:p .",
        "ex:A rdfs:subClassOf _:two .\n_:two a owl:Restriction ; owl:onProperty ex:p .",
    )


# ── the whole point, through git ──────────────────────────────────────────────


def test_a_reformatted_commit_is_a_git_diff_but_not_a_semantic_one(
    ontology_repo: RepoBuilder,
) -> None:
    """Git sees the edit; semanticdiff sees through it."""
    ontology_repo.commit(
        raw=PREFIXES + 'ex:A a owl:Class .\nex:A rdfs:label "A"@en .\nex:B a owl:Class .\n',
        message="first",
    )
    sha = ontology_repo.commit(
        raw=PREFIXES + "# reordered and grouped\nex:B rdf:type owl:Class .\n"
        'ex:A\n    rdf:type owl:Class ;\n    rdfs:label """A"""@en .\n',
        message="reformat only",
    )

    assert raw_diff(ontology_repo.path, sha, ONTOLOGY).strip(), "git must see an edit"

    history = read_history(ontology_repo.path, "HEAD", ONTOLOGY)
    assert history[1].commit.subject == "reformat only"
    assert len(history[1].changes) == 0


def test_a_real_edit_alongside_reformatting_is_still_reported(
    ontology_repo: RepoBuilder,
) -> None:
    """The blindness is to spelling only — a genuine change still comes through."""
    ontology_repo.commit(raw=PREFIXES + "ex:A a owl:Class .\n", message="first")
    ontology_repo.commit(
        raw=PREFIXES + "# reformatted, and one class added\n"
        "ex:A\n    rdf:type owl:Class .\nex:B rdf:type owl:Class .\n",
        message="reformat and add",
    )

    history = read_history(ontology_repo.path, "HEAD", ONTOLOGY)

    assert [c.curie for c in history[1].changes] == ["ex:B"]


# ── equivalences that hold, and one that does not ─────────────────────────────


def test_language_tag_case_is_not_a_change() -> None:
    """RDF 1.1 makes language tags case-insensitive, and rdflib normalises them."""
    assert_same_meaning('ex:A rdfs:label "A"@en .', 'ex:A rdfs:label "A"@EN .')


def test_escaped_and_literal_unicode_are_not_a_change() -> None:
    assert_same_meaning(
        'ex:A rdfs:label "café"@fr .',
        'ex:A rdfs:label "caf\\u00E9"@fr .',
    )


def test_a_value_equal_number_written_differently_is_reported() -> None:
    """Known limitation, asserted so it cannot change unnoticed.

    ``2.0`` and ``2.00`` are the same *value* but not the same RDF *term*: term
    equality compares the lexical form, and the diff is built on term equality,
    as every structural ontology diff is. So a serialiser that changed how it
    writes decimals would show up as a modification.

    Not fixed here: canonicalising the value space of every datatype is a much
    larger job than the noise it removes, and serialisers do not, in practice,
    change their number formatting between commits.
    """
    changes = compare(turtle("ex:A ex:n 2.0 ."), turtle("ex:A ex:n 2.00 ."))

    assert [c.curie for c in changes] == ["ex:A"]
