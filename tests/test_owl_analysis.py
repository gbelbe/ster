"""Tests for owl_analysis — flat stats (backward compat) + full OntologyAnalysis."""

from __future__ import annotations

from ster.model import Concept, Definition, Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.owl_analysis import (
    compute_ontology_analysis,
    compute_owl_analysis,
)

BASE = "https://example.org/onto/"


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _cls(
    name: str, parents: list[str] | None = None, *, lbl: bool = True, cmt: bool = True
) -> RDFClass:
    return RDFClass(
        uri=BASE + name,
        labels=[Label(lang="en", value=name)] if lbl else [],
        comments=[Definition(lang="en", value=f"About {name}.")] if cmt else [],
        sub_class_of=[BASE + p for p in (parents or [])],
    )


def _ind(name: str, types: list[str] | None = None, *, lbl: bool = True) -> OWLIndividual:
    return OWLIndividual(
        uri=BASE + name,
        labels=[Label(lang="en", value=name)] if lbl else [],
        types=[BASE + t for t in (types or [])],
    )


def _prop(
    name: str,
    domains: list[str] | None = None,
    ranges: list[str] | None = None,
    *,
    lbl: bool = True,
) -> OWLProperty:
    return OWLProperty(
        uri=BASE + name,
        labels=[Label(lang="en", value=name)] if lbl else [],
        domains=[BASE + d for d in (domains or [])],
        ranges=[BASE + r for r in (ranges or [])],
    )


def _make_taxonomy(
    class_defs: list[tuple[str, list[str], bool, bool]],
    promoted_uris: list[str] | None = None,
) -> Taxonomy:
    """Backward-compat helper used by existing flat-stats tests."""
    t = Taxonomy()
    for name, parents, has_label, has_comment in class_defs:
        t.owl_classes[BASE + name] = _cls(name, parents, lbl=has_label, cmt=has_comment)
    for uri in promoted_uris or []:
        t.concepts[uri] = Concept(uri=uri)
    return t


# ═══════════════════════════════════════════════════════════════════════════════
# Backward-compat flat stats (compute_owl_analysis)
# ═══════════════════════════════════════════════════════════════════════════════


def test_empty_taxonomy():
    t = Taxonomy()
    stats = compute_owl_analysis(t)
    assert stats.total_classes == 0
    assert stats.promoted == 0
    assert stats.missing_label == 0


def test_total_classes():
    t = _make_taxonomy(
        [
            ("Animal", [], True, True),
            ("Dog", ["Animal"], True, True),
            ("Cat", ["Animal"], True, False),
        ]
    )
    assert compute_owl_analysis(t).total_classes == 3


def test_root_classes_single():
    t = _make_taxonomy([("Animal", [], True, True), ("Dog", ["Animal"], True, True)])
    assert compute_owl_analysis(t).root_classes == 1


def test_root_classes_multiple():
    t = _make_taxonomy(
        [("Animal", [], True, True), ("Vehicle", [], True, True), ("Dog", ["Animal"], True, True)]
    )
    assert compute_owl_analysis(t).root_classes == 2


def test_max_depth_flat():
    t = _make_taxonomy([("A", [], True, True), ("B", [], True, True)])
    assert compute_owl_analysis(t).max_depth == 0


def test_max_depth_hierarchy():
    t = _make_taxonomy(
        [
            ("Animal", [], True, True),
            ("Mammal", ["Animal"], True, True),
            ("Dog", ["Mammal"], True, True),
        ]
    )
    assert compute_owl_analysis(t).max_depth == 2


def test_promoted_count():
    t = _make_taxonomy(
        [("Animal", [], True, True), ("Dog", ["Animal"], True, True)],
        promoted_uris=[BASE + "Dog"],
    )
    stats = compute_owl_analysis(t)
    assert stats.promoted == 1
    assert stats.pure_classes == 1


def test_pure_classes_all_pure():
    t = _make_taxonomy([("A", [], True, True), ("B", [], True, True)])
    stats = compute_owl_analysis(t)
    assert stats.pure_classes == 2
    assert stats.promoted == 0


