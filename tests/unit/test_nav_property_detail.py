"""Tests for ster/nav/logic/_property_.py's build_property_detail /
build_properties_section_fields."""

from __future__ import annotations

from ster.handles import assign_handles
from ster.model import Definition, OWLProperty, Taxonomy
from ster.nav.logic import build_properties_section_fields, build_property_detail

BASE_P = "https://example.org/prop/"


def _property_taxonomy():
    t = Taxonomy()
    t.owl_properties[BASE_P + "hasFriend"] = OWLProperty(
        uri=BASE_P + "hasFriend",
        prop_type="ObjectProperty",
        comments=[Definition(lang="en", value="Friendship relation.")],
    )
    assign_handles(t)
    return t


def test_build_property_detail_missing_uri_returns_empty():
    t = _property_taxonomy()
    assert build_property_detail(t, BASE_P + "ghost", "en") == []


def test_build_property_detail_includes_comment_field():
    t = _property_taxonomy()
    fields = build_property_detail(t, BASE_P + "hasFriend", "en")
    comment_fields = [f for f in fields if f.meta.get("type") == "prop_comment"]
    assert any("Friendship relation." in (f.value or "") for f in comment_fields)


def test_properties_section_shows_annotation_property_stat():
    t = Taxonomy()
    t.owl_properties[BASE_P + "hasFriend"] = OWLProperty(
        uri=BASE_P + "hasFriend", prop_type="ObjectProperty"
    )
    t.owl_properties[BASE_P + "seeAlso"] = OWLProperty(
        uri=BASE_P + "seeAlso", prop_type="AnnotationProperty"
    )
    assign_handles(t)
    fields = build_properties_section_fields(t, "en")
    ann_stat = next(f for f in fields if f.key == "props:ann")
    assert ann_stat.value == "1"
