"""Unit tests for SPARQL editor smart-completion helpers."""

from __future__ import annotations

from ster.model import Concept, OWLIndividual, RDFClass, Taxonomy
from ster.nav.query_logic import (
    _auto_close_bracket,
    _clause_expand,
    _qname_prefix_at_cursor,
    _sparql_kw_insert,
)
from ster.nav.state import QueryState
from ster.sparql_query import build_prefix_header, build_qname_index, extract_query_variables

_KAI_NS = "https://ex.org/kai/"


# ── build_prefix_header ───────────────────────────────────────────────────────


def test_prefix_header_contains_rdf():
    assert "PREFIX rdf:" in build_prefix_header({})


def test_prefix_header_contains_rdfs():
    assert "PREFIX rdfs:" in build_prefix_header({})


def test_prefix_header_contains_owl():
    assert "PREFIX owl:" in build_prefix_header({})


def test_prefix_header_contains_skos():
    assert "PREFIX skos:" in build_prefix_header({})


def test_prefix_header_includes_custom_binding():
    header = build_prefix_header({"kai": _KAI_NS})
    assert "PREFIX kai:" in header
    assert _KAI_NS in header


def test_prefix_header_no_duplicate_when_binding_matches_standard():
    # If the file declares rdf: with the canonical URI, it must appear exactly once.
    header = build_prefix_header({"rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"})
    assert header.count("PREFIX rdf:") == 1


def test_prefix_header_ends_with_blank_line():
    header = build_prefix_header({})
    assert header.endswith("\n\n")


def test_prefix_header_each_line_is_valid_sparql_prefix():
    header = build_prefix_header({"kai": _KAI_NS})
    for line in header.strip().splitlines():
        assert line.startswith("PREFIX ") and ": <" in line and line.endswith(">")


# ── build_qname_index ─────────────────────────────────────────────────────────


def test_qname_index_includes_class_local_names():
    tax = Taxonomy()
    tax.namespace_bindings["kai"] = _KAI_NS
    tax.owl_classes[_KAI_NS + "Digital"] = RDFClass(uri=_KAI_NS + "Digital")
    idx = build_qname_index(tax)
    assert "Digital" in idx.get("kai", [])


def test_qname_index_includes_individual_local_names():
    tax = Taxonomy()
    tax.namespace_bindings["kai"] = _KAI_NS
    tax.owl_individuals[_KAI_NS + "KnowledgeEngineer"] = OWLIndividual(
        uri=_KAI_NS + "KnowledgeEngineer"
    )
    idx = build_qname_index(tax)
    assert "KnowledgeEngineer" in idx.get("kai", [])


def test_qname_index_includes_concept_local_names():
    tax = Taxonomy()
    tax.namespace_bindings["ex"] = "https://ex.org/"
    tax.concepts["https://ex.org/Agile"] = Concept(uri="https://ex.org/Agile")
    idx = build_qname_index(tax)
    assert "Agile" in idx.get("ex", [])


def test_qname_index_always_includes_skos_preflabel():
    idx = build_qname_index(Taxonomy())
    assert "prefLabel" in idx.get("skos", [])


def test_qname_index_always_includes_rdf_type():
    idx = build_qname_index(Taxonomy())
    assert "type" in idx.get("rdf", [])


def test_qname_index_lists_are_sorted():
    tax = Taxonomy()
    tax.namespace_bindings["kai"] = _KAI_NS
    for name in ("Zebra", "Alpha", "Mango"):
        tax.owl_classes[_KAI_NS + name] = RDFClass(uri=_KAI_NS + name)
    idx = build_qname_index(tax)
    kai_names = [n for n in idx["kai"] if n in ("Zebra", "Alpha", "Mango")]
    assert kai_names == sorted(kai_names)


def test_qname_index_no_duplicates():
    tax = Taxonomy()
    tax.namespace_bindings["kai"] = _KAI_NS
    tax.owl_classes[_KAI_NS + "Digital"] = RDFClass(uri=_KAI_NS + "Digital")
    idx = build_qname_index(tax)
    assert idx["kai"].count("Digital") == 1


# ── extract_query_variables ───────────────────────────────────────────────────


def test_extract_variables_finds_named_vars():
    buf = "SELECT ?concept WHERE { ?concept a skos:Concept . }"
    assert "concept" in extract_query_variables(buf)


def test_extract_variables_deduplicates():
    buf = "SELECT ?s WHERE { ?s ?p ?s . }"
    result = extract_query_variables(buf)
    assert result.count("s") == 1


