"""Unit tests for the read-only MCP context layer (:mod:`ster.mcp_context`).

These cover the context assembly on its own — no protocol, no transport — so a
failure here points at the graph logic rather than the MCP plumbing.
"""

from __future__ import annotations

import pytest

from ster import mcp_context as mc
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

NS = "https://example.org/zoo#"


def _lbl(value: str, lang: str = "en") -> Label:
    return Label(lang=lang, value=value, type=LabelType.PREF)


@pytest.fixture
def zoo() -> Taxonomy:
    """A small mixed SKOS + OWL taxonomy: Animal → Mammal → {Dog, Cat}."""
    tax = Taxonomy()
    tax.ontology_uri = "https://example.org/zoo"
    tax.schemes[NS + "Scheme"] = ConceptScheme(
        uri=NS + "Scheme",
        labels=[_lbl("Zoo Scheme")],
        top_concepts=[NS + "Animal"],
    )
    tax.concepts[NS + "Animal"] = Concept(
        uri=NS + "Animal",
        labels=[_lbl("Animal"), _lbl("Animal", "fr")],
        definitions=[Definition(lang="en", value="A living creature.")],
        narrower=[NS + "Mammal"],
        top_concept_of=NS + "Scheme",
    )
    tax.concepts[NS + "Mammal"] = Concept(
        uri=NS + "Mammal",
        labels=[_lbl("Mammal")],
        broader=[NS + "Animal"],
        narrower=[NS + "Dog", NS + "Cat"],
    )
    tax.concepts[NS + "Dog"] = Concept(
        uri=NS + "Dog", labels=[_lbl("Dog")], broader=[NS + "Mammal"]
    )
    tax.concepts[NS + "Cat"] = Concept(
        uri=NS + "Cat", labels=[_lbl("Cat")], broader=[NS + "Mammal"]
    )
    tax.owl_classes[NS + "Enclosure"] = RDFClass(uri=NS + "Enclosure", labels=[_lbl("Enclosure")])
    tax.owl_classes[NS + "Aviary"] = RDFClass(
        uri=NS + "Aviary", labels=[_lbl("Aviary")], sub_class_of=[NS + "Enclosure"]
    )
    tax.owl_individuals[NS + "Rex"] = OWLIndividual(
        uri=NS + "Rex", labels=[_lbl("Rex")], types=[NS + "Enclosure"]
    )
    return tax


# ── overview ──────────────────────────────────────────────────────────────────


def test_get_overview_reports_counts_and_base_uri(zoo):
    out = mc.overview(zoo)
    assert out["ontology_uri"] == "https://example.org/zoo"
    assert out["counts"]["concepts"] == 4
    assert out["counts"]["classes"] == 2
    assert out["counts"]["individuals"] == 1


def test_get_overview_lists_schemes_and_languages(zoo):
    out = mc.overview(zoo)
    assert out["schemes"] == [{"uri": NS + "Scheme", "label": "Zoo Scheme"}]
    assert out["languages"] == ["en", "fr"]


# ── entity ────────────────────────────────────────────────────────────────────


def test_get_entity_returns_labels_definition_and_types(zoo):
    out = mc.entity(zoo, NS + "Animal")
    assert out["kind"] == "concept"
    assert out["label"] == "Animal"
    assert out["descriptions"] == ["A living creature."]


def test_get_entity_includes_parent_and_children(zoo):
    out = mc.entity(zoo, NS + "Mammal")
    assert out["parents"] == [{"uri": NS + "Animal", "label": "Animal"}]
    assert {c["label"] for c in out["children"]} == {"Dog", "Cat"}


def test_get_entity_unknown_uri_returns_error_not_exception(zoo):
    out = mc.entity(zoo, NS + "Nope")
    assert out["error"] == "unknown_uri"


def test_get_entity_resolves_owl_subclass_hierarchy(zoo):
    """Parents/children work for OWL classes, not just SKOS concepts."""
    assert mc.entity(zoo, NS + "Aviary")["parents"] == [
        {"uri": NS + "Enclosure", "label": "Enclosure"}
    ]
    assert mc.entity(zoo, NS + "Enclosure")["children"] == [
        {"uri": NS + "Aviary", "label": "Aviary"}
    ]


def test_get_entity_individual_reports_its_types(zoo):
    assert mc.entity(zoo, NS + "Rex")["types"] == [NS + "Enclosure"]


# ── search ────────────────────────────────────────────────────────────────────


def test_search_entities_matches_label_substring_case_insensitive(zoo):
    hits = mc.search(zoo, "mamm")
    assert [h["uri"] for h in hits] == [NS + "Mammal"]


