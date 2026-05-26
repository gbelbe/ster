"""Unit tests for _class_hierarchy_candidates() — hierarchical class picker helper."""

from __future__ import annotations

from ster.model import Label, RDFClass, Taxonomy
from ster.nav.viewer import _class_hierarchy_candidates

NS = "https://example.org/onto#"


def uri(name: str) -> str:
    return NS + name


def _cls(name: str, parent: str | None = None) -> RDFClass:
    return RDFClass(
        uri=uri(name),
        labels=[Label("en", name)],
        sub_class_of=[uri(parent)] if parent else [],
    )


def _uris(candidates: list[tuple[str, str]]) -> list[str]:
    return [u for u, _ in candidates]


def _displays(candidates: list[tuple[str, str]]) -> list[str]:
    return [d for _, d in candidates]


def _label_of(display: str) -> str:
    """Strip the tree connector prefix and return the bare label."""
    for sep in ("└── ", "├── "):
        idx = display.rfind(sep)
        if idx != -1:
            return display[idx + 4 :]
    return display


# ── tests ─────────────────────────────────────────────────────────────────────


def test_empty():
    tax = Taxonomy()
    assert _class_hierarchy_candidates(tax, "en", set()) == []


def test_single_root():
    tax = Taxonomy()
    tax.owl_classes[uri("A")] = _cls("A")
    result = _class_hierarchy_candidates(tax, "en", set())
    assert _uris(result) == [uri("A")]
    assert "└── " in _displays(result)[0]
    assert _label_of(_displays(result)[0]) == "A"


def test_child_indented():
    tax = Taxonomy()
    tax.owl_classes[uri("Root")] = _cls("Root")
    tax.owl_classes[uri("Child")] = _cls("Child", parent="Root")
    result = _class_hierarchy_candidates(tax, "en", set())
    assert _uris(result) == [uri("Root"), uri("Child")]
    root_d, child_d = _displays(result)
    # Root has no leading continuation; child has a continuation block
    assert root_d.startswith("└── ") or root_d.startswith("├── ")
    assert "│" in child_d or child_d.startswith("    ")
    # Child display is longer than root (has extra prefix)
    assert len(child_d) > len(root_d)


def test_grandchild_deeper():
    tax = Taxonomy()
    tax.owl_classes[uri("A")] = _cls("A")
    tax.owl_classes[uri("B")] = _cls("B", parent="A")
    tax.owl_classes[uri("C")] = _cls("C", parent="B")
    result = _class_hierarchy_candidates(tax, "en", set())
    assert _uris(result) == [uri("A"), uri("B"), uri("C")]
    a_d, b_d, c_d = _displays(result)
    # Each level has a strictly longer prefix
    assert len(b_d) > len(a_d)
    assert len(c_d) > len(b_d)
    # Each display ends with its label
    assert _label_of(a_d) == "A"
    assert _label_of(b_d) == "B"
    assert _label_of(c_d) == "C"


def test_roots_sorted_alphabetically():
    tax = Taxonomy()
    tax.owl_classes[uri("Zebra")] = _cls("Zebra")
    tax.owl_classes[uri("Apple")] = _cls("Apple")
    result = _class_hierarchy_candidates(tax, "en", set())
    assert _label_of(_displays(result)[0]) == "Apple"
    assert _label_of(_displays(result)[1]) == "Zebra"


def test_children_sorted_alphabetically():
    tax = Taxonomy()
    tax.owl_classes[uri("Root")] = _cls("Root")
    tax.owl_classes[uri("Zebra")] = _cls("Zebra", parent="Root")
    tax.owl_classes[uri("Apple")] = _cls("Apple", parent="Root")
    result = _class_hierarchy_candidates(tax, "en", set())
    assert _uris(result) == [uri("Root"), uri("Apple"), uri("Zebra")]


def test_excluded_uri_absent():
    tax = Taxonomy()
    tax.owl_classes[uri("Root")] = _cls("Root")
    tax.owl_classes[uri("Child")] = _cls("Child", parent="Root")
    result = _class_hierarchy_candidates(tax, "en", {uri("Root")})
    assert uri("Root") not in _uris(result)
    assert uri("Child") in _uris(result)


def test_excluded_parent_children_still_appear():
    tax = Taxonomy()
    tax.owl_classes[uri("Root")] = _cls("Root")
    tax.owl_classes[uri("Mid")] = _cls("Mid", parent="Root")
    tax.owl_classes[uri("Leaf")] = _cls("Leaf", parent="Mid")
    result = _class_hierarchy_candidates(tax, "en", {uri("Mid")})
    uris_out = _uris(result)
    assert uri("Root") in uris_out
    assert uri("Mid") not in uris_out
    assert uri("Leaf") in uris_out


def test_unlabelled_class_uses_local_name():
    tax = Taxonomy()
    tax.owl_classes[uri("A")] = RDFClass(uri=uri("A"))
    result = _class_hierarchy_candidates(tax, "en", set())
    assert len(result) == 1
    # label() falls back to local_name ("A"), not the full URI
    assert _label_of(result[0][1]) == "A"
