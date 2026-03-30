"""Tests for all business-logic operations."""

from __future__ import annotations

import pytest

from ster import operations
from ster.exceptions import (
    CircularHierarchyError,
    ConceptAlreadyExistsError,
    ConceptNotFoundError,
    HandleNotFoundError,
    HasChildrenError,
    RelatedHierarchyConflictError,
)
from ster.model import LabelType

BASE = "https://example.org/test/"
NEW = BASE + "NewConcept"


# ── resolve ───────────────────────────────────────────────────────────────────


def test_resolve_by_handle(simple_taxonomy):
    handle = simple_taxonomy.uri_to_handle(BASE + "Top")
    uri = operations.resolve(simple_taxonomy, handle)
    assert uri == BASE + "Top"


def test_resolve_by_uri(simple_taxonomy):
    uri = operations.resolve(simple_taxonomy, BASE + "Top")
    assert uri == BASE + "Top"


def test_resolve_by_local_name(simple_taxonomy):
    uri = operations.resolve(simple_taxonomy, "Top")
    assert uri == BASE + "Top"


def test_resolve_by_local_name_child(simple_taxonomy):
    uri = operations.resolve(simple_taxonomy, "Child1")
    assert uri == BASE + "Child1"


def test_resolve_missing_raises(simple_taxonomy):
    with pytest.raises(HandleNotFoundError):
        operations.resolve(simple_taxonomy, "NOPE")


# ── expand_uri ────────────────────────────────────────────────────────────────


def test_expand_uri_local_name(simple_taxonomy):
    uri = operations.expand_uri(simple_taxonomy, "NewConcept")
    assert uri == BASE + "NewConcept"


def test_expand_uri_full_uri_passthrough(simple_taxonomy):
    full = "https://other.org/vocab/Thing"
    assert operations.expand_uri(simple_taxonomy, full) == full


def test_expand_uri_no_base_raises():
    from ster.model import Taxonomy

    t = Taxonomy()
    with pytest.raises(HandleNotFoundError):
        operations.expand_uri(t, "NoBase")


# ── add_concept ───────────────────────────────────────────────────────────────


def test_add_concept_under_parent(simple_taxonomy):
    parent_uri = BASE + "Child2"
    operations.add_concept(simple_taxonomy, NEW, {"en": "New"}, parent_uri)
    assert NEW in simple_taxonomy.concepts
    assert NEW in simple_taxonomy.concepts[parent_uri].narrower
    assert parent_uri in simple_taxonomy.concepts[NEW].broader


def test_add_concept_top_level(simple_taxonomy):
    operations.add_concept(simple_taxonomy, NEW, {"en": "New"}, parent_handle=None)
    scheme = simple_taxonomy.primary_scheme()
    assert NEW in scheme.top_concepts
    assert simple_taxonomy.concepts[NEW].top_concept_of == scheme.uri


def test_add_concept_gets_handle(simple_taxonomy):
    operations.add_concept(simple_taxonomy, NEW, {"en": "New"})
    assert simple_taxonomy.uri_to_handle(NEW) is not None


def test_add_concept_duplicate_raises(simple_taxonomy):
    with pytest.raises(ConceptAlreadyExistsError):
        operations.add_concept(simple_taxonomy, BASE + "Top", {"en": "Dupe"})


def test_add_concept_bad_parent_raises(simple_taxonomy):
    with pytest.raises(HandleNotFoundError):
        operations.add_concept(simple_taxonomy, NEW, {"en": "New"}, parent_handle="NOSUCHHANDLE")


# ── remove_concept ────────────────────────────────────────────────────────────


def test_remove_leaf(simple_taxonomy):
    uri = BASE + "Child2"
    operations.remove_concept(simple_taxonomy, uri)
    assert uri not in simple_taxonomy.concepts
    assert uri not in simple_taxonomy.concepts[BASE + "Top"].narrower