def test_missing_label():
    t = _make_taxonomy([("Animal", [], True, True), ("Ghost", [], False, False)])
    stats = compute_owl_analysis(t)
    assert stats.missing_label == 1
    assert stats.missing_comment == 1


def test_all_labeled():
    t = _make_taxonomy([("A", [], True, True), ("B", [], True, True)])
    assert compute_owl_analysis(t).missing_label == 0


# ═══════════════════════════════════════════════════════════════════════════════
# compute_ontology_analysis — OntologyStats
# ═══════════════════════════════════════════════════════════════════════════════


def test_empty_ontology_analysis():
    a = compute_ontology_analysis(Taxonomy())
    assert a.stats.total_classes == 0
    assert a.stats.total_individuals == 0
    assert a.stats.total_properties == 0
    assert a.issues == []
    assert a.level_summaries == []
    assert a.property_fill_global == {}


def test_class_label_pct_all_labeled():
    t = Taxonomy()
    for name in ("A", "B", "C"):
        t.owl_classes[BASE + name] = _cls(name)
    a = compute_ontology_analysis(t)
    assert a.stats.label_pct == 100


def test_class_label_pct_partial():
    t = Taxonomy()
    t.owl_classes[BASE + "A"] = _cls("A", lbl=True)
    t.owl_classes[BASE + "B"] = _cls("B", lbl=True)
    t.owl_classes[BASE + "C"] = _cls("C", lbl=False)
    a = compute_ontology_analysis(t)
    assert a.stats.label_pct == 66


def test_class_comment_pct_partial():
    t = Taxonomy()
    t.owl_classes[BASE + "A"] = _cls("A", cmt=True)
    t.owl_classes[BASE + "B"] = _cls("B", cmt=False)
    t.owl_classes[BASE + "C"] = _cls("C", cmt=False)
    a = compute_ontology_analysis(t)
    assert a.stats.comment_pct == 33


# ═══════════════════════════════════════════════════════════════════════════════
# Level summaries
# ═══════════════════════════════════════════════════════════════════════════════


def test_level_summaries_flat():
    t = Taxonomy()
    for name in ("A", "B", "C"):
        t.owl_classes[BASE + name] = _cls(name)
    a = compute_ontology_analysis(t)
    assert len(a.level_summaries) == 1
    ls = a.level_summaries[0]
    assert ls.depth == 0
    assert ls.n_classes == 3
    assert ls.label_pct == 100


def test_level_summaries_hierarchy():
    t = Taxonomy()
    t.owl_classes[BASE + "Animal"] = _cls("Animal")
    t.owl_classes[BASE + "Mammal"] = _cls("Mammal", ["Animal"])
    t.owl_classes[BASE + "Dog"] = _cls("Dog", ["Mammal"])
    a = compute_ontology_analysis(t)
    depths = [ls.depth for ls in a.level_summaries]
    assert depths == [0, 1, 2]
    assert a.level_summaries[0].n_classes == 1  # Animal
    assert a.level_summaries[1].n_classes == 1  # Mammal
    assert a.level_summaries[2].n_classes == 1  # Dog


def test_level_summary_label_pct_per_depth():
    t = Taxonomy()
    t.owl_classes[BASE + "Animal"] = _cls("Animal", lbl=True)
    t.owl_classes[BASE + "Dog"] = _cls("Dog", ["Animal"], lbl=False)
    a = compute_ontology_analysis(t)
    assert a.level_summaries[0].label_pct == 100  # depth 0 — Animal has label
    assert a.level_summaries[1].label_pct == 0  # depth 1 — Dog has no label


# ═══════════════════════════════════════════════════════════════════════════════
# Individual stats
# ═══════════════════════════════════════════════════════════════════════════════


def test_individual_label_pct_full():
    t = Taxonomy()
    t.owl_classes[BASE + "Dog"] = _cls("Dog")
    t.owl_individuals[BASE + "Rex"] = _ind("Rex", ["Dog"], lbl=True)
    t.owl_individuals[BASE + "Buddy"] = _ind("Buddy", ["Dog"], lbl=True)
    a = compute_ontology_analysis(t)
    assert a.stats.total_individuals == 2
    assert a.stats.individual_label_pct == 100