def test_extract_variables_empty_buffer():
    assert extract_query_variables("") == []


def test_extract_variables_returns_sorted():
    buf = "SELECT ?z ?a ?m WHERE { ?z ?a ?m . }"
    result = extract_query_variables(buf)
    assert result == sorted(result)


# ── _auto_close_bracket ───────────────────────────────────────────────────────


def test_auto_close_brace_expands_to_block():
    buf, pos = _auto_close_bracket("WHERE ", 6, "{")
    assert "{\n" in buf and "\n}" in buf


def test_auto_close_brace_cursor_is_inside():
    buf, pos = _auto_close_bracket("WHERE ", 6, "{")
    open_pos = buf.find("{")
    close_pos = buf.rfind("}")
    assert open_pos < pos < close_pos


def test_auto_close_brace_preserves_prefix_and_suffix():
    buf, _pos = _auto_close_bracket("WHERE ", 6, "{")
    assert buf.startswith("WHERE ")
    assert buf.endswith("}")


def test_auto_close_paren_inserts_closing_paren():
    buf, pos = _auto_close_bracket("FILTER ", 7, "(")
    assert "()" in buf
    assert pos == buf.index("(") + 1  # cursor between parens


def test_auto_close_brace_indentation_follows_current_line():
    # Line starts with 2 spaces → inner indent should be 4 spaces
    buf, pos = _auto_close_bracket("  OPTIONAL ", 11, "{")
    lines = buf.split("\n")
    assert lines[1].startswith("    ")  # 4 spaces indent


# ── _clause_expand ────────────────────────────────────────────────────────────


def test_clause_expand_where_adds_braces():
    result = _clause_expand("WHERE", indent=0)
    assert result is not None
    assert "{\n" in result and "\n}" in result


def test_clause_expand_optional_adds_braces():
    result = _clause_expand("OPTIONAL", indent=0)
    assert result is not None
    assert "{" in result


def test_clause_expand_filter_adds_parens():
    result = _clause_expand("FILTER", indent=0)
    assert result is not None
    assert "()" in result


def test_clause_expand_no_match_returns_none():
    assert _clause_expand("SELECT", indent=0) is None
    assert _clause_expand("LIMIT", indent=0) is None


def test_clause_expand_respects_indent():
    result = _clause_expand("WHERE", indent=2)
    assert result is not None
    lines = result.split("\n")
    # Inner line should have indent+2 spaces
    assert lines[1].startswith("    ")
    # Closing brace should have indent spaces
    assert lines[-1].startswith("  }")


# ── _sparql_kw_insert with expansion ─────────────────────────────────────────


def test_kw_insert_where_expands_block():
    qs = QueryState(query_buffer="WH", query_pos=2)
    _sparql_kw_insert(qs, "WHERE")
    assert "{\n" in qs.query_buffer and "\n}" in qs.query_buffer


def test_kw_insert_where_cursor_inside_block():
    qs = QueryState(query_buffer="WH", query_pos=2)
    _sparql_kw_insert(qs, "WHERE")
    open_pos = qs.query_buffer.find("{")
    close_pos = qs.query_buffer.rfind("}")
    assert open_pos < qs.query_pos < close_pos


def test_kw_insert_select_no_expansion():
    qs = QueryState(query_buffer="SEL", query_pos=3)
    _sparql_kw_insert(qs, "SELECT")
    assert qs.query_buffer == "SELECT"


def test_kw_insert_filter_expands_parens():
    qs = QueryState(query_buffer="FIL", query_pos=3)
    _sparql_kw_insert(qs, "FILTER")
    assert "()" in qs.query_buffer


# ── _qname_prefix_at_cursor ───────────────────────────────────────────────────


def test_qname_prefix_detected_after_colon():
    buf = "kai:"
    assert _qname_prefix_at_cursor(buf, 4, {"kai"}) == "kai"


def test_qname_prefix_unknown_prefix_returns_none():
    buf = "unknown:"
    assert _qname_prefix_at_cursor(buf, 8, {"kai"}) is None


def test_qname_prefix_no_colon_returns_none():
    buf = "kai"
    assert _qname_prefix_at_cursor(buf, 3, {"kai"}) is None


def test_qname_prefix_mid_buffer():
    buf = "SELECT kai:"
    assert _qname_prefix_at_cursor(buf, len(buf), {"kai"}) == "kai"
