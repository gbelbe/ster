"""Unit tests for _class_quality_fields in ster/nav/logic.py."""

from __future__ import annotations

from ster.model import Definition, Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.nav.logic import _class_quality_fields

BASE = "https://example.org/onto/"


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _cls(
    name: str, parents: list[str] | None = None, *, lbl: bool = True, cmt: bool = True
) -> RDFClass:
    return RDFClass(
        uri=BASE + name,
        labels=[Label(lang="en", value=name)] if lbl else [],
        comments=[Definition(lang="en", value=f"About {name}.")] if cmt else [],
        sub_class_of=[BASE + p for p in (parents or [])],
    )


def _ind(
    name: str,
    types: list[str] | None = None,
    *,
    lbl: bool = True,
    prop_values: list[tuple[str, str]] | None = None,
) -> OWLIndividual:
    ind = OWLIndividual(
        uri=BASE + name,
        labels=[Label(lang="en", value=name)] if lbl else [],
        types=[BASE + t for t in (types or [])],
    )
    if prop_values:
        ind.property_values = prop_values
    return ind


def _prop(
    name: str,
    domains: list[str] | None = None,
    ranges: list[str] | None = None,
) -> OWLProperty:
    return OWLProperty(
        uri=BASE + name,
        labels=[Label(lang="en", value=name)],
        domains=[BASE + d for d in (domains or [])],
        ranges=[BASE + r for r in (ranges or [])],
    )


def _taxonomy(
    classes: list[RDFClass],
    individuals: list[OWLIndividual] | None = None,
    properties: list[OWLProperty] | None = None,
) -> Taxonomy:
    t = Taxonomy()
    for cls in classes:
        t.owl_classes[cls.uri] = cls
    for ind in individuals or []:
        t.owl_individuals[ind.uri] = ind
    for prop in properties or []:
        t.owl_properties[prop.uri] = prop
    return t


def _values(fields) -> dict[str, str]:
    return {f.key: f.value for f in fields}


# ── missing URI ───────────────────────────────────────────────────────────────


def test_missing_class_uri_returns_empty():
    t = Taxonomy()
    assert _class_quality_fields(t, BASE + "Unknown", "en") == []


# ── label coverage ────────────────────────────────────────────────────────────


def test_single_class_full_label_coverage():
    t = _taxonomy([_cls("Animal")])
    v = _values(_class_quality_fields(t, BASE + "Animal", "en"))
    assert "100%" in v["cls:q:lbl"]


def test_single_class_no_label_zero_coverage():
    t = _taxonomy([_cls("Animal", lbl=False)])
    v = _values(_class_quality_fields(t, BASE + "Animal", "en"))
    assert "0%" in v["cls:q:lbl"]


def test_subtree_partial_label_coverage():
    # Animal (labeled) + Dog (labeled) + Cat (unlabeled) → 2/3 = 66%
    t = _taxonomy([_cls("Animal"), _cls("Dog", ["Animal"]), _cls("Cat", ["Animal"], lbl=False)])
    v = _values(_class_quality_fields(t, BASE + "Animal", "en"))
    assert "66%" in v["cls:q:lbl"]


def test_label_coverage_only_counts_subtree_not_siblings():
    # Vehicle is not under Animal → should not affect Animal's label coverage
    t = _taxonomy([_cls("Animal"), _cls("Dog", ["Animal"]), _cls("Vehicle", lbl=False)])
    v = _values(_class_quality_fields(t, BASE + "Animal", "en"))
    assert "100%" in v["cls:q:lbl"]


# ── comment coverage ──────────────────────────────────────────────────────────


def test_comment_coverage_field_present():
    t = _taxonomy([_cls("Animal")])
    v = _values(_class_quality_fields(t, BASE + "Animal", "en"))
    assert "cls:q:cmt" in v


def test_comment_coverage_zero_when_missing():
    t = _taxonomy([_cls("Animal", cmt=False)])
    v = _values(_class_quality_fields(t, BASE + "Animal", "en"))
    assert "0%" in v["cls:q:cmt"]


def test_subtree_partial_comment_coverage():
    # Animal (comment) + Dog (no comment) → 1/2 = 50%
    t = _taxonomy([_cls("Animal"), _cls("Dog", ["Animal"], cmt=False)])
    v = _values(_class_quality_fields(t, BASE + "Animal", "en"))
    assert "50%" in v["cls:q:cmt"]


# ── class count ───────────────────────────────────────────────────────────────


def test_n_classes_shown_when_subtree_has_multiple():
    t = _taxonomy([_cls("Animal"), _cls("Dog", ["Animal"])])
    v = _values(_class_quality_fields(t, BASE + "Animal", "en"))
    assert "cls:q:n_classes" in v
    assert "2" in v["cls:q:n_classes"]


def test_n_classes_not_shown_for_leaf():
    t = _taxonomy([_cls("Animal")])
    keys = [f.key for f in _class_quality_fields(t, BASE + "Animal", "en")]
    assert "cls:q:n_classes" not in keys


# ── instance count ────────────────────────────────────────────────────────────


def test_instance_count_zero():
    t = _taxonomy([_cls("Animal")])
    v = _values(_class_quality_fields(t, BASE + "Animal", "en"))
    assert "cls:q:inst:subtree" in v
    assert "0" in v["cls:q:inst:subtree"]


