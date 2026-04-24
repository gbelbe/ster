"""Tests for the pure domain model."""

from __future__ import annotations

from ster.model import (
    Concept,
    ConceptScheme,
    Definition,
    Label,
    LabelType,
    OWLIndividual,
    OWLProperty,
    RDFClass,
    Taxonomy,
    is_builtin_uri,
)

BASE = "https://example.org/test/"


def test_concept_pref_label_by_lang():
    c = Concept(
        uri=BASE + "Foo",
        labels=[
            Label(lang="en", value="Foo"),
            Label(lang="fr", value="Truc"),
        ],
    )
    assert c.pref_label("en") == "Foo"
    assert c.pref_label("fr") == "Truc"


def test_concept_pref_label_fallback_to_first():
    c = Concept(
        uri=BASE + "Foo",
        labels=[Label(lang="fr", value="Truc")],
    )
    assert c.pref_label("en") == "Truc"


def test_concept_pref_label_fallback_to_local_name():
    c = Concept(uri=BASE + "MyLocal")
    assert c.pref_label() == "MyLocal"


def test_concept_local_name_fragment():
    c = Concept(uri="https://example.org/ns#MyThing")
    assert c.local_name == "MyThing"


def test_concept_local_name_path():
    c = Concept(uri="https://example.org/ns/MyThing")
    assert c.local_name == "MyThing"


def test_concept_pref_labels_dict():
    c = Concept(
        uri=BASE + "X",
        labels=[
            Label(lang="en", value="English"),
            Label(lang="fr", value="French"),
            Label(lang="en", value="Alt-en", type=LabelType.ALT),
        ],
    )
    pref = c.pref_labels()
    assert pref == {"en": "English", "fr": "French"}


def test_concept_alt_labels_dict():
    c = Concept(
        uri=BASE + "X",
        labels=[
            Label(lang="en", value="Main", type=LabelType.PREF),
            Label(lang="en", value="Alt1", type=LabelType.ALT),
            Label(lang="en", value="Alt2", type=LabelType.ALT),
            Label(lang="fr", value="AltFr", type=LabelType.ALT),
        ],
    )
    alts = c.alt_labels()
    assert alts["en"] == ["Alt1", "Alt2"]
    assert alts["fr"] == ["AltFr"]


def test_taxonomy_resolve_by_handle():
    t = Taxonomy(
        concepts={BASE + "Foo": Concept(uri=BASE + "Foo")},
        handle_index={"FOO": BASE + "Foo"},
    )
    assert t.resolve("FOO") == BASE + "Foo"
    assert t.resolve("foo") == BASE + "Foo"  # case-insensitive


def test_taxonomy_resolve_by_uri():
    t = Taxonomy(
        concepts={BASE + "Foo": Concept(uri=BASE + "Foo")},
        handle_index={"FOO": BASE + "Foo"},
    )
    assert t.resolve(BASE + "Foo") == BASE + "Foo"


def test_taxonomy_resolve_missing():
    t = Taxonomy()
    assert t.resolve("NOPE") is None


def test_taxonomy_uri_to_handle():
    t = Taxonomy(
        concepts={BASE + "Foo": Concept(uri=BASE + "Foo")},
        handle_index={"FOO": BASE + "Foo"},
    )
    assert t.uri_to_handle(BASE + "Foo") == "FOO"
    assert t.uri_to_handle(BASE + "Missing") is None


def test_concept_scheme_title_fallback():
    s = ConceptScheme(uri=BASE + "MyScheme")
    assert s.title() == "MyScheme"


def test_concept_scheme_title_by_lang():
    s = ConceptScheme(
        uri=BASE + "S",
        labels=[
            Label(lang="en", value="English Title"),
            Label(lang="fr", value="Titre Français"),
        ],
    )
    assert s.title("en") == "English Title"
    assert s.title("fr") == "Titre Français"


# ── RDFClass ──────────────────────────────────────────────────────────────────


def test_rdf_class_local_name_fragment():
    c = RDFClass(uri="https://example.org/ns#Dog")
    assert c.local_name == "Dog"


