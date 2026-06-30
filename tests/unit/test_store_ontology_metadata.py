"""Round-trip unit tests for generic ontology-level descriptive metadata (Slice 1).

Every descriptive predicate on the ``owl:Ontology`` node is captured generically
(``Taxonomy.ontology_annotations``); the well-known few are exposed through typed
accessors (``ontology_title`` etc.) backed by that same store.
"""

from __future__ import annotations

from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import DCTERMS, OWL, XSD

from ster import store
from ster.model import ConceptScheme, Label, OntologyAnnotation, Taxonomy

SKOS_SCOPE_NOTE = "http://www.w3.org/2004/02/skos/core#scopeNote"

ONT = "https://example.org/onto"
DCT = "http://purl.org/dc/terms/"


def _tax() -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = ONT
    return t


def _roundtrip(tax: Taxonomy, tmp_path: Path) -> Taxonomy:
    p = tmp_path / "onto.ttl"
    store.save(tax, p)
    return store.load(p)


def _saved_graph(tax: Taxonomy, tmp_path: Path) -> Graph:
    p = tmp_path / "onto.ttl"
    store.save(tax, p)
    g = Graph()
    g.parse(p, format="turtle")
    return g


def _values(tax: Taxonomy, predicate: str) -> list[str]:
    return [a.value for a in tax.ontology_annotations if a.predicate == predicate]


# ── generic capture ─────────────────────────────────────────────────────────────


def test_arbitrary_literal_predicate_roundtrips(tmp_path: Path) -> None:
    t = _tax()
    t.ontology_annotations.append(OntologyAnnotation(DCT + "publisher", "ACME"))
    assert _values(_roundtrip(t, tmp_path), DCT + "publisher") == ["ACME"]


def test_unknown_predicate_is_preserved(tmp_path: Path) -> None:
    # A predicate ster has no special handling for must still round-trip.
    pred = "https://custom.example/vocab#maturity"
    t = _tax()
    t.ontology_annotations.append(OntologyAnnotation(pred, "stable"))
    assert _values(_roundtrip(t, tmp_path), pred) == ["stable"]


def test_iri_valued_predicate_roundtrips_as_iri(tmp_path: Path) -> None:
    lic = "https://creativecommons.org/licenses/by/4.0/"
    t = _tax()
    t.ontology_annotations.append(OntologyAnnotation(DCT + "license", lic, is_iri=True))
    out = _roundtrip(t, tmp_path)
    assert _values(out, DCT + "license") == [lic]
    assert next(a for a in out.ontology_annotations if a.predicate == DCT + "license").is_iri
    g = _saved_graph(t, tmp_path)
    assert isinstance(next(g.objects(URIRef(ONT), DCTERMS.license)), URIRef)


def test_lang_tagged_literal_roundtrips_with_lang(tmp_path: Path) -> None:
    t = _tax()
    t.ontology_annotations.append(OntologyAnnotation(DCT + "description", "Bonjour", lang="fr"))
    out = _roundtrip(t, tmp_path)
    anno = next(a for a in out.ontology_annotations if a.predicate == DCT + "description")
    assert anno.value == "Bonjour"
    assert anno.lang == "fr"


def test_typed_literal_roundtrips_with_datatype(tmp_path: Path) -> None:
    t = _tax()
    t.ontology_annotations.append(
        OntologyAnnotation(DCT + "created", "2026-06-01", datatype=str(XSD.date))
    )
    out = _roundtrip(t, tmp_path)
    anno = next(a for a in out.ontology_annotations if a.predicate == DCT + "created")
    assert anno.value == "2026-06-01"
    assert anno.datatype == str(XSD.date)
    g = _saved_graph(t, tmp_path)
    assert next(g.objects(URIRef(ONT), DCTERMS.created)).datatype == XSD.date


def test_multiple_values_for_one_predicate_roundtrip(tmp_path: Path) -> None:
    t = _tax()
    t.ontology_annotations.append(OntologyAnnotation(DCT + "creator", "Alice"))
    t.ontology_annotations.append(OntologyAnnotation(DCT + "creator", "Bob"))
    assert set(_values(_roundtrip(t, tmp_path), DCT + "creator")) == {"Alice", "Bob"}


