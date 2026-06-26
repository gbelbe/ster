"""Configured-languages drive the label/description add affordances and stats."""

from __future__ import annotations

from ster.model import Definition, Label, RDFClass, Taxonomy
from ster.nav.logic import (
    _ontology_stats_fields,
    build_rdf_class_detail,
)

NS = "https://ex.org/onto#"


def _class_tax() -> Taxonomy:
    t = Taxonomy()
    t.owl_classes[NS + "Wheel"] = RDFClass(
        uri=NS + "Wheel",
        labels=[Label("en", "Wheel"), Label("de", "Rad")],  # de is present but not configured
        comments=[Definition("en", "round")],
    )
    return t


def _add_langs(fields, action: str) -> set[str]:
    return {f.meta.get("lang") for f in fields if f.meta.get("action") == action}


def test_add_label_row_per_missing_configured_language() -> None:
    fields = build_rdf_class_detail(_class_tax(), NS + "Wheel", "en", ["en", "fr", "es"])
    # en already has a label → no add row; fr and es are missing → one each.
    assert _add_langs(fields, "add_rdf_label") == {"fr", "es"}


def test_non_configured_existing_label_is_shown_without_add() -> None:
    fields = build_rdf_class_detail(_class_tax(), NS + "Wheel", "en", ["en", "fr"])
    # The de label (non-configured) is still rendered as an editable row …
    de_rows = [
        f for f in fields if f.meta.get("type") == "rdf_label" and f.meta.get("lang") == "de"
    ]
    assert de_rows and de_rows[0].value == "Rad"
    # … but no "+ Add label [de]" affordance is offered.
    assert "de" not in _add_langs(fields, "add_rdf_label")


def test_comment_add_rows_follow_configured_languages() -> None:
    fields = build_rdf_class_detail(_class_tax(), NS + "Wheel", "en", ["en", "fr"])
    assert _add_langs(fields, "add_rdf_comment") == {"fr"}  # en present, fr missing


def test_no_configured_langs_falls_back_to_display_lang() -> None:
    # None / empty configured → behave as before (just the display language).
    fields = build_rdf_class_detail(_class_tax(), NS + "Wheel", "fr", None)
    assert _add_langs(fields, "add_rdf_label") == {"fr"}


def test_quality_color_thresholds() -> None:
    from ster.nav.logic import _quality_color

    assert _quality_color(0) == "red"
    assert _quality_color(49) == "red"
    assert _quality_color(50) == "orange"
    assert _quality_color(79) == "orange"
    assert _quality_color(80) == "green"
    assert _quality_color(100) == "green"


def test_lint_colors_follow_their_own_rules() -> None:
    from ster.nav.logic import _errors_color, _warnings_color

    assert _errors_color(0) == "green" and _errors_color(1) == "red"
    assert _warnings_color(9) == "green"
    assert _warnings_color(10) == "orange" and _warnings_color(49) == "orange"
    assert _warnings_color(50) == "red"


def test_coverage_rows_carry_quality_color() -> None:
    from ster.nav.logic import _ontology_stats_fields

    by_key = {f.key: f for f in _ontology_stats_fields(_class_tax(), ["en", "fr"])}
    assert by_key["st:lang_cov:en"].meta.get("color") == "green"  # 100%
    assert by_key["st:lang_cov:fr"].meta.get("color") == "red"  # 0%


def test_stats_coverage_uses_configured_languages() -> None:
    by_key = {f.key: f for f in _ontology_stats_fields(_class_tax(), ["en", "fr"])}
    # A coverage bar per configured language, even one absent from the data (fr).
    assert by_key["st:lang_cov:en"].value.endswith("100%")  # the one class has en
    assert by_key["st:lang_cov:fr"].value.endswith("0%")
    assert "st:lang_cov:de" not in by_key  # de present in data but not configured
    assert by_key["st:langs"].value == "2 (en, fr)"
