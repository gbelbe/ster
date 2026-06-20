"""Unit tests for the New-TUI generic ontology annotation overview (Phase 15).

Covers the pure field-builder layer (build_tui_ontology_overview_fields) and
the annotation catalog helpers — no Textual app needed, just plain Python.
"""

from __future__ import annotations

from ster.model import OntologyAnnotation, RDFClass, Taxonomy
from ster.nav.logic import build_tui_ontology_overview_fields

ONT = "https://example.org/onto"
DCT = "http://purl.org/dc/terms/"
OWL_NS = "http://www.w3.org/2002/07/owl#"
VANN = "http://purl.org/vocab/vann/"
FOAF = "http://xmlns.com/foaf/0.1/"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"


def _tax(**annos: str) -> Taxonomy:
    """Minimal taxonomy with ontology_uri and optional single-valued annotations."""
    t = Taxonomy()
    t.ontology_uri = ONT
    for pred, val in annos.items():
        t.ontology_annotations.append(OntologyAnnotation(pred, val))
    return t


def _fields(tax: Taxonomy) -> list:
    return build_tui_ontology_overview_fields(tax, "en")


def _types(tax: Taxonomy) -> set[str]:
    return {f.meta.get("type", "") for f in _fields(tax)}


def _actions(tax: Taxonomy) -> set[str]:
    return {f.meta.get("action", "") for f in _fields(tax)}


# ── annotation rows ────────────────────────────────────────────────────────────


def test_title_annotation_produces_editable_row() -> None:
    t = _tax()
    t.ontology_title = "My Onto"
    fields = _fields(t)
    row = next(
        f for f in fields if f.meta.get("type") == "ont_annotation" and "title" in f.display.lower()
    )
    assert row.editable
    assert row.value == "My Onto"


def test_description_annotation_produces_editable_row() -> None:
    t = _tax()
    t.ontology_description = "About things."
    fields = _fields(t)
    row = next(
        f
        for f in fields
        if f.meta.get("type") == "ont_annotation" and "description" in f.display.lower()
    )
    assert row.editable
    assert row.value == "About things."


def test_version_info_annotation_produces_editable_row() -> None:
    t = _tax()
    t.version_info = "1.0.0"
    fields = _fields(t)
    row = next(f for f in fields if f.meta.get("predicate") == OWL_NS + "versionInfo")
    assert row.editable
    assert row.value == "1.0.0"


def test_version_iri_annotation_produces_editable_row() -> None:
    t = _tax()
    t.version_iri = "https://example.org/onto/1.0"
    fields = _fields(t)
    row = next(f for f in fields if f.meta.get("predicate") == OWL_NS + "versionIRI")
    assert row.editable
    assert row.value == "https://example.org/onto/1.0"


def test_prior_version_annotation_produces_editable_row() -> None:
    t = _tax()
    t.prior_version = "https://example.org/onto/0.9"
    fields = _fields(t)
    row = next(f for f in fields if f.meta.get("predicate") == OWL_NS + "priorVersion")
    assert row.editable


def test_creator_annotation_produces_editable_row() -> None:
    t = _tax(**{DCT + "creator": "Alice"})
    fields = _fields(t)
    row = next(f for f in fields if f.meta.get("predicate") == DCT + "creator")
    assert row.editable
    assert row.value == "Alice"


def test_generic_unknown_annotation_produces_row() -> None:
    pred = "https://custom.example/vocab#maturity"
    t = _tax(**{pred: "stable"})
    fields = _fields(t)
    row = next(f for f in fields if f.meta.get("predicate") == pred)
    assert row.value == "stable"


# ── multi-valued annotations ───────────────────────────────────────────────────


def test_multivalued_annotation_produces_one_row_per_value() -> None:
    t = _tax()
    t.ontology_annotations.append(OntologyAnnotation(DCT + "creator", "Alice"))
    t.ontology_annotations.append(OntologyAnnotation(DCT + "creator", "Bob"))
    fields = _fields(t)
    # Each annotation produces a value row (type=ont_annotation) + a remove row.
    # We count only the editable value rows here.
    creator_rows = [
        f
        for f in fields
        if f.meta.get("type") == "ont_annotation" and f.meta.get("predicate") == DCT + "creator"
    ]
    assert len(creator_rows) == 2
    assert {r.value for r in creator_rows} == {"Alice", "Bob"}


def test_each_value_row_has_a_remove_action() -> None:
    t = _tax()
    t.ontology_annotations.append(OntologyAnnotation(DCT + "creator", "Alice"))
    t.ontology_annotations.append(OntologyAnnotation(DCT + "creator", "Bob"))
    fields = _fields(t)
    remove_rows = [
        f
        for f in fields
        if f.meta.get("action") == "remove_ont_annotation"
        and f.meta.get("predicate") == DCT + "creator"
    ]
    assert len(remove_rows) == 2
    assert {r.meta.get("value") for r in remove_rows} == {"Alice", "Bob"}


# ── add metadata action ────────────────────────────────────────────────────────


def test_add_metadata_action_row_is_present() -> None:
    assert "add_ont_annotation" in _actions(_tax())


def test_add_metadata_catalog_excludes_already_present_predicates() -> None:
    from ster.nav.logic import annotation_catalog_options

    t = _tax()
    t.ontology_title = "X"  # dct:title already present
    options = annotation_catalog_options(t)
    predicate_uris = {pred for pred, _label in options}
    assert DCT + "title" not in predicate_uris  # already present → excluded
    assert DCT + "creator" in predicate_uris  # not present → included


def test_add_metadata_catalog_uses_prefixed_labels() -> None:
    from ster.nav.logic import annotation_catalog_options

    options = annotation_catalog_options(_tax())
    labels = [label for _pred, label in options]
    assert any("dcterms:creator" in lbl for lbl in labels)
    assert any("dcterms:license" in lbl for lbl in labels)
    assert any("vann:" in lbl for lbl in labels)


# ── no class / property rows ───────────────────────────────────────────────────


def test_overview_contains_no_class_rows() -> None:
    t = _tax()
    t.owl_classes["https://example.org/onto#Animal"] = RDFClass(
        uri="https://example.org/onto#Animal"
    )
    fields = _fields(t)
    # No row should have a value equal to a class URI or display a class label
    class_uris = set(t.owl_classes)
    assert not any(f.value in class_uris for f in fields)


def test_overview_contains_no_property_rows() -> None:
    t = _tax()
    fields = _fields(t)
    assert not any(f.meta.get("type") == "property_row" for f in fields)


# ── identity + action rows still present ──────────────────────────────────────


def test_identity_section_uri_row_present() -> None:
    fields = _fields(_tax())
    assert any(f.meta.get("type") == "uri" for f in fields)


def test_edit_base_uri_action_present() -> None:
    assert "edit_ontology_uri" in _actions(_tax())


def test_view_graph_action_present() -> None:
    assert "view_ontology_graph" in _actions(_tax())
