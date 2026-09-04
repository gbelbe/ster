"""Tests for ster/taxonomy_treemap.py — treemap payload builder."""

from __future__ import annotations

from ster.model import Concept, ConceptScheme, Label, LabelType, RDFClass, Taxonomy
from ster.taxonomy_treemap import (
    NO_SCHEME_URI,
    build_taxonomy_treemap,
    has_taxonomy,
    is_skos_only,
)

BASE = "https://example.org/test/"


def _concept(uri: str, label: str = "", narrower: list[str] | None = None) -> Concept:
    labels = [Label("en", label, LabelType.PREF)] if label else []
    return Concept(uri=uri, labels=labels, narrower=list(narrower or []))


def _link(t: Taxonomy, parent: str, child: str) -> None:
    t.concepts[parent].narrower.append(child)
    t.concepts[child].broader.append(parent)


# ── has_taxonomy / is_skos_only ───────────────────────────────────────────────


def test_has_taxonomy_false_for_empty():
    assert has_taxonomy(Taxonomy()) is False


def test_has_taxonomy_true_with_concepts_only():
    t = Taxonomy()
    t.concepts[BASE + "C0"] = _concept(BASE + "C0", "A")
    assert has_taxonomy(t) is True


def test_is_skos_only_false_when_owl_present():
    t = Taxonomy()
    t.concepts[BASE + "C0"] = _concept(BASE + "C0", "A")
    t.owl_classes[BASE + "Cls"] = RDFClass(uri=BASE + "Cls")
    assert is_skos_only(t) is False


def test_is_skos_only_true_for_pure_skos():
    t = Taxonomy()
    t.concepts[BASE + "C0"] = _concept(BASE + "C0", "A")
    assert is_skos_only(t) is True


def test_is_skos_only_false_for_pure_owl():
    t = Taxonomy()
    t.owl_classes[BASE + "Cls"] = RDFClass(uri=BASE + "Cls")
    assert is_skos_only(t) is False


# ── build_taxonomy_treemap — basic tree shape ─────────────────────────────────


def test_empty_taxonomy_yields_empty_payload():
    payload = build_taxonomy_treemap(Taxonomy())
    assert payload == {"schemes": [], "nodes": {}}


def test_single_scheme_roots_and_depth():
    t = Taxonomy()
    root, child, grandchild = BASE + "R", BASE + "C", BASE + "GC"
    t.concepts[root] = _concept(root, "Root")
    t.concepts[child] = _concept(child, "Child")
    t.concepts[grandchild] = _concept(grandchild, "Grandchild")
    _link(t, root, child)
    _link(t, child, grandchild)
    scheme_uri = BASE + "Scheme"
    t.schemes[scheme_uri] = ConceptScheme(uri=scheme_uri, top_concepts=[root])

    payload = build_taxonomy_treemap(t)

    assert payload["schemes"] == [{"uri": scheme_uri, "title": "Scheme", "roots": [root]}]
    assert payload["nodes"][root]["depth"] == 0
    assert payload["nodes"][child]["depth"] == 1
    assert payload["nodes"][grandchild]["depth"] == 2
    assert payload["nodes"][root]["parent"] is None
    assert payload["nodes"][child]["parent"] == root
    assert payload["nodes"][root]["children"] == [child]
    assert payload["nodes"][root]["schemeUri"] == scheme_uri


def test_descendant_counts_bottom_up():
    t = Taxonomy()
    root, a, b, aa = BASE + "R", BASE + "A", BASE + "B", BASE + "AA"
    for uri, lbl in ((root, "R"), (a, "A"), (b, "B"), (aa, "AA")):
        t.concepts[uri] = _concept(uri, lbl)
    _link(t, root, a)
    _link(t, root, b)
    _link(t, a, aa)
    scheme_uri = BASE + "Scheme"
    t.schemes[scheme_uri] = ConceptScheme(uri=scheme_uri, top_concepts=[root])

    payload = build_taxonomy_treemap(t)

    assert payload["nodes"][aa]["descendantCount"] == 0
    assert payload["nodes"][a]["descendantCount"] == 1
    assert payload["nodes"][b]["descendantCount"] == 0
    assert payload["nodes"][root]["descendantCount"] == 3


