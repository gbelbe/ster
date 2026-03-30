"""Tests for the interactive taxonomy navigator and shell (non-curses parts)."""
from __future__ import annotations
import pytest
from pathlib import Path
from ster.model import Concept, ConceptScheme, Definition, Label, LabelType, Taxonomy
from ster.handles import assign_handles
from ster import operations
from ster.nav import (
    TaxonomyShell, TaxonomyViewer,
    _breadcrumb, _children, _parent_uri,
    flatten_tree, build_detail_fields, build_scheme_fields,
    _count_descendants,
)

BASE = "https://example.org/test/"


@pytest.fixture
def shell(simple_taxonomy, tmp_path) -> TaxonomyShell:
    f = tmp_path / "vocab.ttl"
    f.write_text("")
    return TaxonomyShell(simple_taxonomy, f, lang="en")


# ── navigation helpers ────────────────────────────────────────────────────────

def test_children_root(simple_taxonomy):
    kids = _children(simple_taxonomy, None)
    assert BASE + "Top" in kids


def test_children_concept(simple_taxonomy):
    kids = _children(simple_taxonomy, BASE + "Top")
    assert BASE + "Child1" in kids
    assert BASE + "Child2" in kids


def test_children_leaf(simple_taxonomy):
    assert _children(simple_taxonomy, BASE + "Child2") == []


def test_parent_uri_at_root(simple_taxonomy):
    assert _parent_uri(simple_taxonomy, None) is None


def test_parent_uri_child(simple_taxonomy):
    assert _parent_uri(simple_taxonomy, BASE + "Child1") == BASE + "Top"


def test_breadcrumb_root(simple_taxonomy):
    assert _breadcrumb(simple_taxonomy, None) == "/"


def test_breadcrumb_child(simple_taxonomy):
    bc = _breadcrumb(simple_taxonomy, BASE + "Child1")
    assert "[TOP]" in bc or "[" in bc   # handle varies; path contains at least one handle
    assert bc.startswith("/")


# ── shell prompt ──────────────────────────────────────────────────────────────

def test_initial_prompt_is_root(shell):
    assert shell.prompt == "/ $ "


def test_cd_updates_prompt(shell, simple_taxonomy):
    handle = simple_taxonomy.uri_to_handle(BASE + "Top")
    shell.onecmd(f"cd {handle}")
    assert f"[{handle}]" in shell.prompt


def test_cd_dotdot_goes_up(shell, simple_taxonomy):
    handle_top = simple_taxonomy.uri_to_handle(BASE + "Top")
    handle_child = simple_taxonomy.uri_to_handle(BASE + "Child1")
    shell.onecmd(f"cd {handle_top}")
    shell.onecmd(f"cd {handle_child}")
    shell.onecmd("cd ..")
    assert shell._cwd == BASE + "Top"


def test_cd_slash_goes_to_root(shell, simple_taxonomy):
    handle = simple_taxonomy.uri_to_handle(BASE + "Top")
    shell.onecmd(f"cd {handle}")
    shell.onecmd("cd /")
    assert shell._cwd is None
    assert shell.prompt == "/ $ "


def test_cd_bad_handle_stays_put(shell, capsys):
    shell.onecmd("cd NOPE")
    assert shell._cwd is None


# ── pwd ───────────────────────────────────────────────────────────────────────

def test_pwd_at_root(shell, capsys):
    shell.onecmd("pwd")
    out = capsys.readouterr().out
    assert "/" in out


# ── add ───────────────────────────────────────────────────────────────────────

def test_add_at_cwd(shell, simple_taxonomy):
    handle_top = simple_taxonomy.uri_to_handle(BASE + "Top")
    shell.onecmd(f"cd {handle_top}")
    shell.onecmd('add NewConcept --en "New Concept"')
    assert BASE + "NewConcept" in simple_taxonomy.concepts
    assert BASE + "NewConcept" in simple_taxonomy.concepts[BASE + "Top"].narrower


def test_add_default_label(shell, simple_taxonomy):
    shell.onecmd("add SpadeRudder")
    c = simple_taxonomy.concepts.get(BASE + "SpadeRudder")
    assert c is not None
    assert c.pref_label("en") == "Spade Rudder"


# ── rm ────────────────────────────────────────────────────────────────────────

def test_rm_leaf(shell, simple_taxonomy):
    handle = simple_taxonomy.uri_to_handle(BASE + "Child2")
    shell.onecmd(f"rm {handle} -y")
    assert BASE + "Child2" not in simple_taxonomy.concepts


def test_rm_cascade(shell, simple_taxonomy):
    handle = simple_taxonomy.uri_to_handle(BASE + "Child1")
    shell.onecmd(f"rm {handle} --cascade -y")
    assert BASE + "Child1" not in simple_taxonomy.concepts
    assert BASE + "Grandchild" not in simple_taxonomy.concepts


