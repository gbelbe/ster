"""The shared 'missing element' affordance component.

Every entity detail page offers the same nudge when an expected element is
absent: a dim '＋ Add …' affordance for the entity's essential label (one per
configured language it lacks) and for each configured annotation predicate it
does not carry. These pure helpers back all four entity builders so the rows
are derived once, not copy-pasted per kind.
"""

from __future__ import annotations

from ster.metadata_coverage import MetaProp
from ster.nav.logic import (
    configured_annotation_affordances,
    essential_label_affordances,
)


class _Ann:
    def __init__(self, predicate: str) -> None:
        self.predicate = predicate


class _Entity:
    """Minimal stand-in with the attributes entity_predicates() reads."""

    def __init__(self, labels=(), annotations=()) -> None:
        self.labels = list(labels)
        self.annotations = [_Ann(p) for p in annotations]


RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
PREFLABEL = "http://www.w3.org/2004/02/skos/core#prefLabel"
SEEALSO = "http://www.w3.org/2000/01/rdf-schema#seeAlso"
SOURCE = "http://purl.org/dc/terms/source"


# ── essential label affordance ────────────────────────────────────────────────


def test_essential_label_affordance_per_missing_language() -> None:
    """A concept missing its French prefLabel gets exactly one '＋ Add prefLabel [fr]'."""
    rows = essential_label_affordances(
        "concept", present_langs={"en"}, configured_langs=["en", "fr"]
    )
    assert [r.meta["lang"] for r in rows] == ["fr"]
    assert rows[0].meta["action"] == "add_pref_label"
    assert "prefLabel" in rows[0].display and "[fr]" in rows[0].display


def test_essential_label_affordance_uses_rdfs_label_for_owl_kinds() -> None:
    for kind, action in (
        ("class", "add_rdf_label"),
        ("individual", "add_ind_label"),
        ("property", "add_prop_label"),
    ):
        rows = essential_label_affordances(kind, present_langs=set(), configured_langs=["en"])
        assert rows[0].meta["action"] == action
        assert "rdfs:label" in rows[0].display


def test_no_affordance_when_all_languages_present() -> None:
    rows = essential_label_affordances(
        "class", present_langs={"en", "fr"}, configured_langs=["en", "fr"]
    )
    assert rows == []


def test_unknown_kind_yields_no_affordance() -> None:
    assert (
        essential_label_affordances("section", present_langs=set(), configured_langs=["en"]) == []
    )


# ── configured annotation affordance ──────────────────────────────────────────


def test_configured_annotation_affordance_for_each_missing_predicate() -> None:
    entity = _Entity()  # carries no annotations
    catalog = [MetaProp(SEEALSO, "rdfs:seeAlso"), MetaProp(SOURCE, "dcterms:source")]
    rows = configured_annotation_affordances(entity, catalog)
    preds = [r.meta["predicate"] for r in rows]
    assert preds == [SEEALSO, SOURCE]
    assert all(r.meta["action"] == "add_entity_annotation" for r in rows)
    assert "rdfs:seeAlso" in rows[0].display


def test_no_annotation_affordance_when_predicate_already_present() -> None:
    entity = _Entity(annotations=[SEEALSO])
    catalog = [MetaProp(SEEALSO, "rdfs:seeAlso"), MetaProp(SOURCE, "dcterms:source")]
    rows = configured_annotation_affordances(entity, catalog)
    assert [r.meta["predicate"] for r in rows] == [SOURCE]  # seeAlso already there → skipped


def test_annotation_affordance_empty_when_catalog_unconfigured() -> None:
    assert configured_annotation_affordances(_Entity(), None) == []
    assert configured_annotation_affordances(_Entity(), []) == []