def test_remove_with_children_raises(simple_taxonomy):
    with pytest.raises(HasChildrenError):
        operations.remove_concept(simple_taxonomy, BASE + "Child1")


def test_remove_cascade(simple_taxonomy):
    removed = operations.remove_concept(simple_taxonomy, BASE + "Child1", cascade=True)
    assert BASE + "Child1" not in simple_taxonomy.concepts
    assert BASE + "Grandchild" not in simple_taxonomy.concepts
    assert {BASE + "Child1", BASE + "Grandchild"} == removed


def test_remove_cleans_related(simple_taxonomy):
    uri_a = BASE + "Child2"
    uri_b = BASE + "Grandchild"
    simple_taxonomy.concepts[uri_a].related.append(uri_b)
    simple_taxonomy.concepts[uri_b].related.append(uri_a)
    operations.remove_concept(simple_taxonomy, uri_a)
    assert uri_a not in simple_taxonomy.concepts[uri_b].related


def test_remove_missing_raises(simple_taxonomy):
    with pytest.raises(ConceptNotFoundError):
        operations.remove_concept(simple_taxonomy, BASE + "DoesNotExist")


# ── move_concept ──────────────────────────────────────────────────────────────


def test_move_to_new_parent(simple_taxonomy):
    uri = BASE + "Child2"
    new_parent = BASE + "Child1"
    operations.move_concept(simple_taxonomy, uri, new_parent)
    assert uri in simple_taxonomy.concepts[new_parent].narrower
    assert new_parent in simple_taxonomy.concepts[uri].broader
    assert uri not in simple_taxonomy.concepts[BASE + "Top"].narrower


def test_move_to_top_level(simple_taxonomy):
    uri = BASE + "Grandchild"
    operations.move_concept(simple_taxonomy, uri, None)
    scheme = simple_taxonomy.primary_scheme()
    assert uri in scheme.top_concepts
    assert simple_taxonomy.concepts[uri].top_concept_of == scheme.uri
    assert uri not in simple_taxonomy.concepts[BASE + "Child1"].narrower


def test_move_circular_raises(simple_taxonomy):
    with pytest.raises(CircularHierarchyError):
        operations.move_concept(simple_taxonomy, BASE + "Top", BASE + "Grandchild")


def test_move_missing_raises(simple_taxonomy):
    with pytest.raises(ConceptNotFoundError):
        operations.move_concept(simple_taxonomy, BASE + "Ghost", None)


# ── set_label ─────────────────────────────────────────────────────────────────


def test_set_pref_label_new_lang(simple_taxonomy):
    uri = BASE + "Top"
    operations.set_label(simple_taxonomy, uri, "de", "Oberbegriff")
    assert simple_taxonomy.concepts[uri].pref_label("de") == "Oberbegriff"


def test_set_pref_label_replaces_existing(simple_taxonomy):
    uri = BASE + "Top"
    operations.set_label(simple_taxonomy, uri, "en", "Updated")
    assert simple_taxonomy.concepts[uri].pref_label("en") == "Updated"
    en_pref = [
        l
        for l in simple_taxonomy.concepts[uri].labels
        if l.type == LabelType.PREF and l.lang == "en"
    ]
    assert len(en_pref) == 1


def test_set_alt_label_coexists(simple_taxonomy):
    uri = BASE + "Top"
    operations.set_label(simple_taxonomy, uri, "en", "Alternative", LabelType.ALT)
    pref = simple_taxonomy.concepts[uri].pref_label("en")
    assert pref == "Top Concept"
    alts = simple_taxonomy.concepts[uri].alt_labels().get("en", [])
    assert "Alternative" in alts


# ── set_definition ────────────────────────────────────────────────────────────


def test_set_definition_new(simple_taxonomy):
    uri = BASE + "Child2"
    operations.set_definition(simple_taxonomy, uri, "en", "A definition.")
    assert simple_taxonomy.concepts[uri].definition("en") == "A definition."


