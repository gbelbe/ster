"""Tests for owl_analysis — pure OWL/RDFS class statistics."""

from __future__ import annotations

from ster.model import Concept, Definition, Label, RDFClass, Taxonomy
from ster.owl_analysis import compute_owl_analysis

BASE = "https://example.org/onto/"


def _make_taxonomy(
    class_defs: list[tuple[str, list[str], bool, bool]],
    promoted_uris: list[str] | None = None,
) -> Taxonomy:
    """Build a Taxonomy from (local_name, sub_class_of_locals, has_label, has_comment) tuples."""
    t = Taxonomy()
    for name, parents, has_label, has_comment in class_defs:
        uri = BASE + name
        cls = RDFClass(
            uri=uri,
            labels=[Label(lang="en", value=name)] if has_label else [],
            comments=[Definition(lang="en", value=f"About {name}.")] if has_comment else [],
            sub_class_of=[BASE + p for p in parents],
        )
        t.owl_classes[uri] = cls
    for uri in promoted_uris or []:
        t.concepts[uri] = Concept(uri=uri)
    return t


# ── empty taxonomy ────────────────────────────────────────────────────────────


def test_empty_taxonomy():
    t = Taxonomy()
    stats = compute_owl_analysis(t)
    assert stats.total_classes == 0
    assert stats.promoted == 0
    assert stats.missing_label == 0


# ── total_classes ─────────────────────────────────────────────────────────────


def test_total_classes():
    t = _make_taxonomy(
        [
            ("Animal", [], True, True),
            ("Dog", ["Animal"], True, True),
            ("Cat", ["Animal"], True, False),
        ]
    )
    assert compute_owl_analysis(t).total_classes == 3


# ── root_classes ──────────────────────────────────────────────────────────────


def test_root_classes_single():
    t = _make_taxonomy(
        [
            ("Animal", [], True, True),
            ("Dog", ["Animal"], True, True),
        ]
    )
    assert compute_owl_analysis(t).root_classes == 1


def test_root_classes_multiple():
    t = _make_taxonomy(
        [
            ("Animal", [], True, True),
            ("Vehicle", [], True, True),
            ("Dog", ["Animal"], True, True),
        ]
    )
    assert compute_owl_analysis(t).root_classes == 2


# ── max_depth ─────────────────────────────────────────────────────────────────


def test_max_depth_flat():
    t = _make_taxonomy(
        [
            ("A", [], True, True),
            ("B", [], True, True),
        ]
    )
    assert compute_owl_analysis(t).max_depth == 0


def test_max_depth_hierarchy():
    t = _make_taxonomy(
        [
            ("Animal", [], True, True),
            ("Mammal", ["Animal"], True, True),
            ("Dog", ["Mammal"], True, True),
        ]
    )
    assert compute_owl_analysis(t).max_depth == 2


# ── promoted / pure_classes ───────────────────────────────────────────────────


def test_promoted_count():
    t = _make_taxonomy(
        [("Animal", [], True, True), ("Dog", ["Animal"], True, True)],
        promoted_uris=[BASE + "Dog"],
    )
    stats = compute_owl_analysis(t)
    assert stats.promoted == 1
    assert stats.pure_classes == 1


def test_pure_classes_all_pure():
    t = _make_taxonomy([("A", [], True, True), ("B", [], True, True)])
    stats = compute_owl_analysis(t)
    assert stats.pure_classes == 2
    assert stats.promoted == 0


# ── missing_label / missing_comment ──────────────────────────────────────────


def test_missing_label():
    t = _make_taxonomy(
        [
            ("Animal", [], True, True),
            ("Ghost", [], False, False),  # no label, no comment
        ]
    )
    stats = compute_owl_analysis(t)
    assert stats.missing_label == 1
    assert stats.missing_comment == 1


def test_all_labeled():
    t = _make_taxonomy(
        [
            ("A", [], True, True),
            ("B", [], True, True),
        ]
    )
    assert compute_owl_analysis(t).missing_label == 0