def test_search_entities_respects_limit(zoo):
    assert len(mc.search(zoo, "a", limit=2)) == 2


def test_search_entities_no_match_returns_empty(zoo):
    assert mc.search(zoo, "zzzz") == []


def test_search_entities_blank_query_returns_empty(zoo):
    assert mc.search(zoo, "   ") == []


def test_search_entities_spans_every_kind(zoo):
    assert {h["kind"] for h in mc.search(zoo, "e", limit=50)} >= {"concept", "class"}


# ── ancestors / siblings ──────────────────────────────────────────────────────


def test_ancestors_are_root_first(zoo):
    assert mc.ancestors_of(zoo, NS + "Dog") == [NS + "Animal", NS + "Mammal"]


def test_ancestors_of_root_is_empty(zoo):
    assert mc.ancestors_of(zoo, NS + "Animal") == []


def test_ancestors_stops_on_a_broader_cycle(zoo):
    """A malformed graph must not hang the server."""
    zoo.concepts[NS + "Animal"].broader = [NS + "Dog"]
    assert mc.ancestors_of(zoo, NS + "Dog") == [NS + "Animal", NS + "Mammal"]


def test_siblings_exclude_the_entity_itself(zoo):
    assert mc.siblings_of(zoo, NS + "Dog") == [NS + "Cat"]


# ── current_context ───────────────────────────────────────────────────────────


def test_current_context_returns_focused_entity_when_selection_published(zoo):
    out = mc.current_context(zoo, NS + "Dog")
    assert out["focused"]["label"] == "Dog"


def test_current_context_includes_breadcrumb_ancestors(zoo):
    out = mc.current_context(zoo, NS + "Dog")
    assert [a["label"] for a in out["ancestors"]] == ["Animal", "Mammal"]


def test_current_context_falls_back_to_overview_when_no_selection(zoo):
    out = mc.current_context(zoo, None)
    assert out["focused"] is None
    assert out["overview"]["counts"]["concepts"] == 4


def test_current_context_falls_back_when_selection_is_stale(zoo):
    """A URI that no longer exists must not error — the file was edited underneath."""
    out = mc.current_context(zoo, NS + "Deleted")
    assert out["focused"] is None


# ── SPARQL read-only guard ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "query",
    [
        "SELECT ?s WHERE { ?s ?p ?o }",
        "ASK { ?s ?p ?o }",
        "select ?s where { ?s ?p ?o } limit 10",
        # 'created' must not trip the CREATE keyword — word-boundary anchored.
        "SELECT ?s WHERE { ?s <https://ex.org/created> ?o }",
        # A literal mentioning a keyword is data, not a command.
        'SELECT ?s WHERE { ?s ?p "please delete this" }',
    ],
)
def test_run_sparql_accepts_read_only_queries(query):
    assert mc.is_read_only_sparql(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "INSERT DATA { <a> <b> <c> }",
        "DELETE WHERE { ?s ?p ?o }",
        "DROP GRAPH <g>",
        "CLEAR DEFAULT",
        "LOAD <http://example.org/data>",
        "insert data { <a> <b> <c> }",
    ],
)
def test_run_sparql_rejects_update_keywords(query):
    assert mc.is_read_only_sparql(query) is False


def test_run_sparql_refuses_a_write_query(zoo):
    out = mc.run_sparql(zoo, "INSERT DATA { <a> <b> <c> }")
    assert out["error"] == "read_only"


def test_run_sparql_without_a_source_file_reports_it(zoo):
    assert mc.run_sparql(zoo, "SELECT ?s WHERE { ?s ?p ?o }")["error"] == "no_source_file"


def test_run_sparql_select_returns_columns_and_rows(tmp_path):
    ttl = tmp_path / "zoo.ttl"
    ttl.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        '<https://example.org/zoo#Dog> a owl:Class ; rdfs:label "Dog"@en .\n',
        encoding="utf-8",
    )
    tax = Taxonomy()
    tax.file_path = ttl

    out = mc.run_sparql(tax, "SELECT ?s WHERE { ?s a <http://www.w3.org/2002/07/owl#Class> }")
    assert out["row_count"] == 1
    assert "https://example.org/zoo#Dog" in out["rows"][0][0]


def test_run_sparql_syntax_error_returns_error_payload(tmp_path):
    ttl = tmp_path / "zoo.ttl"
    ttl.write_text("<https://example.org/a> <https://example.org/b> <https://example.org/c> .\n")
    tax = Taxonomy()
    tax.file_path = ttl

    out = mc.run_sparql(tax, "SELECT ?s WHERE {{{")
    assert out["error"] == "query_error"
