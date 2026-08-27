"""Unit tests for the native (pyoxigraph) parse path in :mod:`ster.store`."""

from __future__ import annotations

from pathlib import Path

import pytest
import rdflib

from ster import store

_TTL = (
    "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
    "@prefix gear: <https://example.org/gear#> .\n"
    'gear:Tent a skos:Concept ; skos:prefLabel "Tent"@en, "Tente"@fr .\n'
    'gear:Dome a skos:Concept ; skos:prefLabel "Dome"@en ; skos:broader gear:Tent .\n'
)

_NT = (
    "<https://example.org/gear#Tent> "
    "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
    "<http://www.w3.org/2004/02/skos/core#Concept> .\n"
)

_XML = (
    '<?xml version="1.0"?>\n'
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"\n'
    '         xmlns:skos="http://www.w3.org/2004/02/skos/core#"\n'
    '         xmlns:gear="https://example.org/gear#">\n'
    '  <skos:Concept rdf:about="https://example.org/gear#Tent"/>\n'
    "</rdf:RDF>\n"
)


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("name", "text", "fmt"),
    [("a.ttl", _TTL, "turtle"), ("a.nt", _NT, "nt"), ("a.rdf", _XML, "xml")],
)
def test_native_index_matches_rdflib(tmp_path: Path, name, text, fmt):
    """The native index must carry the same triples as rdflib's."""
    path = _write(tmp_path, name, text)

    native = store._native_index(fmt, path)
    assert native is not None
    (index, by_type, _refs), _ns = native

    graph = rdflib.Graph()
    graph.parse(str(path), format=fmt)
    ref_index, ref_by_type, _refs = store._graph_index(graph)

    assert set(index) == set(ref_index)
    assert {k: sorted(v) for k, v in by_type.items()} == {
        k: sorted(v) for k, v in ref_by_type.items()
    }
    for uri in ref_index:
        assert sorted(map(str, index[uri])) == sorted(map(str, ref_index[uri]))


def test_native_index_preserves_language_tags(tmp_path: Path):
    """@en / @fr must survive the Rust->Python conversion as rdflib Literals."""
    path = _write(tmp_path, "a.ttl", _TTL)

    (index, _by_type, _refs), _ns = store._native_index("turtle", path)

    labels = [
        obj for _p, obj in index["https://example.org/gear#Tent"] if isinstance(obj, rdflib.Literal)
    ]
    assert {lit.language for lit in labels} == {"en", "fr"}


def test_native_index_returns_none_for_unsupported_format(tmp_path: Path):
    """An unmapped format must hand back to the rdflib path, not raise."""
    path = _write(tmp_path, "a.jsonld", "{}")

    assert store._native_index("json-ld", path) is None


def test_native_index_returns_none_on_parse_error(tmp_path: Path):
    """A file the Rust parser rejects falls back rather than failing the load."""
    path = _write(tmp_path, "bad.ttl", "@prefix ex: <https://example.org/> .\nex:A a ex:B\n")

    assert store._native_index("turtle", path) is None


def test_native_turtle_captures_file_prefixes(tmp_path: Path):
    path = _write(tmp_path, "a.ttl", _TTL)

    _parsed, ns_graph = store._native_index("turtle", path)

    bindings = {str(p): str(n) for p, n in ns_graph.namespace_manager.namespaces()}
    assert bindings["gear"] == "https://example.org/gear#"


def test_native_rdfxml_captures_xmlns_prefixes(tmp_path: Path):
    """RDF/XML prefixes come from an expat scan; pyoxigraph does not report them."""
    path = _write(tmp_path, "a.rdf", _XML)

    _parsed, ns_graph = store._native_index("xml", path)

    bindings = {str(p): str(n) for p, n in ns_graph.namespace_manager.namespaces()}
    assert bindings["gear"] == "https://example.org/gear#"


def test_load_matches_rdflib_for_a_clashing_prefix(tmp_path: Path):
    """rdflib rebinds a file's "geo" to "geo1"; the native path must not diverge."""
    text = (
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        "@prefix geo: <http://www.w3.org/2003/01/geo/wgs84_pos#> .\n"
        "@prefix ex: <https://example.org/x#> .\n"
        'ex:P a skos:Concept ; geo:lat "1.0" .\n'
    )
    path = _write(tmp_path, "clash.ttl", text)

    taxonomy = store.load(path)

    graph = rdflib.Graph()
    graph.parse(str(path), format="turtle")
    assert taxonomy.namespace_bindings == store.graph_to_taxonomy(graph).namespace_bindings


def test_rdfxml_with_a_doctype_falls_back(tmp_path: Path):
    """A DTD is the vector for entity-expansion attacks, so it is refused here.

    Returning None hands the file to rdflib, which still opens it — the file is
    not rejected, only this reader declines to be the one to scan it.
    """
    text = _XML.replace(
        '<?xml version="1.0"?>\n',
        '<?xml version="1.0"?>\n<!DOCTYPE rdf:RDF [<!ENTITY a "b">]>\n',
    )
    path = _write(tmp_path, "doctype.rdf", text)

    assert store._xmlns_prefixes(path) is None
    assert store._native_index("xml", path) is None
