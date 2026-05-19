"""Unit tests for build_properties_section_fields."""

from __future__ import annotations

from ster.model import Label, OWLProperty, Taxonomy
from ster.nav.logic import build_properties_section_fields

BASE = "https://example.org/onto/"


def _tax(*props: OWLProperty) -> Taxonomy:
    t = Taxonomy()
    for p in props:
        t.owl_properties[p.uri] = p
    return t


def _prop(
    name: str,
    *,
    prop_type: str = "ObjectProperty",
    labels: list | None = None,
    domains: list | None = None,
    ranges: list | None = None,
) -> OWLProperty:
    return OWLProperty(
        uri=BASE + name,
        prop_type=prop_type,
        labels=labels if labels is not None else [Label("en", name)],
        domains=domains or [],
        ranges=ranges or [],
    )


def _nav_fields(fields):
    return [f for f in fields if f.meta.get("type") == "navigate_property"]


def _stat_values(fields):
    return [f.value for f in fields if f.meta.get("type") == "stat"]


# ── Empty taxonomy ─────────────────────────────────────────────────────────────


def test_empty_taxonomy_returns_zero_count():
    fields = build_properties_section_fields(Taxonomy(), lang="en")
    stats = _stat_values(fields)
    assert "0" in stats


def test_empty_taxonomy_has_no_nav_items():
    fields = build_properties_section_fields(Taxonomy(), lang="en")
    assert _nav_fields(fields) == []


# ── Count stats ────────────────────────────────────────────────────────────────


def test_total_count_stat():
    fields = build_properties_section_fields(_tax(_prop("a"), _prop("b"), _prop("c")), lang="en")
    assert "3" in _stat_values(fields)


def test_data_property_count():
    t = _tax(
        _prop("dp", prop_type="DatatypeProperty"),
        _prop("op", prop_type="ObjectProperty"),
    )
    fields = build_properties_section_fields(t, lang="en")
    data_fields = [
        f for f in fields if f.meta.get("type") == "stat" and "data" in f.display.lower()
    ]
    assert data_fields, "No data property stat field"
    assert "1" in data_fields[0].value


def test_object_property_count():
    t = _tax(
        _prop("dp", prop_type="DatatypeProperty"),
        _prop("op", prop_type="ObjectProperty"),
    )
    fields = build_properties_section_fields(t, lang="en")
    obj_fields = [
        f for f in fields if f.meta.get("type") == "stat" and "object" in f.display.lower()
    ]
    assert obj_fields, "No object property stat field"
    assert "1" in obj_fields[0].value


# ── Coverage stats ─────────────────────────────────────────────────────────────


def test_label_coverage_all_labeled():
    t = _tax(_prop("a"), _prop("b"))
    fields = build_properties_section_fields(t, lang="en")
    assert any("100%" in v for v in _stat_values(fields))


def test_label_coverage_partial():
    t = _tax(_prop("a"), _prop("b", labels=[]))
    fields = build_properties_section_fields(t, lang="en")
    assert any("50%" in v for v in _stat_values(fields))


def test_label_coverage_none():
    t = _tax(_prop("a", labels=[]), _prop("b", labels=[]))
    fields = build_properties_section_fields(t, lang="en")
    assert any("0%" in v for v in _stat_values(fields))


def test_domain_coverage_partial():
    t = _tax(_prop("a", domains=[BASE + "C"]), _prop("b"))
    fields = build_properties_section_fields(t, lang="en")
    assert any("50%" in v for v in _stat_values(fields))


def test_range_coverage_partial():
    t = _tax(_prop("a", ranges=[BASE + "C"]), _prop("b"))
    fields = build_properties_section_fields(t, lang="en")
    assert any("50%" in v for v in _stat_values(fields))


def test_domain_coverage_full():
    t = _tax(_prop("a", domains=[BASE + "C"]), _prop("b", domains=[BASE + "D"]))
    fields = build_properties_section_fields(t, lang="en")
    assert any("100%" in v for v in _stat_values(fields))


# ── Navigate items ─────────────────────────────────────────────────────────────


def test_property_list_items_present():
    t = _tax(_prop("hasAge"), _prop("hasName"))
    fields = build_properties_section_fields(t, lang="en")
    nav = _nav_fields(fields)
    uris = {f.meta["uri"] for f in nav}
    assert BASE + "hasAge" in uris
    assert BASE + "hasName" in uris


def test_property_list_sorted_by_label():
    t = _tax(_prop("zebra"), _prop("apple"), _prop("mango"))
    fields = build_properties_section_fields(t, lang="en")
    nav = _nav_fields(fields)
    labels = [f.display for f in nav]
    assert labels == sorted(labels)


def test_property_item_meta_navigate():
    t = _tax(_prop("hasAge"))
    fields = build_properties_section_fields(t, lang="en")
    nav = _nav_fields(fields)
    assert len(nav) == 1
    assert nav[0].meta["type"] == "navigate_property"
    assert nav[0].meta["uri"] == BASE + "hasAge"


def test_property_item_not_editable():
    t = _tax(_prop("hasAge"))
    fields = build_properties_section_fields(t, lang="en")
    for f in _nav_fields(fields):
        assert not f.editable


def test_property_item_display_uses_label():
    t = _tax(_prop("hasAge"))
    fields = build_properties_section_fields(t, lang="en")
    nav = _nav_fields(fields)
    assert nav[0].display == "hasAge"


def test_property_item_display_falls_back_to_local_name():
    p = OWLProperty(uri=BASE + "hasAge", labels=[])
    fields = build_properties_section_fields(_tax(p), lang="en")
    nav = _nav_fields(fields)
    assert nav[0].display == "hasAge"
