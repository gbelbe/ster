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
    field_markup,
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
    assert "Identity" in out and "Labels" in out


def test_detail_view_omits_danger_note_and_schema_add() -> None:
    """The detail view drops the Danger Zone + Note (markdown) sections and the
    schema:* add actions (for classes and individuals alike); delete/convert stay on
    the right-click context menu."""
    tax = store.load(_DEMO)
    for uri in (_ZOO + "Cat", _ZOO + "Rex"):  # a class and an individual
        sections = build_sections(tax, uri, "en")
        titles = {s.title for s in sections}
        assert "Danger Zone" not in titles
        assert "Note (markdown)" not in titles
        actions = [f.meta.get("action") for s in sections for f in s.fields]
        assert not any(a and a.startswith("add_schema") for a in actions)
        # the destructive actions are gone from the detail panel entirely
        assert "delete_class" not in actions and "delete_individual" not in actions
        assert "edit_note" not in actions and "delete_note" not in actions


def test_class_properties_are_editable_and_have_no_add_actions() -> None:
    """The class Properties section drops the '+ Add …' actions; each direct property
    row is an editable action (edit_property → the edit modal)."""
    tax = store.load(_DEMO)
    sections = build_sections(tax, _ZOO + "Animal", "en")  # Animal has hasOwner/hasAge
    actions = [f.meta.get("action") for s in sections for f in s.fields]
    assert "add_class_property" not in actions  # no more "+ Add relationship/attribute"
    props = next(s for s in sections if s.title == "Properties")
    edit_rows = [f for f in props.fields if f.meta.get("action") == "edit_property"]
    assert edit_rows, "direct property rows should offer edit_property"
    assert all(f.meta.get("uri") for f in edit_rows)  # each names its property


def test_inherited_properties_render_as_collapsible_grouped_by_parent() -> None:
    """Inherited properties are tucked into a collapsed 'N inherited properties'
    disclosure, grouped under an 'inherited from <ancestor>:' sub-header."""
    tax = store.load(_DEMO)
    sections = build_sections(tax, _ZOO + "Dog", "en")  # Dog inherits hasOwner/hasAge from Animal
    collapsible = next((s for s in sections if s.collapsible), None)
    assert collapsible is not None and "inherited" in collapsible.title
    subtitles = [s.title for s in sections if s.title.startswith("inherited from")]
    assert any("Animal" in s for s in subtitles)


def test_class_detail_omits_hierarchy_section() -> None:
    """The OWL class detail drops its Hierarchy section (subClassOf + inline add/remove);
    superclass edits live in the tree + context menu. Concepts keep their Hierarchy."""
    tax = store.load(_DEMO)
    class_titles = {s.title for s in build_sections(tax, _ZOO + "Cat", "en")}
    assert "Hierarchy" not in class_titles
    class_actions = [
        f.meta.get("action") for s in build_sections(tax, _ZOO + "Cat", "en") for f in s.fields
    ]
    assert "link_superclass" not in class_actions and "remove_superclass" not in class_actions


def test_render_detail_individual_shows_property_value() -> None:
    tax = store.load(_DEMO)
    # Rex hasOwner Alice — the value must surface in the rendered detail.
    assert "Alice" in render_detail(tax, _ZOO + "Rex", "en")


def test_render_detail_unknown_uri_is_empty() -> None:
    tax = store.load(_DEMO)
    assert render_detail(tax, _ZOO + "DoesNotExist", "en") == ""


def test_markdown_value_row_autolinks_bare_urls_into_clickable_links() -> None:
    """A bare URL in a rendered Markdown value becomes a clickable hyperlink (OSC 8) —
    Rich only linkifies explicit [text](url) markup, so the row auto-links first."""
    import io

    from rich.console import Console

    from ster.tui.detail_view import _markdown_row_content, _renders_markdown
    from ster.tui.urls import autolink_urls

    field = DetailField(
        "k", "Comment", "See https://example.org now", editable=True, meta={"type": "ind_comment"}
    )
    assert _renders_markdown(field)
    # the bare URL is turned into a Markdown link before rendering …
    assert autolink_urls(field.value) == "See [https://example.org](https://example.org) now"
    # … so Rich emits a terminal hyperlink (OSC 8) for it → clickable
    con = Console(file=io.StringIO(), force_terminal=True, width=80)
    con.print(_markdown_row_content(field, actionable=True))
    assert "\x1b]8;" in con.file.getvalue()


def test_property_row_markup_has_no_colon_before_type() -> None:
    """A property row (plain_value meta) renders 'name (Type)' with a space, no ': ';
    ordinary rows keep the 'label: value' colon."""
    prop_row = DetailField(
        "classprop:x", "hasName", "(Object Prop.)", editable=False, meta={"plain_value": True}
    )
    assert field_markup(prop_row) == "hasName (Object Prop.)"
    plain_row = DetailField("k", "label", "v", editable=False, meta={})
    assert field_markup(plain_row) == "label: v"


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
