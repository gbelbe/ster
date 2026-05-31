"""Unit tests for _sanitize_ontpub_graph — the pre-processing step before pyLODE."""

from __future__ import annotations

import tempfile
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF

from ster.html_export import _sanitize_ontpub_graph

NS = "https://example.org/onto#"
ONT = "https://example.org/onto"


def _write_ttl(content: str) -> Path:
    with tempfile.NamedTemporaryFile(suffix=".ttl", delete=False, mode="w") as f:
        f.write(content)
        return Path(f.name)


def _load_sanitized(ttl: str) -> tuple[Graph, Path]:
    src = _write_ttl(ttl)
    tmp = _sanitize_ontpub_graph(src)
    src.unlink(missing_ok=True)
    g = Graph()
    g.parse(str(tmp))
    return g, tmp


# ── bare-namespace URI removal ────────────────────────────────────────────────


def test_removes_triples_with_hash_ending_subject():
    """ns1: a owl:ObjectProperty → triple removed from sanitized graph."""
    ttl = (
        f"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        f"@prefix ns1: <{NS}> .\n"
        f"<{ONT}> a owl:Ontology .\n"
        f"ns1: a owl:ObjectProperty .\n"  # bare namespace URI as entity
    )
    g, tmp = _load_sanitized(ttl)
    tmp.unlink(missing_ok=True)
    bad = URIRef(NS)  # ends with '#'
    assert not list(g.triples((bad, None, None)))


def test_preserves_normal_entities():
    """Real class declarations in the ontology are kept."""
    ttl = (
        f"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        f"@prefix ns1: <{NS}> .\n"
        f"<{ONT}> a owl:Ontology .\n"
        f"ns1:MyClass a owl:Class .\n"
    )
    g, tmp = _load_sanitized(ttl)
    tmp.unlink(missing_ok=True)
    assert (URIRef(NS + "MyClass"), RDF.type, OWL.Class) in g


# ── dcterms:title injection ───────────────────────────────────────────────────


def test_adds_title_from_rdfs_label():
    ttl = (
        f"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        f"@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        f'<{ONT}> a owl:Ontology ; rdfs:label "Kai" .\n'
    )
    g, tmp = _load_sanitized(ttl)
    tmp.unlink(missing_ok=True)
    title = g.value(URIRef(ONT), DCTERMS.title)
    assert str(title) == "Kai"


def test_adds_title_from_uri_local_name_when_no_label():
    ttl = f"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n<{ONT}> a owl:Ontology .\n"
    g, tmp = _load_sanitized(ttl)
    tmp.unlink(missing_ok=True)
    title = g.value(URIRef(ONT), DCTERMS.title)
    assert title is not None
    assert str(title) != ""


def test_preserves_existing_title():
    ttl = (
        f"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        f"@prefix dcterms: <http://purl.org/dc/terms/> .\n"
        f'<{ONT}> a owl:Ontology ; dcterms:title "Custom Title" .\n'
    )
    g, tmp = _load_sanitized(ttl)
    tmp.unlink(missing_ok=True)
    assert str(g.value(URIRef(ONT), DCTERMS.title)) == "Custom Title"


# ── dcterms:description injection ────────────────────────────────────────────


def test_adds_description_from_rdfs_label():
    ttl = (
        f"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        f"@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        f'<{ONT}> a owl:Ontology ; rdfs:label "Kai" .\n'
    )
    g, tmp = _load_sanitized(ttl)
    tmp.unlink(missing_ok=True)
    desc = g.value(URIRef(ONT), DCTERMS.description)
    assert str(desc) == "Kai"


def test_adds_empty_description_when_no_label():
    ttl = f"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n<{ONT}> a owl:Ontology .\n"
    g, tmp = _load_sanitized(ttl)
    tmp.unlink(missing_ok=True)
    desc = g.value(URIRef(ONT), DCTERMS.description)
    assert desc is not None


def test_preserves_existing_description():
    ttl = (
        f"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        f"@prefix dcterms: <http://purl.org/dc/terms/> .\n"
        f'<{ONT}> a owl:Ontology ; dcterms:description "Existing desc" .\n'
    )
    g, tmp = _load_sanitized(ttl)
    tmp.unlink(missing_ok=True)
    assert str(g.value(URIRef(ONT), DCTERMS.description)) == "Existing desc"


# ── temp file cleanup ─────────────────────────────────────────────────────────


def test_returns_path_to_existing_file():
    ttl = f"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n<{ONT}> a owl:Ontology .\n"
    src = _write_ttl(ttl)
    tmp = _sanitize_ontpub_graph(src)
    src.unlink(missing_ok=True)
    assert tmp.exists()
    assert tmp.suffix == ".ttl"
    tmp.unlink(missing_ok=True)
