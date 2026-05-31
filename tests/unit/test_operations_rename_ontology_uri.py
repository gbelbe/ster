"""Unit tests for rename_ontology_uri() and collect_ontology_entities()."""

from __future__ import annotations

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.operations import (
    collect_ontology_entities,
    count_ontology_rename_changes,
    rename_ontology_uri,
)

OLD = "https://example.org/onto"
NEW = "https://example.org/animals"
EXT = "https://external.org"


def _cls(uri: str, *parents: str) -> RDFClass:
    local = uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    return RDFClass(uri=uri, labels=[Label("en", local)], sub_class_of=list(parents))


def _ind(uri: str, *types: str) -> OWLIndividual:
    local = uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    return OWLIndividual(uri=uri, labels=[Label("en", local)], types=list(types))


def _prop(
    uri: str, domains: list[str] | None = None, ranges: list[str] | None = None
) -> OWLProperty:
    local = uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    return OWLProperty(
        uri=uri,
        labels=[Label("en", local)],
        domains=list(domains or []),
        ranges=list(ranges or []),
    )


def _tax_hash(cls_names: list[str], ont: str = OLD) -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = ont
    for name in cls_names:
        u = f"{ont}#{name}"
        t.owl_classes[u] = _cls(u)
    return t


# ── rename_ontology_uri ────────────────────────────────────────────────────────


def test_rename_updates_ontology_uri():
    t = _tax_hash(["Dog"])
    rename_ontology_uri(t, NEW, "#")
    assert t.ontology_uri == NEW


def test_rename_updates_class_uris():
    t = _tax_hash(["Dog", "Cat"])
    rename_ontology_uri(t, NEW, "#")
    assert f"{NEW}#Dog" in t.owl_classes
    assert f"{NEW}#Cat" in t.owl_classes
    assert f"{OLD}#Dog" not in t.owl_classes
    assert f"{OLD}#Cat" not in t.owl_classes


def test_rename_updates_individual_uris():
    t = _tax_hash(["Dog"])
    ind_uri = f"{OLD}#Rex"
    t.owl_individuals[ind_uri] = _ind(ind_uri, f"{OLD}#Dog")
    rename_ontology_uri(t, NEW, "#")
    assert f"{NEW}#Rex" in t.owl_individuals
    assert ind_uri not in t.owl_individuals


def test_rename_updates_property_uris():
    t = _tax_hash(["Dog"])
    prop_uri = f"{OLD}#hasMaster"
    t.owl_properties[prop_uri] = _prop(prop_uri, domains=[f"{OLD}#Dog"])
    rename_ontology_uri(t, NEW, "#")
    assert f"{NEW}#hasMaster" in t.owl_properties
    assert prop_uri not in t.owl_properties


def test_rename_preserves_external_uris():
    t = _tax_hash(["Dog"])
    ext_cls = f"{EXT}/Animal"
    t.owl_classes[ext_cls] = _cls(ext_cls)
    rename_ontology_uri(t, NEW, "#")
    assert ext_cls in t.owl_classes
    assert f"{NEW}#Animal" not in t.owl_classes


def test_rename_preserves_subclass_references_across_renamed_uris():
    t = _tax_hash(["Animal", "Dog"])
    t.owl_classes[f"{OLD}#Dog"].sub_class_of.append(f"{OLD}#Animal")
    rename_ontology_uri(t, NEW, "#")
    assert f"{NEW}#Animal" in t.owl_classes[f"{NEW}#Dog"].sub_class_of
    assert f"{OLD}#Animal" not in t.owl_classes[f"{NEW}#Dog"].sub_class_of


def test_rename_preserves_external_subclass_reference():
    t = _tax_hash(["Dog"])
    ext = f"{EXT}/Animal"
    t.owl_classes[ext] = _cls(ext)
    t.owl_classes[f"{OLD}#Dog"].sub_class_of.append(ext)
    rename_ontology_uri(t, NEW, "#")
    assert ext in t.owl_classes[f"{NEW}#Dog"].sub_class_of


def test_rename_updates_individual_types_to_new_uri():
    t = _tax_hash(["Dog"])
    ind_uri = f"{OLD}#Rex"
    t.owl_individuals[ind_uri] = _ind(ind_uri, f"{OLD}#Dog")
    rename_ontology_uri(t, NEW, "#")
    assert f"{NEW}#Dog" in t.owl_individuals[f"{NEW}#Rex"].types
    assert f"{OLD}#Dog" not in t.owl_individuals[f"{NEW}#Rex"].types