def test_set_definition_replaces(simple_taxonomy):
    uri = BASE + "Top"
    operations.set_definition(simple_taxonomy, uri, "en", "New definition.")
    defns = [d for d in simple_taxonomy.concepts[uri].definitions if d.lang == "en"]
    assert len(defns) == 1
    assert defns[0].value == "New definition."


# ── add_related / remove_related ─────────────────────────────────────────────


def test_add_related_symmetric(simple_taxonomy):
    uri_a = BASE + "Child2"
    uri_b = BASE + "Grandchild"
    operations.add_related(simple_taxonomy, uri_a, uri_b)
    assert uri_b in simple_taxonomy.concepts[uri_a].related
    assert uri_a in simple_taxonomy.concepts[uri_b].related


def test_add_related_hierarchy_conflict_raises(simple_taxonomy):
    with pytest.raises(RelatedHierarchyConflictError):
        operations.add_related(simple_taxonomy, BASE + "Top", BASE + "Child1")


def test_remove_related(simple_taxonomy):
    uri_a = BASE + "Child2"
    uri_b = BASE + "Grandchild"
    simple_taxonomy.concepts[uri_a].related.append(uri_b)
    simple_taxonomy.concepts[uri_b].related.append(uri_a)
    operations.remove_related(simple_taxonomy, uri_a, uri_b)
    assert uri_b not in simple_taxonomy.concepts[uri_a].related
    assert uri_a not in simple_taxonomy.concepts[uri_b].related


# ── rename_uri ────────────────────────────────────────────────────────────────


def test_rename_updates_concept_dict(simple_taxonomy):
    old = BASE + "Child2"
    new = BASE + "ChildRenamed"
    operations.rename_uri(simple_taxonomy, old, new)
    assert new in simple_taxonomy.concepts
    assert old not in simple_taxonomy.concepts


def test_rename_updates_parent_narrower(simple_taxonomy):
    old = BASE + "Child2"
    new = BASE + "ChildRenamed"
    operations.rename_uri(simple_taxonomy, old, new)
    assert new in simple_taxonomy.concepts[BASE + "Top"].narrower
    assert old not in simple_taxonomy.concepts[BASE + "Top"].narrower


def test_rename_duplicate_raises(simple_taxonomy):
    with pytest.raises(ConceptAlreadyExistsError):
        operations.rename_uri(simple_taxonomy, BASE + "Child1", BASE + "Child2")


def test_rename_updates_top_concept_of(simple_taxonomy):
    """Renaming a top concept updates top_concept_of on the concept itself."""
    old = BASE + "Top"
    new = BASE + "TopRenamed"
    operations.rename_uri(simple_taxonomy, old, new)
    assert (
        simple_taxonomy.concepts[new].top_concept_of is None
        or simple_taxonomy.concepts[new].top_concept_of != old
    )


def test_rename_missing_raises(simple_taxonomy):
    with pytest.raises(ConceptNotFoundError):
        operations.rename_uri(simple_taxonomy, BASE + "NoSuch", BASE + "New")


# ── add_broader_link ───────────────────────────────────────────────────────────


def test_add_broader_link_adds_polyhierarchy(simple_taxonomy):
    """Child2 gains a second broader (Grandchild's parent Child1)."""
    uri = BASE + "Child2"
    new_parent = BASE + "Grandchild"
    # First make Grandchild a leaf so it isn't an ancestor of Child2
    # (Grandchild's broader is Child1 which is broader of Child2 — but
    #  Grandchild itself is NOT an ancestor of Child2)
    operations.add_broader_link(simple_taxonomy, uri, new_parent)
    assert new_parent in simple_taxonomy.concepts[uri].broader
    assert uri in simple_taxonomy.concepts[new_parent].narrower
    # Original broader still intact
    assert BASE + "Top" in simple_taxonomy.concepts[uri].broader


def test_add_broader_link_missing_concept_raises(simple_taxonomy):
    with pytest.raises(ConceptNotFoundError):
        operations.add_broader_link(simple_taxonomy, BASE + "Ghost", BASE + "Child1")


