"""Unit tests for the composite class commands (OwlCreateClass / OwlSaveClass)."""

from __future__ import annotations

from pathlib import Path

from ster.core.commands import OwlCreateClass, OwlSaveClass
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
