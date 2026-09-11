"""Unit tests for the read-only MCP context layer (:mod:`ster.mcp_context`).

These cover the context assembly on its own — no protocol, no transport — so a
failure here points at the graph logic rather than the MCP plumbing.
"""

from __future__ import annotations

import pytest

from ster import mcp_context as mc
from ster import store
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


def test_run_sparql_answers_a_taxonomy_that_has_no_file(zoo):
    """It used to report no_source_file, because the query read the file. It
    reads the model now, so an in-memory taxonomy answers like any other — a
    capability gained, not a contract quietly dropped."""
    out = mc.run_sparql(zoo, "SELECT ?s WHERE { ?s ?p ?o }")

    assert "error" not in out
    assert out["row_count"] > 0


def test_run_sparql_select_returns_columns_and_rows(tmp_path):
    ttl = tmp_path / "zoo.ttl"
    ttl.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        '<https://example.org/zoo#Dog> a owl:Class ; rdfs:label "Dog"@en .\n',
        encoding="utf-8",
    )
    # Loaded, not just pointed at: run_sparql answers from the session's model
    # so the map sees context files and unsaved edits, and a Taxonomy carrying
    # only a path is a shape no caller actually holds.
    tax = store.load(ttl)

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


# ── get_vocabulary ────────────────────────────────────────────────────────────
#
# The probe reads the *file*, not the in-memory Taxonomy: an agent composing
# SPARQL needs the predicates actually asserted on disk, which is what its query
# will run against.

SKOS_TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://example.org/zoo#> .
ex:Animal a skos:Concept ; skos:prefLabel "Animal"@en, "Animal"@fr .
ex:Mammal a skos:Concept ; skos:prefLabel "Mammal"@en, "Mammifere"@fr ;
    skos:broader ex:Animal ; skos:notation "M1" .
ex:Dog a skos:Concept ; skos:prefLabel "Dog"@en ; skos:broader ex:Mammal .
"""

OWL_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <https://example.org/zoo#> .
ex:Enclosure a owl:Class ; rdfs:label "Enclosure"@en .
ex:Aviary a owl:Class ; rdfs:label "Aviary"@en ; rdfs:subClassOf ex:Enclosure .
"""


def _tax_from(tmp_path, ttl: str, name: str = "vocab.ttl") -> Taxonomy:
    """*name* must be distinct per call within a test: load_graph_cached keys its
    cache on (path, mtime), and two writes to the same path close enough in time
    can land on the same mtime — the second read would then silently see the
    first write's stale cached graph instead of its own content."""
    path = tmp_path / name
    path.write_text(ttl, encoding="utf-8")
    tax = Taxonomy()
    tax.file_path = path
    return tax


def test_vocabulary_reports_skos_shape_for_a_concept_scheme(tmp_path):
    assert mc.vocabulary(_tax_from(tmp_path, SKOS_TTL))["shape"] == "skos"


def test_vocabulary_reports_owl_shape_for_a_class_hierarchy(tmp_path):
    assert mc.vocabulary(_tax_from(tmp_path, OWL_TTL))["shape"] == "owl"


def test_vocabulary_reports_mixed_shape(tmp_path):
    out = mc.vocabulary(_tax_from(tmp_path, SKOS_TTL + OWL_TTL))
    assert out["shape"] == "mixed"


def test_vocabulary_ranks_predicates_by_use(tmp_path):
    out = mc.vocabulary(_tax_from(tmp_path, SKOS_TTL))
    counts = [p["count"] for p in out["predicates"]]
    assert counts == sorted(counts, reverse=True)
    # skos:prefLabel is asserted 5 times, more than any other predicate here.
    assert out["predicates"][0]["prefixed"] == "skos:prefLabel"


def test_vocabulary_identifies_the_dominant_label_predicate(tmp_path):
    """A file using rdfs:label must never send the agent to skos:prefLabel."""
    out = mc.vocabulary(_tax_from(tmp_path, OWL_TTL))
    assert "rdfs:label" in out["label_predicates"]
    assert "skos:prefLabel" not in out["label_predicates"]


def test_vocabulary_lists_hierarchy_predicates_actually_present(tmp_path):
    # Two different files: load_graph_cached's (path, mtime) key can't tell two
    # writes to the same path apart when they land in the same mtime tick.
    assert mc.vocabulary(_tax_from(tmp_path, SKOS_TTL, "skos.ttl"))["hierarchy_predicates"] == [
        "skos:broader"
    ]
    assert mc.vocabulary(_tax_from(tmp_path, OWL_TTL, "owl.ttl"))["hierarchy_predicates"] == [
        "rdfs:subClassOf"
    ]


def test_vocabulary_reports_namespace_bindings_from_the_file(tmp_path):
    """Prefix bindings are invisible to SPARQL — only the parsed graph has them."""
    out = mc.vocabulary(_tax_from(tmp_path, SKOS_TTL))
    assert out["namespaces"]["ex"] == "https://example.org/zoo#"


def test_vocabulary_lists_every_language_tag(tmp_path):
    assert mc.vocabulary(_tax_from(tmp_path, SKOS_TTL))["languages"] == ["en", "fr"]


def test_vocabulary_counts_types(tmp_path):
    out = mc.vocabulary(_tax_from(tmp_path, SKOS_TTL))
    concept = next(t for t in out["types"] if t["prefixed"] == "skos:Concept")
    assert concept["count"] == 3


def test_vocabulary_without_source_file_returns_error(zoo):
    assert mc.vocabulary(zoo)["error"] == "no_source_file"


def test_vocabulary_on_empty_graph_returns_empty_inventory(tmp_path):
    out = mc.vocabulary(_tax_from(tmp_path, "# nothing here\n"))
    assert out["predicates"] == []
    assert out["label_predicates"] == []
    assert out["shape"] == "unknown"
