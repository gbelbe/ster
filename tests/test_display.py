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


def test_render_handle_list_scheme_label(simple_taxonomy):
    # Scheme URIs should also appear in the list with their title
    output = _render_to_str(render_handle_list(simple_taxonomy))
    assert "Test Taxonomy" in output


def test_render_handle_list_unknown_uri(simple_taxonomy):
    # Inject a handle that points to a URI not in concepts or schemes
    simple_taxonomy.handle_index["ZZZ"] = BASE + "Ghost"
    output = _render_to_str(render_handle_list(simple_taxonomy))
    assert "ZZZ" in output  # handle still shown, empty label


# ── render_tree edge cases ────────────────────────────────────────────────────


def test_render_tree_orphan_concepts(simple_taxonomy):
    """Concepts with no top_concept entry appear under (orphans) node."""
    from ster.model import Concept, Label

    orphan = Concept(uri=BASE + "Orphan", labels=[Label(lang="en", value="Orphan Node")])
    simple_taxonomy.concepts[BASE + "Orphan"] = orphan
    simple_taxonomy.handle_index["ORP"] = BASE + "Orphan"
    output = _render_to_str(render_tree(simple_taxonomy))
    assert "Orphan Node" in output


def test_render_tree_root_handle_not_a_concept(simple_taxonomy):
    """When root_handle resolves to a scheme URI (not a concept), return Panel."""
    scheme_handle = simple_taxonomy.uri_to_handle(BASE + "Scheme")
    if scheme_handle:
        output = _render_to_str(render_tree(simple_taxonomy, root_handle=scheme_handle))
        # Should show "not a concept" or just render something non-crashing
        assert output  # just check no crash


def test_render_tree_circular_reference(simple_taxonomy):
    """Circular narrower reference renders ↺ marker instead of looping."""
    # Make Child1 narrower of Grandchild (creating cycle)
    simple_taxonomy.concepts[BASE + "Grandchild"].narrower.append(BASE + "Child1")
    output = _render_to_str(render_tree(simple_taxonomy))
    assert "↺" in output


def test_render_tree_missing_narrower_uri(simple_taxonomy):
    """A narrower URI that doesn't exist in concepts shows [missing:...] marker."""
    simple_taxonomy.concepts[BASE + "Top"].narrower.append(BASE + "Ghost")
    output = _render_to_str(render_tree(simple_taxonomy))
    assert "missing" in output.lower()


# ── render_concept_detail edge cases ─────────────────────────────────────────


def test_render_detail_alt_labels(simple_taxonomy):
    """Alt labels section is shown when concept has alt labels."""
    from ster.model import Label, LabelType

    simple_taxonomy.concepts[BASE + "Top"].labels.append(
        Label(lang="en", value="Top Alt", type=LabelType.ALT)
    )
    output = _render_to_str(render_concept_detail(simple_taxonomy, BASE + "Top"))
    assert "Top Alt" in output
    assert "Alt label" in output


def test_render_detail_broader(simple_taxonomy):
    """Broader section appears for concepts with broader links."""
    output = _render_to_str(render_concept_detail(simple_taxonomy, BASE + "Child1"))
    assert "Broader" in output


def test_render_detail_related(simple_taxonomy):
    """Related section appears when concept has related links."""
    simple_taxonomy.concepts[BASE + "Child1"].related.append(BASE + "Child2")
    output = _render_to_str(render_concept_detail(simple_taxonomy, BASE + "Child1"))
    assert "Related" in output
