"""Unit tests for ns1:note annotation property on OWL entities."""

from __future__ import annotations

import tempfile
from pathlib import Path

NS = "https://example.org/onto#"


def _uri(name: str) -> str:
    return NS + name


# ── Model defaults ────────────────────────────────────────────────────────────


def test_rdfclass_has_note_field():
    from ster.model import RDFClass

    assert RDFClass(uri=_uri("A")).note == ""


def test_individual_has_note_field():
    from ster.model import OWLIndividual

    assert OWLIndividual(uri=_uri("Ind")).note == ""


def test_property_has_note_field():
    from ster.model import OWLProperty

    assert OWLProperty(uri=_uri("prop")).note == ""


# ── Store round-trips ─────────────────────────────────────────────────────────


def _roundtrip(taxonomy):
    from ster import store

    with tempfile.NamedTemporaryFile(suffix=".ttl", delete=False) as f:
        tmp = Path(f.name)
    store.save(taxonomy, tmp)
    result = store.load(tmp)
    tmp.unlink(missing_ok=True)
    return result


def test_save_load_class_note():
    from ster.model import RDFClass, Taxonomy

    t = Taxonomy()
    t.owl_classes[_uri("A")] = RDFClass(uri=_uri("A"), note="hello world")
    reloaded = _roundtrip(t)
    assert reloaded.owl_classes[_uri("A")].note == "hello world"


def test_save_load_individual_note():
    from ster.model import OWLIndividual, RDFClass, Taxonomy

    t = Taxonomy()
    t.owl_classes[_uri("C")] = RDFClass(uri=_uri("C"))
    t.owl_individuals[_uri("Ind")] = OWLIndividual(
        uri=_uri("Ind"), types=[_uri("C")], note="ind note"
    )
    reloaded = _roundtrip(t)
    assert reloaded.owl_individuals[_uri("Ind")].note == "ind note"


def test_save_load_property_note():
    from ster.model import OWLProperty, Taxonomy

    t = Taxonomy()
    t.owl_properties[_uri("prop")] = OWLProperty(uri=_uri("prop"), note="prop note")
    reloaded = _roundtrip(t)
    assert reloaded.owl_properties[_uri("prop")].note == "prop note"


def test_note_with_newlines_preserved():
    from ster.model import RDFClass, Taxonomy

    t = Taxonomy()
    multiline = "line1\nline2\nline3"
    t.owl_classes[_uri("A")] = RDFClass(uri=_uri("A"), note=multiline)
    reloaded = _roundtrip(t)
    assert reloaded.owl_classes[_uri("A")].note == multiline


def test_empty_note_not_serialised():
    from rdflib import URIRef

    from ster import store
    from ster.model import RDFClass, Taxonomy

    t = Taxonomy()
    t.owl_classes[_uri("A")] = RDFClass(uri=_uri("A"), note="")
    g = store.taxonomy_to_graph(t)
    note_pred = URIRef(store.NOTE_PROPERTY_URI)
    triples = list(g.triples((None, note_pred, None)))
    assert triples == []


# ── Markdown renderer ─────────────────────────────────────────────────────────


def test_render_heading():
    from ster.nav.logic import render_note_markdown

    result = render_note_markdown("# Title")
    assert result == [("Title", True)]


def test_render_heading_strips_markers():
    from ster.nav.logic import render_note_markdown

    result = render_note_markdown("## Section")
    assert result == [("Section", True)]


def test_render_bold_stripped():
    from ster.nav.logic import render_note_markdown

    result = render_note_markdown("**bold** text")
    line, is_bold = result[0]
    assert "bold" in line
    assert "**" not in line


def test_render_bullet():
    from ster.nav.logic import render_note_markdown

    result = render_note_markdown("- item one")
    assert result == [("• item one", False)]


def test_render_bullet_star():
    from ster.nav.logic import render_note_markdown

    result = render_note_markdown("* item two")
    assert result == [("• item two", False)]


def test_render_plain_passthrough():
    from ster.nav.logic import render_note_markdown

    result = render_note_markdown("plain text")
    assert result == [("plain text", False)]


def test_render_multiline():
    from ster.nav.logic import render_note_markdown

    text = "# Title\n- item\nplain"
    result = render_note_markdown(text)
    assert len(result) == 3
    assert result[0] == ("Title", True)
    assert result[1] == ("• item", False)
    assert result[2] == ("plain", False)


# ── Detail field builders ─────────────────────────────────────────────────────


def test_class_detail_has_note_section():
    from ster.model import RDFClass, Taxonomy
    from ster.nav.logic import build_rdf_class_detail

    t = Taxonomy()
    t.owl_classes[_uri("A")] = RDFClass(uri=_uri("A"), note="# Hello")
    fields = build_rdf_class_detail(t, _uri("A"), "en")
    types = [f.meta.get("type") for f in fields]
    assert "note_line" in types


def test_individual_detail_has_note_section():
    from ster.model import OWLIndividual, Taxonomy
    from ster.nav.logic import build_individual_detail

    t = Taxonomy()
    t.owl_individuals[_uri("Ind")] = OWLIndividual(uri=_uri("Ind"), note="# Hello")
    fields = build_individual_detail(t, _uri("Ind"), "en")
    types = [f.meta.get("type") for f in fields]
    assert "note_line" in types


def test_property_detail_has_note_section():
    from ster.model import OWLProperty, Taxonomy
    from ster.nav.logic import build_property_detail

    t = Taxonomy()
    t.owl_properties[_uri("prop")] = OWLProperty(uri=_uri("prop"), note="# Hello")
    fields = build_property_detail(t, _uri("prop"), "en")
    types = [f.meta.get("type") for f in fields]
    assert "note_line" in types


def test_class_detail_shows_edit_action_when_empty():
    from ster.model import RDFClass, Taxonomy
    from ster.nav.logic import build_rdf_class_detail

    t = Taxonomy()
    t.owl_classes[_uri("A")] = RDFClass(uri=_uri("A"), note="")
    fields = build_rdf_class_detail(t, _uri("A"), "en")
    actions = [f.meta.get("action") for f in fields if f.meta.get("action")]
    assert "edit_note" in actions


def test_class_detail_shows_delete_action_when_has_note():
    from ster.model import RDFClass, Taxonomy
    from ster.nav.logic import build_rdf_class_detail

    t = Taxonomy()
    t.owl_classes[_uri("A")] = RDFClass(uri=_uri("A"), note="some note")
    fields = build_rdf_class_detail(t, _uri("A"), "en")
    actions = [f.meta.get("action") for f in fields if f.meta.get("action")]
    assert "delete_note" in actions
    assert "edit_note" in actions
