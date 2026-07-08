"""Unit tests for the composite OwlCreateObjectProperty command."""

from __future__ import annotations

from pathlib import Path

from ster.core.commands import OwlCreateObjectProperty
from ster.model import OWLProperty, Taxonomy

_P = Path("o.ttl")
NS = "https://ex.org/onto#"


def _labels(prop: OWLProperty) -> dict[str, str]:
    return {lbl.lang: lbl.value for lbl in prop.labels}


def _comments(prop: OWLProperty) -> dict[str, str]:
    return {c.lang: c.value for c in prop.comments}


def test_create_object_property_sets_type_labels_comments_domain_range() -> None:
    t = Taxonomy()
    cmd = OwlCreateObjectProperty(
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


def test_create_object_property_without_domain_range_or_extra_langs() -> None:
    t = Taxonomy()
    OwlCreateObjectProperty(_P, NS + "relatedTo", labels=(("en", "related to"),)).apply(t)
    prop = t.owl_properties[NS + "relatedTo"]
    assert prop.prop_type == "ObjectProperty"
    assert _labels(prop) == {"en": "related to"}
    assert prop.domains == [] and prop.ranges == []


def test_create_object_property_skips_blank_label_and_comment_values() -> None:
    t = Taxonomy()
    OwlCreateObjectProperty(
        _P,
        NS + "p",
        labels=(("en", "P"), ("fr", "")),  # blank fr → no fr label
        comments=(("en", ""),),  # blank → no comment
    ).apply(t)
    prop = t.owl_properties[NS + "p"]
    assert _labels(prop) == {"en": "P"}
    assert _comments(prop) == {}
