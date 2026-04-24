"""Tests for the RDF persistence layer."""

from __future__ import annotations

import pytest

from ster import store
from ster.handles import assign_handles
from ster.model import Concept, ConceptScheme, Label, Taxonomy

BASE = "https://example.org/test/"


def test_load_finds_scheme(taxonomy):
    assert BASE + "Scheme" in taxonomy.schemes


def test_load_finds_all_concepts(taxonomy):
    expected = {BASE + c for c in ("Top", "Child1", "Child2", "Grandchild")}
    assert expected == set(taxonomy.concepts)


def test_load_pref_labels(taxonomy):
    top = taxonomy.concepts[BASE + "Top"]
    assert top.pref_label("en") == "Top Concept"
    assert top.pref_label("fr") == "Concept Principal"


def test_load_alt_label(taxonomy):
    child2 = taxonomy.concepts[BASE + "Child2"]
    alts = child2.alt_labels()
    assert "Second child" in alts.get("en", [])


def test_load_definition(taxonomy):
    top = taxonomy.concepts[BASE + "Top"]
    assert top.definition("en") == "The root concept."


def test_load_narrower(taxonomy):
    top = taxonomy.concepts[BASE + "Top"]
    assert BASE + "Child1" in top.narrower
    assert BASE + "Child2" in top.narrower


def test_load_normalizes_broader(taxonomy):
    """Broader links should be populated even if only narrower is in the file."""
    child1 = taxonomy.concepts[BASE + "Child1"]
    assert BASE + "Top" in child1.broader


def test_load_top_concepts(taxonomy):
    scheme = taxonomy.schemes[BASE + "Scheme"]
    assert BASE + "Top" in scheme.top_concepts


def test_load_assigns_handles(taxonomy):
    assert len(taxonomy.handle_index) > 0
    # Every concept and scheme should have a handle
    for uri in list(taxonomy.concepts) + list(taxonomy.schemes):
        assert taxonomy.uri_to_handle(uri) is not None


def test_base_uri_round_trip(tmp_path):
    """base_uri stored as void:uriSpace survives a save/reload cycle."""
    from ster import operations
    from ster.model import Taxonomy

    t = Taxonomy()
    operations.create_scheme(t, BASE + "Scheme", {"en": "Test"}, base_uri=BASE)
    out = tmp_path / "out.ttl"
    store.save(t, out)
    reloaded = store.load(out)
    scheme = reloaded.primary_scheme()
    assert scheme is not None
    assert scheme.base_uri == BASE


def test_taxonomy_base_uri_derived_from_concepts(simple_taxonomy):
    """Taxonomy.base_uri() returns scheme.base_uri when set."""
    assert simple_taxonomy.base_uri() == BASE


