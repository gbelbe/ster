"""Unit tests for SPARQL QName autocomplete improvements."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ster.model import OWLIndividual, RDFClass, Taxonomy
from ster.sparql_query import (
    _sparql_context_at_cursor,
    _uri_index_cache,
    build_uri_index,
    build_uri_index_cached,
    qname_candidates,
)

_NS = "https://ex.org/kai/"


def _make_taxonomy() -> Taxonomy:
    tax = Taxonomy()
    for name in ("Digital", "Analog"):
        uri = _NS + name
        tax.owl_classes[uri] = RDFClass(uri=uri)
    ind_uri = _NS + "Device"
    tax.owl_individuals[ind_uri] = OWLIndividual(uri=ind_uri)
    tax.namespace_bindings["kai"] = _NS
    return tax


# ── build_uri_index ───────────────────────────────────────────────────────────


def test_build_uri_index_separates_classes_and_individuals() -> None:
    tax = _make_taxonomy()
    idx = build_uri_index(tax)
    kai = idx["kai"]
    assert "Digital" in kai["classes"]
    assert "Analog" in kai["classes"]
    assert "Device" not in kai["classes"]
    assert "Device" in kai["individuals"]
    assert "Digital" not in kai["individuals"]


def test_build_uri_index_all_contains_everything() -> None:
    tax = _make_taxonomy()
    idx = build_uri_index(tax)
    kai = idx["kai"]
    assert "Digital" in kai["all"]
    assert "Analog" in kai["all"]
    assert "Device" in kai["all"]


def test_build_uri_index_sorted_alphabetically() -> None:
    tax = _make_taxonomy()
    idx = build_uri_index(tax)
    for bucket in idx["kai"].values():
        if isinstance(bucket, list):
            assert bucket == sorted(bucket)


def test_build_uri_index_standard_prefix_classes_only() -> None:
    """Standard prefixes (owl:, rdfs:) include well-known class names in 'classes'."""
    tax = Taxonomy()
    tax.namespace_bindings["owl"] = "http://www.w3.org/2002/07/owl#"
    idx = build_uri_index(tax)
    assert "Class" in idx.get("owl", {}).get("classes", [])


# ── _sparql_context_at_cursor ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "buf,pos,expected",
    [
        ("?x a kai:", 9, "class"),
        ("?x rdf:type kai:", 16, "class"),
        ("rdfs:subClassOf kai:", 20, "class"),
        ("rdfs:domain kai:", 16, "class"),
        ("rdfs:range kai:", 15, "class"),
        ("owl:equivalentClass kai:", 24, "class"),
        ("owl:disjointWith kai:", 21, "class"),
        ("?x ?p kai:", 10, "any"),
        ("PREFIX kai: <ns>", 16, "any"),
    ],
)
def test_sparql_context_at_cursor(buf: str, pos: int, expected: str) -> None:
    assert _sparql_context_at_cursor(buf, pos) == expected


# ── qname_candidates ──────────────────────────────────────────────────────────


def test_qname_candidates_class_context() -> None:
    tax = _make_taxonomy()
    idx = build_uri_index(tax)
    result = qname_candidates(idx, "kai", "", "class")
    assert "Digital" in result
    assert "Analog" in result
    assert "Device" not in result


def test_qname_candidates_any_context() -> None:
    tax = _make_taxonomy()
    idx = build_uri_index(tax)
    result = qname_candidates(idx, "kai", "", "any")
    assert "Digital" in result
    assert "Device" in result


def test_qname_candidates_alphabetical() -> None:
    tax = _make_taxonomy()
    idx = build_uri_index(tax)
    result = qname_candidates(idx, "kai", "", "any")
    assert result == sorted(result)


def test_qname_candidates_filter_case_insensitive() -> None:
    tax = _make_taxonomy()
    idx = build_uri_index(tax)
    result = qname_candidates(idx, "kai", "di", "any")
    assert "Digital" in result
    assert "Analog" not in result
    assert "Device" not in result


def test_qname_candidates_unknown_prefix_returns_empty() -> None:
    tax = _make_taxonomy()
    idx = build_uri_index(tax)
    assert qname_candidates(idx, "unknown", "", "any") == []


# ── build_uri_index_cached ───────────────────────────────────────────────────


_VALID_TTL = (
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix kai: <https://ex.org/kai/> .\n"
    "kai:Digital a owl:Class .\n"
)


def test_build_uri_index_cached_returns_same_object_twice(tmp_path: Path) -> None:
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL, encoding="utf-8")
    _uri_index_cache.clear()
    first = build_uri_index_cached([ttl])
    second = build_uri_index_cached([ttl])
    assert first is second


def test_build_uri_index_cached_rebuilds_on_mtime_change(tmp_path: Path) -> None:
    ttl = tmp_path / "test.ttl"
    ttl.write_text(_VALID_TTL, encoding="utf-8")
    _uri_index_cache.clear()
    first = build_uri_index_cached([ttl])
    # Simulate mtime change by patching stat

    original_stat = ttl.stat()

    class FakeStat:
        st_mtime = original_stat.st_mtime + 1

    with patch.object(Path, "stat", return_value=FakeStat()):
        second = build_uri_index_cached([ttl])
    assert first is not second


# ── scroll logic ──────────────────────────────────────────────────────────────


def test_qn_scroll_advances_when_cursor_goes_past_window() -> None:
    """qn_scroll must be updated so the selected item stays in the visible window."""
    from ster.nav.query_logic import _qn_clamp_scroll

    # 20 candidates, window height 5, cursor moves to item 7
    scroll = _qn_clamp_scroll(cursor=7, scroll=0, window_h=5)
    assert scroll <= 7
    assert scroll + 5 > 7


def test_qn_scroll_does_not_go_negative() -> None:
    from ster.nav.query_logic import _qn_clamp_scroll

    scroll = _qn_clamp_scroll(cursor=0, scroll=3, window_h=5)
    assert scroll == 0


def test_qn_scroll_moves_up_when_cursor_above_window() -> None:
    from ster.nav.query_logic import _qn_clamp_scroll

    scroll = _qn_clamp_scroll(cursor=2, scroll=5, window_h=5)
    assert scroll == 2
