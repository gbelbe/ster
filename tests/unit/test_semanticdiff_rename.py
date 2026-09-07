"""Unit tests for rename detection.

A URI change under an unchanged label is a rename, not a delete plus an add —
the ugliest false signal a naive graph diff produces. The heuristic is
deliberately conservative: it pairs only when the (kind, label, language) key is
unique on both sides.
"""

from __future__ import annotations

from rdflib import Graph

from semanticdiff.changeset import compare
from semanticdiff.rename import detect_renames
from semanticdiff.vocabulary import Change, ChangeKind, ChangeSet, EntityKind

PREFIXES = """
@prefix ex:   <http://example.org/> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
"""

STORE = "Store"


def graph(body: str) -> Graph:
    g = Graph()
    g.parse(data=PREFIXES + body, format="turtle")
    return g


def change(
    kind: ChangeKind,
    curie: str,
    label: str | None = None,
    lang: str | None = "en",
    entity: EntityKind = EntityKind.CLASS,
) -> Change:
    return Change(
        kind=kind,
        entity=entity,
        uri=f"http://example.org/{curie.split(':')[-1]}",
        curie=curie,
        label=label,
        label_lang=lang if label else None,
    )


# ── the pairing rule, tested directly ─────────────────────────────────────────


def test_same_label_new_uri_reported_as_rename() -> None:
    changes = ChangeSet(
        (
            change(ChangeKind.REMOVED, "ex:Shop", STORE),
            change(ChangeKind.ADDED, "ex:Store", STORE),
        )
    )

    result = detect_renames(changes)

    assert len(result) == 1
    renamed = result.changes[0]
    assert renamed.kind is ChangeKind.RENAMED
    assert renamed.curie == "ex:Store"
    assert renamed.previous_curie == "ex:Shop"


def test_rename_removes_the_add_and_delete_pair() -> None:
    changes = ChangeSet(
        (
            change(ChangeKind.REMOVED, "ex:Shop", STORE),
            change(ChangeKind.ADDED, "ex:Store", STORE),
        )
    )

    kinds = {c.kind for c in detect_renames(changes)}

    assert ChangeKind.ADDED not in kinds
    assert ChangeKind.REMOVED not in kinds


def test_unrelated_add_and_delete_not_paired() -> None:
    changes = ChangeSet(
        (
            change(ChangeKind.REMOVED, "ex:Shop", STORE),
            change(ChangeKind.ADDED, "ex:Van", "Van"),
        )
    )

    assert {c.kind for c in detect_renames(changes)} == {ChangeKind.REMOVED, ChangeKind.ADDED}


def test_ambiguous_label_shared_by_two_entities_not_paired() -> None:
    changes = ChangeSet(
        (
            change(ChangeKind.REMOVED, "ex:ShopA", STORE),
            change(ChangeKind.REMOVED, "ex:ShopB", STORE),
            change(ChangeKind.ADDED, "ex:Store", STORE),
        )
    )

    result = detect_renames(changes)

    assert all(c.kind is not ChangeKind.RENAMED for c in result)
    assert len(result) == 3


def test_ambiguous_addition_side_not_paired() -> None:
    changes = ChangeSet(
        (
            change(ChangeKind.REMOVED, "ex:Shop", STORE),
            change(ChangeKind.ADDED, "ex:StoreA", STORE),
            change(ChangeKind.ADDED, "ex:StoreB", STORE),
        )
    )

    assert all(c.kind is not ChangeKind.RENAMED for c in detect_renames(changes))


def test_entities_of_different_kinds_not_paired() -> None:
    changes = ChangeSet(
        (
            change(ChangeKind.REMOVED, "ex:Shop", STORE, entity=EntityKind.CLASS),
            change(ChangeKind.ADDED, "ex:store", STORE, entity=EntityKind.PROPERTY),
        )
    )

    assert all(c.kind is not ChangeKind.RENAMED for c in detect_renames(changes))


def test_unlabelled_entities_never_paired() -> None:
    changes = ChangeSet(
        (
            change(ChangeKind.REMOVED, "ex:Shop", None),
            change(ChangeKind.ADDED, "ex:Store", None),
        )
    )

    assert all(c.kind is not ChangeKind.RENAMED for c in detect_renames(changes))


def test_rename_matches_on_matching_language_tag() -> None:
    changes = ChangeSet(
        (
            change(ChangeKind.REMOVED, "ex:Shop", STORE, lang="en"),
            change(ChangeKind.ADDED, "ex:Store", STORE, lang="fr"),
        )
    )

    assert all(c.kind is not ChangeKind.RENAMED for c in detect_renames(changes))


def test_modified_changes_pass_through_untouched() -> None:
    changes = ChangeSet((change(ChangeKind.MODIFIED, "ex:Product", "Product"),))

    assert detect_renames(changes).changes == changes.changes


def test_empty_changeset_is_returned_unchanged() -> None:
    assert len(detect_renames(ChangeSet(()))) == 0


# ── the same rule, reached through compare() ──────────────────────────────────


def test_compare_reports_a_rename_end_to_end() -> None:
    base = graph('ex:Shop a owl:Class ; rdfs:label "Store"@en .')
    later = graph('ex:Store a owl:Class ; rdfs:label "Store"@en .')

    changes = compare(base, later)

    assert len(changes) == 1
    assert changes.changes[0].kind is ChangeKind.RENAMED
    assert changes.changes[0].previous_curie == "ex:Shop"


def test_compare_pairs_skos_concepts_on_their_pref_label() -> None:
    base = graph('ex:T1 a skos:Concept ; skos:prefLabel "Tools"@en .')
    later = graph('ex:Tools a skos:Concept ; skos:prefLabel "Tools"@en .')

    changes = compare(base, later)

    assert changes.changes[0].kind is ChangeKind.RENAMED
    assert changes.changes[0].entity is EntityKind.CONCEPT