def test_direct_instances_of_class_counted():
    t = _taxonomy([_cls("Animal")], individuals=[_ind("Rex", ["Animal"]), _ind("Fido", ["Animal"])])
    v = _values(_class_quality_fields(t, BASE + "Animal", "en"))
    assert "2" in v["cls:q:inst:subtree"]


def test_instances_of_subclass_counted_in_parent_subtree():
    # Rex typed as Dog (subclass of Animal) → counts under Animal's subtree
    t = _taxonomy(
        [_cls("Animal"), _cls("Dog", ["Animal"])],
        individuals=[_ind("Rex", ["Dog"])],
    )
    v = _values(_class_quality_fields(t, BASE + "Animal", "en"))
    assert "1" in v["cls:q:inst:subtree"]


def test_instances_outside_subtree_excluded():
    # Whiskers is a Cat, not under Animal
    t = _taxonomy(
        [_cls("Animal"), _cls("Cat")],
        individuals=[_ind("Whiskers", ["Cat"])],
    )
    v = _values(_class_quality_fields(t, BASE + "Animal", "en"))
    assert "0" in v["cls:q:inst:subtree"]


# ── property fill ─────────────────────────────────────────────────────────────


def test_property_fill_field_present_when_domain_in_subtree():
    prop = _prop("hasOwner", domains=["Animal"])
    t = _taxonomy([_cls("Animal")], individuals=[_ind("Rex", ["Animal"])], properties=[prop])
    keys = [f.key for f in _class_quality_fields(t, BASE + "Animal", "en")]
    assert f"cls:q:fill:{BASE}hasOwner" in keys


def test_property_fill_not_shown_when_domain_outside_subtree():
    prop = _prop("hasOwner", domains=["Cat"])
    t = _taxonomy([_cls("Animal"), _cls("Cat")], properties=[prop])
    keys = [f.key for f in _class_quality_fields(t, BASE + "Animal", "en")]
    assert f"cls:q:fill:{BASE}hasOwner" not in keys


def test_property_fill_not_shown_when_no_domain_individuals():
    # Property has domain=Animal but no individuals are of that type
    prop = _prop("hasOwner", domains=["Animal"])
    t = _taxonomy([_cls("Animal")], properties=[prop])
    keys = [f.key for f in _class_quality_fields(t, BASE + "Animal", "en")]
    assert f"cls:q:fill:{BASE}hasOwner" not in keys


def test_no_properties_means_no_fill_fields():
    t = _taxonomy([_cls("Animal")])
    fill_fields = [f for f in _class_quality_fields(t, BASE + "Animal", "en") if "fill" in f.key]
    assert fill_fields == []


def test_property_fill_zero_percent_when_no_assertions():
    prop = _prop("hasOwner", domains=["Animal"])
    t = _taxonomy([_cls("Animal")], individuals=[_ind("Rex", ["Animal"])], properties=[prop])
    v = _values(_class_quality_fields(t, BASE + "Animal", "en"))
    assert "0%" in v[f"cls:q:fill:{BASE}hasOwner"]


def test_property_fill_100_percent_when_all_filled():
    prop = _prop("hasOwner", domains=["Animal"], ranges=["Person"])
    alice = _ind("Alice", ["Person"])
    rex = _ind("Rex", ["Animal"], prop_values=[(BASE + "hasOwner", BASE + "Alice")])
    t = _taxonomy(
        [_cls("Animal"), _cls("Person")],
        individuals=[rex, alice],
        properties=[prop],
    )
    v = _values(_class_quality_fields(t, BASE + "Animal", "en"))
    assert "100%" in v[f"cls:q:fill:{BASE}hasOwner"]


def test_property_fill_shown_via_subclass_domain():
    # Property domain is Dog (subclass of Animal) — should appear on Animal's quality panel
    prop = _prop("hasOwner", domains=["Dog"])
    t = _taxonomy(
        [_cls("Animal"), _cls("Dog", ["Animal"])],
        individuals=[_ind("Rex", ["Dog"])],
        properties=[prop],
    )
    keys = [f.key for f in _class_quality_fields(t, BASE + "Animal", "en")]
    assert f"cls:q:fill:{BASE}hasOwner" in keys


# ── structure / separators ────────────────────────────────────────────────────


def test_quality_separator_present():
    t = _taxonomy([_cls("Animal")])
    sep_labels = [
        f.display
        for f in _class_quality_fields(t, BASE + "Animal", "en")
        if f.meta.get("type") == "separator"
    ]
    assert any("Quality" in lbl for lbl in sep_labels)


def test_fill_separator_present_when_fill_fields_exist():
    prop = _prop("hasOwner", domains=["Animal"])
    t = _taxonomy([_cls("Animal")], individuals=[_ind("Rex", ["Animal"])], properties=[prop])
    sep_labels = [
        f.display
        for f in _class_quality_fields(t, BASE + "Animal", "en")
        if f.meta.get("type") == "separator"
    ]
    assert any("Fill" in lbl or "Property" in lbl for lbl in sep_labels)


def test_fill_separator_absent_when_no_fill_fields():
    t = _taxonomy([_cls("Animal")])
    sep_labels = [
        f.display
        for f in _class_quality_fields(t, BASE + "Animal", "en")
        if f.meta.get("type") == "separator"
    ]
    assert not any("Fill" in lbl or "Property" in lbl for lbl in sep_labels)
