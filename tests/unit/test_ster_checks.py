"""Unit tests for ster-specific semanticlint URI quality checks."""

from __future__ import annotations

from rdflib import RDF, Graph, URIRef
from rdflib.namespace import OWL, RDFS
from semanticlint.checks.base import CheckConfig, Severity

from ster.plugins.semanticlint.checks import FileSchemeURICheck, NonHTTPSchemeURICheck

BASE = "https://example.org/onto#"
FILE = "file:///Users/me/onto.owl#"


def _graph(*triples) -> Graph:
    g = Graph()
    for s, p, o in triples:
        g.add((s, p, o))
    return g


def _cfg() -> CheckConfig:
    return CheckConfig()


# ── URI001: file:// scheme ─────────────────────────────────────────────────────


def test_file_uri_class_raises_error():
    g = _graph((URIRef(FILE + "Person"), RDF.type, OWL.Class))
    v = FileSchemeURICheck().run(g, _cfg())
    assert len(v) == 1
    assert v[0].check_id == "URI001"
    assert v[0].severity == Severity.ERROR


def test_file_uri_property_raises_error():
    g = _graph((URIRef(FILE + "hasProp"), RDF.type, OWL.ObjectProperty))
    v = FileSchemeURICheck().run(g, _cfg())
    assert len(v) == 1
    assert v[0].check_id == "URI001"


def test_file_uri_individual_raises_error():
    g = _graph((URIRef(FILE + "alice"), RDF.type, OWL.NamedIndividual))
    v = FileSchemeURICheck().run(g, _cfg())
    assert len(v) == 1
    assert v[0].check_id == "URI001"


def test_http_uri_no_uri001():
    g = _graph((URIRef(BASE + "Person"), RDF.type, OWL.Class))
    v = FileSchemeURICheck().run(g, _cfg())
    assert v == []


def test_https_uri_no_uri001():
    g = _graph((URIRef("https://ex.org/onto#Person"), RDF.type, OWL.Class))
    v = FileSchemeURICheck().run(g, _cfg())
    assert v == []


def test_multiple_file_uris_all_reported():
    g = Graph()
    for name in ("A", "B", "C"):
        g.add((URIRef(FILE + name), RDF.type, OWL.Class))
    v = FileSchemeURICheck().run(g, _cfg())
    assert len(v) == 3
    assert all(x.check_id == "URI001" for x in v)


def test_builtin_owl_uris_not_flagged_by_uri001():
    g = _graph((OWL.Class, RDFS.subClassOf, RDFS.Resource))
    v = FileSchemeURICheck().run(g, _cfg())
    assert v == []


def test_uri001_subject_is_populated():
    uri = FILE + "Person"
    g = _graph((URIRef(uri), RDF.type, OWL.Class))
    v = FileSchemeURICheck().run(g, _cfg())
    assert str(v[0].subject) == uri


# ── URI002: non-HTTP(S) scheme ─────────────────────────────────────────────────


def test_urn_class_raises_uri002():
    g = _graph((URIRef("urn:example:Person"), RDF.type, OWL.Class))
    v = NonHTTPSchemeURICheck().run(g, _cfg())
    assert len(v) == 1
    assert v[0].check_id == "URI002"
    assert v[0].severity == Severity.WARNING


def test_http_uri_no_uri002():
    g = _graph((URIRef(BASE + "Person"), RDF.type, OWL.Class))
    v = NonHTTPSchemeURICheck().run(g, _cfg())
    assert v == []


def test_https_uri_no_uri002():
    g = _graph((URIRef("https://ex.org/onto#Person"), RDF.type, OWL.Class))
    v = NonHTTPSchemeURICheck().run(g, _cfg())
    assert v == []


def test_file_uri_not_double_reported_by_uri002():
    # file:// URIs are covered by URI001; URI002 should not also flag them
    g = _graph((URIRef(FILE + "Person"), RDF.type, OWL.Class))
    v = NonHTTPSchemeURICheck().run(g, _cfg())
    assert v == []


def test_builtin_uris_not_flagged_by_uri002():
    g = _graph((OWL.Class, RDFS.subClassOf, RDFS.Resource))
    v = NonHTTPSchemeURICheck().run(g, _cfg())
    assert v == []


def test_clean_graph_no_violations():
    g = Graph()
    for name in ("A", "B"):
        g.add((URIRef(f"https://example.org/onto#{name}"), RDF.type, OWL.Class))
    v = FileSchemeURICheck().run(g, _cfg()) + NonHTTPSchemeURICheck().run(g, _cfg())
    assert v == []
