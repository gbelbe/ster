"""Tests for the display layer."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from ster.display import render_concept_detail, render_handle_list, render_tree

BASE = "https://example.org/test/"


def _render_to_str(renderable) -> str:
    buf = StringIO()
    con = Console(file=buf, highlight=False, markup=False)
    con.print(renderable)
    return buf.getvalue()


# ── render_tree ───────────────────────────────────────────────────────────────


def test_render_tree_contains_all_handles(simple_taxonomy):
    output = _render_to_str(render_tree(simple_taxonomy))
    for handle in simple_taxonomy.handle_index:
        if simple_taxonomy.handle_index[handle] in simple_taxonomy.concepts:
            assert f"[{handle}]" in output, f"Handle [{handle}] missing from tree output"


def test_render_tree_contains_labels(simple_taxonomy):
    output = _render_to_str(render_tree(simple_taxonomy))
    assert "Top Concept" in output
    assert "Child One" in output
    assert "Child Two" in output
    assert "Grandchild" in output


def test_render_subtree_excludes_siblings(simple_taxonomy):
    child1_uri = BASE + "Child1"
    child1_handle = simple_taxonomy.uri_to_handle(child1_uri)
    output = _render_to_str(render_tree(simple_taxonomy, root_handle=child1_handle))
    assert "Child One" in output
    assert "Grandchild" in output
    # Child2 is a sibling, should NOT appear
    assert "Child Two" not in output


def test_render_tree_unknown_handle(simple_taxonomy):
    output = _render_to_str(render_tree(simple_taxonomy, root_handle="ZZZNOPE"))
    assert "not found" in output.lower()


# ── render_concept_detail ─────────────────────────────────────────────────────


def test_render_detail_contains_uri(simple_taxonomy):
    uri = BASE + "Top"
    output = _render_to_str(render_concept_detail(simple_taxonomy, uri))
    assert uri in output


def test_render_detail_contains_all_labels(simple_taxonomy):
    uri = BASE + "Top"
    output = _render_to_str(render_concept_detail(simple_taxonomy, uri))
    assert "Top Concept" in output
    assert "Concept Principal" in output


def test_render_detail_contains_definition(simple_taxonomy):
    uri = BASE + "Top"
    output = _render_to_str(render_concept_detail(simple_taxonomy, uri))
    assert "The root." in output


def test_render_detail_contains_narrower_handles(simple_taxonomy):
    uri = BASE + "Top"
    output = _render_to_str(render_concept_detail(simple_taxonomy, uri))
    child1_handle = simple_taxonomy.uri_to_handle(BASE + "Child1")
    child2_handle = simple_taxonomy.uri_to_handle(BASE + "Child2")
    assert f"[{child1_handle}]" in output
    assert f"[{child2_handle}]" in output


def test_render_detail_missing_concept(simple_taxonomy):
    output = _render_to_str(render_concept_detail(simple_taxonomy, BASE + "Ghost"))
    assert "not found" in output.lower()


# ── render_handle_list ────────────────────────────────────────────────────────


def test_render_handle_list_row_count(simple_taxonomy):
    output = _render_to_str(render_handle_list(simple_taxonomy))
    # Each handle should appear exactly once
    for handle in simple_taxonomy.handle_index:
        assert handle in output


def test_render_handle_list_contains_labels(simple_taxonomy):
    output = _render_to_str(render_handle_list(simple_taxonomy))
    assert "Top Concept" in output
    assert "Child One" in output