def test_multiple_schemes():
    t = Taxonomy()
    r1, r2 = BASE + "R1", BASE + "R2"
    t.concepts[r1] = _concept(r1, "R1")
    t.concepts[r2] = _concept(r2, "R2")
    s1, s2 = BASE + "S1", BASE + "S2"
    t.schemes[s1] = ConceptScheme(uri=s1, top_concepts=[r1])
    t.schemes[s2] = ConceptScheme(uri=s2, top_concepts=[r2])

    payload = build_taxonomy_treemap(t)

    assert {s["uri"] for s in payload["schemes"]} == {s1, s2}
    assert payload["nodes"][r1]["schemeUri"] == s1
    assert payload["nodes"][r2]["schemeUri"] == s2


# ── multi-parent: first-parent-wins ───────────────────────────────────────────


def test_multi_parent_first_parent_wins_no_double_count():
    t = Taxonomy()
    root, a, b, shared = BASE + "R", BASE + "A", BASE + "B", BASE + "Shared"
    for uri, lbl in ((root, "R"), (a, "A"), (b, "B"), (shared, "Shared")):
        t.concepts[uri] = _concept(uri, lbl)
    _link(t, root, a)
    _link(t, root, b)
    _link(t, a, shared)
    _link(t, b, shared)  # second parent — must be ignored
    scheme_uri = BASE + "Scheme"
    t.schemes[scheme_uri] = ConceptScheme(uri=scheme_uri, top_concepts=[root])

    payload = build_taxonomy_treemap(t)

    # 'a' is dequeued before 'b' (BFS, top_concepts/narrower list order), so
    # 'shared' keeps 'a' as its only parent.
    assert payload["nodes"][shared]["parent"] == a
    assert payload["nodes"][a]["children"] == [shared]
    assert payload["nodes"][b]["children"] == []
    # total distinct concepts under root: a, b, shared = 3 (not 4 — no double count)
    assert payload["nodes"][root]["descendantCount"] == 3


# ── orphan concepts ────────────────────────────────────────────────────────────


def test_orphan_concepts_grouped_under_synthetic_scheme():
    t = Taxonomy()
    in_scheme, orphan = BASE + "In", BASE + "Orphan"
    t.concepts[in_scheme] = _concept(in_scheme, "In")
    t.concepts[orphan] = _concept(orphan, "Orphan")
    scheme_uri = BASE + "Scheme"
    t.schemes[scheme_uri] = ConceptScheme(uri=scheme_uri, top_concepts=[in_scheme])

    payload = build_taxonomy_treemap(t)

    no_scheme = next(s for s in payload["schemes"] if s["uri"] == NO_SCHEME_URI)
    assert no_scheme["roots"] == [orphan]
    assert payload["nodes"][orphan]["schemeUri"] == NO_SCHEME_URI
    assert payload["nodes"][orphan]["depth"] == 0


def test_no_synthetic_scheme_when_no_orphans():
    t = Taxonomy()
    root = BASE + "R"
    t.concepts[root] = _concept(root, "R")
    scheme_uri = BASE + "Scheme"
    t.schemes[scheme_uri] = ConceptScheme(uri=scheme_uri, top_concepts=[root])

    payload = build_taxonomy_treemap(t)

    assert all(s["uri"] != NO_SCHEME_URI for s in payload["schemes"])


def test_orphan_cycle_does_not_hang_and_keeps_all_concepts():
    t = Taxonomy()
    a, b = BASE + "A", BASE + "B"
    t.concepts[a] = _concept(a, "A")
    t.concepts[b] = _concept(b, "B")
    _link(t, a, b)
    _link(t, b, a)  # pure cycle, no reference-free entry point, no scheme at all

    payload = build_taxonomy_treemap(t)

    assert set(payload["nodes"]) == {a, b}
    no_scheme = next(s for s in payload["schemes"] if s["uri"] == NO_SCHEME_URI)
    assert set(no_scheme["roots"]) == {a, b}
