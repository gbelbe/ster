"""Generic class/property annotation capture + round-trip.

Regression for a silent data-loss bug: the loader recognised only a fixed
allow-list of predicates on classes and properties (label/comment/subClassOf/
domain/…); every *other* predicate (skos:note, rdfs:seeAlso, dcterms:source, …)
was dropped on load and therefore never written back on save. Root cause: the
class/property parse loops had no catch-all (individuals did). The fix gives
RDFClass / OWLProperty a generic ``annotations`` bucket, fed by the same
catch-all individuals already used.
"""

from __future__ import annotations

from pathlib import Path

from ster import store

_NS = "https://ex.org/o#"
_TTL = """\
@prefix : <https://ex.org/o#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

:Cat a owl:Class ;
    rdfs:label "Cat" ;
    skos:note "a feline"@en ;
    rdfs:seeAlso <https://ex.org/ref> ;
    dcterms:modified "2026-06-30"^^xsd:date .

:knows a owl:ObjectProperty ;
    rdfs:label "knows" ;
    dcterms:source <https://ex.org/src> .
"""

_SKOS_NOTE = "http://www.w3.org/2004/02/skos/core#note"
_SEE_ALSO = "http://www.w3.org/2000/01/rdf-schema#seeAlso"
_MODIFIED = "http://purl.org/dc/terms/modified"
_SOURCE = "http://purl.org/dc/terms/source"
_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


def _load(tmp_path: Path):  # noqa: ANN202
    p = tmp_path / "o.ttl"
    p.write_text(_TTL, encoding="utf-8")
    return store.load(p), p


def test_class_nonstructural_predicates_captured_regression(tmp_path: Path) -> None:
    """Regression: undeclared predicates on a class land in its annotations bucket,
    and structured/identity predicates are not duplicated into it."""
    tax, _ = _load(tmp_path)
    preds = {a.predicate for a in tax.owl_classes[f"{_NS}Cat"].annotations}
    assert {_SKOS_NOTE, _SEE_ALSO, _MODIFIED} <= preds
    assert _LABEL not in preds  # structured field, not double-counted
    assert _RDF_TYPE not in preds  # the owl:Class declaration is not an annotation


def test_property_nonstructural_predicate_captured(tmp_path: Path) -> None:
    tax, _ = _load(tmp_path)
    preds = {a.predicate for a in tax.owl_properties[f"{_NS}knows"].annotations}
    assert _SOURCE in preds
    assert _LABEL not in preds


def test_annotation_object_kinds_preserved(tmp_path: Path) -> None:
    """IRI object, lang-tagged literal, and typed literal keep their shape."""
    tax, _ = _load(tmp_path)
    by_pred = {a.predicate: a for a in tax.owl_classes[f"{_NS}Cat"].annotations}
    note = by_pred[_SKOS_NOTE]
    assert note.value == "a feline" and note.lang == "en" and not note.is_iri
    see = by_pred[_SEE_ALSO]
    assert see.is_iri and see.value == "https://ex.org/ref"
    modified = by_pred[_MODIFIED]
    assert modified.datatype.endswith("#date") and modified.value == "2026-06-30"


def test_class_and_property_annotations_round_trip(tmp_path: Path) -> None:
    """Save → reload preserves every captured annotation (the data-loss fix)."""
    tax, path = _load(tmp_path)
    store.save(tax, path)
    reloaded = store.load(path)
    cat_preds = {a.predicate for a in reloaded.owl_classes[f"{_NS}Cat"].annotations}
    knows_preds = {a.predicate for a in reloaded.owl_properties[f"{_NS}knows"].annotations}
    assert {_SKOS_NOTE, _SEE_ALSO, _MODIFIED} <= cat_preds
    assert _SOURCE in knows_preds
    note = next(
        a for a in reloaded.owl_classes[f"{_NS}Cat"].annotations if a.predicate == _SKOS_NOTE
    )
    assert note.value == "a feline" and note.lang == "en"  # stable through the trip