# ── typed accessors over the generic store ──────────────────────────────────────


def test_typed_accessors_roundtrip(tmp_path: Path) -> None:
    t = _tax()
    t.ontology_title = "Example Ontology"
    t.ontology_description = "An **example** ontology."
    t.version_info = "1.2.0"
    t.version_iri = "https://example.org/onto/1.2.0"
    out = _roundtrip(t, tmp_path)
    assert out.ontology_title == "Example Ontology"
    assert out.ontology_description == "An **example** ontology."
    assert out.version_info == "1.2.0"
    assert out.version_iri == "https://example.org/onto/1.2.0"


def test_typed_accessor_writes_into_annotation_store() -> None:
    t = _tax()
    t.ontology_title = "X"
    assert _values(t, DCT + "title") == ["X"]


def test_version_iri_is_stored_as_iri(tmp_path: Path) -> None:
    t = _tax()
    t.version_iri = "https://example.org/onto/1.0"
    g = _saved_graph(t, tmp_path)
    assert isinstance(next(g.objects(URIRef(ONT), OWL.versionIRI)), URIRef)


def test_setting_typed_accessor_replaces_not_appends() -> None:
    t = _tax()
    t.ontology_title = "First"
    t.ontology_title = "Second"
    assert _values(t, DCT + "title") == ["Second"]


# ── defaults / pre-fill / backward compatibility ────────────────────────────────


def test_absent_metadata_yields_empty_store(tmp_path: Path) -> None:
    out = _roundtrip(_tax(), tmp_path)
    assert out.ontology_annotations == []
    assert out.ontology_title is None
    assert out.version_info is None


def test_label_only_prefills_title_and_description(tmp_path: Path) -> None:
    ttl = (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        '<https://ex.org/onto> a owl:Ontology ; rdfs:label "Kai" .\n'
    )
    p = tmp_path / "onto.ttl"
    p.write_text(ttl)
    out = store.load(p)
    assert out.ontology_label == "Kai"
    assert out.ontology_title == "Kai"
    assert out.ontology_description == "Kai"


def test_load_save_load_is_idempotent(tmp_path: Path) -> None:
    t = _tax()
    t.ontology_title = "T"
    t.ontology_annotations.append(OntologyAnnotation(DCT + "creator", "Alice"))
    t.ontology_annotations.append(OntologyAnnotation(DCT + "license", "https://x/lic", is_iri=True))
    once = _roundtrip(t, tmp_path)
    twice = _roundtrip(once, tmp_path)
    assert sorted((a.predicate, a.value) for a in twice.ontology_annotations) == sorted(
        (a.predicate, a.value) for a in once.ontology_annotations
    )


# ── ConceptScheme generic extras (taxonomies) ───────────────────────────────────


def test_scheme_generic_annotations_roundtrip(tmp_path: Path) -> None:
    t = Taxonomy()
    s = ConceptScheme(uri="https://ex.org/scheme")
    s.labels.append(Label(lang="en", value="My Scheme"))
    s.annotations.append(OntologyAnnotation(SKOS_SCOPE_NOTE, "Use with care", lang="en"))
    s.annotations.append(OntologyAnnotation(DCT + "subject", "https://ex.org/topic", is_iri=True))
    t.schemes[s.uri] = s

    out = _roundtrip(t, tmp_path)
    os = out.schemes["https://ex.org/scheme"]
    preds = {a.predicate for a in os.annotations}
    assert SKOS_SCOPE_NOTE in preds
    assert DCT + "subject" in preds


def test_scheme_structured_title_not_duplicated_into_annotations(tmp_path: Path) -> None:
    t = Taxonomy()
    s = ConceptScheme(uri="https://ex.org/scheme")
    s.labels.append(Label(lang="en", value="My Scheme"))  # dcterms:title (structured)
    t.schemes[s.uri] = s

    out = _roundtrip(t, tmp_path)
    os = out.schemes["https://ex.org/scheme"]
    assert os.title("en") == "My Scheme"
    assert DCT + "title" not in {a.predicate for a in os.annotations}