def test_individual_label_pct_partial():
    t = Taxonomy()
    t.owl_classes[BASE + "Dog"] = _cls("Dog")
    t.owl_individuals[BASE + "Rex"] = _ind("Rex", ["Dog"], lbl=True)
    t.owl_individuals[BASE + "Ghost"] = _ind("Ghost", ["Dog"], lbl=False)
    a = compute_ontology_analysis(t)
    assert a.stats.individual_label_pct == 50


def test_individual_typed_pct_full():
    t = Taxonomy()
    t.owl_classes[BASE + "Dog"] = _cls("Dog")
    t.owl_individuals[BASE + "Rex"] = _ind("Rex", ["Dog"])
    a = compute_ontology_analysis(t)
    assert a.stats.individual_typed_pct == 100


def test_individual_typed_pct_partial():
    t = Taxonomy()
    t.owl_classes[BASE + "Dog"] = _cls("Dog")
    t.owl_individuals[BASE + "Rex"] = _ind("Rex", ["Dog"])  # typed
    t.owl_individuals[BASE + "Unknown"] = _ind("Unknown", ["UnknownClass"])  # untyped
    a = compute_ontology_analysis(t)
    assert a.stats.individual_typed_pct == 50


def test_level_summary_aggregates_individuals():
    t = Taxonomy()
    t.owl_classes[BASE + "Animal"] = _cls("Animal")
    t.owl_classes[BASE + "Dog"] = _cls("Dog", ["Animal"])
    t.owl_individuals[BASE + "Rex"] = _ind("Rex", ["Dog"])
    a = compute_ontology_analysis(t)
    # Rex is a Dog (depth 1) — depth-0 (Animal) has 0 direct individuals
    assert a.level_summaries[0].n_individuals == 0  # Animal — no direct instances
    assert a.level_summaries[1].n_individuals == 1  # Dog — Rex


# ═══════════════════════════════════════════════════════════════════════════════
# Property fill rate
# ═══════════════════════════════════════════════════════════════════════════════


def _make_fill_taxonomy() -> tuple[Taxonomy, str, str, str]:
    """Dog –[hasFriend]→ Dog, with 2 dogs and 1 friendship asserted."""
    t = Taxonomy()
    t.owl_classes[BASE + "Dog"] = _cls("Dog")
    rex = OWLIndividual(
        uri=BASE + "Rex",
        labels=[Label(lang="en", value="Rex")],
        types=[BASE + "Dog"],
        property_values=[(BASE + "hasFriend", BASE + "Buddy")],
    )
    buddy = OWLIndividual(
        uri=BASE + "Buddy",
        labels=[Label(lang="en", value="Buddy")],
        types=[BASE + "Dog"],
    )
    t.owl_individuals[BASE + "Rex"] = rex
    t.owl_individuals[BASE + "Buddy"] = buddy
    p = OWLProperty(
        uri=BASE + "hasFriend",
        labels=[Label(lang="en", value="hasFriend")],
        domains=[BASE + "Dog"],
        ranges=[BASE + "Dog"],
    )
    t.owl_properties[BASE + "hasFriend"] = p
    return t, BASE + "Rex", BASE + "Buddy", BASE + "hasFriend"


def test_property_fill_rate_full():
    t, rex, buddy, p_uri = _make_fill_taxonomy()
    # Add the reverse friendship so both are filled
    t.owl_individuals[buddy].property_values.append((p_uri, rex))
    a = compute_ontology_analysis(t)
    assert a.property_fill_global[p_uri] == 1.0


def test_property_fill_rate_partial():
    t, _rex, _buddy, p_uri = _make_fill_taxonomy()
    # Only Rex has the property → 1/2 = 0.5
    a = compute_ontology_analysis(t)
    assert a.property_fill_global[p_uri] == 0.5


def test_property_fill_no_domain_individuals():
    t = Taxonomy()
    t.owl_classes[BASE + "Dog"] = _cls("Dog")
    # Property has domain Dog but there are no Dog individuals
    t.owl_properties[BASE + "hasFriend"] = _prop("hasFriend", ["Dog"], ["Dog"])
    a = compute_ontology_analysis(t)
    # No domain individuals → not in fill_global, no low_fill issue
    assert BASE + "hasFriend" not in a.property_fill_global
    fill_issues = [i for i in a.issues if i.issue_key == "property_low_fill"]
    assert fill_issues == []


