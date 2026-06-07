"""Unit tests for the shared display-language field and _available_langs OWL extension."""

from __future__ import annotations

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.nav.logic import (
    _available_langs,
    _display_lang_field,
    build_ontology_overview_fields,
)

BASE = "https://example.org/onto/"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _tax_with_owl(
    class_langs: list[str] | None = None,
    ind_langs: list[str] | None = None,
    prop_langs: list[str] | None = None,
) -> Taxonomy:
    tax = Taxonomy()
    if class_langs:
        tax.owl_classes[BASE + "A"] = RDFClass(
            uri=BASE + "A",
            labels=[Label(lang=lg, value="A") for lg in class_langs],
        )
    if ind_langs:
        tax.owl_individuals[BASE + "i"] = OWLIndividual(
            uri=BASE + "i",
            labels=[Label(lang=lg, value="i") for lg in ind_langs],
        )
    if prop_langs:
        tax.owl_properties[BASE + "p"] = OWLProperty(
            uri=BASE + "p",
            labels=[Label(lang=lg, value="p") for lg in prop_langs],
        )
    return tax


# ── _display_lang_field ───────────────────────────────────────────────────────


def test_display_lang_field_action():
    f = _display_lang_field("en")
    assert f.meta.get("action") == "pick_lang"


def test_display_lang_field_value():
    f = _display_lang_field("fr")
    assert f.value == "fr"


def test_display_lang_field_key():
    f = _display_lang_field("en")
    assert f.key == "display_lang"


def test_display_lang_field_not_editable():
    f = _display_lang_field("en")
    assert f.editable is False


# ── _available_langs OWL extension ───────────────────────────────────────────


def test_available_langs_owl_classes():
    tax = _tax_with_owl(class_langs=["en", "fr"])
    assert "fr" in _available_langs(tax)
    assert "en" in _available_langs(tax)


def test_available_langs_owl_individuals():
    tax = _tax_with_owl(ind_langs=["de"])
    assert "de" in _available_langs(tax)


def test_available_langs_owl_properties():
    tax = _tax_with_owl(prop_langs=["es"])
    assert "es" in _available_langs(tax)


def test_available_langs_combined():
    tax = _tax_with_owl(class_langs=["en"], ind_langs=["fr"], prop_langs=["de"])
    result = _available_langs(tax)
    assert set(result) == {"en", "fr", "de"}
    assert result == sorted(result)


def test_available_langs_empty_owl():
    assert _available_langs(Taxonomy()) == []


# ── build_ontology_overview_fields ───────────────────────────────────────────


def test_ontology_overview_has_display_lang():
    tax = _tax_with_owl(class_langs=["en"])
    fields = build_ontology_overview_fields(tax, "en")
    keys = [f.key for f in fields]
    assert "display_lang" in keys


def test_ontology_overview_display_lang_pick_lang():
    tax = _tax_with_owl(class_langs=["en"])
    fields = build_ontology_overview_fields(tax, "en")
    f = next(f for f in fields if f.key == "display_lang")
    assert f.meta.get("action") == "pick_lang"


def test_ontology_overview_lang_value_passed_through():
    tax = _tax_with_owl(class_langs=["fr"])
    fields = build_ontology_overview_fields(tax, "fr")
    f = next(f for f in fields if f.key == "display_lang")
    assert f.value == "fr"
