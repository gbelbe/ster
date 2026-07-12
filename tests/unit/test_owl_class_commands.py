"""Unit tests for the composite class commands (OwlCreateClass / OwlSaveClass)."""

from __future__ import annotations

from pathlib import Path

from ster.core.commands import OwlCreateClass, OwlSaveClass, OwlSetComment, OwlSetLabel
from ster.model import Definition, Label, RDFClass, Taxonomy

_P = Path("o.ttl")
NS = "https://ex.org/onto#"


def _labels(cls: RDFClass) -> dict[str, str]:
    return {lbl.lang: lbl.value for lbl in cls.labels}


def _comments(cls: RDFClass) -> dict[str, str]:
    return {c.lang: c.value for c in cls.comments}


# ── OwlCreateClass ─────────────────────────────────────────────────────────────


def test_create_class_sets_labels_and_comments_and_parent() -> None:
    t = Taxonomy()
    t.owl_classes[NS + "Thing"] = RDFClass(uri=NS + "Thing")
    cmd = OwlCreateClass(
        _P,
        NS + "Vehicle",
        parent_uri=NS + "Thing",
        labels=(("en", "Vehicle"), ("fr", "Véhicule")),
        comments=(("en", "A wheeled thing"),),
    )
    cmd.apply(t)
    cls = t.owl_classes[NS + "Vehicle"]
    assert _labels(cls) == {"en": "Vehicle", "fr": "Véhicule"}
    assert _comments(cls) == {"en": "A wheeled thing"}
    assert NS + "Thing" in cls.sub_class_of


def test_create_class_skips_empty_values() -> None:
    t = Taxonomy()
    OwlCreateClass(
        _P, NS + "Bare", labels=(("en", "Bare"), ("fr", "")), comments=(("en", ""),)
    ).apply(t)
    cls = t.owl_classes[NS + "Bare"]
    assert _labels(cls) == {"en": "Bare"}  # the empty fr label was not created
    assert cls.comments == []


# ── OwlSaveClass ───────────────────────────────────────────────────────────────


def _seed() -> Taxonomy:
    t = Taxonomy()
    t.owl_classes[NS + "Car"] = RDFClass(
        uri=NS + "Car",
        labels=[Label("en", "Car"), Label("fr", "Voiture")],
        comments=[Definition("en", "old comment")],
    )
    return t


def test_save_class_upserts_and_clears() -> None:
    t = _seed()
    OwlSaveClass(
        _P,
        NS + "Car",
        NS + "Car",  # no rename
        labels=(("en", "Automobile"), ("fr", "")),  # change en, clear fr
        comments=(("en", "new comment"), ("fr", "commentaire")),
    ).apply(t)
    cls = t.owl_classes[NS + "Car"]
    assert _labels(cls) == {"en": "Automobile"}  # fr label cleared
    assert _comments(cls) == {"en": "new comment", "fr": "commentaire"}


def test_save_class_renames_and_cascades() -> None:
    t = _seed()
    # A subclass references Car as its parent — the rename must cascade.
    t.owl_classes[NS + "Sedan"] = RDFClass(uri=NS + "Sedan", sub_class_of=[NS + "Car"])
    OwlSaveClass(_P, NS + "Car", NS + "Automobile", labels=(("en", "Automobile"),)).apply(t)
    assert NS + "Car" not in t.owl_classes
    assert NS + "Automobile" in t.owl_classes
    assert NS + "Automobile" in t.owl_classes[NS + "Sedan"].sub_class_of


# ── OwlSetLabel / OwlSetComment — single-field inline edit ─────────────────────
# Regression: clearing a label/comment via the inline edit must *remove* that
# language's entry, not upsert an empty-string literal. An empty `rdfs:label ""`
# still satisfies every "has a label" check (semanticlint QUA004 / RDS001, the
# overview coverage), so the class wrongly stayed at 100 % coverage / green glyph.
# Root cause: OwlSetLabel.apply called set_owl_label unconditionally (upsert),
# unlike the batch OwlSaveClass path which already removes on empty.


def test_set_label_empty_removes_that_language_regression() -> None:
    t = _seed()  # Car has en + fr labels
    OwlSetLabel(_P, NS + "Car", "fr", "").apply(t)  # user clears the fr label
    cls = t.owl_classes[NS + "Car"]
    assert _labels(cls) == {"en": "Car"}  # fr removed, not left as ("fr", "")
    assert all(lbl.value for lbl in cls.labels)  # no empty-string label survives


def test_set_label_empty_on_last_label_leaves_class_unlabelled_regression() -> None:
    t = Taxonomy()
    t.owl_classes[NS + "Bare"] = RDFClass(uri=NS + "Bare", labels=[Label("en", "Bare")])
    OwlSetLabel(_P, NS + "Bare", "en", "").apply(t)  # clear the only label
    assert t.owl_classes[NS + "Bare"].labels == []  # truly unlabelled → lint can flag it


def test_set_label_non_empty_still_upserts() -> None:
    t = _seed()
    OwlSetLabel(_P, NS + "Car", "en", "Automobile").apply(t)
    assert _labels(t.owl_classes[NS + "Car"]) == {"en": "Automobile", "fr": "Voiture"}


def test_set_comment_empty_removes_that_language_regression() -> None:
    t = _seed()  # Car has an en comment
    OwlSetComment(_P, NS + "Car", "en", "").apply(t)
    assert t.owl_classes[NS + "Car"].comments == []