def test_rename_hash_to_slash_changes_separator():
    t = _tax_hash(["Dog"])
    rename_ontology_uri(t, OLD, "/")
    assert f"{OLD}/Dog" in t.owl_classes
    assert f"{OLD}#Dog" not in t.owl_classes


def test_rename_slash_to_hash_changes_separator():
    t = Taxonomy()
    t.ontology_uri = OLD
    u = f"{OLD}/Dog"
    t.owl_classes[u] = _cls(u)
    rename_ontology_uri(t, OLD, "#")
    assert f"{OLD}#Dog" in t.owl_classes
    assert f"{OLD}/Dog" not in t.owl_classes


def test_rename_noop_when_same_uri_and_same_sep():
    t = _tax_hash(["Dog"])
    rename_ontology_uri(t, OLD, "#")
    assert f"{OLD}#Dog" in t.owl_classes
    assert t.ontology_uri == OLD


def test_rename_does_not_touch_unrelated_class():
    t = _tax_hash(["Dog"])
    other = "https://other.org/Cat"
    t.owl_classes[other] = _cls(other)
    rename_ontology_uri(t, NEW, "#")
    assert other in t.owl_classes


# ── collect_ontology_entities ─────────────────────────────────────────────────


def test_collect_finds_local_class_uris():
    t = _tax_hash(["Dog", "Cat"])
    found = collect_ontology_entities(t)
    assert f"{OLD}#Dog" in found
    assert f"{OLD}#Cat" in found


def test_collect_excludes_external_uris():
    t = _tax_hash(["Dog"])
    ext = f"{EXT}/Animal"
    t.owl_classes[ext] = _cls(ext)
    found = collect_ontology_entities(t)
    assert ext not in found


def test_collect_includes_individuals_and_properties():
    t = _tax_hash(["Dog"])
    ind_uri = f"{OLD}#Rex"
    prop_uri = f"{OLD}#hasMaster"
    t.owl_individuals[ind_uri] = _ind(ind_uri)
    t.owl_properties[prop_uri] = _prop(prop_uri)
    found = collect_ontology_entities(t)
    assert ind_uri in found
    assert prop_uri in found


def test_collect_empty_when_no_ontology_uri():
    t = Taxonomy()
    t.owl_classes["https://example.org/Dog"] = _cls("https://example.org/Dog")
    assert collect_ontology_entities(t) == []


# ── count_ontology_rename_changes ─────────────────────────────────────────────


def test_count_changes_slash_to_hash():
    t = Taxonomy()
    t.ontology_uri = OLD
    u = f"{OLD}/Dog"
    t.owl_classes[u] = _cls(u)
    old_base, new_base, count = count_ontology_rename_changes(t, OLD, "#")
    assert count == 1
    assert old_base == f"{OLD}/"
    assert new_base == f"{OLD}#"


def test_count_changes_hash_to_slash():
    t = _tax_hash(["Dog", "Cat"])
    old_base, new_base, count = count_ontology_rename_changes(t, OLD, "/")
    assert count == 2
    assert old_base == f"{OLD}#"
    assert new_base == f"{OLD}/"


def test_count_changes_no_change_returns_zero():
    t = _tax_hash(["Dog"])
    _, _, count = count_ontology_rename_changes(t, OLD, "#")
    assert count == 0


def test_count_changes_uri_change():
    t = _tax_hash(["Dog", "Cat"])
    _, _, count = count_ontology_rename_changes(t, NEW, "#")
    assert count == 2


def test_count_changes_includes_all_entity_types():
    t = _tax_hash(["Dog"])
    ind_uri = f"{OLD}#Rex"
    prop_uri = f"{OLD}#hasMaster"
    t.owl_individuals[ind_uri] = _ind(ind_uri)
    t.owl_properties[prop_uri] = _prop(prop_uri)
    _, _, count = count_ontology_rename_changes(t, NEW, "#")
    assert count == 3


def test_count_changes_external_excluded():
    t = _tax_hash(["Dog"])
    ext = f"{EXT}/Animal"
    t.owl_classes[ext] = _cls(ext)
    _, _, count = count_ontology_rename_changes(t, NEW, "#")
    assert count == 1


def test_count_changes_returns_correct_bases():
    t = _tax_hash(["Dog"])
    old_base, new_base, _ = count_ontology_rename_changes(t, NEW, "/")
    assert old_base == f"{OLD}#"
    assert new_base == f"{NEW}/"
