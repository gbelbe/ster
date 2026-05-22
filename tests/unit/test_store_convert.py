"""Unit tests for store.convert, convert_to_ttl, file_hash, is_rdfxml_path."""

from __future__ import annotations

from pathlib import Path

import pytest
from rdflib import Graph, URIRef

from ster import store

_S = URIRef("https://example.org/subject")
_P = URIRef("https://example.org/predicate")
_O = URIRef("https://example.org/object")
_TRIPLE = (_S, _P, _O)

_RDF_XML = """\
<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about="https://example.org/subject">
    <ns0:predicate xmlns:ns0="https://example.org/" rdf:resource="https://example.org/object"/>
  </rdf:Description>
</rdf:RDF>
"""

_TTL = "@prefix ex: <https://example.org/> .\nex:subject ex:predicate ex:object .\n"


# ── _detect_format ────────────────────────────────────────────────────────────


def test_detect_format_owl_returns_xml():
    assert store._detect_format(Path("ontology.owl")) == "xml"


def test_detect_format_n3_returns_n3():
    assert store._detect_format(Path("data.n3")) == "n3"


def test_detect_format_unsupported_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        store._detect_format(Path("data.csv"))


# ── is_rdfxml_path ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("ext", [".rdf", ".xml", ".owl"])
def test_is_rdfxml_path_true(ext):
    assert store.is_rdfxml_path(Path(f"file{ext}")) is True


@pytest.mark.parametrize("ext", [".ttl", ".jsonld", ".n3", ".json"])
def test_is_rdfxml_path_false(ext):
    assert store.is_rdfxml_path(Path(f"file{ext}")) is False


def test_is_rdfxml_path_case_insensitive():
    assert store.is_rdfxml_path(Path("file.OWL")) is True
    assert store.is_rdfxml_path(Path("file.RDF")) is True


# ── file_hash ─────────────────────────────────────────────────────────────────


def test_file_hash_stable(tmp_path):
    f = tmp_path / "a.ttl"
    f.write_text(_TTL)
    assert store.file_hash(f) == store.file_hash(f)


def test_file_hash_changes_on_edit(tmp_path):
    f = tmp_path / "a.ttl"
    f.write_text(_TTL)
    h1 = store.file_hash(f)
    f.write_text(_TTL + "# extra\n")
    assert store.file_hash(f) != h1


def test_file_hash_returns_string(tmp_path):
    f = tmp_path / "a.ttl"
    f.write_text(_TTL)
    assert isinstance(store.file_hash(f), str)


# ── convert ───────────────────────────────────────────────────────────────────


def test_convert_rdfxml_to_ttl(tmp_path):
    src = tmp_path / "onto.rdf"
    src.write_text(_RDF_XML)
    dst = tmp_path / "onto.ttl"

    result = store.convert(src, dst)

    assert result == dst
    assert dst.exists()
    g = Graph()
    g.parse(str(dst), format="turtle")
    assert _TRIPLE in g


def test_convert_owl_to_ttl(tmp_path):
    src = tmp_path / "onto.owl"
    src.write_text(_RDF_XML)
    dst = tmp_path / "onto.ttl"

    store.convert(src, dst)

    g = Graph()
    g.parse(str(dst), format="turtle")
    assert _TRIPLE in g


def test_convert_ttl_to_rdfxml(tmp_path):
    src = tmp_path / "onto.ttl"
    src.write_text(_TTL)
    dst = tmp_path / "onto.rdf"

    store.convert(src, dst)

    g = Graph()
    g.parse(str(dst), format="xml")
    assert _TRIPLE in g


def test_convert_ttl_to_owl(tmp_path):
    src = tmp_path / "onto.ttl"
    src.write_text(_TTL)
    dst = tmp_path / "onto.owl"

    store.convert(src, dst)

    g = Graph()
    g.parse(str(dst), format="xml")
    assert _TRIPLE in g


def test_convert_returns_output_path(tmp_path):
    src = tmp_path / "onto.rdf"
    src.write_text(_RDF_XML)
    dst = tmp_path / "onto.ttl"
    assert store.convert(src, dst) == dst


def test_convert_unsupported_input_raises(tmp_path):
    src = tmp_path / "data.csv"
    src.write_text("not rdf")
    dst = tmp_path / "data.ttl"
    with pytest.raises(ValueError, match="Unsupported"):
        store.convert(src, dst)