def test_rdf_class_local_name_path():
    c = RDFClass(uri="https://example.org/ns/Dog")
    assert c.local_name == "Dog"


def test_rdf_class_label_by_lang():
    c = RDFClass(
        uri=BASE + "Dog",
        labels=[Label(lang="en", value="Dog"), Label(lang="fr", value="Chien")],
    )
    assert c.label("en") == "Dog"
    assert c.label("fr") == "Chien"


def test_rdf_class_label_fallback_to_first():
    c = RDFClass(uri=BASE + "Dog", labels=[Label(lang="fr", value="Chien")])
    assert c.label("en") == "Chien"


def test_rdf_class_label_fallback_to_local_name():
    c = RDFClass(uri=BASE + "Dog")
    assert c.label() == "Dog"


# ── is_builtin_uri ────────────────────────────────────────────────────────────


def test_is_builtin_uri_owl():
    assert is_builtin_uri("http://www.w3.org/2002/07/owl#Class")


def test_is_builtin_uri_rdfs():
    assert is_builtin_uri("http://www.w3.org/2000/01/rdf-schema#Resource")


def test_is_builtin_uri_user_defined():
    assert not is_builtin_uri(BASE + "Dog")


# ── Taxonomy.node_type ────────────────────────────────────────────────────────


def test_node_type_concept_only():
    t = Taxonomy(concepts={BASE + "Dog": Concept(uri=BASE + "Dog")})
    assert t.node_type(BASE + "Dog") == "concept"


def test_node_type_class_only():
    t = Taxonomy(owl_classes={BASE + "Dog": RDFClass(uri=BASE + "Dog")})
    assert t.node_type(BASE + "Dog") == "class"


def test_node_type_promoted():
    t = Taxonomy(
        concepts={BASE + "Dog": Concept(uri=BASE + "Dog")},
        owl_classes={BASE + "Dog": RDFClass(uri=BASE + "Dog")},
    )
    assert t.node_type(BASE + "Dog") == "promoted"


def test_node_type_unknown():
    t = Taxonomy()
    assert t.node_type(BASE + "Missing") == "unknown"


def test_node_type_individual():
    t = Taxonomy(owl_individuals={BASE + "Fido": OWLIndividual(uri=BASE + "Fido")})
    assert t.node_type(BASE + "Fido") == "individual"


def test_node_type_property():
    t = Taxonomy(owl_properties={BASE + "hasName": OWLProperty(uri=BASE + "hasName")})
    assert t.node_type(BASE + "hasName") == "property"


# ── Concept.local_name edge case ──────────────────────────────────────────────


def test_concept_local_name_no_separator():
    c = Concept(uri="urn:simple")
    assert c.local_name == "urn:simple"


# ── Concept.definition ────────────────────────────────────────────────────────


def test_concept_definition_found():
    c = Concept(uri=BASE + "X", definitions=[Definition("en", "An explanation")])
    assert c.definition("en") == "An explanation"


def test_concept_definition_not_found():
    c = Concept(uri=BASE + "X", definitions=[Definition("fr", "Explication")])
    assert c.definition("en") is None


def test_concept_definition_empty():
    c = Concept(uri=BASE + "X")
    assert c.definition() is None


# ── OWLProperty ───────────────────────────────────────────────────────────────


def test_owl_property_local_name_hash():
    p = OWLProperty(uri="https://example.org/onto#hasName")
    assert p.local_name == "hasName"


def test_owl_property_local_name_slash():
    p = OWLProperty(uri="https://example.org/onto/hasName")
    assert p.local_name == "hasName"


def test_owl_property_local_name_no_separator():
    p = OWLProperty(uri="urn:hasName")
    assert p.local_name == "urn:hasName"


def test_owl_property_label_by_lang():
    p = OWLProperty(uri=BASE + "p", labels=[Label("en", "has name"), Label("fr", "a nom")])
    assert p.label("en") == "has name"
    assert p.label("fr") == "a nom"


def test_owl_property_label_fallback_to_first():
    p = OWLProperty(uri=BASE + "p", labels=[Label("fr", "a nom")])
    assert p.label("en") == "a nom"