def test_property_fill_no_domain_defined():
    t = Taxonomy()
    t.owl_classes[BASE + "Dog"] = _cls("Dog")
    t.owl_individuals[BASE + "Rex"] = _ind("Rex", ["Dog"])
    # Property has no domain — fill not computed
    t.owl_properties[BASE + "hasFriend"] = _prop("hasFriend", domains=None)
    a = compute_ontology_analysis(t)
    assert BASE + "hasFriend" not in a.property_fill_global


def test_property_fill_subclass_membership():
    """Individual of a subclass counts as member of the domain superclass."""
    t = Taxonomy()
    t.owl_classes[BASE + "Animal"] = _cls("Animal")
    t.owl_classes[BASE + "Dog"] = _cls("Dog", ["Animal"])
    rex = OWLIndividual(
        uri=BASE + "Rex",
        labels=[Label(lang="en", value="Rex")],
        types=[BASE + "Dog"],  # Dog is a subclass of Animal
        property_values=[(BASE + "hasPet", BASE + "Rex")],
    )
    t.owl_individuals[BASE + "Rex"] = rex
    # Property domain is Animal — Rex (a Dog) should count
    t.owl_properties[BASE + "hasPet"] = _prop("hasPet", ["Animal"], ["Animal"])
    a = compute_ontology_analysis(t)
    # Rex has a hasPet assertion pointing to itself (also an Animal via Dog)
    assert a.property_fill_global[BASE + "hasPet"] == 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# Issue detectors
# ═══════════════════════════════════════════════════════════════════════════════


def test_issue_class_missing_label():
    t = Taxonomy()
    t.owl_classes[BASE + "Ghost"] = _cls("Ghost", lbl=False)
    a = compute_ontology_analysis(t)
    keys = [i.issue_key for i in a.issues]
    assert "class_missing_label" in keys
    issue = next(i for i in a.issues if i.issue_key == "class_missing_label")
    assert issue.severity == "error"
    assert issue.entity_uri == BASE + "Ghost"


def test_issue_class_missing_comment():
    t = Taxonomy()
    t.owl_classes[BASE + "A"] = _cls("A", cmt=False)
    a = compute_ontology_analysis(t)
    keys = [i.issue_key for i in a.issues]
    assert "class_missing_comment" in keys
    issue = next(i for i in a.issues if i.issue_key == "class_missing_comment")
    assert issue.severity == "info"


def test_no_comment_issue_when_commented():
    t = Taxonomy()
    t.owl_classes[BASE + "A"] = _cls("A", cmt=True)
    a = compute_ontology_analysis(t)
    assert not any(i.issue_key == "class_missing_comment" for i in a.issues)


def test_issue_individual_missing_label():
    t = Taxonomy()
    t.owl_classes[BASE + "Dog"] = _cls("Dog")
    t.owl_individuals[BASE + "Rex"] = _ind("Rex", ["Dog"], lbl=False)
    a = compute_ontology_analysis(t)
    keys = [i.issue_key for i in a.issues]
    assert "individual_missing_label" in keys
    issue = next(i for i in a.issues if i.issue_key == "individual_missing_label")
    assert issue.severity == "warning"
    assert issue.entity_uri == BASE + "Rex"


def test_issue_individual_no_type():
    t = Taxonomy()
    t.owl_individuals[BASE + "Mystery"] = _ind("Mystery", types=[])
    a = compute_ontology_analysis(t)
    keys = [i.issue_key for i in a.issues]
    assert "individual_no_type" in keys
    issue = next(i for i in a.issues if i.issue_key == "individual_no_type")
    assert issue.severity == "warning"


def test_no_no_type_issue_when_typed():
    t = Taxonomy()
    t.owl_classes[BASE + "Dog"] = _cls("Dog")
    t.owl_individuals[BASE + "Rex"] = _ind("Rex", ["Dog"])
    a = compute_ontology_analysis(t)
    assert not any(i.issue_key == "individual_no_type" for i in a.issues)