def test_rm_current_cwd_resets_to_root(shell, simple_taxonomy):
    handle = simple_taxonomy.uri_to_handle(BASE + "Child2")
    shell.onecmd(f"cd {handle}")
    shell.onecmd(f"rm {handle} -y")
    assert shell._cwd is None


# ── mv ────────────────────────────────────────────────────────────────────────

def test_mv_reparent(shell, simple_taxonomy):
    h_child2 = simple_taxonomy.uri_to_handle(BASE + "Child2")
    h_child1 = simple_taxonomy.uri_to_handle(BASE + "Child1")
    shell.onecmd(f"mv {h_child2} --parent {h_child1}")
    assert BASE + "Child2" in simple_taxonomy.concepts[BASE + "Child1"].narrower


def test_mv_to_top_level(shell, simple_taxonomy):
    h_gc = simple_taxonomy.uri_to_handle(BASE + "Grandchild")
    shell.onecmd(f"mv {h_gc} /")
    scheme = simple_taxonomy.primary_scheme()
    assert BASE + "Grandchild" in scheme.top_concepts


# ── label / define ────────────────────────────────────────────────────────────

def test_label_command(shell, simple_taxonomy):
    handle = simple_taxonomy.uri_to_handle(BASE + "Top")
    shell.onecmd(f'label {handle} de "Oberbegriff"')
    assert simple_taxonomy.concepts[BASE + "Top"].pref_label("de") == "Oberbegriff"


def test_define_command(shell, simple_taxonomy):
    handle = simple_taxonomy.uri_to_handle(BASE + "Child2")
    shell.onecmd(f'define {handle} en "A definition."')
    assert simple_taxonomy.concepts[BASE + "Child2"].definition("en") == "A definition."


# ── quit ──────────────────────────────────────────────────────────────────────

def test_quit_returns_true(shell):
    assert shell.onecmd("quit") is True


def test_exit_returns_true(shell):
    assert shell.onecmd("exit") is True


# ── TaxonomyViewer helpers ────────────────────────────────────────────────────

@pytest.fixture
def viewer(simple_taxonomy, tmp_path, monkeypatch) -> TaxonomyViewer:
    f = tmp_path / "vocab.ttl"
    f.write_text("")
    import ster.nav as nav_mod
    monkeypatch.setattr(nav_mod, "_load_prefs", lambda: {})
    return TaxonomyViewer(simple_taxonomy, f, lang="en")


def test_flatten_tree_contains_all_concepts(simple_taxonomy):
    lines = flatten_tree(simple_taxonomy)
    uris = {l.uri for l in lines}
    assert BASE + "Top" in uris
    assert BASE + "Child1" in uris
    assert BASE + "Child2" in uris
    assert BASE + "Grandchild" in uris


def test_flatten_tree_depth_order(simple_taxonomy):
    lines = flatten_tree(simple_taxonomy)
    by_uri = {l.uri: l.depth for l in lines}
    assert by_uri[BASE + "Top"] == 0
    assert by_uri[BASE + "Child1"] == 1
    assert by_uri[BASE + "Grandchild"] == 2


def test_flatten_tree_prefix_chars(simple_taxonomy):
    lines = flatten_tree(simple_taxonomy)
    top_line = next(l for l in lines if l.uri == BASE + "Top")
    assert "└" in top_line.prefix or "├" in top_line.prefix


