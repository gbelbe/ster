"""Unit tests for ster.tui.detail — grouping a flat DetailField list into the
sections that the Textual DetailView renders as composable blocks.

Pure logic (no Textual), so it is cheap to cover exhaustively. This is the
foundation seam of the Textual detail view: build_*_detail (logic.py) emits a
flat, separator-delimited DetailField list; group_sections turns it into the
typed sections the block widgets compose from.
"""

from __future__ import annotations

from pathlib import Path

from ster import store
from ster.nav.logic import DetailField, build_rdf_class_detail
from ster.tui.detail import DetailSection, group_sections, render_detail

_DEMO = Path(__file__).parents[2] / "ster" / "tui" / "demo.ttl"
_ZOO = "https://example.org/zoo/"


def _f(type_: str, display: str = "x") -> DetailField:
    return DetailField(key=display, display=display, value="", editable=False, meta={"type": type_})


# ── pure structure ────────────────────────────────────────────────────────────


def test_group_sections_empty() -> None:
    assert group_sections([]) == []


def test_group_sections_leading_fields_form_untitled_section() -> None:
    fields = [_f("stat", "a"), _f("separator", "Labels"), _f("rdf_label", "b")]
    sections = group_sections(fields)
    assert [s.title for s in sections] == ["", "Labels"]
    assert [f.display for f in sections[0].fields] == ["a"]
    assert [f.display for f in sections[1].fields] == ["b"]


def test_group_sections_excludes_separator_rows() -> None:
    fields = [_f("separator", "Identity"), _f("uri", "URI"), _f("separator_danger", "Danger")]
    sections = group_sections(fields)
    for s in sections:
        assert all(f.meta.get("type") not in ("separator", "separator_danger") for f in s.fields)


def test_group_sections_marks_danger_section() -> None:
    fields = [_f("separator", "Identity"), _f("separator_danger", "Danger Zone"), _f("action_del")]
    sections = group_sections(fields)
    by_title = {s.title: s for s in sections}
    assert by_title["Identity"].danger is False
    assert by_title["Danger Zone"].danger is True


# ── against a real class detail ─────────────────────────────────────────────────


def test_group_sections_class_detail_titles_in_order() -> None:
    tax = store.load(_DEMO)
    cls = next(iter(tax.owl_classes))
    sections = group_sections(build_rdf_class_detail(tax, cls, "en"))
    titles = [s.title for s in sections]
    # The class detail opens with Identity and ends with the danger zone.
    assert titles[0] == "Identity"
    assert "Labels" in titles and "Hierarchy" in titles
    assert titles[-1] == "Danger Zone"
    assert isinstance(sections[0], DetailSection)


# ── render_detail (Rich markup) ─────────────────────────────────────────────────


def test_render_detail_class_has_section_titles() -> None:
    tax = store.load(_DEMO)
    out = render_detail(tax, _ZOO + "Cat", "en")
    assert "Identity" in out and "Labels" in out and "Danger Zone" in out


def test_render_detail_danger_section_is_styled() -> None:
    tax = store.load(_DEMO)
    out = render_detail(tax, _ZOO + "Cat", "en")
    assert "[bold red]Danger Zone[/]" in out


def test_render_detail_individual_shows_property_value() -> None:
    tax = store.load(_DEMO)
    # Rex hasOwner Alice — the value must surface in the rendered detail.
    assert "Alice" in render_detail(tax, _ZOO + "Rex", "en")


def test_render_detail_unknown_uri_is_empty() -> None:
    tax = store.load(_DEMO)
    assert render_detail(tax, _ZOO + "DoesNotExist", "en") == ""
