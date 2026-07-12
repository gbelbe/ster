"""Unit tests for the composite individual commands
(OwlCreateIndividualFull / OwlSaveIndividual) used by the add/edit individual modal."""

from __future__ import annotations

from pathlib import Path

from ster.core.commands import OwlCreateIndividualFull, OwlSaveIndividual
from ster.model import Label, OWLIndividual, RDFClass, Taxonomy

_P = Path("o.ttl")
NS = "https://ex.org/onto#"
DOG = NS + "Dog"
PERSON = NS + "Person"


def _labels(ind: OWLIndividual) -> dict[str, str]:
    return {lbl.lang: lbl.value for lbl in ind.labels}


def _comments(ind: OWLIndividual) -> dict[str, str]:
    return {c.lang: c.value for c in ind.comments}


def _seed() -> Taxonomy:
    t = Taxonomy()
    t.owl_classes[DOG] = RDFClass(uri=DOG)
    t.owl_classes[PERSON] = RDFClass(uri=PERSON)
    t.owl_individuals[NS + "Alice"] = OWLIndividual(uri=NS + "Alice", types=[PERSON])
    return t


# ── OwlCreateIndividualFull ─────────────────────────────────────────────────────


def test_create_individual_types_labels_comments_and_values() -> None:
    t = _seed()
    OwlCreateIndividualFull(
        _P,
        NS + "Buddy",
        type_uri=DOG,
        labels=(("en", "Buddy"), ("fr", "Buddy")),
        comments=(("en", "A good dog"),),
        obj_values=((NS + "hasOwner", NS + "Alice"),),
        lit_values=((NS + "breed", "Labrador"),),
    ).apply(t)
    ind = t.owl_individuals[NS + "Buddy"]
    assert DOG in ind.types
    assert _labels(ind) == {"en": "Buddy", "fr": "Buddy"}
    assert _comments(ind) == {"en": "A good dog"}
    assert (NS + "hasOwner", NS + "Alice") in ind.property_values
    assert any(pv[0] == NS + "breed" and pv[1] == "Labrador" for pv in ind.literal_values)


def test_create_individual_skips_empty_values() -> None:
    t = _seed()
    OwlCreateIndividualFull(
        _P,
        NS + "Bare",
        type_uri=DOG,
        labels=(("en", "Bare"), ("fr", "")),
        obj_values=((NS + "hasOwner", ""),),
        lit_values=((NS + "breed", ""),),
    ).apply(t)
    ind = t.owl_individuals[NS + "Bare"]
    assert _labels(ind) == {"en": "Bare"}
    assert ind.property_values == []
    assert ind.literal_values == []


def test_create_individual_without_type() -> None:
    t = _seed()
    OwlCreateIndividualFull(_P, NS + "Loose", type_uri=None).apply(t)
    assert NS + "Loose" in t.owl_individuals
    assert t.owl_individuals[NS + "Loose"].types == []


# ── OwlSaveIndividual ───────────────────────────────────────────────────────────


def test_save_individual_renames_and_sets_label_comment() -> None:
    t = _seed()
    t.owl_individuals[NS + "Rex"] = OWLIndividual(
        uri=NS + "Rex", types=[DOG], labels=[Label(lang="en", value="Rex")]
    )
    OwlSaveIndividual(
        _P,
        NS + "Rex",
        NS + "Rexy",
        labels=(("en", "Rexy"),),
        comments=(("en", "renamed"),),
    ).apply(t)
    assert NS + "Rex" not in t.owl_individuals
    ind = t.owl_individuals[NS + "Rexy"]
    assert _labels(ind) == {"en": "Rexy"}
    assert _comments(ind) == {"en": "renamed"}
    assert DOG in ind.types  # type preserved through the edit


def test_save_individual_empty_value_clears_that_language() -> None:
    t = _seed()
    t.owl_individuals[NS + "Rex"] = OWLIndividual(
        uri=NS + "Rex",
        labels=[Label(lang="en", value="Rex"), Label(lang="fr", value="Rex")],
    )
    OwlSaveIndividual(_P, NS + "Rex", NS + "Rex", labels=(("en", "Rex"), ("fr", ""))).apply(t)
    assert _labels(t.owl_individuals[NS + "Rex"]) == {"en": "Rex"}


# ── OwlChangeIndividualType (re-classify via the editable instanceOf row) ────────


def test_change_individual_type_reclassifies() -> None:
    from ster.core.commands import OwlChangeIndividualType

    t = _seed()  # Alice : Person
    OwlChangeIndividualType(_P, NS + "Alice", PERSON, DOG).apply(t)
    assert t.owl_individuals[NS + "Alice"].types == [DOG]  # Person dropped, Dog added


def test_change_individual_type_to_same_is_a_noop() -> None:
    from ster.core.commands import OwlChangeIndividualType

    t = _seed()
    OwlChangeIndividualType(_P, NS + "Alice", PERSON, PERSON).apply(t)
    assert t.owl_individuals[NS + "Alice"].types == [PERSON]
