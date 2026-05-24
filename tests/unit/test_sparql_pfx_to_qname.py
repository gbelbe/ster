"""Tests for the prefix-popup → QName-popup transition when ':' is typed.

Covers both paths:
  • pfx_active = True  → open_qname_popup_on_colon  (inserts ':' then opens popup)
  • pfx_active = False → apply_qname_popup_from_colon (buffer already has ':')
"""

from __future__ import annotations

from ster.model import OWLIndividual, RDFClass, Taxonomy
from ster.nav.query_logic import (
    apply_qname_popup_from_colon,
    open_qname_popup_on_colon,
)
from ster.nav.state import QueryState
from ster.sparql_query import (
    build_qname_index,
    build_uri_index,
    parse_buffer_prefixes,
)

_NS = "https://ex.org/kai/"


def _make_taxonomy() -> Taxonomy:
    tax = Taxonomy()
    tax.namespace_bindings["kai"] = _NS
    tax.owl_classes[_NS + "Digital"] = RDFClass(uri=_NS + "Digital")
    tax.owl_individuals[_NS + "Dev1"] = OWLIndividual(uri=_NS + "Dev1", types=[_NS + "Digital"])
    return tax


def _known_from_tax(tax: Taxonomy, buf: str = "") -> set[str]:
    """Build `known` the same way the viewer does."""
    idx = build_uri_index(tax)
    return set(idx.keys()) | set(build_qname_index(tax).keys()) | parse_buffer_prefixes(buf)


# ── known-set construction ────────────────────────────────────────────────────


def test_known_includes_kai_from_uri_index() -> None:
    tax = _make_taxonomy()
    known = set(build_uri_index(tax).keys())
    assert "kai" in known


def test_known_includes_kai_from_qname_index() -> None:
    tax = _make_taxonomy()
    known = set(build_qname_index(tax).keys())
    assert "kai" in known


def test_known_includes_kai_from_prefix_declaration() -> None:
    buf = f"PREFIX kai: <{_NS}>\n\nSELECT ?b WHERE {{\n  ?b a kai"
    known = parse_buffer_prefixes(buf)
    assert "kai" in known


def test_known_includes_kai_from_union_of_all_sources() -> None:
    tax = _make_taxonomy()
    buf = f"PREFIX kai: <{_NS}>\n\nSELECT ?b WHERE {{\n  ?b a kai"
    known = _known_from_tax(tax, buf)
    assert "kai" in known


# ── open_qname_popup_on_colon (pfx_active path) ───────────────────────────────


def test_pfx_colon_opens_qname_popup() -> None:
    """Typing ':' while pfx_active sets qn_active=True for a known prefix."""
    tax = _make_taxonomy()
    known = _known_from_tax(tax)
    qs = QueryState(query_buffer="SELECT ?b WHERE {\n  ?b a kai", query_pos=28)
    qs.pfx_active = True

    opened = open_qname_popup_on_colon(qs, known)

    assert opened is True
    assert qs.qn_active is True
    assert qs.qn_prefix == "kai"
    assert qs.qn_filter == ""
    assert qs.query_buffer.endswith("kai:")


def test_pfx_colon_does_not_open_for_unknown_prefix() -> None:
    known: set[str] = {"skos", "owl"}  # 'kai' absent
    qs = QueryState(query_buffer="SELECT ?b WHERE {\n  ?b a kai", query_pos=28)
    qs.pfx_active = True

    opened = open_qname_popup_on_colon(qs, known)

    assert opened is False
    assert qs.qn_active is False
    # ':' was still inserted even though popup didn't open
    assert qs.query_buffer.endswith("kai:")


def test_pfx_colon_inserts_colon_into_buffer() -> None:
    """The ':' is always inserted regardless of whether the popup opens."""
    known: set[str] = set()
    qs = QueryState(query_buffer="PREFIX kai: <ns>\n?b a owl", query_pos=25)

    open_qname_popup_on_colon(qs, known)

    assert "owl:" in qs.query_buffer


def test_pfx_colon_sets_correct_trigger_pos() -> None:
    tax = _make_taxonomy()
    known = _known_from_tax(tax)
    buf = "SELECT ?b WHERE {\n  ?b a kai"
    qs = QueryState(query_buffer=buf, query_pos=len(buf))

    open_qname_popup_on_colon(qs, known)

    # trigger_pos must be AFTER the ':' (cursor is right after ':')
    assert qs.qn_trigger_pos == len(buf) + 1  # +1 for inserted ':'


def test_pfx_colon_clears_breadcrumb() -> None:
    tax = _make_taxonomy()
    known = _known_from_tax(tax)
    qs = QueryState(query_buffer="?b a kai", query_pos=8)
    qs.qn_breadcrumb = ["SomeParent"]

    open_qname_popup_on_colon(qs, known)

    assert qs.qn_breadcrumb == []


# ── apply_qname_popup_from_colon (normal ':' path, already inserted) ──────────


def test_normal_colon_opens_qname_popup() -> None:
    """Normal ':' handler: buffer already has 'kai:', popup should open."""
    tax = _make_taxonomy()
    known = _known_from_tax(tax)
    buf = "SELECT ?b WHERE {\n  ?b a kai:"
    qs = QueryState(query_buffer=buf, query_pos=len(buf))

    opened = apply_qname_popup_from_colon(qs, known)

    assert opened is True
    assert qs.qn_active is True
    assert qs.qn_prefix == "kai"


def test_normal_colon_no_popup_for_unknown_prefix() -> None:
    known: set[str] = {"skos"}
    buf = "SELECT ?b WHERE {\n  ?b a kai:"
    qs = QueryState(query_buffer=buf, query_pos=len(buf))

    opened = apply_qname_popup_from_colon(qs, known)

    assert opened is False
    assert qs.qn_active is False


def test_normal_colon_no_popup_when_buffer_ends_without_colon() -> None:
    known = {"kai"}
    buf = "SELECT ?b WHERE {\n  ?b a kai"
    qs = QueryState(query_buffer=buf, query_pos=len(buf))

    opened = apply_qname_popup_from_colon(qs, known)

    assert opened is False
    assert qs.qn_active is False


def test_normal_colon_context_class_when_after_rdf_type() -> None:
    tax = _make_taxonomy()
    known = _known_from_tax(tax)
    buf = "SELECT ?b WHERE {\n  ?b a kai:"
    qs = QueryState(query_buffer=buf, query_pos=len(buf))

    apply_qname_popup_from_colon(qs, known)

    assert qs.qn_context == "class"
