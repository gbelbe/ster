"""Unit tests for the pure semantic-change core.

`compare()` takes two rdflib graphs and returns the change operations between
them. No git, no files, no I/O — everything here is built from turtle strings.
"""

from __future__ import annotations

from rdflib import Graph

from semanticdiff.changeset import compare
from semanticdiff.vocabulary import Change, ChangeKind, ChangeSet, EntityKind

PREFIXES = """
@prefix ex:   <http://example.org/> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
"""

CLASS_PRODUCT = "ex:Product a owl:Class ."


def graph(body: str) -> Graph:
    """Parse a turtle body with the standard test prefixes prepended."""
    g = Graph()
    g.parse(data=PREFIXES + body, format="turtle")
    return g


def one(changes: ChangeSet, curie: str) -> Change | None:
    """The single change reported for `curie`, or None."""
    hits = [c for c in changes if c.curie == curie]
    assert len(hits) <= 1, f"expected at most one change for {curie}, got {hits}"
    return hits[0] if hits else None


# ── additions ─────────────────────────────────────────────────────────────────


def test_added_class_detected() -> None:
    later = graph(CLASS_PRODUCT + " ex:Vehicle a owl:Class .")

    change = one(compare(graph(CLASS_PRODUCT), later), "ex:Vehicle")

    assert change is not None
    assert change.kind is ChangeKind.ADDED
    assert change.entity is EntityKind.CLASS


def test_added_property_detected() -> None:
    later = graph(CLASS_PRODUCT + " ex:colour a owl:DatatypeProperty .")

    change = one(compare(graph(CLASS_PRODUCT), later), "ex:colour")

    assert change is not None
    assert change.kind is ChangeKind.ADDED
    assert change.entity is EntityKind.PROPERTY


def test_added_individual_detected() -> None:
    base = graph("ex:Shop a owl:Class .")
    later = graph("ex:Shop a owl:Class . ex:lille a ex:Shop .")

    change = one(compare(base, later), "ex:lille")

    assert change is not None
    assert change.kind is ChangeKind.ADDED
    assert change.entity is EntityKind.INDIVIDUAL


def test_added_skos_concept_detected() -> None:
    base = graph("ex:Tools a skos:Concept .")
    later = graph("ex:Tools a skos:Concept . ex:Hammers a skos:Concept .")

    change = one(compare(base, later), "ex:Hammers")

    assert change is not None
    assert change.kind is ChangeKind.ADDED
    assert change.entity is EntityKind.CONCEPT


def test_empty_base_graph_reports_all_as_added() -> None:
    later = graph(CLASS_PRODUCT + " ex:Vehicle a owl:Class .")

    changes = compare(Graph(), later)

    assert {c.curie for c in changes} == {"ex:Product", "ex:Vehicle"}
    assert all(c.kind is ChangeKind.ADDED for c in changes)


# ── removals ──────────────────────────────────────────────────────────────────


def test_removed_class_detected() -> None:
    base = graph(CLASS_PRODUCT + " ex:LegacyStore a owl:Class .")

    change = one(compare(base, graph(CLASS_PRODUCT)), "ex:LegacyStore")

    assert change is not None
    assert change.kind is ChangeKind.REMOVED
    assert change.entity is EntityKind.CLASS


def test_removed_entity_is_classified_from_the_base_graph() -> None:
    change = one(compare(graph("ex:Tools a skos:Concept ."), Graph()), "ex:Tools")

    assert change is not None
    assert change.kind is ChangeKind.REMOVED
    assert change.entity is EntityKind.CONCEPT


# ── modifications ─────────────────────────────────────────────────────────────


def test_modified_class_when_annotation_changes() -> None:
    base = graph('ex:Product a owl:Class ; rdfs:label "Product"@en .')
    later = graph('ex:Product a owl:Class ; rdfs:label "Article"@en .')

    change = one(compare(base, later), "ex:Product")

    assert change is not None
    assert change.kind is ChangeKind.MODIFIED


