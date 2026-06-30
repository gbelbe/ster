"""Unit tests for the New-TUI generic ontology annotation overview (Phase 15).

Covers the pure field-builder layer (build_tui_ontology_overview_fields) and
the annotation catalog helpers — no Textual app needed, just plain Python.
"""

from __future__ import annotations

from ster.model import OntologyAnnotation, RDFClass, Taxonomy
from ster.nav.logic import (
    build_tui_ontology_overview_fields,
    build_tui_taxonomy_overview_fields,
)

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


def test_identity_is_one_line_with_full_uri_separator_and_prefix() -> None:
    """Identity is a single row: the full base URI (with separator) + the prefix."""
    tax = _tax()  # ONT has no trailing separator → default "#"
    fields = _fields(tax)
    uri_rows = [f for f in fields if f.meta.get("type") == "uri"]
    assert len(uri_rows) == 1
    value = uri_rows[0].value
    assert value.startswith(ONT + "#")  # separator appended to the URI
    assert "prefix:" in value  # prefix shown on the same line
    assert uri_rows[0].meta.get("action") == "edit_ontology_uri"
    # No separate Prefix / Domain rows or ✎ links anymore.
    assert not any(f.meta.get("type") == "ont_prefix" for f in fields)
    assert not any(f.display.startswith("✎") for f in fields)
    assert "edit_ontology_domain" not in _actions(tax)


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


# ── taxonomy (SKOS) overview ──────────────────────────────────────────────────


def _skos_tax() -> Taxonomy:
    """A SKOS taxonomy: a scheme + concept, with a 'wv' prefix on its namespace."""
    from ster.model import Concept, ConceptScheme, Label

    NS = "https://example.org/wind/"
    t = Taxonomy()
    t.namespace_bindings["wv"] = NS
    t.schemes[NS + "scheme"] = ConceptScheme(
        uri=NS + "scheme",
        labels=[Label("fr", "Sports wind")],
        creator="Gaetan",
        created="2026-03-25",
        languages=["fr"],
        base_uri=NS,
    )
    t.concepts[NS + "Cat"] = Concept(uri=NS + "Cat", labels=[Label("fr", "Cat")])
    return t


def test_taxonomy_overview_has_no_identity_section() -> None:
    """The taxonomy overview shows only Metadata — no Identity / namespace / prefix rows."""
    fields = build_tui_taxonomy_overview_fields(_skos_tax(), "fr")
    assert not any(f.display == "Identity" for f in fields)
    assert not any(f.key in {"tax:namespace", "tax:prefix", "tax:scheme_uri"} for f in fields)


def test_taxonomy_overview_shows_editable_skos_metadata_not_ontology() -> None:
    fields = build_tui_taxonomy_overview_fields(_skos_tax(), "fr")
    by_display = {f.display: f for f in fields}
    assert by_display["title"].value == "Sports wind"
    assert by_display["creator"].value == "Gaetan"
    assert by_display["languages"].value == "fr"
    # Metadata rows are editable and target the scheme via meta["target_uri"].
    for label in ("title", "creator", "languages"):
        assert by_display[label].editable
        assert by_display[label].meta["target_uri"] == "https://example.org/wind/scheme"
    # No ontology-annotation rows here — this is the SKOS overview.
    assert not any(f.meta.get("type") == "ont_annotation" for f in fields)


def test_taxonomy_overview_handles_no_scheme() -> None:
    assert build_tui_taxonomy_overview_fields(Taxonomy(), "en")[0].value.startswith("No concept")


# ── Stats section ────────────────────────────────────────────────────────────


def _onto_with_hierarchy() -> Taxonomy:
    """A→B→C and A→D (depths 0,1,2,1), 1 obj + 1 datatype prop, 1 individual."""
    from ster.model import Label, OWLIndividual, OWLProperty, RDFClass

    ns = ONT + "#"
    t = _tax()
    t.owl_classes[ns + "A"] = RDFClass(uri=ns + "A", labels=[Label("en", "A")])
    t.owl_classes[ns + "B"] = RDFClass(uri=ns + "B", sub_class_of=[ns + "A"])
    t.owl_classes[ns + "C"] = RDFClass(
        uri=ns + "C", sub_class_of=[ns + "B"], labels=[Label("en", "C"), Label("fr", "C")]
    )
    t.owl_classes[ns + "D"] = RDFClass(uri=ns + "D", sub_class_of=[ns + "A"])
    t.owl_properties[ns + "rel"] = OWLProperty(
        uri=ns + "rel", prop_type="ObjectProperty", domains=[ns + "A"], ranges=[ns + "B"]
    )
    t.owl_properties[ns + "age"] = OWLProperty(uri=ns + "age", prop_type="DatatypeProperty")
    t.owl_individuals[ns + "x"] = OWLIndividual(uri=ns + "x", types=[ns + "C"])
    return t


def _stats(t: Taxonomy) -> dict:
    """Stats fields keyed by ``f.key`` (display labels collide across sections)."""
    from ster.nav.logic import _ontology_stats_fields

    return {f.key: f.value for f in _ontology_stats_fields(t)}


