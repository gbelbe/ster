"""Unit tests for hierarchical class navigation in SPARQL QName popup."""

from __future__ import annotations

from ster.model import RDFClass, Taxonomy
from ster.sparql_query import build_uri_index, qname_level_candidates

_NS = "https://ex.org/kai/"


def _make_hierarchy_taxonomy() -> Taxonomy:
    """
    Thing (root)
      └─ Digital
           └─ Switch
    AnalogDevice (root)
    """
    tax = Taxonomy()
    tax.namespace_bindings["kai"] = _NS

    thing = RDFClass(uri=_NS + "Thing")
    digital = RDFClass(uri=_NS + "Digital", sub_class_of=[_NS + "Thing"])
    switch = RDFClass(uri=_NS + "Switch", sub_class_of=[_NS + "Digital"])
    analog = RDFClass(uri=_NS + "AnalogDevice")

    for cls in (thing, digital, switch, analog):
        tax.owl_classes[cls.uri] = cls
    return tax


# ── build_uri_index: roots ────────────────────────────────────────────────────


def test_roots_contain_parentless_classes() -> None:
    tax = _make_hierarchy_taxonomy()
    idx = build_uri_index(tax)
    roots = idx["kai"]["roots"]
    assert "Thing" in roots
    assert "AnalogDevice" in roots


def test_roots_exclude_classes_with_parent_in_namespace() -> None:
    tax = _make_hierarchy_taxonomy()
    idx = build_uri_index(tax)
    roots = idx["kai"]["roots"]
    assert "Digital" not in roots
    assert "Switch" not in roots


def test_roots_sorted_alphabetically() -> None:
    tax = _make_hierarchy_taxonomy()
    idx = build_uri_index(tax)
    roots = idx["kai"]["roots"]
    assert roots == sorted(roots)


# ── build_uri_index: children map ─────────────────────────────────────────────


def test_children_map_records_direct_subclasses() -> None:
    tax = _make_hierarchy_taxonomy()
    idx = build_uri_index(tax)
    children = idx["kai"]["children"]
    assert "Digital" in children["Thing"]
    assert "Switch" in children["Digital"]


def test_leaf_class_absent_from_children_keys() -> None:
    tax = _make_hierarchy_taxonomy()
    idx = build_uri_index(tax)
    children = idx["kai"]["children"]
    assert "AnalogDevice" not in children
    assert "Switch" not in children


def test_children_sorted_alphabetically() -> None:
    tax = _make_hierarchy_taxonomy()
    # Add two children to Thing
    tax.owl_classes[_NS + "Zebra"] = RDFClass(uri=_NS + "Zebra", sub_class_of=[_NS + "Thing"])
    idx = build_uri_index(tax)
    children_of_thing = idx["kai"]["children"]["Thing"]
    assert children_of_thing == sorted(children_of_thing)


# ── qname_level_candidates ────────────────────────────────────────────────────


def test_level_candidates_root_returns_roots() -> None:
    tax = _make_hierarchy_taxonomy()
    idx = build_uri_index(tax)
    results = qname_level_candidates(idx, "kai", "", "", "class")
    names = [name for name, _ in results]
    assert "Thing" in names
    assert "AnalogDevice" in names
    assert "Digital" not in names
    assert "Switch" not in names


def test_level_candidates_child_level_returns_direct_children() -> None:
    tax = _make_hierarchy_taxonomy()
    idx = build_uri_index(tax)
    results = qname_level_candidates(idx, "kai", "Thing", "", "class")
    names = [name for name, _ in results]
    assert "Digital" in names
    assert "Thing" not in names
    assert "Switch" not in names


def test_level_candidates_has_children_flag_true_for_parent() -> None:
    tax = _make_hierarchy_taxonomy()
    idx = build_uri_index(tax)
    results = qname_level_candidates(idx, "kai", "", "", "class")
    by_name = dict(results)
    assert by_name["Thing"] is True


def test_level_candidates_has_children_flag_false_for_leaf() -> None:
    tax = _make_hierarchy_taxonomy()
    idx = build_uri_index(tax)
    results = qname_level_candidates(idx, "kai", "", "", "class")
    by_name = dict(results)
    assert by_name["AnalogDevice"] is False


def test_level_candidates_filter_applied() -> None:
    tax = _make_hierarchy_taxonomy()
    idx = build_uri_index(tax)
    results = qname_level_candidates(idx, "kai", "", "An", "class")
    names = [name for name, _ in results]
    assert "AnalogDevice" in names
    assert "Thing" not in names


def test_level_candidates_filter_case_insensitive() -> None:
    tax = _make_hierarchy_taxonomy()
    idx = build_uri_index(tax)
    results = qname_level_candidates(idx, "kai", "", "an", "class")
    names = [name for name, _ in results]
    assert "AnalogDevice" in names


def test_level_candidates_any_context_includes_individuals_at_root() -> None:
    from ster.model import OWLIndividual

    tax = _make_hierarchy_taxonomy()
    tax.owl_individuals[_NS + "MyDevice"] = OWLIndividual(uri=_NS + "MyDevice")
    idx = build_uri_index(tax)
    results = qname_level_candidates(idx, "kai", "", "", "any")
    names = [name for name, _ in results]
    assert "MyDevice" in names


def test_level_candidates_unknown_prefix_returns_empty() -> None:
    tax = _make_hierarchy_taxonomy()
    idx = build_uri_index(tax)
    assert qname_level_candidates(idx, "unknown", "", "", "class") == []


def test_level_candidates_parent_with_no_children_returns_empty() -> None:
    tax = _make_hierarchy_taxonomy()
    idx = build_uri_index(tax)
    results = qname_level_candidates(idx, "kai", "AnalogDevice", "", "class")
    assert results == []