def test_modified_class_when_subclass_added() -> None:
    """Object-side attribution: the parent is touched though it is never a subject."""
    later = graph(CLASS_PRODUCT + " ex:Vehicle a owl:Class ; rdfs:subClassOf ex:Product .")

    changes = compare(graph(CLASS_PRODUCT), later)

    assert one(changes, "ex:Vehicle").kind is ChangeKind.ADDED
    assert one(changes, "ex:Product").kind is ChangeKind.MODIFIED


def test_modified_class_when_property_declares_it_as_domain() -> None:
    """The sentence the tool exists to produce: 'class X gained 2 properties'."""
    later = graph("""
        ex:Product a owl:Class .
        ex:colour a owl:DatatypeProperty ; rdfs:domain ex:Product .
        ex:weight a owl:DatatypeProperty ; rdfs:domain ex:Product .
    """)

    change = one(compare(graph(CLASS_PRODUCT), later), "ex:Product")

    assert change.kind is ChangeKind.MODIFIED
    assert "+2 properties" in change.detail


def test_modified_property_when_domain_changes() -> None:
    base = graph("ex:operatedBy a owl:ObjectProperty ; rdfs:domain ex:Place .")
    later = graph("ex:operatedBy a owl:ObjectProperty ; rdfs:domain ex:Site .")

    change = one(compare(base, later), "ex:operatedBy")

    assert change.kind is ChangeKind.MODIFIED
    assert change.entity is EntityKind.PROPERTY


def test_change_detail_records_domain_transition() -> None:
    base = graph("ex:operatedBy a owl:ObjectProperty ; rdfs:domain ex:Place .")
    later = graph("ex:operatedBy a owl:ObjectProperty ; rdfs:domain ex:Site .")

    change = one(compare(base, later), "ex:operatedBy")

    assert "domain ex:Place → ex:Site" in change.detail


def test_object_attribution_reports_removed_subclass_as_negative_detail() -> None:
    base = graph(CLASS_PRODUCT + " ex:Vehicle a owl:Class ; rdfs:subClassOf ex:Product .")
    later = graph(CLASS_PRODUCT + " ex:Vehicle a owl:Class .")

    change = one(compare(base, later), "ex:Product")

    assert change.kind is ChangeKind.MODIFIED
    assert "-1 subclass" in change.detail


def test_broader_change_attributes_to_the_broader_concept() -> None:
    base = graph("ex:Tools a skos:Concept .")
    later = graph("ex:Tools a skos:Concept . ex:Hammers a skos:Concept ; skos:broader ex:Tools .")

    change = one(compare(base, later), "ex:Tools")

    assert change.kind is ChangeKind.MODIFIED
    assert "+1 narrower concept" in change.detail


# ── deprecation ───────────────────────────────────────────────────────────────


def test_deprecation_reported_as_deprecated_not_modified() -> None:
    base = graph("ex:LegacyStore a owl:Class .")
    later = graph("ex:LegacyStore a owl:Class ; owl:deprecated true .")

    assert one(compare(base, later), "ex:LegacyStore").kind is ChangeKind.DEPRECATED


def test_already_deprecated_entity_is_not_re_reported() -> None:
    base = graph('ex:LegacyStore a owl:Class ; owl:deprecated true ; rdfs:label "Old"@en .')
    later = graph('ex:LegacyStore a owl:Class ; owl:deprecated true ; rdfs:label "Older"@en .')

    assert one(compare(base, later), "ex:LegacyStore").kind is ChangeKind.MODIFIED


# ── things that must NOT be reported ──────────────────────────────────────────


def test_identical_graphs_yield_no_changes() -> None:
    assert len(compare(graph(CLASS_PRODUCT), graph(CLASS_PRODUCT))) == 0


def test_reordered_serialisation_yields_no_changes() -> None:
    base = graph('ex:Product a owl:Class ; rdfs:label "Product"@en . ex:Van a owl:Class .')
    later = graph('ex:Van a owl:Class . ex:Product rdfs:label "Product"@en ; a owl:Class .')

    assert len(compare(base, later)) == 0