def test_unsupported_extension_raises(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("nope")
    with pytest.raises(ValueError, match="Unsupported file extension"):
        store.load(p)


def test_round_trip_turtle(tmp_ttl, tmp_path, taxonomy):
    """Load → save → reload should produce the same concepts."""
    out = tmp_path / "out.ttl"
    store.save(taxonomy, out)
    reloaded = store.load(out)
    assert set(reloaded.concepts) == set(taxonomy.concepts)
    assert set(reloaded.schemes) == set(taxonomy.schemes)


def test_round_trip_preserves_labels(tmp_ttl, tmp_path, taxonomy):
    out = tmp_path / "out.ttl"
    store.save(taxonomy, out)
    reloaded = store.load(out)
    for uri, original in taxonomy.concepts.items():
        reloaded_concept = reloaded.concepts[uri]
        assert original.pref_label("en") == reloaded_concept.pref_label("en")


def test_round_trip_jsonld(tmp_path, minimal_turtle):
    ttl = tmp_path / "source.ttl"
    ttl.write_text(minimal_turtle)
    t1 = store.load(ttl)

    jsonld = tmp_path / "out.jsonld"
    store.save(t1, jsonld)
    t2 = store.load(jsonld)

    assert set(t1.concepts) == set(t2.concepts)


# ── top concept normalization ─────────────────────────────────────────────────


def test_load_sets_top_concept_of(taxonomy):
    """Concepts in hasTopConcept get top_concept_of set on load."""
    top = taxonomy.concepts[BASE + "Top"]
    assert top.top_concept_of == BASE + "Scheme"


def test_load_only_top_concept_has_top_concept_of(taxonomy):
    """Non-top concepts do NOT have top_concept_of set."""
    for uri in (BASE + "Child1", BASE + "Child2", BASE + "Grandchild"):
        assert taxonomy.concepts[uri].top_concept_of is None


def test_top_concept_of_round_trips(tmp_ttl, tmp_path, taxonomy):
    """top_concept_of is written as skos:topConceptOf and survives reload."""
    out = tmp_path / "out.ttl"
    store.save(taxonomy, out)
    reloaded = store.load(out)
    top = reloaded.concepts[BASE + "Top"]
    assert top.top_concept_of == BASE + "Scheme"
    # Non-top-concepts should not have it set
    assert reloaded.concepts[BASE + "Child1"].top_concept_of is None


def test_normalize_top_concept_from_has_top_concept():
    """hasTopConcept on scheme → topConceptOf on concept after normalization."""
    t = Taxonomy()
    s = ConceptScheme(uri=BASE + "S", labels=[Label("en", "S")], top_concepts=[BASE + "C"])
    c = Concept(uri=BASE + "C", labels=[Label("en", "C")])
    t.schemes[s.uri] = s
    t.concepts[c.uri] = c
    assign_handles(t)
    store._normalize_hierarchy(t)
    assert t.concepts[BASE + "C"].top_concept_of == BASE + "S"


def test_normalize_top_concept_from_top_concept_of():
    """topConceptOf on concept → hasTopConcept on scheme after normalization."""
    t = Taxonomy()
    s = ConceptScheme(uri=BASE + "S", labels=[Label("en", "S")])
    c = Concept(uri=BASE + "C", labels=[Label("en", "C")], top_concept_of=BASE + "S")
    t.schemes[s.uri] = s
    t.concepts[c.uri] = c
    assign_handles(t)
    store._normalize_hierarchy(t)
    assert BASE + "C" in t.schemes[BASE + "S"].top_concepts


def test_auto_detect_top_concept_no_broader():
    """Concept with no broader and not yet in top_concepts is auto-added."""
    t = Taxonomy()
    s = ConceptScheme(uri=BASE + "S", labels=[Label("en", "S")])
    c = Concept(uri=BASE + "C", labels=[Label("en", "C")])  # no broader, no top_concept_of
    t.schemes[s.uri] = s
    t.concepts[c.uri] = c
    assign_handles(t)
    store._normalize_hierarchy(t)
    assert BASE + "C" in t.schemes[BASE + "S"].top_concepts
    assert t.concepts[BASE + "C"].top_concept_of == BASE + "S"


def test_auto_detect_not_triggered_for_narrower_concepts():
    """Concepts with a broader link are NOT auto-detected as top concepts."""
    t = Taxonomy()
    s = ConceptScheme(uri=BASE + "S", labels=[Label("en", "S")], top_concepts=[BASE + "Parent"])
    parent = Concept(uri=BASE + "Parent", labels=[Label("en", "P")], narrower=[BASE + "Child"])
    child = Concept(uri=BASE + "Child", labels=[Label("en", "C")], broader=[BASE + "Parent"])
    t.schemes[s.uri] = s
    t.concepts[parent.uri] = parent
    t.concepts[child.uri] = child
    assign_handles(t)
    store._normalize_hierarchy(t)
    assert BASE + "Child" not in t.schemes[BASE + "S"].top_concepts
    assert t.concepts[BASE + "Child"].top_concept_of is None


def test_in_scheme_scoped_to_correct_scheme(tmp_path):
    """Each concept is inScheme of exactly the scheme it belongs to."""
    from rdflib import Graph, URIRef
    from rdflib.namespace import SKOS

    t = Taxonomy()
    s1 = ConceptScheme(
        uri=BASE + "S1",
        labels=[Label("en", "S1")],
        top_concepts=[BASE + "C1"],
        base_uri=BASE + "s1/",
    )
    s2 = ConceptScheme(
        uri=BASE + "S2",
        labels=[Label("en", "S2")],
        top_concepts=[BASE + "C2"],
        base_uri=BASE + "s2/",
    )
    c1 = Concept(uri=BASE + "C1", labels=[Label("en", "C1")], top_concept_of=BASE + "S1")
    c2 = Concept(uri=BASE + "C2", labels=[Label("en", "C2")], top_concept_of=BASE + "S2")
    t.schemes[s1.uri] = s1
    t.schemes[s2.uri] = s2
    t.concepts[c1.uri] = c1
    t.concepts[c2.uri] = c2
    assign_handles(t)

    out = tmp_path / "out.ttl"
    store.save(t, out)
    g = Graph()
    g.parse(str(out), format="turtle")

    c1_schemes = {str(o) for o in g.objects(URIRef(BASE + "C1"), SKOS.inScheme)}
    c2_schemes = {str(o) for o in g.objects(URIRef(BASE + "C2"), SKOS.inScheme)}

    assert BASE + "S1" in c1_schemes
    assert BASE + "S2" not in c1_schemes
    assert BASE + "S2" in c2_schemes
    assert BASE + "S1" not in c2_schemes


def test_concept_scheme_uri_helper():
    """_concept_scheme_uri traverses up to find the scheme."""
    from ster.store import _concept_scheme_uri

    t = Taxonomy()
    s = ConceptScheme(uri=BASE + "S", labels=[Label("en", "S")])
    top = Concept(
        uri=BASE + "Top",
        labels=[Label("en", "T")],
        top_concept_of=BASE + "S",
        narrower=[BASE + "Child"],
    )
    child = Concept(uri=BASE + "Child", labels=[Label("en", "C")], broader=[BASE + "Top"])
    t.schemes[s.uri] = s
    t.concepts[top.uri] = top
    t.concepts[child.uri] = child

    assert _concept_scheme_uri(t, BASE + "Top") == BASE + "S"
    assert _concept_scheme_uri(t, BASE + "Child") == BASE + "S"
    assert _concept_scheme_uri(t, BASE + "Ghost") is None


def test_concept_scheme_uri_circular_safe():
    """_concept_scheme_uri handles circular broader references without infinite loop."""
    from ster.store import _concept_scheme_uri

    t = Taxonomy()
    a = Concept(uri=BASE + "A", labels=[Label("en", "A")], broader=[BASE + "B"])
    b = Concept(uri=BASE + "B", labels=[Label("en", "B")], broader=[BASE + "A"])
    t.concepts[a.uri] = a
    t.concepts[b.uri] = b
    # Should return None without crashing
    assert _concept_scheme_uri(t, BASE + "A") is None


# ── top_concept_of in detail fields ──────────────────────────────────────────


def test_build_detail_fields_shows_top_concept_of(simple_taxonomy):
    """Top concept has a topConceptOf field in its detail view."""
    from ster.nav import build_detail_fields

    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    keys = [f.key for f in fields]
    assert "top_concept_of" in keys


def test_build_detail_fields_no_top_concept_of_for_child(simple_taxonomy):
    """Non-top-concept does NOT get a topConceptOf field."""
    from ster.nav import build_detail_fields

    fields = build_detail_fields(simple_taxonomy, BASE + "Child1", "en")
    keys = [f.key for f in fields]
    assert "top_concept_of" not in keys


# ── OWL/RDFS class loading ────────────────────────────────────────────────────

OWL_TURTLE = """\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/onto/> .

ex:Animal a owl:Class ;
    rdfs:label "Animal"@en ;
    rdfs:comment "A living organism."@en .

ex:Dog a owl:Class ;
    rdfs:label "Dog"@en ;
    rdfs:subClassOf ex:Animal .

ex:Cat a owl:Class ;
    rdfs:label "Cat"@en ;
    rdfs:subClassOf ex:Animal ;
    owl:disjointWith ex:Dog .
"""


@pytest.fixture
def owl_ttl(tmp_path):
    p = tmp_path / "onto.ttl"
    p.write_text(OWL_TURTLE, encoding="utf-8")
    return p


def test_load_owl_classes(owl_ttl):
    t = store.load(owl_ttl)
    assert "https://example.org/onto/Animal" in t.owl_classes
    assert "https://example.org/onto/Dog" in t.owl_classes
    assert "https://example.org/onto/Cat" in t.owl_classes


def test_load_owl_class_label(owl_ttl):
    t = store.load(owl_ttl)
    dog = t.owl_classes["https://example.org/onto/Dog"]
    assert dog.label("en") == "Dog"


def test_load_owl_class_comment(owl_ttl):
    t = store.load(owl_ttl)
    animal = t.owl_classes["https://example.org/onto/Animal"]
    assert any(c.value == "A living organism." for c in animal.comments)


def test_load_owl_subclass_of(owl_ttl):
    t = store.load(owl_ttl)
    dog = t.owl_classes["https://example.org/onto/Dog"]
    assert "https://example.org/onto/Animal" in dog.sub_class_of


def test_load_owl_disjoint_with(owl_ttl):
    t = store.load(owl_ttl)
    cat = t.owl_classes["https://example.org/onto/Cat"]
    assert "https://example.org/onto/Dog" in cat.disjoint_with


def test_load_owl_skips_builtin_classes(owl_ttl):
    t = store.load(owl_ttl)
    for uri in t.owl_classes:
        assert not uri.startswith("http://www.w3.org/")


def test_owl_round_trip(owl_ttl, tmp_path):
    t1 = store.load(owl_ttl)
    out = tmp_path / "out.ttl"
    store.save(t1, out)
    t2 = store.load(out)
    assert set(t1.owl_classes) == set(t2.owl_classes)
    dog1 = t1.owl_classes["https://example.org/onto/Dog"]
    dog2 = t2.owl_classes["https://example.org/onto/Dog"]
    assert dog1.sub_class_of == dog2.sub_class_of
    assert dog1.label("en") == dog2.label("en")


# ── Inferred class / individual type loading ──────────────────────────────────

INFERRED_TURTLE = """\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix ex:   <https://example.org/onto/> .

ex:Prop a owl:ObjectProperty ;
    rdfs:range ex:Animal .

# Animal is only declared via rdfs:range — no explicit owl:Class triple.
# Dog is only declared via rdfs:subClassOf — no explicit owl:Class triple.
ex:Dog rdfs:subClassOf ex:Animal ;
    rdfs:label "Dog"@en .

ex:Fido a owl:NamedIndividual ;
    rdf:type ex:Dog ;
    rdfs:label "Fido"@en .
"""


@pytest.fixture
def inferred_ttl(tmp_path):
    p = tmp_path / "inferred.ttl"
    p.write_text(INFERRED_TURTLE, encoding="utf-8")
    return p


def test_inferred_class_from_range(inferred_ttl):
    """A class used only as rdfs:range must appear in owl_classes."""
    t = store.load(inferred_ttl)
    assert "https://example.org/onto/Animal" in t.owl_classes


def test_inferred_class_from_subclass_subject(inferred_ttl):
    """A class used only as rdfs:subClassOf subject must appear in owl_classes."""
    t = store.load(inferred_ttl)
    assert "https://example.org/onto/Dog" in t.owl_classes


def test_inferred_subclass_has_sub_class_of_populated(inferred_ttl):
    """The inferred Dog class must have Animal in sub_class_of."""
    t = store.load(inferred_ttl)
    dog = t.owl_classes["https://example.org/onto/Dog"]
    assert "https://example.org/onto/Animal" in dog.sub_class_of


def test_inferred_class_label(inferred_ttl):
    """Labels are loaded even for inferred (non-declared) classes."""
    t = store.load(inferred_ttl)
    dog = t.owl_classes["https://example.org/onto/Dog"]
    assert dog.label("en") == "Dog"


def test_individual_type_loaded_for_inferred_class(inferred_ttl):
    """Individual rdf:type is loaded even when the class is not formally owl:Class."""
    t = store.load(inferred_ttl)
    fido = t.owl_individuals.get("https://example.org/onto/Fido")
    assert fido is not None
    assert "https://example.org/onto/Dog" in fido.types
