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


def test_resolve_missing_raises(simple_taxonomy):
    with pytest.raises(HandleNotFoundError):
        operations.resolve(simple_taxonomy, "NOPE")


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
    en_pref = [l for l in simple_taxonomy.concepts[uri].labels
               if l.type == LabelType.PREF and l.lang == "en"]
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
