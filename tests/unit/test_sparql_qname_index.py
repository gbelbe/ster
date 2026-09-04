"""Unit tests for build_qname_index."""

from __future__ import annotations

from ster.model import RDFClass, Taxonomy
from ster.sparql_query import build_qname_index

_NS = "https://ex.org/kai/"


def test_build_qname_index_includes_standard_prefixes():
    """Even an empty taxonomy gets the six well-known prefixes populated."""
    tax = Taxonomy()
    idx = build_qname_index(tax)
    for pfx in ("rdf", "rdfs", "owl", "skos", "dcterms", "xsd"):
        assert pfx in idx
        assert idx[pfx] == sorted(idx[pfx])
    assert "type" in idx["rdf"]
    assert "Class" in idx["owl"]


def test_build_qname_index_includes_local_names_from_taxonomy():
    tax = Taxonomy()
    tax.namespace_bindings["kai"] = _NS
    tax.owl_classes[_NS + "Widget"] = RDFClass(uri=_NS + "Widget")
    idx = build_qname_index(tax)
    assert "Widget" in idx["kai"]


def test_build_qname_index_does_not_duplicate_taxonomy_and_standard_entries():
    """A taxonomy-declared local name matching a standard qname isn't duplicated."""
    tax = Taxonomy()
    tax.namespace_bindings["rdf"] = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    tax.owl_classes["http://www.w3.org/1999/02/22-rdf-syntax-ns#type"] = RDFClass(
        uri="http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    )
    idx = build_qname_index(tax)
    assert idx["rdf"].count("type") == 1
