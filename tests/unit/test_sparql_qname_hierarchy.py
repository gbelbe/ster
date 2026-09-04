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


def test_unbound_namespace_class_excluded_from_hierarchy():
    """A class whose URI matches no declared namespace binding is skipped
    when building the hierarchy (no crash, just absent from the index)."""
    tax = _make_hierarchy_taxonomy()
    tax.owl_classes["https://other.org/Unrelated"] = RDFClass(uri="https://other.org/Unrelated")
    idx = build_uri_index(tax)
    assert "kai" in idx
    all_roots_and_children = set(idx["kai"]["roots"])
    for children in idx["kai"]["children"].values():
        all_roots_and_children |= set(children)
    assert "Unrelated" not in all_roots_and_children


def test_class_uri_equal_to_bare_namespace_is_skipped():
    """A class URI identical to the namespace itself (empty local name after
    stripping the prefix) is skipped rather than producing a blank entry."""
    tax = _make_hierarchy_taxonomy()
    tax.owl_classes[_NS] = RDFClass(uri=_NS)
    idx = build_uri_index(tax)
    all_roots = idx["kai"]["roots"]
    assert "" not in all_roots


def test_unbound_namespace_individual_excluded_from_hierarchy():
    from ster.model import OWLIndividual

    tax = _make_hierarchy_taxonomy()
    tax.owl_individuals["https://other.org/ghost"] = OWLIndividual(
        uri="https://other.org/ghost", types=[_NS + "Thing"]
    )
    idx = build_uri_index(tax)
    # No crash, and the individual doesn't leak into the kai namespace bucket
    assert "kai" in idx


def test_individual_uri_equal_to_bare_namespace_is_skipped():
    from ster.model import OWLIndividual

    tax = _make_hierarchy_taxonomy()
    tax.owl_individuals[_NS] = OWLIndividual(uri=_NS, types=[_NS + "Thing"])
    # No crash — the bare-namespace individual has no local name to index
    build_uri_index(tax)


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