def test_build_detail_fields_includes_pref_label(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    keys = [f.key for f in fields]
    assert "pref:en" in keys
    assert "pref:fr" in keys


def test_build_detail_fields_includes_definition(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    keys = [f.key for f in fields]
    assert "def:en" in keys


def test_build_detail_fields_narrower_read_only(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    narrower_fields = [f for f in fields if "narrower" in f.key]
    assert len(narrower_fields) == 2
    assert all(not f.editable for f in narrower_fields)


def test_viewer_initial_cursor(viewer):
    assert viewer._cursor == 0
    # Viewer starts in WELCOME mode (splash screen); transitions to TREE on any key
    assert viewer._mode == TaxonomyViewer._WELCOME


def test_viewer_open_detail(viewer, simple_taxonomy):
    # flat[0] is now the action row; use flat[1] (scheme row) instead
    viewer._cursor = 1
    viewer._open_detail()
    assert viewer._mode == TaxonomyViewer._DETAIL
    assert viewer._detail_uri == viewer._flat[1].uri
    assert len(viewer._detail_fields) > 0


def test_viewer_back_from_detail(viewer):
    viewer._mode = TaxonomyViewer._TREE  # skip welcome for this test
    viewer._cursor = 1  # skip action row at index 0
    viewer._open_detail()
    viewer._back()
    assert viewer._mode == TaxonomyViewer._TREE


def test_viewer_history_preserves_cursor(viewer):
    viewer._cursor = 2
    viewer._open_detail()
    viewer._back()
    assert viewer._cursor == 2


def test_viewer_commit_edit_updates_label(viewer, simple_taxonomy):
    # Position on Top concept's pref:en field (cursor=2: action at 0, scheme at 1, Top at 2)
    viewer._cursor = 2
    viewer._open_detail()
    fields = viewer._detail_fields
    pref_idx = next(i for i, f in enumerate(fields) if f.key == "pref:en")
    viewer._field_cursor = pref_idx
    viewer._edit_value = "Updated Top"
    viewer._edit_pos   = len("Updated Top")
    viewer._commit_edit()
    assert simple_taxonomy.concepts[BASE + "Top"].pref_label("en") == "Updated Top"


# ── multi-scheme flatten_tree ─────────────────────────────────────────────────

def test_flatten_tree_multiple_schemes():
    """All schemes appear as is_scheme rows; concepts under each scheme follow."""
    t = Taxonomy()
    s1 = ConceptScheme(uri=BASE + "S1", labels=[Label(lang="en", value="Scheme 1")],
                       top_concepts=[BASE + "C1"], base_uri=BASE)
    s2 = ConceptScheme(uri=BASE + "S2", labels=[Label(lang="en", value="Scheme 2")],
                       top_concepts=[BASE + "C2"], base_uri=BASE)
    c1 = Concept(uri=BASE + "C1", labels=[Label(lang="en", value="C1")])
    c2 = Concept(uri=BASE + "C2", labels=[Label(lang="en", value="C2")])
    t.schemes[s1.uri] = s1
    t.schemes[s2.uri] = s2
    t.concepts[c1.uri] = c1
    t.concepts[c2.uri] = c2
    assign_handles(t)

    lines = flatten_tree(t)
    scheme_lines = [l for l in lines if l.is_scheme]
    concept_lines = [l for l in lines if not l.is_scheme]
    assert len(scheme_lines) == 2
    assert {sl.uri for sl in scheme_lines} == {BASE + "S1", BASE + "S2"}
    assert {cl.uri for cl in concept_lines} == {BASE + "C1", BASE + "C2"}


def test_flatten_tree_scheme_row_is_first(simple_taxonomy):
    """First row of a single-scheme taxonomy is the scheme row (is_scheme=True)."""
    lines = flatten_tree(simple_taxonomy)
    assert lines[0].is_scheme


def test_flatten_tree_empty_scheme():
    """Scheme with no top concepts still appears as a scheme row."""
    t = Taxonomy()
    s = ConceptScheme(uri=BASE + "Empty", labels=[Label(lang="en", value="Empty")])
    t.schemes[s.uri] = s
    lines = flatten_tree(t)
    assert len(lines) == 1
    assert lines[0].is_scheme
    assert lines[0].uri == BASE + "Empty"


# ── build_scheme_fields ───────────────────────────────────────────────────────

def test_build_scheme_fields_primary_scheme(simple_taxonomy):
    """Without scheme_uri, falls back to primary scheme."""
    fields = build_scheme_fields(simple_taxonomy, "en")
    assert any(f.key == "display_lang" for f in fields)
    assert any(f.meta.get("type") == "scheme_title" for f in fields)


def test_build_scheme_fields_specific_uri(simple_taxonomy):
    """With scheme_uri, uses that scheme."""
    scheme_uri = BASE + "Scheme"
    fields = build_scheme_fields(simple_taxonomy, "en", scheme_uri=scheme_uri)
    assert any(f.key == "scheme_uri" for f in fields)
    uri_field = next(f for f in fields if f.key == "scheme_uri")
    assert uri_field.value == scheme_uri


def test_build_scheme_fields_bad_uri(simple_taxonomy):
    """Unknown scheme_uri returns empty list."""
    fields = build_scheme_fields(simple_taxonomy, "en", scheme_uri="https://no.such/scheme")
    assert fields == []


def test_build_scheme_fields_has_add_scheme_action(simple_taxonomy):
    """The 'Add new scheme' action field is present."""
    fields = build_scheme_fields(simple_taxonomy, "en")
    actions = [f for f in fields if f.meta.get("action") == "add_scheme"]
    assert len(actions) == 1


def test_build_scheme_fields_display_lang_is_first(simple_taxonomy):
    """display_lang is the very first field."""
    fields = build_scheme_fields(simple_taxonomy, "en")
    assert fields[0].key == "display_lang"


# ── scheme detail panel (viewer) ─────────────────────────────────────────────

def test_viewer_open_scheme_detail(viewer, simple_taxonomy):
    """Opening the scheme row (index 1, after action row at 0) loads scheme fields."""
    viewer._cursor = 1   # scheme row (action row is at index 0)
    viewer._open_detail()
    assert viewer._mode == TaxonomyViewer._DETAIL
    assert viewer._detail_uri == BASE + "Scheme"
    assert any(f.key == "display_lang" for f in viewer._detail_fields)


def test_viewer_commit_scheme_title_edit(viewer, simple_taxonomy):
    """Editing a scheme_title field updates the scheme label."""
    viewer._cursor = 1   # scheme row (action row is at index 0)
    viewer._open_detail()
    title_idx = next(
        i for i, f in enumerate(viewer._detail_fields)
        if f.meta.get("type") == "scheme_title"
    )
    viewer._field_cursor = title_idx
    viewer._edit_value   = "Renamed Taxonomy"
    viewer._commit_edit()
    scheme = simple_taxonomy.schemes[BASE + "Scheme"]
    assert any(lbl.value == "Renamed Taxonomy" for lbl in scheme.labels)


def test_viewer_add_scheme_trigger(viewer):
    """Triggering add_scheme action switches to SCHEME_CREATE mode."""
    viewer._trigger_action("add_scheme")
    assert viewer._mode == TaxonomyViewer._SCHEME_CREATE
    assert len(viewer._scheme_create_fields) > 0


# ── scheme detail: add top concept ────────────────────────────────────────────

def test_build_scheme_fields_has_add_top_concept(simple_taxonomy):
    """Scheme detail fields include the '+ Add top concept' action."""
    from ster.nav import build_scheme_fields
    fields = build_scheme_fields(simple_taxonomy, "en", scheme_uri=BASE + "Scheme")
    actions = [f.meta.get("action") for f in fields]
    assert "add_top_concept" in actions


def test_build_scheme_fields_uri_type(simple_taxonomy):
    """URI field uses 'scheme_uri' meta type (read-only); base URI uses 'scheme_base_uri' (editable)."""
    from ster.nav import build_scheme_fields
    fields = build_scheme_fields(simple_taxonomy, "en", scheme_uri=BASE + "Scheme")
    uri_field = next(f for f in fields if f.key == "scheme_uri")
    base_field = next(f for f in fields if f.key == "base_uri")
    assert uri_field.meta.get("type") == "scheme_uri"
    assert base_field.meta.get("type") == "scheme_base_uri"
    assert not uri_field.editable   # URI rename not supported (would break top_concept_of refs)
    assert base_field.editable


def test_add_top_concept_action_enters_create_mode(viewer, simple_taxonomy):
    """add_top_concept action from scheme detail enters CREATE mode."""
    scheme_uri = BASE + "Scheme"
    scheme_idx = next(i for i, l in enumerate(viewer._flat) if l.uri == scheme_uri)
    viewer._cursor = scheme_idx
    viewer._open_detail()
    assert viewer._detail_uri == scheme_uri
    viewer._trigger_action("add_top_concept")
    assert viewer._mode == TaxonomyViewer._CREATE
    assert viewer._create_parent_uri == scheme_uri
    assert len(viewer._create_fields) > 0


def test_add_top_concept_creates_top_concept(viewer, simple_taxonomy):
    """Submitting the create form from scheme detail makes a top concept."""
    scheme_uri = BASE + "Scheme"
    scheme_idx = next(i for i, l in enumerate(viewer._flat) if l.uri == scheme_uri)
    viewer._cursor = scheme_idx
    viewer._open_detail()
    viewer._trigger_action("add_top_concept")

    for f in viewer._create_fields:
        if f.meta.get("field") == "name":
            f.value = "BrandNew"

    viewer._submit_create()

    # Concept should exist
    new_uri = BASE + "BrandNew"
    assert new_uri in simple_taxonomy.concepts

    # It must be a top concept of the scheme (not a narrower of another concept)
    scheme = simple_taxonomy.schemes[scheme_uri]
    assert new_uri in scheme.top_concepts
    concept = simple_taxonomy.concepts[new_uri]
    assert concept.broader == []
    assert concept.top_concept_of == scheme_uri


def test_add_top_concept_uses_scheme_base_uri(viewer, simple_taxonomy):
    """Concept URI is built from the scheme's base_uri, not the primary scheme."""
    scheme_uri = BASE + "Scheme"
    scheme_idx = next(i for i, l in enumerate(viewer._flat) if l.uri == scheme_uri)
    viewer._cursor = scheme_idx
    viewer._open_detail()
    viewer._trigger_action("add_top_concept")

    for f in viewer._create_fields:
        if f.meta.get("field") == "name":
            f.value = "AlphaTest"

    viewer._submit_create()
    assert BASE + "AlphaTest" in simple_taxonomy.concepts


# ── scheme create flow ────────────────────────────────────────────────────────

def test_build_scheme_create_fields(viewer):
    """Scheme create form has required fields."""
    fields = viewer._build_scheme_create_fields()
    field_names = [f.meta.get("field") for f in fields]
    assert "title" in field_names
    assert "uri" in field_names
    assert "base_uri" in field_names
    # Submit + cancel actions
    actions = [f.meta.get("action") for f in fields]
    assert "submit_scheme" in actions
    assert "cancel" in actions


def test_submit_scheme_create_missing_title(viewer):
    """Missing title shows an error and does not create a scheme."""
    viewer._scheme_create_fields = viewer._build_scheme_create_fields()
    # Leave title empty
    for f in viewer._scheme_create_fields:
        if f.meta.get("field") == "uri":
            f.value = "https://example.org/new"
    viewer._submit_scheme_create()
    assert viewer._scheme_create_error != ""
    assert "https://example.org/new" not in viewer.taxonomy.schemes


def test_submit_scheme_create_missing_uri(viewer):
    """Missing URI shows an error."""
    viewer._scheme_create_fields = viewer._build_scheme_create_fields()
    for f in viewer._scheme_create_fields:
        if f.meta.get("field") == "title":
            f.value = "New Scheme"
    viewer._submit_scheme_create()
    assert "required" in viewer._scheme_create_error.lower() or \
           viewer._scheme_create_error != ""


def test_submit_scheme_create_invalid_uri(viewer):
    """Non-URL URI (no ://) shows an error."""
    viewer._scheme_create_fields = viewer._build_scheme_create_fields()
    for f in viewer._scheme_create_fields:
        if f.meta.get("field") == "title":
            f.value = "New Scheme"
        elif f.meta.get("field") == "uri":
            f.value = "not-a-url"
    viewer._submit_scheme_create()
    assert viewer._scheme_create_error != ""


def test_submit_scheme_create_success(viewer, simple_taxonomy):
    """Valid inputs create the scheme and navigate to its detail."""
    viewer._scheme_create_fields = viewer._build_scheme_create_fields()
    new_uri = BASE + "NewScheme"
    for f in viewer._scheme_create_fields:
        if f.meta.get("field") == "title":
            f.value = "New Scheme"
        elif f.meta.get("field") == "uri":
            f.value = new_uri
        elif f.meta.get("field") == "base_uri":
            f.value = BASE + "new/"
    viewer._submit_scheme_create()
    assert viewer._scheme_create_error == ""
    assert new_uri in viewer.taxonomy.schemes
    assert viewer._mode == TaxonomyViewer._DETAIL
    assert viewer._detail_uri == new_uri


def test_submit_scheme_create_duplicate_uri(viewer, simple_taxonomy):
    """Creating a scheme with an already-existing URI shows an error."""
    viewer._scheme_create_fields = viewer._build_scheme_create_fields()
    for f in viewer._scheme_create_fields:
        if f.meta.get("field") == "title":
            f.value = "Duplicate"
        elif f.meta.get("field") == "uri":
            f.value = BASE + "Scheme"  # already exists
    viewer._submit_scheme_create()
    assert viewer._scheme_create_error != ""


def test_submit_scheme_create_base_uri_gets_trailing_slash(viewer, simple_taxonomy):
    """base_uri without trailing / or # gets a / appended."""
    viewer._scheme_create_fields = viewer._build_scheme_create_fields()
    for f in viewer._scheme_create_fields:
        if f.meta.get("field") == "title":
            f.value = "Slash Test"
        elif f.meta.get("field") == "uri":
            f.value = BASE + "SlashScheme"
        elif f.meta.get("field") == "base_uri":
            f.value = "https://example.org/slash"  # no trailing slash
    viewer._submit_scheme_create()
    scheme = viewer.taxonomy.schemes.get(BASE + "SlashScheme")
    assert scheme is not None
    assert scheme.base_uri.endswith("/")


def test_scheme_create_commit_edit_updates_field(viewer):
    """_commit_edit in SCHEME_CREATE mode writes value into form field."""
    viewer._scheme_create_fields = viewer._build_scheme_create_fields()
    viewer._scheme_create_cursor = 0  # title field
    viewer._edit_return_mode     = TaxonomyViewer._SCHEME_CREATE
    viewer._edit_value           = "Draft Title"
    viewer._commit_edit()
    assert viewer._scheme_create_fields[0].value == "Draft Title"


# ── fold / unfold ─────────────────────────────────────────────────────────────

def test_count_descendants_leaf(simple_taxonomy):
    # Child2 is a true leaf; Grandchild is also a leaf
    assert _count_descendants(simple_taxonomy, BASE + "Child2") == 0
    assert _count_descendants(simple_taxonomy, BASE + "Grandchild") == 0


def test_count_descendants_parent(simple_taxonomy):
    # Top → Child1, Child2; Child1 → Grandchild  = 3 descendants
    assert _count_descendants(simple_taxonomy, BASE + "Top") == 3
    # Child1 → Grandchild = 1 descendant
    assert _count_descendants(simple_taxonomy, BASE + "Child1") == 1


def test_count_descendants_missing_uri(simple_taxonomy):
    assert _count_descendants(simple_taxonomy, BASE + "Ghost") == 0


def test_flatten_tree_no_fold(simple_taxonomy):
    flat = flatten_tree(simple_taxonomy)
    uris = [l.uri for l in flat]
    assert BASE + "Top" in uris
    assert BASE + "Child1" in uris
    assert BASE + "Child2" in uris
    # All lines not folded by default
    assert all(not l.is_folded for l in flat)
    assert all(l.hidden_count == 0 for l in flat)


def test_flatten_tree_fold_concept(simple_taxonomy):
    folded = {BASE + "Top"}
    flat = flatten_tree(simple_taxonomy, folded=folded)
    uris = [l.uri for l in flat]
    # Top appears but children are hidden
    assert BASE + "Top" in uris
    assert BASE + "Child1" not in uris
    assert BASE + "Child2" not in uris
    top_line = next(l for l in flat if l.uri == BASE + "Top")
    assert top_line.is_folded
    assert top_line.hidden_count == 3  # Child1, Child2, Grandchild


def test_flatten_tree_fold_scheme(simple_taxonomy):
    scheme_uri = BASE + "Scheme"
    folded = {scheme_uri}
    flat = flatten_tree(simple_taxonomy, folded=folded)
    uris = [l.uri for l in flat]
    assert scheme_uri in uris
    assert BASE + "Top" not in uris
    scheme_line = next(l for l in flat if l.uri == scheme_uri)
    assert scheme_line.is_folded
    assert scheme_line.hidden_count > 0


def test_flatten_tree_fold_leaf_has_no_effect(simple_taxonomy):
    """Folding a leaf concept (no children) is a no-op visually."""
    # Grandchild is a true leaf
    folded = {BASE + "Grandchild"}
    flat_folded   = flatten_tree(simple_taxonomy, folded=folded)
    flat_unfolded = flatten_tree(simple_taxonomy)
    uris_folded   = [l.uri for l in flat_folded]
    uris_unfolded = [l.uri for l in flat_unfolded]
    # Leaf has no children so nothing is hidden — same URIs visible
    assert uris_folded == uris_unfolded
    gc_line = next(l for l in flat_folded if l.uri == BASE + "Grandchild")
    assert not gc_line.is_folded
    assert gc_line.hidden_count == 0


def test_viewer_fold_unfold_via_space(viewer, simple_taxonomy):
    """Pressing space on a concept with children toggles fold state."""
    import curses
    # Find cursor position of Top concept in the flat list
    top_idx = next(i for i, l in enumerate(viewer._flat) if l.uri == BASE + "Top")
    viewer._cursor = top_idx
    n_before = len(viewer._flat)

    viewer._on_tree(ord(" "), 24)  # fold
    assert BASE + "Top" in viewer._folded
    # Children should no longer appear
    uris = [l.uri for l in viewer._flat]
    assert BASE + "Child1" not in uris
    assert len(viewer._flat) < n_before
    # Cursor should still be on Top
    assert viewer._flat[viewer._cursor].uri == BASE + "Top"

    viewer._on_tree(ord(" "), 24)  # unfold
    assert BASE + "Top" not in viewer._folded
    uris = [l.uri for l in viewer._flat]
    assert BASE + "Child1" in uris
    assert len(viewer._flat) == n_before


def test_viewer_space_on_leaf_does_nothing(viewer, simple_taxonomy):
    """Space on a leaf concept (no children) does not fold anything."""
    child2_idx = next(i for i, l in enumerate(viewer._flat) if l.uri == BASE + "Child2")
    viewer._cursor = child2_idx
    n_before = len(viewer._flat)
    viewer._on_tree(ord(" "), 24)
    assert BASE + "Child2" not in viewer._folded
    assert len(viewer._flat) == n_before


def test_viewer_space_on_scheme_folds_scheme(viewer, simple_taxonomy):
    """Space on a scheme row folds the whole scheme."""
    scheme_uri = BASE + "Scheme"
    scheme_idx = next(i for i, l in enumerate(viewer._flat) if l.uri == scheme_uri)
    viewer._cursor = scheme_idx
    viewer._on_tree(ord(" "), 24)
    assert scheme_uri in viewer._folded
    uris = [l.uri for l in viewer._flat]
    assert BASE + "Top" not in uris
    scheme_line = viewer._flat[viewer._cursor]
    assert scheme_line.is_folded
    assert scheme_line.hidden_count > 0


# ── detail view: narrower navigation & colour hints ──────────────────────────

def test_detail_footer_hint_narrower(viewer, simple_taxonomy):
    """Detail footer says 'Enter: open concept' when cursor is on a narrower field."""
    viewer._cursor = next(i for i, l in enumerate(viewer._flat) if l.uri == BASE + "Top")
    viewer._open_detail()
    # Find a narrower field
    narrower_idx = next(
        i for i, f in enumerate(viewer._detail_fields)
        if f.key.startswith("narrower:")
    )
    viewer._field_cursor = narrower_idx
    footer = viewer._detail_footer()
    assert "Enter: open concept" in footer


def test_detail_footer_hint_action(viewer, simple_taxonomy):
    """Detail footer says 'Enter: execute' when cursor is on an action field."""
    viewer._cursor = next(i for i, l in enumerate(viewer._flat) if l.uri == BASE + "Top")
    viewer._open_detail()
    action_idx = next(
        i for i, f in enumerate(viewer._detail_fields)
        if f.meta.get("type") == "action"
    )
    viewer._field_cursor = action_idx
    footer = viewer._detail_footer()
    assert "Enter: execute" in footer


def test_enter_on_narrower_navigates(viewer, simple_taxonomy):
    """Pressing Enter on a narrower field opens the child concept's detail."""
    import curses
    viewer._cursor = next(i for i, l in enumerate(viewer._flat) if l.uri == BASE + "Top")
    viewer._open_detail()
    assert viewer._mode == TaxonomyViewer._DETAIL

    narrower_idx = next(
        i for i, f in enumerate(viewer._detail_fields)
        if f.key.startswith("narrower:") and "Child1" in f.key
    )
    viewer._field_cursor = narrower_idx
    viewer._on_detail(ord("\n"), 24)

    # Should now be viewing Child1's detail
    assert viewer._detail_uri == BASE + "Child1"
    # cursor lands on first non-separator row (>= 1 because index 0 is a separator)
    assert viewer._detail_fields[viewer._field_cursor].meta.get("type") != "separator"
    # Can go back to Top
    viewer._back()
    assert viewer._detail_uri == BASE + "Top"


def test_enter_on_narrower_missing_uri_does_nothing(viewer, simple_taxonomy):
    """Enter on a narrower field whose URI is not in taxonomy does nothing."""
    import curses
    from ster.nav import DetailField
    viewer._cursor = next(i for i, l in enumerate(viewer._flat) if l.uri == BASE + "Top")
    viewer._open_detail()
    # Inject a broken narrower field
    ghost_field = DetailField(
        key="narrower:ghost",
        display="↓ narrower",
        value="ghost",
        editable=False,
        meta={"type": "relation", "uri": BASE + "Ghost"},
    )
    viewer._detail_fields.insert(0, ghost_field)
    viewer._field_cursor = 0
    prev_uri = viewer._detail_uri
    viewer._on_detail(ord("\n"), 24)
    # Should not have navigated anywhere
    assert viewer._detail_uri == prev_uri


def test_action_label_not_truncated(simple_taxonomy):
    """The '+ Add narrower concept' action label must not be truncated to lbl_w."""
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    add_action = next(f for f in fields if f.meta.get("action") == "add_narrower")
    assert add_action.display == "+ Add narrower concept"


def test_tree_footer_contains_space_fold_hint(viewer, simple_taxonomy):
    """The tree footer must mention the Space fold shortcut."""
    footer = viewer._tree_footer(24)
    assert "Spc" in footer or "Space" in footer or "fold" in footer.lower()


# ── action row (➕ Add new scheme) in tree ────────────────────────────────────

def test_flat_first_row_is_action(viewer):
    """After _rebuild(), flat[0] is the '➕ Add new scheme' action row."""
    from ster.nav import _ACTION_ADD_SCHEME
    assert viewer._flat[0].is_action
    assert viewer._flat[0].uri == _ACTION_ADD_SCHEME


def test_flat_second_row_is_scheme(viewer, simple_taxonomy):
    """After _rebuild(), flat[1] is the scheme row (not action)."""
    assert viewer._flat[1].is_scheme


def test_tree_footer_add_hint(viewer):
    """Tree footer contains '+: add' hint."""
    footer = viewer._tree_footer(24)
    assert "+: add" in footer or "+:" in footer


def test_enter_on_action_row_triggers_scheme_create(viewer):
    """Pressing Enter on action row (cursor=0) launches SCHEME_CREATE mode."""
    viewer._cursor = 0
    viewer._on_tree(ord("\n"), 24)
    assert viewer._mode == TaxonomyViewer._SCHEME_CREATE


def test_plus_on_action_row_triggers_scheme_create(viewer):
    """Pressing + on action row launches SCHEME_CREATE mode."""
    viewer._cursor = 0
    viewer._on_tree(ord("+"), 24)
    assert viewer._mode == TaxonomyViewer._SCHEME_CREATE


def test_plus_on_scheme_row_enters_create_mode(viewer, simple_taxonomy):
    """Pressing + on a scheme row launches CREATE mode for a top concept."""
    scheme_idx = next(i for i, l in enumerate(viewer._flat) if l.is_scheme)
    viewer._cursor = scheme_idx
    viewer._on_tree(ord("+"), 24)
    assert viewer._mode == TaxonomyViewer._CREATE
    assert viewer._create_parent_uri == BASE + "Scheme"


def test_plus_on_concept_row_enters_create_mode(viewer, simple_taxonomy):
    """Pressing + on a concept row launches CREATE mode for a narrower concept."""
    concept_idx = next(
        i for i, l in enumerate(viewer._flat)
        if not l.is_scheme and not l.is_action
    )
    viewer._cursor = concept_idx
    viewer._on_tree(ord("+"), 24)
    assert viewer._mode == TaxonomyViewer._CREATE
    assert viewer._create_parent_uri == viewer._flat[concept_idx].uri


# ── scheme URI and base URI editability ───────────────────────────────────────

def test_scheme_uri_field_readonly(simple_taxonomy):
    """scheme_uri field is read-only (URI rename would break top_concept_of references)."""
    fields = build_scheme_fields(simple_taxonomy, "en", scheme_uri=BASE + "Scheme")
    uri_f = next(f for f in fields if f.key == "scheme_uri")
    assert not uri_f.editable


def test_scheme_base_uri_field_editable(simple_taxonomy):
    """base_uri field is editable=True with type scheme_base_uri."""
    fields = build_scheme_fields(simple_taxonomy, "en", scheme_uri=BASE + "Scheme")
    base_f = next(f for f in fields if f.key == "base_uri")
    assert base_f.editable
    assert base_f.meta.get("type") == "scheme_base_uri"


def test_commit_scheme_base_uri_edit(viewer, simple_taxonomy):
    """Editing base_uri field updates scheme.base_uri."""
    viewer._cursor = 1  # scheme row
    viewer._open_detail()
    base_idx = next(i for i, f in enumerate(viewer._detail_fields) if f.key == "base_uri")
    viewer._field_cursor = base_idx
    viewer._edit_value = "https://example.org/new/"
    viewer._commit_edit()
    scheme = simple_taxonomy.schemes[BASE + "Scheme"]
    assert scheme.base_uri == "https://example.org/new/"


def test_add_top_concept_display_uses_emoji(simple_taxonomy):
    """The 'Add top concept' action label uses the ➕ emoji."""
    fields = build_scheme_fields(simple_taxonomy, "en", scheme_uri=BASE + "Scheme")
    action = next(f for f in fields if f.meta.get("action") == "add_top_concept")
    assert action.display.startswith("➕")


# ── regression: cancel from CREATE/SCHEME_CREATE triggered from tree ──────────

def test_cancel_create_from_tree_returns_to_tree(viewer, simple_taxonomy):
    """Esc from CREATE mode entered via '+' from the tree returns to TREE, not DETAIL."""
    # Navigate to a concept row and press +
    concept_idx = next(
        i for i, l in enumerate(viewer._flat)
        if not l.is_scheme and not l.is_action
    )
    viewer._mode = viewer._TREE
    viewer._cursor = concept_idx
    viewer._on_tree(ord("+"), 24)
    assert viewer._mode == viewer._CREATE
    # Esc should go back to TREE, not DETAIL
    viewer._on_create(27, 24)
    assert viewer._mode == viewer._TREE


def test_cancel_scheme_create_from_tree_returns_to_tree(viewer):
    """Esc from SCHEME_CREATE entered via action row returns to TREE, not DETAIL."""
    viewer._mode = viewer._TREE
    viewer._cursor = 0  # action row
    viewer._on_tree(ord("\n"), 24)
    assert viewer._mode == viewer._SCHEME_CREATE
    # Esc should go back to TREE
    viewer._on_scheme_create(27, 24)
    assert viewer._mode == viewer._TREE


def test_cancel_create_from_detail_returns_to_detail(viewer, simple_taxonomy):
    """Esc from CREATE mode entered via detail panel returns to DETAIL."""
    scheme_idx = next(i for i, l in enumerate(viewer._flat) if l.is_scheme)
    viewer._cursor = scheme_idx
    viewer._open_detail()
    assert viewer._mode == viewer._DETAIL
    viewer._trigger_action("add_top_concept")
    assert viewer._mode == viewer._CREATE
    viewer._on_create(27, 24)
    assert viewer._mode == viewer._DETAIL


# ── regression: scheme URI is read-only (rename would break top_concept_of) ───

def test_scheme_uri_not_editable_in_detail(viewer, simple_taxonomy):
    """Pressing Enter on the URI field in scheme detail must not enter EDIT mode."""
    viewer._cursor = 1  # scheme row
    viewer._open_detail()
    uri_idx = next(i for i, f in enumerate(viewer._detail_fields) if f.key == "scheme_uri")
    viewer._field_cursor = uri_idx
    viewer._on_detail(ord("\n"), 24)
    assert viewer._mode == viewer._DETAIL   # not EDIT