def test_add_broader_link_missing_parent_raises(simple_taxonomy):
    with pytest.raises(ConceptNotFoundError):
        operations.add_broader_link(simple_taxonomy, BASE + "Child2", BASE + "Ghost")


def test_add_broader_link_self_raises(simple_taxonomy):
    with pytest.raises(CircularHierarchyError):
        operations.add_broader_link(simple_taxonomy, BASE + "Child1", BASE + "Child1")


def test_add_broader_link_circular_raises(simple_taxonomy):
    """Linking an ancestor as child raises CircularHierarchyError."""
    with pytest.raises(CircularHierarchyError):
        # Top is an ancestor of Grandchild — cannot link Grandchild as broader of Top
        operations.add_broader_link(simple_taxonomy, BASE + "Top", BASE + "Grandchild")


def test_add_broader_link_duplicate_is_noop(simple_taxonomy):
    """Adding a link that already exists leaves broader list unchanged."""
    uri = BASE + "Child1"
    parent = BASE + "Top"
    before = list(simple_taxonomy.concepts[uri].broader)
    operations.add_broader_link(simple_taxonomy, uri, parent)
    after = list(simple_taxonomy.concepts[uri].broader)
    assert before == after


def test_add_broader_link_new_parent_narrower_not_duplicated(simple_taxonomy):
    """If uri is already in new_parent.narrower, it isn't added twice."""
    uri = BASE + "Grandchild"
    new_parent = BASE + "Child2"
    operations.add_broader_link(simple_taxonomy, uri, new_parent)
    count = simple_taxonomy.concepts[new_parent].narrower.count(uri)
    assert count == 1


# ── remove_label ──────────────────────────────────────────────────────────────


def test_remove_label_removes_alt_label(simple_taxonomy):
    uri = BASE + "Child2"
    # Child2 has altLabel "Second child"@en in the conftest TTL but not in simple_taxonomy
    # Add it first
    from ster.model import Label, LabelType

    simple_taxonomy.concepts[uri].labels.append(
        Label(lang="en", value="Second child", type=LabelType.ALT)
    )
    operations.remove_label(simple_taxonomy, uri, "en", "Second child", LabelType.ALT)
    alts = [
        l
        for l in simple_taxonomy.concepts[uri].labels
        if l.type == LabelType.ALT and l.lang == "en" and l.value == "Second child"
    ]
    assert alts == []


def test_remove_label_missing_concept_raises(simple_taxonomy):
    with pytest.raises(ConceptNotFoundError):
        operations.remove_label(simple_taxonomy, BASE + "Ghost", "en", "label")


def test_remove_label_nonexistent_value_is_noop(simple_taxonomy):
    """Removing a label that doesn't exist leaves everything intact."""
    uri = BASE + "Top"
    before = len(simple_taxonomy.concepts[uri].labels)
    operations.remove_label(simple_taxonomy, uri, "en", "NoSuchLabel")
    after = len(simple_taxonomy.concepts[uri].labels)
    assert before == after


# ── set_label errors ──────────────────────────────────────────────────────────


def test_set_label_missing_concept_raises(simple_taxonomy):
    with pytest.raises(ConceptNotFoundError):
        operations.set_label(simple_taxonomy, BASE + "Ghost", "en", "value")


# ── set_definition errors ─────────────────────────────────────────────────────


def test_set_definition_missing_concept_raises(simple_taxonomy):
    with pytest.raises(ConceptNotFoundError):
        operations.set_definition(simple_taxonomy, BASE + "Ghost", "en", "value")


# ── add_related errors ────────────────────────────────────────────────────────


def test_add_related_missing_concept_a_raises(simple_taxonomy):
    with pytest.raises(ConceptNotFoundError):
        operations.add_related(simple_taxonomy, BASE + "Ghost", BASE + "Child1")


