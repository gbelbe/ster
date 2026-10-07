"""get_overview reads the store SPARQL runs against, so its figures are the ones a query returns."""

from __future__ import annotations

import pytest
import rdflib
from rdflib import RDF, SKOS, URIRef

from ster import mcp_context as mc
from ster.model import Concept, ConceptScheme, Label, LabelType, RDFClass, Taxonomy
from ster.sparql_query import run_query_on_taxonomy

NS = "https://example.org/g#"
CONCEPTS_WITH_HIDDEN = 2  # the one declared, and the one only the store holds
FINGERPRINT_DIGITS = 16  # 64 bits, in hex


def _label(value: str, lang: str = "en") -> Label:
    return Label(lang=lang, value=value, type=LabelType.PREF)


def _taxonomy() -> Taxonomy:
    tax = Taxonomy()
    tax.ontology_uri = "https://example.org/g"
    tax.schemes[NS + "S"] = ConceptScheme(
        uri=NS + "S", labels=[_label("Scheme"), _label("Schéma", "fr")]
    )
    tax.concepts[NS + "A"] = Concept(uri=NS + "A", labels=[_label("A"), _label("A", "fr")])
    tax.owl_classes[NS + "Thing"] = RDFClass(uri=NS + "Thing", labels=[_label("Thing", "de")])
    return tax


def _count(tax: Taxonomy, rdf_type: str) -> int:
    rows = run_query_on_taxonomy(
        tax, f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ ?s a <{rdf_type}> }}"
    ).rows
    return int(rows[0][0])


def test_the_counts_are_what_a_sparql_count_returns():
    tax = _taxonomy()
    counts = mc.overview(tax)["counts"]
    assert counts["concepts"] == _count(tax, str(SKOS.Concept)) == 1
    assert counts["schemes"] == _count(tax, str(SKOS.ConceptScheme)) == 1
    assert counts["classes"] == _count(tax, "http://www.w3.org/2002/07/owl#Class") == 1


def test_a_triple_the_model_cannot_describe_is_still_counted():
    """The model sets such triples aside as residue; the store, and so SPARQL, holds them."""
    tax = _taxonomy()
    tax.residue.append((URIRef(NS + "Hidden"), RDF.type, SKOS.Concept))
    assert _count(tax, str(SKOS.Concept)) == CONCEPTS_WITH_HIDDEN
    assert mc.overview(tax)["counts"]["concepts"] == CONCEPTS_WITH_HIDDEN


def test_an_instance_of_a_class_declared_nowhere_is_an_individual():
    tax = _taxonomy()
    tax.residue.append((URIRef(NS + "x1"), RDF.type, URIRef("https://example.org/other#Widget")))
    counts = mc.overview(tax)["counts"]
    assert counts["individuals"] == 1
    assert counts["classes"] == 1  # the widget class is mentioned, not declared


def test_concepts_schemes_and_classes_are_not_individuals():
    assert mc.overview(_taxonomy())["counts"]["individuals"] == 0


def test_the_ontology_and_the_languages_come_from_the_store():
    tax = _taxonomy()
    tax.residue.append(
        (URIRef(tax.ontology_uri or ""), rdflib.DCTERMS.title, rdflib.Literal("Graph G"))
    )
    out = mc.overview(tax)
    assert (out["ontology_uri"], out["title"]) == ("https://example.org/g", "Graph G")
    assert out["languages"] == ["de", "en", "fr"]


def test_a_scheme_is_labelled_in_the_asked_language_then_by_its_local_name():
    assert mc.overview(_taxonomy(), "fr")["schemes"] == [{"uri": NS + "S", "label": "Schéma"}]
    tax = (
        _taxonomy()
    )  # the store is built once per model, so change the model before the first question
    tax.schemes[NS + "Bare"] = ConceptScheme(uri=NS + "Bare")
    labels = {s["uri"]: s["label"] for s in mc.overview(tax)["schemes"]}
    assert labels == {NS + "S": "Scheme", NS + "Bare": "Bare"}


def test_the_graph_has_a_stamp_that_is_the_same_for_the_same_content():
    one, two = mc.overview(_taxonomy())["graph"], mc.overview(_taxonomy())["graph"]
    assert one == two
    assert one["triples"] > 0 and len(one["fingerprint"]) == FINGERPRINT_DIGITS


def test_any_change_to_the_graph_changes_the_stamp():
    before = mc.overview(_taxonomy())["graph"]
    tax = _taxonomy()
    tax.residue.append((URIRef(NS + "extra"), RDF.type, SKOS.Concept))
    after = mc.overview(tax)["graph"]
    assert after["fingerprint"] != before["fingerprint"]
    assert after["triples"] == before["triples"] + 1


def test_blank_node_labels_do_not_change_the_stamp():
    def with_blank(label: str):
        tax = _taxonomy()
        tax.residue.append((rdflib.BNode(label), RDF.type, SKOS.Concept))
        return mc.overview(tax)["graph"]

    assert with_blank("a1") == with_blank("zz9")


def test_the_answer_says_nothing_about_which_files_the_graph_came_from():
    tax = _taxonomy()
    out = mc.overview(tax)
    assert "context_files" not in out
    assert set(out) == {
        "ontology_uri",
        "title",
        "file",
        "graph",
        "server",
        "counts",
        "schemes",
        "languages",
    }


def test_an_empty_graph_has_zero_everything():
    out = mc.overview(Taxonomy())
    assert out["counts"] == dict.fromkeys(
        ("schemes", "concepts", "classes", "individuals", "properties"), 0
    )
    assert (out["ontology_uri"], out["schemes"], out["languages"]) == (None, [], [])


def test_the_overview_says_when_this_ster_process_started():
    first, second = mc.overview(_taxonomy())["server"], mc.overview(_taxonomy())["server"]
    assert first == second  # one process, one start
    assert first["started"].endswith("Z")


def test_a_model_that_refuses_attributes_still_gets_a_stamp_each_time():
    from ster.graph_overview import graph_fingerprint

    class Stubborn(Taxonomy):
        def __setattr__(self, name, value):
            if name == "_ster_fingerprint":
                raise AttributeError(name)  # nothing can be remembered on it
            super().__setattr__(name, value)

    tax = Stubborn()
    tax.concepts[NS + "A"] = Concept(uri=NS + "A", labels=[_label("A")])
    assert graph_fingerprint(tax) == graph_fingerprint(tax)  # recomputed, and the same


def test_a_failing_overview_query_is_reported(monkeypatch):
    import ster.graph_overview as go
    from ster.sparql_query import QueryResult

    monkeypatch.setattr(go, "run_query_on_taxonomy", lambda *_a: QueryResult([], [], error="boom"))
    with pytest.raises(ValueError, match="boom"):
        go.graph_overview(_taxonomy())
