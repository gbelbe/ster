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
from ster.tui.detail import (
    OVERVIEW_URI,
    DetailSection,
    build_sections,
    group_sections,
    render_detail,
)

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


# ── build_sections hoists ＋ Add… to the top of each section ────────────────────


def test_build_sections_hoists_create_action_to_top_of_section() -> None:
    tax = store.load(_DEMO)
    sections = build_sections(tax, OVERVIEW_URI, "en")
    metadata = next(s for s in sections if s.title == "Metadata")
    # The "＋ Add metadata" action is the first row, above the annotation values.
    assert metadata.fields, "Metadata section should not be empty"
    assert metadata.fields[0].display.lstrip().startswith("＋")


def test_build_sections_keeps_value_order_after_the_create_action() -> None:
    # A synthetic section: value, create, value → create hoisted, values keep order.
    from ster.tui.detail import _creates_first

    a = DetailField("a", "alpha", "1", editable=True, meta={"type": "rdf_label"})
    add = DetailField("add", "＋ Add", "", editable=False, meta={"type": "action_add"})
    b = DetailField("b", "beta", "2", editable=True, meta={"type": "rdf_label"})
    assert [f.display for f in _creates_first([a, add, b])] == ["＋ Add", "alpha", "beta"]


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


# ── Quality sections relocate under "Property Fill" ────────────────────────────


def _grp(title: str = "", **kw) -> DetailSection:  # type: ignore[no-untyped-def]
    return DetailSection(title=title, **kw)


def test_issue_sections_land_under_property_fill_inside_the_box() -> None:
    """The plugin's quality sections splice in right after the 'Property Fill' section,
    still inside the Quality & Coverage group (before its group-end)."""
    from ster.nav.logic import _sep, _stat
    from ster.tui.detail_view import _insert_issue_sections

    sections = [
        _grp("Identity"),
        _grp("Quality & Coverage", group=True),
        _grp("Completeness"),
        _grp("Property Fill"),
        _grp("", group_end=True),
    ]
    issue_fields = [_sep("Issues"), _stat("stq:error", "Errors", "2")]
    out = _insert_issue_sections(sections, issue_fields)
    titles = [s.title for s in out]
    assert titles.index("Issues") == titles.index("Property Fill") + 1  # directly under it
    assert out[titles.index("Issues") + 1].group_end  # still inside the bordered box


def test_issue_sections_fall_back_to_after_identity_without_property_fill() -> None:
    """When there's no Property Fill (concept / individual / leaf class), the quality
    sections keep their after-Identity placement."""
    from ster.nav.logic import _sep, _stat
    from ster.tui.detail_view import _insert_issue_sections

    sections = [_grp("Identity"), _grp("Labels")]
    out = _insert_issue_sections(sections, [_sep("Issues"), _stat("stq:clean", "✓ no issues", "")])
    assert [s.title for s in out] == ["Identity", "Issues", "Labels"]