def test_stats_counts_depth_and_structure() -> None:
    s = _stats(_onto_with_hierarchy())
    assert s["st:classes"] == "4"
    assert s["st:obj_props"] == "1"
    assert s["st:dt_props"] == "1"
    assert s["st:props"] == "2"
    assert s["st:individuals"] == "1"
    assert s["st:avg_depth"] == "1.0"  # (0+1+2+1)/4
    assert s["st:max_depth"] == "2"
    assert s["st:roots"] == "1"  # A
    assert s["st:leaves"] == "2"  # C and D


def test_stats_coverage_languages_and_completeness() -> None:
    s = _stats(_onto_with_hierarchy())
    # Coverage rows render as a block bar followed by the percentage.
    assert s["st:label_cov"].endswith("50%")  # A and C labelled of 4
    assert s["st:comment_cov"].endswith("0%")
    assert s["st:langs"] == "2 (en, fr)"
    assert s["st:lang_cov:fr"].endswith("25%")  # only C has a fr label
    assert s["st:incomplete_props"] == "1"  # age
    assert s["st:unused"] == "3"  # A, B, D


def test_stats_grouped_into_subject_sections() -> None:
    titles = [
        f.display for f in _fields(_onto_with_hierarchy()) if f.meta.get("type") == "separator"
    ]
    for section in ("Classes", "Properties", "Individuals", "Quality & coverage"):
        assert section in titles, section
    # The stats subjects all come after Metadata.
    assert titles.index("Classes") > titles.index("Metadata")


def test_stats_empty_ontology_has_no_depth_rows() -> None:
    s = _stats(_tax())  # no classes
    assert s["st:classes"] == "0"
    assert "st:avg_depth" not in s  # depth rows omitted when there are no classes


# ── Errors and Warnings (semanticlint) section ────────────────────────────────


def _by_key(fields: list) -> dict:
    return {f.key: f for f in fields}


def test_lint_section_shows_error_and_warning_counts() -> None:
    lint = {"error": 2, "warning": 3, "info": 1}
    fields = build_tui_ontology_overview_fields(_tax(), "en", None, lint)
    titles = [f.display for f in fields if f.meta.get("type") == "separator"]
    assert "Errors and Warnings" in titles
    by_key = _by_key(fields)
    assert by_key["st:lint_error"].value == "2"
    assert by_key["st:lint_warning"].value == "3"
    # Info is no longer shown in this section.
    assert "st:lint_info" not in by_key


def test_lint_nonzero_rows_link_to_a_severity_filtered_modal() -> None:
    lint = {"error": 2, "warning": 3, "info": 0}
    by_key = _by_key(build_tui_ontology_overview_fields(_tax(), "en", None, lint))
    err, warn = by_key["st:lint_error"], by_key["st:lint_warning"]
    assert err.meta.get("action") == "view_lint" and err.meta.get("lint_severity") == "error"
    assert warn.meta.get("action") == "view_lint" and warn.meta.get("lint_severity") == "warning"
    # 2 errors → red; 3 warnings (< 10) → green.
    assert err.meta.get("color") == "red"
    assert warn.meta.get("color") == "green"


def test_lint_zero_rows_are_not_actionable() -> None:
    lint = {"error": 0, "warning": 0, "info": 0}
    by_key = _by_key(build_tui_ontology_overview_fields(_tax(), "en", None, lint))
    assert by_key["st:lint_error"].meta.get("action") is None  # nothing to open
    assert by_key["st:lint_warning"].meta.get("action") is None
    assert by_key["st:lint_error"].meta.get("color") == "green"  # 0 errors → green
    assert by_key["st:lint_warning"].meta.get("color") == "green"  # 0 warnings → green


def test_lint_section_sits_right_after_metadata() -> None:
    lint = {"error": 1, "warning": 0, "info": 0}
    activity = {"last": "2026-06-20", "total": 12, "last_month": 3}
    fields = build_tui_ontology_overview_fields(_tax(), "en", activity, lint)
    titles = [f.display for f in fields if f.meta.get("type") == "separator"]
    assert titles.index("Errors and Warnings") == titles.index("Metadata") + 1
    # …and therefore before the stats and Activity blocks.
    assert titles.index("Errors and Warnings") < titles.index("Classes")
    assert titles.index("Errors and Warnings") < titles.index("Activity")


def test_no_lint_section_without_file() -> None:
    fields = build_tui_ontology_overview_fields(_tax(), "en", None, None)
    assert "Errors and Warnings" not in [
        f.display for f in fields if f.meta.get("type") == "separator"
    ]


# ── Activity section (git) ────────────────────────────────────────────────────


def test_activity_section_renders_git_stats() -> None:
    activity = {"last": "2026-06-20", "total": 12, "last_month": 3}
    fields = build_tui_ontology_overview_fields(_tax(), "en", activity)
    titles = [f.display for f in fields if f.meta.get("type") == "separator"]
    assert "Activity" in titles
    d = {f.display: f.value for f in fields}
    assert d["last edited"] == "2026-06-20"
    assert d["total edits"] == "12"
    assert d["edits (last 30 days)"] == "3"


def test_no_activity_section_without_git() -> None:
    fields = build_tui_ontology_overview_fields(_tax(), "en", None)
    assert "Activity" not in [f.display for f in fields if f.meta.get("type") == "separator"]