def test_convert_unsupported_output_raises(tmp_path):
    src = tmp_path / "onto.ttl"
    src.write_text(_TTL)
    dst = tmp_path / "data.csv"
    with pytest.raises(ValueError, match="Unsupported"):
        store.convert(src, dst)


# ── convert_to_ttl ────────────────────────────────────────────────────────────


def test_convert_to_ttl_default_output_path(tmp_path):
    src = tmp_path / "onto.rdf"
    src.write_text(_RDF_XML)

    result = store.convert_to_ttl(src)

    expected = tmp_path / "onto.ttl"
    assert result == expected
    assert expected.exists()


def test_convert_to_ttl_explicit_output_path(tmp_path):
    src = tmp_path / "onto.rdf"
    src.write_text(_RDF_XML)
    dst = tmp_path / "result.ttl"

    result = store.convert_to_ttl(src, dst)

    assert result == dst
    assert dst.exists()


def test_convert_to_ttl_owl_extension(tmp_path):
    src = tmp_path / "onto.owl"
    src.write_text(_RDF_XML)

    out = store.convert_to_ttl(src)

    g = Graph()
    g.parse(str(out), format="turtle")
    assert _TRIPLE in g


def test_convert_to_ttl_output_is_valid_turtle(tmp_path):
    src = tmp_path / "onto.rdf"
    src.write_text(_RDF_XML)

    out = store.convert_to_ttl(src)

    g = Graph()
    g.parse(str(out), format="turtle")
    assert len(g) > 0


def test_convert_to_ttl_unsupported_extension_raises(tmp_path):
    src = tmp_path / "data.csv"
    src.write_text("not rdf")
    with pytest.raises(ValueError, match="Unsupported"):
        store.convert_to_ttl(src)


# ── _sniff_format ─────────────────────────────────────────────────────────────


def test_sniff_format_xml_declaration_returns_xml(tmp_path):
    f = tmp_path / "f.ttl"
    f.write_bytes(b'<?xml version="1.0"?>\n<rdf:RDF/>')
    assert store._sniff_format(f) == "xml"


def test_sniff_format_rdf_rdf_tag_returns_xml(tmp_path):
    f = tmp_path / "f.ttl"
    f.write_bytes(b"<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'/>")
    assert store._sniff_format(f) == "xml"


def test_sniff_format_turtle_prefix_returns_turtle(tmp_path):
    f = tmp_path / "f.rdf"
    f.write_text("@prefix ex: <https://example.org/> .\n")
    assert store._sniff_format(f) == "turtle"


def test_sniff_format_sparql_prefix_returns_turtle(tmp_path):
    f = tmp_path / "f.rdf"
    f.write_text("PREFIX ex: <https://example.org/>\n")
    assert store._sniff_format(f) == "turtle"


def test_sniff_format_unknown_returns_none(tmp_path):
    f = tmp_path / "f.ttl"
    f.write_text("this is not rdf at all")
    assert store._sniff_format(f) is None


# ── load with wrong extension ─────────────────────────────────────────────────


def test_load_rdfxml_with_ttl_extension_succeeds(tmp_path):
    f = tmp_path / "onto.ttl"
    f.write_text(_RDF_XML)
    taxonomy = store.load(f)
    assert taxonomy is not None


def test_load_turtle_with_rdf_extension_succeeds(tmp_path):
    f = tmp_path / "onto.rdf"
    f.write_text(_TTL)
    taxonomy = store.load(f)
    assert taxonomy is not None


# ── detect_format_mismatch ────────────────────────────────────────────────────


def test_detect_format_mismatch_rdfxml_in_ttl(tmp_path):
    f = tmp_path / "onto.ttl"
    f.write_text(_RDF_XML)
    result = store.detect_format_mismatch(f)
    assert result == ("turtle", "xml")


def test_detect_format_mismatch_turtle_in_rdf(tmp_path):
    f = tmp_path / "onto.rdf"
    f.write_text(_TTL)
    result = store.detect_format_mismatch(f)
    assert result == ("xml", "turtle")


def test_detect_format_mismatch_none_when_correct_ttl(tmp_path):
    f = tmp_path / "onto.ttl"
    f.write_text(_TTL)
    assert store.detect_format_mismatch(f) is None


def test_detect_format_mismatch_none_when_correct_rdf(tmp_path):
    f = tmp_path / "onto.rdf"
    f.write_text(_RDF_XML)
    assert store.detect_format_mismatch(f) is None