def test_relabelled_blank_nodes_yield_no_changes() -> None:
    base = graph("""
        ex:Vehicle a owl:Class ; rdfs:subClassOf [
            a owl:Restriction ;
            owl:onProperty ex:wheels ;
            owl:minCardinality "2"^^xsd:nonNegativeInteger
        ] .
    """)
    later = Graph()
    later.parse(data=base.serialize(format="nt"), format="nt")

    assert len(compare(base, later)) == 0


# ── classification and naming edge cases ──────────────────────────────────────


def test_untyped_subject_classified_as_other() -> None:
    later = graph(CLASS_PRODUCT + ' ex:mystery rdfs:comment "no type"@en .')

    assert one(compare(graph(CLASS_PRODUCT), later), "ex:mystery").entity is EntityKind.OTHER


def test_full_uri_kept_alongside_the_curie() -> None:
    change = one(compare(Graph(), graph(CLASS_PRODUCT)), "ex:Product")

    assert change.uri == "http://example.org/Product"


def test_unprefixed_uri_falls_back_to_the_full_uri_as_curie() -> None:
    later = Graph()
    later.parse(
        data="<http://nowhere.test/Thing> a <http://www.w3.org/2002/07/owl#Class> .",
        format="turtle",
    )

    assert {c.curie for c in compare(Graph(), later)} == {"http://nowhere.test/Thing"}


# ── the ChangeSet container ───────────────────────────────────────────────────


def test_changeset_counts_by_kind() -> None:
    base = graph("ex:A a owl:Class . ex:B a owl:Class .")
    later = graph('ex:A a owl:Class ; rdfs:label "A"@en . ex:C a owl:Class .')

    counts = compare(base, later).counts()

    assert counts[ChangeKind.ADDED] == 1
    assert counts[ChangeKind.REMOVED] == 1
    assert counts[ChangeKind.MODIFIED] == 1


def test_changeset_for_uri_matches_curie_or_full_uri() -> None:
    changes = compare(Graph(), graph(CLASS_PRODUCT))

    assert len(changes.for_uri("ex:Product")) == 1
    assert len(changes.for_uri("http://example.org/Product")) == 1
    assert len(changes.for_uri("ex:Absent")) == 0


# ── the class an individual belongs to ────────────────────────────────────────
#
# Carried so a summary can count individuals against their class. On a real
# ontology they are ~99% of every commit, so listing them one per line buries
# the handful of class and property changes that the reader actually came for.


def test_individual_records_the_class_it_instantiates() -> None:
    base = graph("ex:Shop a owl:Class .")
    later = graph('ex:Shop a owl:Class ; rdfs:label "Shop"@en . ex:lille a ex:Shop .')

    assert one(compare(base, later), "ex:lille").of_class == "Shop"


def test_individual_falls_back_to_the_curie_when_the_class_is_unlabelled() -> None:
    base = graph("ex:Shop a owl:Class .")
    later = graph("ex:Shop a owl:Class . ex:lille a ex:Shop .")

    assert one(compare(base, later), "ex:lille").of_class == "ex:Shop"


def test_individual_with_no_named_type_has_no_class() -> None:
    later = graph('ex:mystery rdfs:comment "no type"@en .')

    assert one(compare(Graph(), later), "ex:mystery").of_class is None


def test_a_class_change_carries_no_of_class() -> None:
    assert one(compare(Graph(), graph(CLASS_PRODUCT)), "ex:Product").of_class is None


def test_named_individual_alone_is_not_treated_as_the_class() -> None:
    """owl:NamedIndividual says the thing exists, not what it is."""
    later = graph("ex:lille a owl:NamedIndividual .")

    assert one(compare(Graph(), later), "ex:lille").of_class is None


def test_a_multi_typed_individual_reports_the_same_class_every_time() -> None:
    later = graph("""
        ex:Shop a owl:Class . ex:Depot a owl:Class .
        ex:lille a owl:NamedIndividual, ex:Shop, ex:Depot .
    """)

    assert one(compare(Graph(), later), "ex:lille").of_class == "ex:Depot"


