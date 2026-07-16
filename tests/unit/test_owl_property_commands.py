"""Unit tests for the composite OwlCreateProperty command."""

from __future__ import annotations

from pathlib import Path

from ster.core.commands import OwlCreateProperty
from ster.model import OWLProperty, Taxonomy

_P = Path("o.ttl")
NS = "https://ex.org/onto#"


def _labels(prop: OWLProperty) -> dict[str, str]:
    return {lbl.lang: lbl.value for lbl in prop.labels}


def _comments(prop: OWLProperty) -> dict[str, str]:
    return {c.lang: c.value for c in prop.comments}


def test_create_object_property_sets_type_labels_comments_domain_range() -> None:
    t = Taxonomy()
    cmd = OwlCreateProperty(
        _P,
        NS + "hasOwner",
        labels=(("en", "has owner"), ("fr", "a pour propriétaire")),
        comments=(("en", "Links an animal to its owner"),),
        domain_uri=NS + "Animal",
        range_uri=NS + "Person",
    )
    (touched,) = cmd.apply(t)
    assert touched == NS + "hasOwner"
    prop = t.owl_properties[NS + "hasOwner"]
    assert prop.prop_type == "ObjectProperty"
    assert _labels(prop) == {"en": "has owner", "fr": "a pour propriétaire"}
    assert _comments(prop) == {"en": "Links an animal to its owner"}
    assert prop.domains == [NS + "Animal"]
    assert prop.ranges == [NS + "Person"]


def test_create_datatype_property_sets_its_type() -> None:
    t = Taxonomy()
    OwlCreateProperty(_P, NS + "age", labels=(("en", "age"),), prop_type="DatatypeProperty").apply(
        t
    )
    prop = t.owl_properties[NS + "age"]
    assert prop.prop_type == "DatatypeProperty"
    assert _labels(prop) == {"en": "age"}


def test_create_annotation_property_sets_its_type() -> None:
    t = Taxonomy()
    OwlCreateProperty(
        _P, NS + "editorialNote", labels=(("en", "editorial note"),), prop_type="AnnotationProperty"
    ).apply(t)
    prop = t.owl_properties[NS + "editorialNote"]
    assert prop.prop_type == "AnnotationProperty"
    assert _labels(prop) == {"en": "editorial note"}


def test_create_object_property_without_domain_range_or_extra_langs() -> None:
    t = Taxonomy()
    OwlCreateProperty(_P, NS + "relatedTo", labels=(("en", "related to"),)).apply(t)
    prop = t.owl_properties[NS + "relatedTo"]
    assert prop.prop_type == "ObjectProperty"
    assert _labels(prop) == {"en": "related to"}
    assert prop.domains == [] and prop.ranges == []


def test_create_object_property_skips_blank_label_and_comment_values() -> None:
    t = Taxonomy()
    OwlCreateProperty(
        _P,
        NS + "p",
        labels=(("en", "P"), ("fr", "")),  # blank fr → no fr label
        comments=(("en", ""),),  # blank → no comment
    ).apply(t)
    prop = t.owl_properties[NS + "p"]
    assert _labels(prop) == {"en": "P"}
    assert _comments(prop) == {}


def test_save_property_renames_and_sets_labels_domain_range() -> None:
    from ster.core.commands import OwlSaveProperty

    t = Taxonomy()
    OwlCreateProperty(
        _P,
        NS + "hasOwner",
        labels=(("en", "has owner"),),
        domain_uri=NS + "Animal",
        range_uri=NS + "Person",
    ).apply(t)
    OwlSaveProperty(
        _P,
        NS + "hasOwner",
        NS + "hasKeeper",
        labels=(("en", "has keeper"), ("fr", "a pour gardien")),
        comments=(("en", "the keeper"),),
        domains=(NS + "Pet",),
        ranges=(NS + "Human",),
    ).apply(t)
    assert NS + "hasOwner" not in t.owl_properties  # renamed
    prop = t.owl_properties[NS + "hasKeeper"]
    assert _labels(prop) == {"en": "has keeper", "fr": "a pour gardien"}
    assert _comments(prop) == {"en": "the keeper"}
    assert prop.domains == [NS + "Pet"] and prop.ranges == [NS + "Human"]


def test_save_property_without_rename_replaces_domain_range() -> None:
    from ster.core.commands import OwlSaveProperty

    t = Taxonomy()
    OwlCreateProperty(
        _P, NS + "p", labels=(("en", "P"),), domain_uri=NS + "A", range_uri=NS + "B"
    ).apply(t)
    OwlSaveProperty(_P, NS + "p", NS + "p", labels=(("en", "P"),), domains=(), ranges=()).apply(t)
    prop = t.owl_properties[NS + "p"]
    assert prop.domains == [] and prop.ranges == []  # cleared
