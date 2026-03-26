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
    flatten_tree, build_detail_fields,
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
def viewer(simple_taxonomy, tmp_path) -> TaxonomyViewer:
    f = tmp_path / "vocab.ttl"
    f.write_text("")
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
    assert viewer._mode == TaxonomyViewer._TREE


def test_viewer_open_detail(viewer, simple_taxonomy):
    viewer._open_detail()
    assert viewer._mode == TaxonomyViewer._DETAIL
    assert viewer._detail_uri == viewer._flat[0].uri
    assert len(viewer._detail_fields) > 0


def test_viewer_back_from_detail(viewer):
    viewer._open_detail()
    viewer._back()
    assert viewer._mode == TaxonomyViewer._TREE


def test_viewer_history_preserves_cursor(viewer):
    viewer._cursor = 2
    viewer._open_detail()
    viewer._back()
    assert viewer._cursor == 2


def test_viewer_commit_edit_updates_label(viewer, simple_taxonomy):
    # Position on Top concept's pref:en field
    viewer._open_detail()
    fields = viewer._detail_fields
    pref_idx = next(i for i, f in enumerate(fields) if f.key == "pref:en")
    viewer._field_cursor = pref_idx
    viewer._edit_value = "Updated Top"
    viewer._edit_pos   = len("Updated Top")
    viewer._commit_edit()
    assert simple_taxonomy.concepts[BASE + "Top"].pref_label("en") == "Updated Top"
