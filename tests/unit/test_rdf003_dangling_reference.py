"""Fixing a malformed URI that is only ever referenced, never defined.

RDF003 flags any malformed URI in the graph, and the likeliest way one appears
is a typo in a *link* — `skos:broader <…gear#Camping#>` pointing at nothing.
The fix used to build a RenameEntity, which looks the subject up among the
defined entities, finds nothing, and fails with "Concept not found" while the
row stays on screen.
"""

from __future__ import annotations

import pytest

from ster.domain.cross import retarget_uri_references
from ster.model import (
    Concept,
    ConceptScheme,
    Label,
    LabelType,
    OntologyAnnotation,
    OWLIndividual,
    OWLProperty,
    RDFClass,
    Taxonomy,
)

NS = "https://example.org/gear#"
BAD = NS + "Camping#"
GOOD = NS + "Camping%23"


def _lbl(v: str) -> Label:
    return Label(lang="en", value=v, type=LabelType.PREF)


@pytest.fixture
def tax() -> Taxonomy:
    """Tent points at a malformed URI that no entity defines."""
    t = Taxonomy()
    t.schemes[NS + "Scheme"] = ConceptScheme(uri=NS + "Scheme", labels=[_lbl("Scheme")])
    t.concepts[NS + "Tent"] = Concept(uri=NS + "Tent", labels=[_lbl("Tent")], broader=[BAD])
    return t


def test_the_dangling_uri_is_not_a_defined_entity(tax):
    """The premise: this is why the rename could not find it."""
    assert BAD not in tax.concepts
    assert BAD not in tax.owl_classes
    assert BAD not in tax.owl_individuals


def test_retarget_rewrites_a_broader_reference(tax):
    changed = retarget_uri_references(tax, BAD, GOOD)

    assert tax.concepts[NS + "Tent"].broader == [GOOD]
    assert changed == 1


def test_retarget_reports_nothing_to_do_for_an_unreferenced_uri(tax):
    assert retarget_uri_references(tax, NS + "Nobody", GOOD) == 0


def test_retarget_covers_every_skos_link(tax):
    concept = tax.concepts[NS + "Tent"]
    concept.narrower = [BAD]
    concept.related = [BAD]
    concept.close_match = [BAD]

    retarget_uri_references(tax, BAD, GOOD)

    assert concept.narrower == [GOOD]
    assert concept.related == [GOOD]
    assert concept.close_match == [GOOD]


def test_retarget_covers_scheme_top_concepts(tax):
    tax.schemes[NS + "Scheme"].top_concepts = [BAD]

    retarget_uri_references(tax, BAD, GOOD)

    assert tax.schemes[NS + "Scheme"].top_concepts == [GOOD]


def test_retarget_covers_owl_subclass_links(tax):
    tax.owl_classes[NS + "Shelter"] = RDFClass(uri=NS + "Shelter", sub_class_of=[BAD])

    retarget_uri_references(tax, BAD, GOOD)

    assert tax.owl_classes[NS + "Shelter"].sub_class_of == [GOOD]


def test_retarget_leaves_other_links_alone(tax):
    tax.concepts[NS + "Tent"].broader = [BAD, NS + "Outdoor"]

    retarget_uri_references(tax, BAD, GOOD)

    assert tax.concepts[NS + "Tent"].broader == [GOOD, NS + "Outdoor"]


def test_retarget_covers_the_single_valued_concept_links(tax):
    """top_concept_of and focus hold one URI, not a list."""
    concept = tax.concepts[NS + "Tent"]
    concept.broader = []
    concept.top_concept_of = BAD
    concept.focus = BAD

    assert retarget_uri_references(tax, BAD, GOOD) == 2
    assert (concept.top_concept_of, concept.focus) == (GOOD, GOOD)


def test_retarget_covers_property_domains_ranges_and_hierarchy(tax):
    tax.owl_properties[NS + "fits"] = OWLProperty(
        uri=NS + "fits",
        domains=[BAD],
        ranges=[BAD],
        sub_property_of=[BAD],
        inverse_of=[BAD],
    )

    retarget_uri_references(tax, BAD, GOOD)

    prop = tax.owl_properties[NS + "fits"]
    assert (prop.domains, prop.ranges, prop.sub_property_of, prop.inverse_of) == (
        [GOOD],
        [GOOD],
        [GOOD],
        [GOOD],
    )


def test_retarget_covers_class_equivalence_and_disjointness(tax):
    tax.owl_classes[NS + "Shelter"] = RDFClass(
        uri=NS + "Shelter", equivalent_class=[BAD], disjoint_with=[BAD]
    )

    retarget_uri_references(tax, BAD, GOOD)

    cls = tax.owl_classes[NS + "Shelter"]
    assert (cls.equivalent_class, cls.disjoint_with) == ([GOOD], [GOOD])


def test_retarget_covers_an_individuals_type_and_assertions(tax):
    tax.concepts[NS + "Tent"].broader = []  # count only what this test sets up
    tax.owl_individuals[NS + "Tent1"] = OWLIndividual(
        uri=NS + "Tent1",
        types=[BAD],
        property_values=[(BAD, NS + "x"), (NS + "p", BAD), (NS + "keep", NS + "y")],
        literal_values=[(BAD, "42", ""), (NS + "q", "7", "")],
    )

    changed = retarget_uri_references(tax, BAD, GOOD)

    ind = tax.owl_individuals[NS + "Tent1"]
    assert ind.types == [GOOD]
    assert ind.property_values == [(GOOD, NS + "x"), (NS + "p", GOOD), (NS + "keep", NS + "y")]
    assert ind.literal_values == [(GOOD, "42", ""), (NS + "q", "7", "")]
    assert changed == 4