def test_issue_property_missing_label():
    t = Taxonomy()
    t.owl_properties[BASE + "hasFriend"] = _prop("hasFriend", lbl=False)
    a = compute_ontology_analysis(t)
    keys = [i.issue_key for i in a.issues]
    assert "property_missing_label" in keys
    issue = next(i for i in a.issues if i.issue_key == "property_missing_label")
    assert issue.severity == "warning"


def test_issue_property_missing_domain():
    t = Taxonomy()
    t.owl_properties[BASE + "p"] = _prop("p", domains=None, ranges=["Dog"])
    a = compute_ontology_analysis(t)
    assert any(i.issue_key == "property_missing_domain" for i in a.issues)


def test_issue_property_missing_range():
    t = Taxonomy()
    t.owl_classes[BASE + "Dog"] = _cls("Dog")
    t.owl_properties[BASE + "p"] = _prop("p", domains=["Dog"], ranges=None)
    a = compute_ontology_analysis(t)
    assert any(i.issue_key == "property_missing_range" for i in a.issues)


def test_issue_property_low_fill():
    t, _rex, _buddy, p_uri = _make_fill_taxonomy()
    # Only Rex has the property → fill = 0.5 < PROPERTY_FILL_THRESHOLD
    a = compute_ontology_analysis(t)
    assert any(i.issue_key == "property_low_fill" for i in a.issues)
    issue = next(i for i in a.issues if i.issue_key == "property_low_fill")
    assert issue.severity == "warning"
    assert issue.entity_uri == p_uri
    assert issue.extra["fill_rate"] == 0.5


def test_no_low_fill_issue_when_adequate():
    t, rex, buddy, p_uri = _make_fill_taxonomy()
    t.owl_individuals[buddy].property_values.append((p_uri, rex))
    a = compute_ontology_analysis(t)
    assert not any(i.issue_key == "property_low_fill" for i in a.issues)


def test_no_low_fill_issue_when_no_domain_individuals():
    t = Taxonomy()
    t.owl_classes[BASE + "Dog"] = _cls("Dog")
    t.owl_properties[BASE + "p"] = _prop("p", ["Dog"], ["Dog"])
    a = compute_ontology_analysis(t)
    assert not any(i.issue_key == "property_low_fill" for i in a.issues)


# ═══════════════════════════════════════════════════════════════════════════════
# ClassMetrics
# ═══════════════════════════════════════════════════════════════════════════════


def test_class_metrics_depth():
    t = Taxonomy()
    t.owl_classes[BASE + "Animal"] = _cls("Animal")
    t.owl_classes[BASE + "Dog"] = _cls("Dog", ["Animal"])
    a = compute_ontology_analysis(t)
    by_uri = {cm.class_uri: cm for cm in a.class_metrics}
    assert by_uri[BASE + "Animal"].depth == 0
    assert by_uri[BASE + "Dog"].depth == 1


def test_class_metrics_n_individuals():
    t = Taxonomy()
    t.owl_classes[BASE + "Dog"] = _cls("Dog")
    t.owl_individuals[BASE + "Rex"] = _ind("Rex", ["Dog"])
    t.owl_individuals[BASE + "Buddy"] = _ind("Buddy", ["Dog"])
    a = compute_ontology_analysis(t)
    cm = next(c for c in a.class_metrics if c.class_uri == BASE + "Dog")
    assert cm.n_individuals == 2


def test_class_metrics_property_fill():
    t, _rex, _buddy, p_uri = _make_fill_taxonomy()
    t.owl_individuals[BASE + "Buddy"].property_values.append((p_uri, BASE + "Rex"))
    a = compute_ontology_analysis(t)
    cm = next(c for c in a.class_metrics if c.class_uri == BASE + "Dog")
    assert p_uri in cm.property_fill
    assert cm.property_fill[p_uri] == 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# Issues are sorted by severity then message
# ═══════════════════════════════════════════════════════════════════════════════


def test_issues_sorted_by_severity():
    t = Taxonomy()
    t.owl_classes[BASE + "A"] = _cls("A", lbl=False, cmt=False)
    a = compute_ontology_analysis(t)
    severities = [i.severity for i in a.issues]
    rank = {"error": 0, "warning": 1, "info": 2}
    assert severities == sorted(severities, key=lambda s: rank.get(s, 99))
