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


# ── Note detail preview: first line only + open button ────────────────────────


def _class_note_fields(note: str):
    from ster.model import RDFClass, Taxonomy
    from ster.nav.logic import build_rdf_class_detail

    t = Taxonomy()
    t.owl_classes[_uri("A")] = RDFClass(uri=_uri("A"), note=note)
    return build_rdf_class_detail(t, _uri("A"), "en")


def test_multiline_note_shows_only_first_line():
    fields = _class_note_fields("# Title\nbody one\nbody two\nbody three")
    note_lines = [f for f in fields if f.meta.get("type") == "note_line"]
    assert len(note_lines) == 1
    assert note_lines[0].value == "Title"  # first line, heading marker stripped


def test_multiline_note_shows_more_hint():
    fields = _class_note_fields("# Title\na\nb\nc")  # 4 lines → 3 more
    more = [f for f in fields if f.meta.get("type") == "note_more"]
    assert len(more) == 1
    assert "3 more" in more[0].value


def test_single_line_note_has_no_more_hint():
    fields = _class_note_fields("# Only title")
    assert not [f for f in fields if f.meta.get("type") == "note_more"]
    assert len([f for f in fields if f.meta.get("type") == "note_line"]) == 1


def test_note_has_open_action_when_non_empty():
    fields = _class_note_fields("# Title\nmore")
    opens = [
        f
        for f in fields
        if f.meta.get("type") == "action_add" and f.meta.get("action") == "edit_note"
    ]
    assert opens
    assert "Open" in opens[0].display


# ── Note editor: save behaviour ───────────────────────────────────────────────


def _viewer_with_open_note(tmp_path, buffer: str):
    """A viewer with the note editor open on a fresh class, backed by a saved file."""
    from ster import store
    from ster.model import RDFClass, Taxonomy
    from ster.nav.state import NoteEditState
    from ster.nav.viewer import TaxonomyViewer

    t = Taxonomy()
    t.owl_classes[_uri("A")] = RDFClass(uri=_uri("A"))
    f = tmp_path / "v.ttl"
    store.save(t, f)
    v = TaxonomyViewer(t, f, lang="en")
    v._detail_uri = _uri("A")
    v._state = NoteEditState(
        buffer=buffer, pos=len(buffer), return_uri=_uri("A"), entity_type="class"
    )
    return v, f, t


def test_note_editor_esc_commits_in_memory(tmp_path):
    v, _f, t = _viewer_with_open_note(tmp_path, "# Note\nbody")
    v._on_note_edit(27)  # Esc
    assert t.owl_classes[_uri("A")].note == "# Note\nbody"


def test_note_editor_esc_persists_to_file(tmp_path):
    from ster import store

    v, f, _t = _viewer_with_open_note(tmp_path, "persisted on esc")
    v._on_note_edit(27)  # Esc
    assert store.load(f).owl_classes[_uri("A")].note == "persisted on esc"


def test_note_editor_esc_returns_to_detail(tmp_path):
    from ster.nav.state import DetailState

    v, _f, _t = _viewer_with_open_note(tmp_path, "x")
    v._on_note_edit(27)  # Esc
    assert isinstance(v._state, DetailState)


def test_note_editor_ctrl_s_persists_to_file(tmp_path):
    from ster import store

    v, f, _t = _viewer_with_open_note(tmp_path, "saved via ctrl s")
    v._on_note_edit(19)  # Ctrl+S
    assert store.load(f).owl_classes[_uri("A")].note == "saved via ctrl s"


def test_note_editor_inserts_accented_char(tmp_path):
    # Regression: accents were mangled because input was read byte-wise.
    # Given the real codepoint, the editor inserts the character intact.
    from ster.nav.state import NoteEditState

    v, _f, _t = _viewer_with_open_note(tmp_path, "caf")
    v._on_note_edit(0x00E9)  # é
    assert isinstance(v._state, NoteEditState)
    assert v._state.buffer == "café"


def test_note_editor_inserts_symbol_above_latin1(tmp_path):
    from ster.nav.state import NoteEditState

    v, _f, _t = _viewer_with_open_note(tmp_path, "price ")
    v._on_note_edit(0x20AC)  # €
    assert isinstance(v._state, NoteEditState)
    assert v._state.buffer == "price €"


def test_note_editor_saves_property_note(tmp_path):
    # The commit path differs per entity kind; cover the property branch.
    from ster import store
    from ster.model import OWLProperty, Taxonomy
    from ster.nav.state import NoteEditState
    from ster.nav.viewer import TaxonomyViewer

    t = Taxonomy()
    t.owl_properties[_uri("p")] = OWLProperty(uri=_uri("p"))
    f = tmp_path / "v.ttl"
    store.save(t, f)
    v = TaxonomyViewer(t, f, lang="en")
    v._detail_uri = _uri("p")
    v._state = NoteEditState(
        buffer="prop note", pos=9, return_uri=_uri("p"), entity_type="property"
    )
    v._on_note_edit(19)  # Ctrl+S
    assert store.load(f).owl_properties[_uri("p")].note == "prop note"