def test_retarget_covers_a_bad_uri_used_as_a_predicate(tax):
    """A malformed URI can be the property of an annotation, not only its object."""
    tax.concepts[NS + "Tent"].broader = []  # count only what this test sets up
    tax.owl_properties[NS + "fits"] = OWLProperty(uri=NS + "fits")
    tax.owl_properties[NS + "fits"].annotations = [
        OntologyAnnotation(predicate=BAD, value="note", is_iri=False)
    ]

    assert retarget_uri_references(tax, BAD, GOOD) == 1
    assert tax.owl_properties[NS + "fits"].annotations[0].predicate == GOOD


def test_retarget_covers_scheme_and_ontology_annotations(tax):
    tax.concepts[NS + "Tent"].broader = []  # count only what this test sets up
    tax.schemes[NS + "Scheme"].annotations = [
        OntologyAnnotation(predicate="http://ex/p", value=BAD, is_iri=True)
    ]
    tax.ontology_annotations = [OntologyAnnotation(predicate="http://ex/q", value=BAD, is_iri=True)]

    assert retarget_uri_references(tax, BAD, GOOD) == 2
    assert tax.schemes[NS + "Scheme"].annotations[0].value == GOOD
    assert tax.ontology_annotations[0].value == GOOD


# ── the fixer picks the right command ─────────────────────────────────────────


def test_the_fixer_retargets_when_the_subject_is_only_referenced(tax, tmp_path):
    from ster.core.commands.cross import RetargetReferences
    from ster.plugins.semanticlint import fixes

    issue = {"check_id": "RDF003", "subject": BAD}

    commands = fixes.commands_for(issue, tax, tmp_path / "o.ttl", GOOD)

    assert len(commands) == 1
    assert isinstance(commands[0], RetargetReferences)


def test_the_fixer_still_renames_a_real_entity(tmp_path):
    """The defined-entity case must keep working."""
    from ster.core.commands.cross import RenameEntity
    from ster.plugins.semanticlint import fixes

    t = Taxonomy()
    t.concepts[BAD] = Concept(uri=BAD, labels=[_lbl("Camping")])
    issue = {"check_id": "RDF003", "subject": BAD}

    commands = fixes.commands_for(issue, t, tmp_path / "o.ttl", GOOD)

    assert len(commands) == 1
    assert isinstance(commands[0], RenameEntity)


def test_the_command_applies_end_to_end(tax, tmp_path):
    from ster.core.commands.cross import RetargetReferences

    RetargetReferences(tmp_path / "o.ttl", BAD, GOOD).apply(tax)

    assert tax.concepts[NS + "Tent"].broader == [GOOD]


# ── the malformed URI must not survive the round-trip ─────────────────────────

PUN_TTL = f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix gear: <{NS}> .

gear:themes a skos:ConceptScheme ; skos:prefLabel "Themes"@en .
gear:Camping a skos:Concept ; skos:prefLabel "Camping"@en ; skos:inScheme gear:themes .
gear:Tent a owl:Class, skos:Concept ;
    rdfs:label "Tent"@en ;
    skos:prefLabel "Tent"@en ;
    skos:inScheme gear:themes ;
    skos:broader gear:Camping, <{BAD}> .
"""


def test_a_pun_keeps_the_bad_link_on_its_class_facet(tmp_path):
    """The premise of the round-trip bug, pinned separately.

    gear:Tent is a pun — owl:Class *and* skos:Concept. The loader files
    ``skos:broader`` under the concept and, because the class facet accepts any
    predicate it does not model, under the class's generic annotations too. Fixing
    only the concept left the class's copy to be serialised straight back out.
    """
    from ster import store

    path = tmp_path / "gear.ttl"
    path.write_text(PUN_TTL, encoding="utf-8")
    tax = store.load(path)

    values = [a.value for a in tax.owl_classes[NS + "Tent"].annotations]
    assert BAD in values


def test_the_bad_uri_is_gone_from_the_file_after_a_save(tmp_path):
    """The symptom the user hit: reopening kept re-reporting the same error."""
    from ster import store

    path = tmp_path / "gear.ttl"
    path.write_text(PUN_TTL, encoding="utf-8")
    tax = store.load(path)

    retarget_uri_references(tax, BAD, GOOD)
    store.save(tax, path)

    assert f"<{BAD}>" not in path.read_text(encoding="utf-8")
    assert BAD not in store.load(path).concepts[NS + "Tent"].broader


def test_retarget_covers_annotation_objects(tmp_path):
    from ster.model import OntologyAnnotation

    tax = Taxonomy()
    tax.owl_classes[NS + "Tent"] = RDFClass(uri=NS + "Tent")
    tax.owl_classes[NS + "Tent"].annotations = [
        OntologyAnnotation(predicate="http://ex/p", value=BAD, is_iri=True)
    ]

    assert retarget_uri_references(tax, BAD, GOOD) == 1
    assert tax.owl_classes[NS + "Tent"].annotations[0].value == GOOD


def test_retarget_leaves_a_literal_that_merely_contains_the_uri(tmp_path):
    """A note *mentioning* the URI is prose, not a link — rewriting it is not a fix."""
    from ster.model import OntologyAnnotation

    tax = Taxonomy()
    tax.owl_classes[NS + "Tent"] = RDFClass(uri=NS + "Tent")
    note = OntologyAnnotation(predicate="http://ex/note", value=BAD, is_iri=False)
    tax.owl_classes[NS + "Tent"].annotations = [note]

    assert retarget_uri_references(tax, BAD, GOOD) == 0
    assert note.value == BAD
