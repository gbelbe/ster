"""Tests for the interactive taxonomy navigator and shell (non-curses parts)."""

from __future__ import annotations

import pytest

from ster.handles import assign_handles
from ster.model import Concept, ConceptScheme, Label, Taxonomy
from ster.nav import (
    TaxonomyShell,
    TaxonomyViewer,
    _breadcrumb,
    _children,
    _count_descendants,
    _parent_uri,
    build_concept_detail,
    build_detail_fields,
    build_scheme_detail,
    build_scheme_fields,
    flatten_tree,
)
from ster.nav.editor import _apply_line_edit
from ster.nav.state import (
    BatchConceptDraft,
    BatchCreateState,
    CreateState,
    DetailState,
    EditState,
    SchemeCreateState,
    TreeState,
    WelcomeState,
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
    assert "[TOP]" in bc or "[" in bc  # handle varies; path contains at least one handle
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
    import ster.nav.viewer as nav_mod

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
    narrower_fields = [f for f in fields if f.key.startswith("narrower:")]
    assert len(narrower_fields) == 2
    assert all(not f.editable for f in narrower_fields)


def test_viewer_initial_cursor(viewer):
    assert viewer._tree.cursor == 0
    # Viewer starts in WELCOME mode (splash screen); transitions to TREE on any key
    assert isinstance(viewer._state, WelcomeState)


def test_run_flushes_stdin_before_and_after_curses(viewer, monkeypatch):
    """stdin is flushed both before curses starts and after it exits.

    Regression: pressing Escape twice quickly in the tree view caused the second
    Escape to survive into the next viewer launch and exit it immediately.

    The fix requires two flushes:
    - Before curses: discards stale bytes left by the home-screen picker.
    - After curses (in finally): discards bytes that ncurses pushes back to the
      OS input queue when endwin() is called on exit.
    """
    termios = pytest.importorskip("termios")
    import ster.nav.viewer as nav_mod

    class _FakeTTY:
        def isatty(self):
            return True

        def fileno(self):
            return 0

    monkeypatch.setattr(nav_mod.sys, "stdin", _FakeTTY())
    monkeypatch.setattr(nav_mod.sys, "stdout", _FakeTTY())

    flush_calls: list[int] = []
    wrapper_call_count: list[int] = [0]

    def _fake_wrapper(fn):
        wrapper_call_count[0] += 1
        # Record how many flushes happened before curses
        flush_calls.append("curses_ran")

    monkeypatch.setattr(termios, "tcflush", lambda fd, queue: flush_calls.append(queue))
    monkeypatch.setattr(nav_mod.curses, "wrapper", _fake_wrapper)

    viewer.run()

    # At least one TCIFLUSH before curses and one after
    curses_idx = flush_calls.index("curses_ran")
    before = flush_calls[:curses_idx]
    after = flush_calls[curses_idx + 1 :]
    assert termios.TCIFLUSH in before, "stdin must be flushed before curses starts"
    assert termios.TCIFLUSH in after, "stdin must be flushed after curses exits (endwin regression)"


def test_viewer_open_detail(viewer, simple_taxonomy):
    # flat[0] is the scheme row
    viewer._tree.cursor = 0
    viewer._open_detail()
    assert isinstance(viewer._state, DetailState)
    assert viewer._detail_uri == viewer._tree.flat[0].uri
    assert len(viewer._detail_fields) > 0


def test_viewer_back_from_detail(viewer):
    viewer._state = TreeState()  # skip welcome for this test
    viewer._tree.cursor = 0  # scheme row
    viewer._open_detail()
    viewer._back()
    assert isinstance(viewer._state, TreeState)


def test_viewer_history_preserves_cursor(viewer):
    viewer._tree.cursor = 1
    viewer._open_detail()
    viewer._back()
    assert viewer._tree.cursor == 1


def test_viewer_commit_edit_updates_label(viewer, simple_taxonomy):
    # Position on Top concept's pref:en field (scheme at 0, Top at 1)
    viewer._tree.cursor = 1
    viewer._open_detail()
    fields = viewer._detail_fields
    pref_idx = next(i for i, f in enumerate(fields) if f.key == "pref:en")
    viewer._field_cursor = pref_idx
    viewer._state = EditState(
        buffer="Updated Top", pos=len("Updated Top"), field=fields[pref_idx], return_to=None
    )
    viewer._commit_edit()
    assert simple_taxonomy.concepts[BASE + "Top"].pref_label("en") == "Updated Top"


# ── multi-scheme flatten_tree ─────────────────────────────────────────────────


def test_flatten_tree_multiple_schemes():
    """All schemes appear as is_scheme rows; concepts under each scheme follow."""
    t = Taxonomy()
    s1 = ConceptScheme(
        uri=BASE + "S1",
        labels=[Label(lang="en", value="Scheme 1")],
        top_concepts=[BASE + "C1"],
        base_uri=BASE,
    )
    s2 = ConceptScheme(
        uri=BASE + "S2",
        labels=[Label(lang="en", value="Scheme 2")],
        top_concepts=[BASE + "C2"],
        base_uri=BASE,
    )
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


def test_build_scheme_fields_display_lang_is_first(simple_taxonomy):
    """display_lang is the very first field."""
    fields = build_scheme_fields(simple_taxonomy, "en")
    assert fields[0].key == "display_lang"


# ── scheme detail panel (viewer) ─────────────────────────────────────────────


def test_viewer_open_scheme_detail(viewer, simple_taxonomy):
    """Opening the scheme row (index 0) loads scheme fields."""
    viewer._tree.cursor = 0  # scheme row
    viewer._open_detail()
    assert isinstance(viewer._state, DetailState)
    assert viewer._detail_uri == BASE + "Scheme"
    assert any(f.key == "display_lang" for f in viewer._detail_fields)


def test_viewer_commit_scheme_title_edit(viewer, simple_taxonomy):
    """Editing a scheme_title field updates the scheme label."""
    viewer._tree.cursor = 0  # scheme row
    viewer._open_detail()
    title_idx = next(
        i for i, f in enumerate(viewer._detail_fields) if f.meta.get("type") == "scheme_title"
    )
    viewer._field_cursor = title_idx
    viewer._state = EditState(
        buffer="Renamed Taxonomy",
        pos=len("Renamed Taxonomy"),
        field=viewer._detail_fields[title_idx],
        return_to=None,
    )
    viewer._commit_edit()
    scheme = simple_taxonomy.schemes[BASE + "Scheme"]
    assert any(lbl.value == "Renamed Taxonomy" for lbl in scheme.labels)


def test_viewer_add_scheme_trigger(viewer):
    """Triggering add_scheme action switches to SCHEME_CREATE mode."""
    viewer._trigger_action("add_scheme")
    assert isinstance(viewer._state, SchemeCreateState)
    assert len(viewer._state.fields) > 0


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
    assert not uri_field.editable  # URI rename not supported (would break top_concept_of refs)
    assert base_field.editable


def test_add_top_concept_action_enters_create_mode(viewer, simple_taxonomy):
    """add_top_concept action from scheme detail enters CREATE mode (choose step)."""
    scheme_uri = BASE + "Scheme"
    scheme_idx = next(i for i, l in enumerate(viewer._tree.flat) if l.uri == scheme_uri)
    viewer._tree.cursor = scheme_idx
    viewer._open_detail()
    assert viewer._detail_uri == scheme_uri
    viewer._trigger_action("add_top_concept")
    assert isinstance(viewer._state, CreateState)
    assert viewer._state.parent_uri == scheme_uri
    assert viewer._state.step == "choose"


def test_add_top_concept_creates_top_concept(viewer, simple_taxonomy):
    """Submitting the create form from scheme detail makes a top concept."""
    scheme_uri = BASE + "Scheme"
    scheme_idx = next(i for i, l in enumerate(viewer._tree.flat) if l.uri == scheme_uri)
    viewer._tree.cursor = scheme_idx
    viewer._open_detail()
    viewer._trigger_action("add_top_concept")

    # Simulate user choosing "manual entry"
    cs = viewer._state
    cs.ai_cursor = 0
    viewer._on_create_choose(ord("\n"), cs)
    assert cs.step == "form"
    assert len(cs.fields) > 0

    for f in cs.fields:
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
    scheme_idx = next(i for i, l in enumerate(viewer._tree.flat) if l.uri == scheme_uri)
    viewer._tree.cursor = scheme_idx
    viewer._open_detail()
    viewer._trigger_action("add_top_concept")

    # Simulate user choosing "manual entry"
    cs = viewer._state
    cs.ai_cursor = 0
    viewer._on_create_choose(ord("\n"), cs)
    assert cs.step == "form"

    for f in cs.fields:
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
    fields = viewer._build_scheme_create_fields()
    for f in fields:
        if f.meta.get("field") == "uri":
            f.value = "https://example.org/new"
    viewer._state = SchemeCreateState(fields=fields)
    viewer._submit_scheme_create()
    assert isinstance(viewer._state, SchemeCreateState)
    assert viewer._state.error != ""
    assert "https://example.org/new" not in viewer.taxonomy.schemes


def test_submit_scheme_create_missing_uri(viewer):
    """Missing URI shows an error."""
    fields = viewer._build_scheme_create_fields()
    for f in fields:
        if f.meta.get("field") == "title":
            f.value = "New Scheme"
    viewer._state = SchemeCreateState(fields=fields)
    viewer._submit_scheme_create()
    assert isinstance(viewer._state, SchemeCreateState)
    assert viewer._state.error != ""


def test_submit_scheme_create_invalid_uri(viewer):
    """Non-URL URI (no ://) shows an error."""
    fields = viewer._build_scheme_create_fields()
    for f in fields:
        if f.meta.get("field") == "title":
            f.value = "New Scheme"
        elif f.meta.get("field") == "uri":
            f.value = "not-a-url"
    viewer._state = SchemeCreateState(fields=fields)
    viewer._submit_scheme_create()
    assert isinstance(viewer._state, SchemeCreateState)
    assert viewer._state.error != ""


def test_submit_scheme_create_success(viewer, simple_taxonomy):
    """Valid inputs create the scheme and navigate to its detail."""
    new_uri = BASE + "NewScheme"
    fields = viewer._build_scheme_create_fields()
    for f in fields:
        if f.meta.get("field") == "title":
            f.value = "New Scheme"
        elif f.meta.get("field") == "uri":
            f.value = new_uri
        elif f.meta.get("field") == "base_uri":
            f.value = BASE + "new/"
    viewer._state = SchemeCreateState(fields=fields)
    viewer._submit_scheme_create()
    assert new_uri in viewer.taxonomy.schemes
    assert isinstance(viewer._state, DetailState)
    assert viewer._detail_uri == new_uri


def test_submit_scheme_create_duplicate_uri(viewer, simple_taxonomy):
    """Creating a scheme with an already-existing URI shows an error."""
    fields = viewer._build_scheme_create_fields()
    for f in fields:
        if f.meta.get("field") == "title":
            f.value = "Duplicate"
        elif f.meta.get("field") == "uri":
            f.value = BASE + "Scheme"  # already exists
    viewer._state = SchemeCreateState(fields=fields)
    viewer._submit_scheme_create()
    assert isinstance(viewer._state, SchemeCreateState)
    assert viewer._state.error != ""


def test_submit_scheme_create_base_uri_gets_trailing_slash(viewer, simple_taxonomy):
    """base_uri without trailing / or # gets a / appended."""
    fields = viewer._build_scheme_create_fields()
    for f in fields:
        if f.meta.get("field") == "title":
            f.value = "Slash Test"
        elif f.meta.get("field") == "uri":
            f.value = BASE + "SlashScheme"
        elif f.meta.get("field") == "base_uri":
            f.value = "https://example.org/slash"  # no trailing slash
    viewer._state = SchemeCreateState(fields=fields)
    viewer._submit_scheme_create()
    scheme = viewer.taxonomy.schemes.get(BASE + "SlashScheme")
    assert scheme is not None
    assert scheme.base_uri.endswith("/")


def test_scheme_create_commit_edit_updates_field(viewer):
    """_commit_edit in SCHEME_CREATE mode writes value into form field."""
    fields = viewer._build_scheme_create_fields()
    scs = SchemeCreateState(fields=fields, cursor=0)
    viewer._state = EditState(
        buffer="Draft Title", pos=len("Draft Title"), field=fields[0], return_to=scs
    )
    viewer._commit_edit()
    assert scs.fields[0].value == "Draft Title"


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
    flat_folded = flatten_tree(simple_taxonomy, folded=folded)
    flat_unfolded = flatten_tree(simple_taxonomy)
    uris_folded = [l.uri for l in flat_folded]
    uris_unfolded = [l.uri for l in flat_unfolded]
    # Leaf has no children so nothing is hidden — same URIs visible
    assert uris_folded == uris_unfolded
    gc_line = next(l for l in flat_folded if l.uri == BASE + "Grandchild")
    assert not gc_line.is_folded
    assert gc_line.hidden_count == 0


def test_viewer_fold_unfold_via_space(viewer, simple_taxonomy):
    """Pressing space on a concept with children toggles fold state."""
    # Find cursor position of Top concept in the flat list
    top_idx = next(i for i, l in enumerate(viewer._tree.flat) if l.uri == BASE + "Top")
    viewer._tree.cursor = top_idx
    n_before = len(viewer._tree.flat)

    viewer._on_tree(ord(" "), 24)  # fold
    assert BASE + "Top" in viewer._tree.folded
    # Children should no longer appear
    uris = [l.uri for l in viewer._tree.flat]
    assert BASE + "Child1" not in uris
    assert len(viewer._tree.flat) < n_before
    # Cursor should still be on Top
    assert viewer._tree.flat[viewer._tree.cursor].uri == BASE + "Top"

    viewer._on_tree(ord(" "), 24)  # unfold
    assert BASE + "Top" not in viewer._tree.folded
    uris = [l.uri for l in viewer._tree.flat]
    assert BASE + "Child1" in uris
    assert len(viewer._tree.flat) == n_before


def test_viewer_space_on_leaf_does_nothing(viewer, simple_taxonomy):
    """Space on a leaf concept (no children) does not fold anything."""
    child2_idx = next(i for i, l in enumerate(viewer._tree.flat) if l.uri == BASE + "Child2")
    viewer._tree.cursor = child2_idx
    n_before = len(viewer._tree.flat)
    viewer._on_tree(ord(" "), 24)
    assert BASE + "Child2" not in viewer._tree.folded
    assert len(viewer._tree.flat) == n_before


def test_viewer_space_on_scheme_folds_scheme(viewer, simple_taxonomy):
    """Space on a scheme row folds the whole scheme."""
    scheme_uri = BASE + "Scheme"
    scheme_idx = next(i for i, l in enumerate(viewer._tree.flat) if l.uri == scheme_uri)
    viewer._tree.cursor = scheme_idx
    viewer._on_tree(ord(" "), 24)
    assert scheme_uri in viewer._tree.folded
    uris = [l.uri for l in viewer._tree.flat]
    assert BASE + "Top" not in uris
    scheme_line = viewer._tree.flat[viewer._tree.cursor]
    assert scheme_line.is_folded
    assert scheme_line.hidden_count > 0


# ── detail view: narrower navigation & colour hints ──────────────────────────


def test_detail_footer_hint_narrower(viewer, simple_taxonomy):
    """Detail footer says 'Enter: open concept' when cursor is on a narrower field."""
    viewer._tree.cursor = next(i for i, l in enumerate(viewer._tree.flat) if l.uri == BASE + "Top")
    viewer._open_detail()
    # Find a narrower field
    narrower_idx = next(
        i for i, f in enumerate(viewer._detail_fields) if f.key.startswith("narrower:")
    )
    viewer._field_cursor = narrower_idx
    footer = viewer._detail_footer()
    assert "Enter: open concept" in footer


def test_detail_footer_hint_action(viewer, simple_taxonomy):
    """Detail footer says 'Enter: execute' when cursor is on an action field."""
    viewer._tree.cursor = next(i for i, l in enumerate(viewer._tree.flat) if l.uri == BASE + "Top")
    viewer._open_detail()
    action_idx = next(
        i for i, f in enumerate(viewer._detail_fields) if f.meta.get("type") == "action"
    )
    viewer._field_cursor = action_idx
    footer = viewer._detail_footer()
    assert "Enter: execute" in footer


def test_enter_on_narrower_navigates(viewer, simple_taxonomy):
    """Pressing Enter on a narrower field opens the child concept's detail."""
    viewer._tree.cursor = next(i for i, l in enumerate(viewer._tree.flat) if l.uri == BASE + "Top")
    viewer._open_detail()
    assert isinstance(viewer._state, DetailState)

    narrower_idx = next(
        i
        for i, f in enumerate(viewer._detail_fields)
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
    from ster.nav import DetailField

    viewer._tree.cursor = next(i for i, l in enumerate(viewer._tree.flat) if l.uri == BASE + "Top")
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


def test_flat_first_row_is_scheme(viewer, simple_taxonomy):
    """After _rebuild(), flat[0] is the scheme row."""
    assert viewer._tree.flat[0].is_scheme


def test_tree_footer_add_hint(viewer):
    """Tree footer contains '+: add' hint."""
    footer = viewer._tree_footer(24)
    assert "+: add" in footer or "+:" in footer


def test_plus_on_scheme_row_enters_create_mode(viewer, simple_taxonomy):
    """Pressing + on a scheme row launches CREATE mode for a top concept."""
    scheme_idx = next(i for i, l in enumerate(viewer._tree.flat) if l.is_scheme)
    viewer._tree.cursor = scheme_idx
    viewer._on_tree(ord("+"), 24)
    assert isinstance(viewer._state, CreateState)
    assert viewer._state.parent_uri == BASE + "Scheme"


def test_plus_on_concept_row_enters_create_mode(viewer, simple_taxonomy):
    """Pressing + on a concept row launches CREATE mode for a narrower concept."""
    concept_idx = next(
        i for i, l in enumerate(viewer._tree.flat) if not l.is_scheme and not l.is_file
    )
    viewer._tree.cursor = concept_idx
    viewer._on_tree(ord("+"), 24)
    assert isinstance(viewer._state, CreateState)
    assert viewer._state.parent_uri == viewer._tree.flat[concept_idx].uri


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
    viewer._tree.cursor = 0  # scheme row
    viewer._open_detail()
    base_idx = next(i for i, f in enumerate(viewer._detail_fields) if f.key == "base_uri")
    viewer._field_cursor = base_idx
    viewer._state = EditState(
        buffer="https://example.org/new/",
        pos=len("https://example.org/new/"),
        field=viewer._detail_fields[base_idx],
        return_to=None,
    )
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
        i for i, l in enumerate(viewer._tree.flat) if not l.is_scheme and not l.is_file
    )
    viewer._state = TreeState()
    viewer._tree.cursor = concept_idx
    viewer._on_tree(ord("+"), 24)
    assert isinstance(viewer._state, CreateState)
    # Esc should go back to TREE, not DETAIL
    viewer._on_create(27, 24)
    assert isinstance(viewer._state, TreeState)


def test_cancel_scheme_create_from_tree_returns_to_tree(viewer):
    """Esc from SCHEME_CREATE entered from tree returns to TREE, not DETAIL."""
    viewer._state = TreeState()
    viewer._trigger_action("add_scheme")
    assert isinstance(viewer._state, SchemeCreateState)
    # Esc should go back to TREE
    viewer._on_scheme_create(27, 24)
    assert isinstance(viewer._state, TreeState)


def test_cancel_create_from_detail_returns_to_detail(viewer, simple_taxonomy):
    """Esc from CREATE mode entered via detail panel returns to DETAIL."""
    scheme_idx = next(i for i, l in enumerate(viewer._tree.flat) if l.is_scheme)
    viewer._tree.cursor = scheme_idx
    viewer._open_detail()
    assert isinstance(viewer._state, DetailState)
    viewer._trigger_action("add_top_concept")
    assert isinstance(viewer._state, CreateState)
    viewer._on_create(27, 24)
    assert isinstance(viewer._state, DetailState)


# ── regression: scheme URI is read-only (rename would break top_concept_of) ───


def test_scheme_uri_not_editable_in_detail(viewer, simple_taxonomy):
    """Pressing Enter on the URI field in scheme detail must not enter EDIT mode."""
    viewer._tree.cursor = 0  # scheme row
    viewer._open_detail()
    uri_idx = next(i for i, f in enumerate(viewer._detail_fields) if f.key == "scheme_uri")
    viewer._field_cursor = uri_idx
    viewer._on_detail(ord("\n"), 24)
    assert isinstance(viewer._state, DetailState)  # not EDIT


# ── new build_concept_detail / build_scheme_detail tests ──────────────────────


def test_build_concept_detail_has_stats_for_concept_with_narrowers(simple_taxonomy):
    """Stats section appears when concept has narrowers."""
    fields = build_concept_detail(simple_taxonomy, BASE + "Top", "en")
    keys = [f.key for f in fields]
    assert "stat:direct_narrower" in keys
    assert "stat:total_descendants" in keys


def test_build_concept_detail_no_stats_for_leaf(simple_taxonomy):
    """Overview/Completion sections absent for leaf concepts."""
    fields = build_concept_detail(simple_taxonomy, BASE + "Child2", "en")
    keys = [f.key for f in fields]
    assert "stat:direct_narrower" not in keys
    assert not any(k.startswith("ccomp:") for k in keys)


def test_build_concept_detail_completion_for_concept_with_narrowers(simple_taxonomy):
    """Completion bars appear for concepts that have narrowers."""
    # Top has Child1 (with Grandchild) and Child2, all have prefLabel en + fr
    fields = build_concept_detail(simple_taxonomy, BASE + "Top", "en")
    keys = [f.key for f in fields]
    assert any(k.startswith("ccomp:pref_label:") for k in keys)


def test_build_concept_detail_overview_languages(simple_taxonomy):
    """Overview section lists languages found in subtree prefLabels."""
    fields = build_concept_detail(simple_taxonomy, BASE + "Top", "en")
    lang_field = next((f for f in fields if f.key == "stat:subtree_langs"), None)
    assert lang_field is not None
    assert "en" in lang_field.value
    assert "fr" in lang_field.value


def test_build_concept_detail_has_scope_note_if_present(simple_taxonomy):
    """scopeNote rows appear if the concept has scope_notes."""
    from ster.model import Definition

    simple_taxonomy.concepts[BASE + "Top"].scope_notes.append(
        Definition(lang="en", value="A scope note.")
    )
    fields = build_concept_detail(simple_taxonomy, BASE + "Top", "en")
    keys = [f.key for f in fields]
    assert "scope:en" in keys


def test_build_concept_detail_add_related_action_present(simple_taxonomy):
    """Action to add related concept is always present in Actions section."""
    fields = build_concept_detail(simple_taxonomy, BASE + "Top", "en")
    actions = [f.meta.get("action") for f in fields]
    assert "add_related" in actions


def test_build_scheme_detail_has_top_concepts(simple_taxonomy):
    """Scheme detail shows top concepts as navigable rows."""
    scheme_uri = BASE + "Scheme"
    fields = build_scheme_detail(simple_taxonomy, scheme_uri, "en")
    tc_fields = [f for f in fields if f.key.startswith("tc:")]
    assert len(tc_fields) > 0
    assert all(f.meta.get("nav") for f in tc_fields)


def test_build_scheme_detail_top_concept_of_is_navigable(simple_taxonomy):
    """topConceptOf field on a concept is navigable (→ scheme detail)."""
    top_uri = BASE + "Top"
    fields = build_concept_detail(simple_taxonomy, top_uri, "en")
    tco = next((f for f in fields if f.key == "top_concept_of"), None)
    assert tco is not None
    assert tco.meta.get("nav") is True


# ── AI feature ────────────────────────────────────────────────────────────────


def test_ai_is_available_returns_bool():
    """ai.is_available() always returns a bool (True if llm is installed)."""
    from ster import ai

    result = ai.is_available()
    assert isinstance(result, bool)


def test_ai_is_configured_false_without_config(tmp_path, monkeypatch):
    """ai.is_configured() returns False when no model has been saved."""
    from ster import ai

    monkeypatch.setattr(ai, "_CONFIG_PATH", tmp_path / "ai.json")
    assert ai.is_configured() is False


def test_ai_get_saved_model_none_without_config(tmp_path, monkeypatch):
    """ai.get_saved_model() returns None when config file is absent."""
    from ster import ai

    monkeypatch.setattr(ai, "_CONFIG_PATH", tmp_path / "nonexistent.json")
    assert ai.get_saved_model() is None


def test_ai_save_and_load_model(tmp_path, monkeypatch):
    """Saving a model ID persists it and get_saved_model returns it."""
    from ster import ai

    config_path = tmp_path / "ai.json"
    monkeypatch.setattr(ai, "_CONFIG_PATH", config_path)
    ai.save_model("gpt-4o")
    assert ai.get_saved_model() == "gpt-4o"
    assert config_path.exists()


def test_ai_discover_models_returns_tuple():
    """ai.discover_models() always returns (list, list) even if llm not installed."""
    from ster import ai

    online, offline = ai.discover_models()
    assert isinstance(online, list)
    assert isinstance(offline, list)


# ── Batch concept wizard — state dataclasses ─────────────────────────────────


def test_batch_concept_draft_defaults():
    """BatchConceptDraft has sensible defaults for all optional fields."""
    draft = BatchConceptDraft(name="Machine Learning", pref_label="Machine Learning")
    assert draft.alt_labels == []
    assert draft.alt_checked == []
    assert draft.definition == ""
    assert draft.alts_generating is False
    assert draft.def_generating is False
    assert draft.alts_error == ""
    assert draft.def_error == ""


def test_batch_create_state_defaults():
    """BatchCreateState defaults to 'label' step with empty drafts."""
    bcs = BatchCreateState()
    assert bcs.step == "label"
    assert bcs.drafts == []
    assert bcs.current == 0
    assert bcs.label_buffer == ""
    assert bcs.label_pos == 0
    assert bcs.error == ""


# ── Batch concept wizard — _apply_line_edit ──────────────────────────────────


def _make_viewer(taxonomy, tmp_path):
    """Helper: create a TaxonomyViewer pointing at a temp file."""
    f = tmp_path / "vocab.ttl"
    f.write_text("")
    return TaxonomyViewer(taxonomy, f, lang="en")


def test_apply_line_edit_printable():
    """Printable char inserts at cursor position."""
    buf, pos = _apply_line_edit("ab", 1, ord("X"))
    assert buf == "aXb"
    assert pos == 2


def test_apply_line_edit_backspace():
    """Backspace removes the char before the cursor."""
    buf, pos = _apply_line_edit("abc", 2, 127)
    assert buf == "ac"
    assert pos == 1


def test_apply_line_edit_ctrl_a():
    """Ctrl+A moves cursor to start."""
    buf, pos = _apply_line_edit("hello", 4, 1)
    assert buf == "hello"
    assert pos == 0


def test_apply_line_edit_ctrl_e():
    """Ctrl+E moves cursor to end."""
    buf, pos = _apply_line_edit("hello", 2, 5)
    assert buf == "hello"
    assert pos == 5


def test_apply_line_edit_ctrl_k():
    """Ctrl+K kills text from cursor to end of line."""
    buf, pos = _apply_line_edit("hello world", 5, 11)
    assert buf == "hello"
    assert pos == 5


def test_apply_line_edit_ctrl_w():
    """Ctrl+W deletes the word before the cursor."""
    buf, pos = _apply_line_edit("foo bar", 7, 23)
    assert buf == "foo "
    assert pos == 4


def test_apply_line_edit_unknown_key():
    """Unknown keys leave buffer and position unchanged."""
    buf, pos = _apply_line_edit("abc", 1, 999)
    assert buf == "abc"
    assert pos == 1


# ── Batch concept wizard — _launch_batch_create ──────────────────────────────


def test_launch_batch_create_builds_drafts(simple_taxonomy, tmp_path):
    """_launch_batch_create builds BatchCreateState from checked candidates."""
    v = _make_viewer(simple_taxonomy, tmp_path)
    cs = CreateState(
        parent_uri=BASE + "Scheme",
        ai_candidates=["Alpha", "Beta", "Gamma"],
        ai_checked=[True, False, True],
        came_from_tree=True,
    )
    v._state = cs
    v._launch_batch_create(cs)

    bcs = v._state
    assert isinstance(bcs, BatchCreateState)
    assert len(bcs.drafts) == 2
    assert bcs.drafts[0].name == "Alpha"
    assert bcs.drafts[1].name == "Gamma"
    assert bcs.drafts[0].alts_generating is False
    assert bcs.drafts[1].alts_generating is False
    assert bcs.came_from_tree is True
    assert bcs.step == "label"


# ── Batch concept wizard — _batch_advance_or_recap ───────────────────────────


def test_batch_advance_or_recap_next_concept(simple_taxonomy, tmp_path):
    """Advances to the next concept when not on last draft."""
    v = _make_viewer(simple_taxonomy, tmp_path)
    bcs = BatchCreateState(
        drafts=[
            BatchConceptDraft(name="A", pref_label="A"),
            BatchConceptDraft(name="B", pref_label="B"),
        ],
        current=0,
        step="definition",
    )
    v._state = bcs
    v._batch_advance_or_recap(bcs)

    assert bcs.current == 1
    assert bcs.step == "label"
    assert bcs.label_buffer == "B"


def test_batch_advance_or_recap_last_goes_to_recap(simple_taxonomy, tmp_path):
    """Advances to 'recap' step when on the last draft."""
    v = _make_viewer(simple_taxonomy, tmp_path)
    bcs = BatchCreateState(
        drafts=[BatchConceptDraft(name="Only", pref_label="Only")],
        current=0,
        step="definition",
    )
    v._state = bcs
    v._batch_advance_or_recap(bcs)

    assert bcs.step == "recap"
    assert bcs.recap_cursor == 0


# ── Batch concept wizard — _on_batch_label ───────────────────────────────────


def test_on_batch_label_enter_advances_to_definition(simple_taxonomy, tmp_path):
    """Enter on label step confirms the label and moves to definition step with def_generating."""
    v = _make_viewer(simple_taxonomy, tmp_path)
    bcs = BatchCreateState(
        drafts=[BatchConceptDraft(name="Alpha", pref_label="Alpha")],
        current=0,
        step="label",
        label_buffer="Machine Learning",
        label_pos=16,
    )
    v._state = bcs
    v._on_batch_label(ord("\n"), 24, bcs)

    assert bcs.step == "definition"
    assert bcs.drafts[0].pref_label == "Machine Learning"
    assert bcs.drafts[0].def_generating is True


def test_on_batch_label_esc_cancels_to_tree(simple_taxonomy, tmp_path):
    """Esc on label step cancels and returns to TreeState (came_from_tree=True)."""
    v = _make_viewer(simple_taxonomy, tmp_path)
    bcs = BatchCreateState(
        drafts=[BatchConceptDraft(name="Alpha", pref_label="Alpha")],
        came_from_tree=True,
        step="label",
        label_buffer="Alpha",
    )
    v._state = bcs
    v._on_batch_label(27, 24, bcs)

    assert isinstance(v._state, TreeState)


def test_on_batch_label_edit_updates_buffer(simple_taxonomy, tmp_path):
    """Typing in label step appends to the label_buffer."""
    v = _make_viewer(simple_taxonomy, tmp_path)
    bcs = BatchCreateState(
        drafts=[BatchConceptDraft(name="Alpha", pref_label="Alpha")],
        step="label",
        label_buffer="A",
        label_pos=1,
    )
    v._state = bcs
    v._on_batch_label(ord("I"), 24, bcs)

    assert bcs.label_buffer == "AI"
    assert bcs.label_pos == 2


# ── Batch concept wizard — _on_batch_alt_labels ──────────────────────────────


def test_on_batch_alt_labels_space_toggles(simple_taxonomy, tmp_path):
    """Space toggles a checkbox in alt_labels step."""
    v = _make_viewer(simple_taxonomy, tmp_path)
    draft = BatchConceptDraft(
        name="Alpha",
        pref_label="Alpha",
        alt_labels=["ML", "AI"],
        alt_checked=[True, True],
    )
    bcs = BatchCreateState(drafts=[draft], step="alt_labels", alt_cursor=0)
    v._state = bcs
    v._on_batch_alt_labels(ord(" "), 24, bcs)

    assert draft.alt_checked[0] is False
    assert draft.alt_checked[1] is True


def test_on_batch_alt_labels_enter_on_done_creates_and_confirms(simple_taxonomy, tmp_path):
    """Enter on 'Done' row in alt_labels step creates the concept and goes to confirm."""
    v = _make_viewer(simple_taxonomy, tmp_path)
    draft = BatchConceptDraft(
        name="OnlyUnique2", pref_label="Only Unique 2", alt_labels=["ML"], alt_checked=[True]
    )
    bcs = BatchCreateState(
        parent_uri=BASE + "Scheme",
        drafts=[draft],
        current=0,
        step="alt_labels",
        alt_cursor=1,  # Done row (index = len(alt_labels))
    )
    v._state = bcs
    v._on_batch_alt_labels(ord("\n"), 24, bcs)

    assert bcs.step == "confirm"
    assert any("OnlyUnique2" in uri for uri in simple_taxonomy.concepts)


def test_on_batch_alt_labels_esc_returns_to_alt_prompt_review(simple_taxonomy, tmp_path):
    """Esc in alt_labels step goes back to alt_prompt_review step."""
    v = _make_viewer(simple_taxonomy, tmp_path)
    draft = BatchConceptDraft(
        name="Alpha", pref_label="Alpha", alt_labels=["ML"], alt_checked=[True]
    )
    bcs = BatchCreateState(drafts=[draft], step="alt_labels")
    v._state = bcs
    v._on_batch_alt_labels(27, 24, bcs)

    assert bcs.step == "alt_prompt_review"


# ── Batch concept wizard — _on_batch_definition ──────────────────────────────


def test_on_batch_definition_enter_advances_to_alt_prompt_review(simple_taxonomy, tmp_path):
    """Enter in definition step renders the alt-labels prompt and goes to alt_prompt_review."""
    v = _make_viewer(simple_taxonomy, tmp_path)
    draft = BatchConceptDraft(
        name="OnlyUnique", pref_label="Only Unique", definition="A definition."
    )
    bcs = BatchCreateState(
        parent_uri=BASE + "Scheme",
        drafts=[draft],
        current=0,
        step="definition",
    )
    v._state = bcs
    v._on_batch_definition(ord("\n"), 24, bcs)

    assert bcs.step == "alt_prompt_review"
    assert "Only Unique" in bcs.alt_prompt_buffer
    # Concept NOT yet created at definition step
    assert not any("OnlyUnique" in uri for uri in simple_taxonomy.concepts)


def test_on_batch_definition_esc_returns_to_label(simple_taxonomy, tmp_path):
    """Esc in definition step goes back to label step."""
    v = _make_viewer(simple_taxonomy, tmp_path)
    draft = BatchConceptDraft(name="Only", pref_label="Only")
    bcs = BatchCreateState(drafts=[draft], step="definition")
    v._state = bcs
    v._on_batch_definition(27, 24, bcs)

    assert bcs.step == "label"


def test_on_batch_definition_edit_updates_definition(simple_taxonomy, tmp_path):
    """Typing in definition step appends to draft.definition."""
    v = _make_viewer(simple_taxonomy, tmp_path)
    draft = BatchConceptDraft(name="Only", pref_label="Only", definition="A")
    bcs = BatchCreateState(drafts=[draft], step="definition")
    bcs.def_pos = 1
    v._state = bcs
    v._on_batch_definition(ord("B"), 24, bcs)

    assert draft.definition == "AB"
    assert bcs.def_pos == 2


# ── Batch concept wizard — _on_batch_confirm ─────────────────────────────────


def test_on_batch_confirm_continue_advances_to_next_label(simple_taxonomy, tmp_path):
    """Continue in confirm step (not last) advances to label step of next concept."""
    v = _make_viewer(simple_taxonomy, tmp_path)
    drafts = [
        BatchConceptDraft(name="Alpha", pref_label="Alpha"),
        BatchConceptDraft(name="Beta", pref_label="Beta"),
    ]
    bcs = BatchCreateState(drafts=drafts, current=0, step="confirm", confirm_cursor=0)
    v._state = bcs
    v._on_batch_confirm(ord("\n"), 24, bcs)

    assert bcs.current == 1
    assert bcs.step == "label"
    assert bcs.label_buffer == "Beta"


def test_on_batch_confirm_stop_navigates_away(simple_taxonomy, tmp_path):
    """Stop (cursor=1) in confirm step navigates back to tree or detail."""
    v = _make_viewer(simple_taxonomy, tmp_path)
    # Pre-create a concept so _navigate_after_batch can find it
    from ster import operations

    operations.add_concept(
        simple_taxonomy,
        BASE + "ConfirmStop",
        {"en": "Confirm Stop"},
        parent_handle=None,
    )
    v._rebuild()
    drafts = [BatchConceptDraft(name="ConfirmStop", pref_label="Confirm Stop")]
    bcs = BatchCreateState(
        parent_uri=BASE + "Scheme",
        drafts=drafts,
        current=0,
        step="confirm",
        confirm_cursor=1,
        came_from_tree=True,
    )
    v._state = bcs
    v._on_batch_confirm(ord("\n"), 24, bcs)

    # Should have navigated to a non-batch state
    assert not isinstance(v._state, BatchCreateState)


def test_on_batch_confirm_last_concept_shows_done_only(simple_taxonomy, tmp_path):
    """On the last concept, confirm cursor is capped at 0 (only Done action)."""
    v = _make_viewer(simple_taxonomy, tmp_path)
    drafts = [BatchConceptDraft(name="Solo", pref_label="Solo")]
    bcs = BatchCreateState(drafts=drafts, current=0, step="confirm", confirm_cursor=0)
    v._state = bcs
    # Down key should not go past 0 on last concept
    v._on_batch_confirm(258, 24, bcs)  # 258 = curses.KEY_DOWN
    assert bcs.confirm_cursor == 0  # stays at 0 — only 1 action ("Done")


# ── Batch concept wizard — AI functions ──────────────────────────────────────


def test_suggest_alt_labels_parses_response(tmp_path, monkeypatch):
    """suggest_alt_labels cleans and returns parsed labels from LLM response."""
    from ster import ai

    monkeypatch.setattr(ai, "_call", lambda prompt, task: "1. ML\n2. AI\n3. Deep Learning\n")
    result = ai.suggest_alt_labels("Machine Learning", "Tech taxonomy", "", "en")
    assert result == ["ML", "AI", "Deep Learning"]


def test_suggest_alt_labels_caps_at_five(tmp_path, monkeypatch):
    """suggest_alt_labels returns at most 5 labels."""
    from ster import ai

    monkeypatch.setattr(ai, "_call", lambda p, t: "A\nB\nC\nD\nE\nF\nG\n")
    result = ai.suggest_alt_labels("X", "T", "", "en")
    assert len(result) <= 5


def test_suggest_definition_strips_response(tmp_path, monkeypatch):
    """suggest_definition returns stripped text from LLM response."""
    from ster import ai

    monkeypatch.setattr(ai, "_call", lambda p, t: "  A concise definition.  \n")
    result = ai.suggest_definition("Concept", "Taxonomy", "", None, "en")
    assert result == "A concise definition."