# ── changes inside blank nodes ────────────────────────────────────────────────
#
# Regression: graph_diff saw these, and attribution threw them away, because the
# changed triple's subject is a BNode and _touched() kept only URIRefs. Nothing
# else implicated the owning class — `ex:Car rdfs:subClassOf _:b` does not itself
# change — so a cardinality edit reported *nothing at all*, which a reader cannot
# tell apart from "nothing changed". That covers restrictions, anonymous class
# expressions and RDF lists: most of OWL's expressive machinery.

RESTRICTION = """
    ex:Car a owl:Class ; rdfs:subClassOf [
        a owl:Restriction ; owl:onProperty ex:wheels ;
        owl:cardinality "%s"^^xsd:nonNegativeInteger
    ] .
"""


def test_a_cardinality_change_inside_a_restriction_is_reported_regression() -> None:
    change = one(compare(graph(RESTRICTION % "4"), graph(RESTRICTION % "3")), "ex:Car")

    assert change is not None, "a cardinality change must not vanish"
    assert change.kind is ChangeKind.MODIFIED
    assert change.entity is EntityKind.CLASS


def test_the_owning_class_is_named_rather_than_the_blank_node() -> None:
    changes = compare(graph(RESTRICTION % "4"), graph(RESTRICTION % "3"))

    assert [c.curie for c in changes] == ["ex:Car"]


def test_a_changed_restriction_property_is_reported() -> None:
    base = graph(RESTRICTION % "4")
    later = graph(RESTRICTION.replace("ex:wheels", "ex:doors") % "4")

    assert one(compare(base, later), "ex:Car").kind is ChangeKind.MODIFIED


def test_an_added_restriction_is_reported() -> None:
    base = graph("ex:Car a owl:Class .")

    assert one(compare(base, graph(RESTRICTION % "4")), "ex:Car").kind is ChangeKind.MODIFIED


def test_a_removed_restriction_is_reported() -> None:
    later = graph("ex:Car a owl:Class .")

    assert one(compare(graph(RESTRICTION % "4"), later), "ex:Car").kind is ChangeKind.MODIFIED


def test_a_changed_union_member_is_reported() -> None:
    base = graph("ex:A a owl:Class ; owl:unionOf ( ex:B ex:C ) .")
    later = graph("ex:A a owl:Class ; owl:unionOf ( ex:B ex:D ) .")

    assert one(compare(base, later), "ex:A").kind is ChangeKind.MODIFIED


def test_a_reordered_rdf_list_is_reported() -> None:
    """A list is ordered, so its order is part of what it says."""
    base = graph("ex:A a owl:Class ; owl:intersectionOf ( ex:B ex:C ) .")
    later = graph("ex:A a owl:Class ; owl:intersectionOf ( ex:C ex:B ) .")

    assert one(compare(base, later), "ex:A").kind is ChangeKind.MODIFIED


def test_a_change_nested_two_blank_nodes_deep_is_reported() -> None:
    nested = """
        ex:A a owl:Class ; rdfs:subClassOf [
            a owl:Restriction ; owl:onProperty ex:p ;
            owl:someValuesFrom [ a owl:Restriction ; owl:onProperty ex:q ;
                                 owl:cardinality "%s"^^xsd:nonNegativeInteger ]
        ] .
    """
    assert one(compare(graph(nested % "1"), graph(nested % "2")), "ex:A") is not None


def test_an_unchanged_restriction_reports_nothing() -> None:
    """The owner is only implicated when its description actually differs."""
    assert len(compare(graph(RESTRICTION % "4"), graph(RESTRICTION % "4"))) == 0


def test_one_class_changing_does_not_implicate_another_with_a_restriction() -> None:
    other = "ex:Van a owl:Class ; rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:p ] ."
    base = graph(RESTRICTION % "4" + other)
    later = graph(RESTRICTION % "3" + other)

    assert [c.curie for c in compare(base, later)] == ["ex:Car"]
