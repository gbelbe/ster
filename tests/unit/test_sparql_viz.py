"""Unit tests for the SPARQL → graph viz bridge.

Covers:
  - extract_result_uris  (sparql_query module)
  - build_query_result_graph  (viz_vowl module)
"""

from __future__ import annotations

from ster.model import Concept, RDFClass, Taxonomy
from ster.sparql_query import extract_result_uris
from ster.viz_vowl import build_query_result_graph

_NS = "http://ex.org/"


# ── extract_result_uris ───────────────────────────────────────────────────────


def test_extract_uris_from_single_column():
    rows = [[_NS + "A"], [_NS + "B"]]
    assert extract_result_uris(rows) == {_NS + "A", _NS + "B"}


def test_extract_uris_from_multiple_columns():
    rows = [[_NS + "A", _NS + "B"]]
    assert extract_result_uris(rows) == {_NS + "A", _NS + "B"}


def test_literal_values_are_skipped():
    rows = [["Cat"], ["42"], ["some label"]]
    assert extract_result_uris(rows) == set()


def test_mixed_row_extracts_only_uris():
    rows = [["Cat", _NS + "A", "literal"]]
    assert extract_result_uris(rows) == {_NS + "A"}


def test_empty_rows_returns_empty_set():
    assert extract_result_uris([]) == set()


def test_https_uris_are_extracted():
    rows = [["https://example.org/Thing"]]
    assert "https://example.org/Thing" in extract_result_uris(rows)


def test_duplicate_uris_are_deduplicated():
    rows = [[_NS + "A"], [_NS + "A"]]
    assert extract_result_uris(rows) == {_NS + "A"}


# ── build_query_result_graph — empty / unknown ─────────────────────────────────


def test_empty_uri_set_returns_empty_graph():
    tax = Taxonomy()
    tax.concepts[_NS + "A"] = Concept(uri=_NS + "A")
    result = build_query_result_graph(tax, set())
    assert result["nodes"] == []
    assert result["links"] == []


def test_unknown_uri_is_skipped():
    tax = Taxonomy()
    tax.concepts[_NS + "A"] = Concept(uri=_NS + "A")
    result = build_query_result_graph(tax, {_NS + "UNKNOWN"})
    assert result["nodes"] == []


# ── build_query_result_graph — nodes ──────────────────────────────────────────


def test_known_concept_uri_appears_as_node():
    tax = Taxonomy()
    tax.concepts[_NS + "A"] = Concept(uri=_NS + "A")
    result = build_query_result_graph(tax, {_NS + "A"})
    ids = [n["id"] for n in result["nodes"]]
    assert _NS + "A" in ids


def test_known_class_uri_appears_as_node():
    tax = Taxonomy()
    tax.owl_classes[_NS + "Cls"] = RDFClass(uri=_NS + "Cls")
    result = build_query_result_graph(tax, {_NS + "Cls"})
    ids = [n["id"] for n in result["nodes"]]
    assert _NS + "Cls" in ids


def test_only_matched_uris_become_nodes():
    tax = Taxonomy()
    tax.concepts[_NS + "A"] = Concept(uri=_NS + "A")
    tax.concepts[_NS + "B"] = Concept(uri=_NS + "B")
    result = build_query_result_graph(tax, {_NS + "A"})
    ids = [n["id"] for n in result["nodes"]]
    assert _NS + "A" in ids
    assert _NS + "B" not in ids


# ── build_query_result_graph — links ──────────────────────────────────────────


def test_link_between_two_result_uris_is_included():
    tax = Taxonomy()
    tax.concepts[_NS + "Parent"] = Concept(uri=_NS + "Parent")
    tax.concepts[_NS + "Child"] = Concept(uri=_NS + "Child", broader=[_NS + "Parent"])
    result = build_query_result_graph(tax, {_NS + "Parent", _NS + "Child"})
    sources = [lk["source"] for lk in result["links"]]
    assert _NS + "Child" in sources


def test_link_to_external_node_is_excluded():
    tax = Taxonomy()
    tax.concepts[_NS + "Parent"] = Concept(uri=_NS + "Parent")
    tax.concepts[_NS + "Child"] = Concept(uri=_NS + "Child", broader=[_NS + "Parent"])
    # Only Child in result set — Parent is absent, so the broader link is excluded
    result = build_query_result_graph(tax, {_NS + "Child"})
    assert result["links"] == []


def test_subclass_link_between_two_result_classes_is_included():
    tax = Taxonomy()
    tax.owl_classes[_NS + "Animal"] = RDFClass(uri=_NS + "Animal")
    tax.owl_classes[_NS + "Dog"] = RDFClass(uri=_NS + "Dog", sub_class_of=[_NS + "Animal"])
    result = build_query_result_graph(tax, {_NS + "Animal", _NS + "Dog"})
    link_types = [lk["type"] for lk in result["links"]]
    assert "subClassOf" in link_types


# ── build_query_result_graph — layout ─────────────────────────────────────────


def test_result_graph_always_uses_force_layout():
    tax = Taxonomy()
    tax.concepts[_NS + "A"] = Concept(uri=_NS + "A")
    result = build_query_result_graph(tax, {_NS + "A"})
    assert result["layout"] == "force"


def test_result_graph_uses_force_layout_even_for_owl_only():
    tax = Taxonomy()
    tax.owl_classes[_NS + "Cls"] = RDFClass(uri=_NS + "Cls")
    result = build_query_result_graph(tax, {_NS + "Cls"})
    assert result["layout"] == "force"