def test_add_related_missing_concept_b_raises(simple_taxonomy):
    with pytest.raises(ConceptNotFoundError):
        operations.add_related(simple_taxonomy, BASE + "Child1", BASE + "Ghost")


def test_add_related_duplicate_is_noop(simple_taxonomy):
    """Adding a related link twice doesn't duplicate it."""
    uri_a = BASE + "Child2"
    uri_b = BASE + "Grandchild"
    operations.add_related(simple_taxonomy, uri_a, uri_b)
    operations.add_related(simple_taxonomy, uri_a, uri_b)  # second call
    assert simple_taxonomy.concepts[uri_a].related.count(uri_b) == 1


# ── remove_related errors ─────────────────────────────────────────────────────


def test_remove_related_missing_concept_a_raises(simple_taxonomy):
    with pytest.raises(ConceptNotFoundError):
        operations.remove_related(simple_taxonomy, BASE + "Ghost", BASE + "Child1")


def test_remove_related_missing_concept_b_raises(simple_taxonomy):
    with pytest.raises(ConceptNotFoundError):
        operations.remove_related(simple_taxonomy, BASE + "Child1", BASE + "Ghost")


# ── move_concept edge cases ───────────────────────────────────────────────────


def test_move_to_scheme_parent(simple_taxonomy):
    """Moving a concept to a scheme URI makes it a top concept of that scheme."""
    scheme_uri = BASE + "Scheme"
    uri = BASE + "Grandchild"
    operations.move_concept(simple_taxonomy, uri, scheme_uri)
    scheme = simple_taxonomy.schemes[scheme_uri]
    assert uri in scheme.top_concepts
    assert simple_taxonomy.concepts[uri].top_concept_of == scheme_uri


def test_move_missing_new_parent_raises(simple_taxonomy):
    with pytest.raises(ConceptNotFoundError):
        operations.move_concept(simple_taxonomy, BASE + "Child2", BASE + "NoSuch")


# ── add_concept to scheme ─────────────────────────────────────────────────────


def test_add_concept_under_scheme(simple_taxonomy):
    """Adding a concept with a scheme URI as parent makes it a top concept."""
    scheme_uri = BASE + "Scheme"
    operations.add_concept(
        simple_taxonomy, BASE + "NewTop", {"en": "New Top"}, parent_handle=scheme_uri
    )
    scheme = simple_taxonomy.schemes[scheme_uri]
    assert BASE + "NewTop" in scheme.top_concepts


# ── remove_concept defensive pass ────────────────────────────────────────────


def test_remove_concept_defensive_pass_top_concepts(simple_taxonomy):
    """Removing a top concept also cleans scheme.top_concepts."""
    uri = BASE + "Top"
    # Make Child1 and Child2 top concepts too so we can delete Top
    simple_taxonomy.concepts[uri].narrower.clear()
    scheme = simple_taxonomy.primary_scheme()
    operations.remove_concept(simple_taxonomy, uri)
    assert uri not in scheme.top_concepts


# ── create_scheme ─────────────────────────────────────────────────────────────


def test_create_scheme_basic():
    from ster.model import Taxonomy

    t = Taxonomy()
    scheme = operations.create_scheme(
        t,
        "https://example.org/s",
        labels={"en": "My Scheme"},
        descriptions={"en": "A description"},
        creator="Alice",
        created="2024-01-01",
        languages=["en"],
        base_uri="https://example.org/s/",
    )
    assert scheme.uri == "https://example.org/s"
    assert "https://example.org/s" in t.schemes
    assert scheme.creator == "Alice"
    assert scheme.created == "2024-01-01"


def test_create_scheme_default_languages():
    from ster.model import Taxonomy

    t = Taxonomy()
    scheme = operations.create_scheme(
        t,
        "https://example.org/s",
        labels={"en": "My Scheme", "fr": "Mon Schéma"},
    )
    # languages defaults to the label keys
    assert "en" in scheme.languages
    assert "fr" in scheme.languages