def test_owl_property_label_fallback_to_local():
    p = OWLProperty(uri=BASE + "hasName")
    assert p.label("en") == "hasName"


# ── OWLIndividual ─────────────────────────────────────────────────────────────


def test_owl_individual_local_name_hash():
    ind = OWLIndividual(uri="https://example.org/onto#Fido")
    assert ind.local_name == "Fido"


def test_owl_individual_local_name_slash():
    ind = OWLIndividual(uri="https://example.org/onto/Fido")
    assert ind.local_name == "Fido"


def test_owl_individual_local_name_no_separator():
    ind = OWLIndividual(uri="urn:Fido")
    assert ind.local_name == "urn:Fido"


def test_owl_individual_label_by_lang():
    ind = OWLIndividual(uri=BASE + "Fido", labels=[Label("en", "Fido"), Label("fr", "Fidou")])
    assert ind.label("en") == "Fido"


def test_owl_individual_label_fallback_to_first():
    ind = OWLIndividual(uri=BASE + "Fido", labels=[Label("fr", "Fidou")])
    assert ind.label("en") == "Fidou"


def test_owl_individual_label_fallback_to_local():
    ind = OWLIndividual(uri=BASE + "Fido")
    assert ind.label("en") == "Fido"


# ── RDFClass.local_name edge case ─────────────────────────────────────────────


def test_rdf_class_local_name_no_separator():
    c = RDFClass(uri="urn:Dog")
    assert c.local_name == "urn:Dog"


# ── ConceptScheme.local_name ──────────────────────────────────────────────────


def test_concept_scheme_local_name_hash():
    s = ConceptScheme(uri="https://example.org/onto#MyScheme")
    assert s.local_name == "MyScheme"


def test_concept_scheme_local_name_slash_trailing():
    s = ConceptScheme(uri="https://example.org/onto/MyScheme/")
    assert s.local_name == "MyScheme"


def test_concept_scheme_local_name_no_separator():
    s = ConceptScheme(uri="urn:MyScheme")
    assert s.local_name == "urn:MyScheme"


def test_concept_scheme_title_fallback_to_first_pref():
    s = ConceptScheme(
        uri=BASE + "S",
        labels=[Label("fr", "Titre", type=LabelType.PREF)],
    )
    assert s.title("en") == "Titre"


# ── Taxonomy.primary_scheme ───────────────────────────────────────────────────


def test_taxonomy_primary_scheme_none():
    t = Taxonomy()
    assert t.primary_scheme() is None


def test_taxonomy_primary_scheme_returns_first():
    s1 = ConceptScheme(uri=BASE + "S1")
    s2 = ConceptScheme(uri=BASE + "S2")
    t = Taxonomy(schemes={s1.uri: s1, s2.uri: s2})
    assert t.primary_scheme() is s1


# ── Taxonomy.base_uri ─────────────────────────────────────────────────────────


def test_taxonomy_base_uri_from_scheme_base_uri():
    s = ConceptScheme(uri=BASE + "S", base_uri="https://example.org/test/")
    t = Taxonomy(
        schemes={s.uri: s},
        concepts={BASE + "A": Concept(uri=BASE + "A")},
    )
    assert t.base_uri() == "https://example.org/test/"


def test_taxonomy_base_uri_derived_from_concepts():
    t = Taxonomy(
        concepts={
            "https://example.org/ns/A": Concept(uri="https://example.org/ns/A"),
            "https://example.org/ns/B": Concept(uri="https://example.org/ns/B"),
        }
    )
    assert t.base_uri() == "https://example.org/ns/"


def test_taxonomy_base_uri_derived_from_scheme_uri():
    s = ConceptScheme(uri="https://example.org/ns/MyScheme")
    t = Taxonomy(schemes={s.uri: s})
    result = t.base_uri()
    assert result in ("https://example.org/ns/", "https://example.org/ns#")


def test_taxonomy_base_uri_empty_fallback():
    t = Taxonomy()
    assert t.base_uri() == ""
