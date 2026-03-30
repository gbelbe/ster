"""Tests for ster/nav_logic.py — pure tree/detail logic, no curses."""

from __future__ import annotations

from ster.handles import assign_handles
from ster.model import (
    Concept,
    ConceptScheme,
    Label,
    LabelType,
    Taxonomy,
)
from ster.nav_logic import (
    _available_langs,
    _breadcrumb,
    _children,
    _count_descendants,
    _flatten_taxonomy,
    _parent_uri,
    build_detail_fields,
    build_scheme_fields,
    flatten_tree,
)
from ster.workspace import TaxonomyWorkspace

BASE = "https://example.org/test/"


# ── _count_descendants ────────────────────────────────────────────────────────


def test_count_descendants_leaf(simple_taxonomy):
    assert _count_descendants(simple_taxonomy, BASE + "Child2") == 0


def test_count_descendants_one_level(simple_taxonomy):
    # Child1 has one child: Grandchild
    assert _count_descendants(simple_taxonomy, BASE + "Child1") == 1


def test_count_descendants_top(simple_taxonomy):
    # Top -> Child1 -> Grandchild, Top -> Child2 = 3
    assert _count_descendants(simple_taxonomy, BASE + "Top") == 3


def test_count_descendants_missing(simple_taxonomy):
    assert _count_descendants(simple_taxonomy, BASE + "Nonexistent") == 0


# ── flatten_tree (single taxonomy) ───────────────────────────────────────────


def test_flatten_tree_returns_scheme_and_concepts(simple_taxonomy):
    lines = flatten_tree(simple_taxonomy)
    uris = [l.uri for l in lines]
    assert BASE + "Scheme" in uris
    assert BASE + "Top" in uris
    assert BASE + "Child1" in uris
    assert BASE + "Child2" in uris
    assert BASE + "Grandchild" in uris


def test_flatten_tree_scheme_first(simple_taxonomy):
    lines = flatten_tree(simple_taxonomy)
    assert lines[0].is_scheme
    assert lines[0].uri == BASE + "Scheme"


def test_flatten_tree_folded_scheme(simple_taxonomy):
    folded = {BASE + "Scheme"}
    lines = flatten_tree(simple_taxonomy, folded=folded)
    uris = [l.uri for l in lines]
    # Only scheme row should be present when scheme is folded
    assert BASE + "Scheme" in uris
    assert BASE + "Top" not in uris
    scheme_line = next(l for l in lines if l.is_scheme)
    assert scheme_line.is_folded is True
    assert scheme_line.hidden_count > 0


def test_flatten_tree_folded_concept(simple_taxonomy):
    folded = {BASE + "Top"}
    lines = flatten_tree(simple_taxonomy, folded=folded)
    uris = [l.uri for l in lines]
    assert BASE + "Top" in uris
    assert BASE + "Child1" not in uris
    top_line = next(l for l in lines if l.uri == BASE + "Top")
    assert top_line.is_folded is True


# ── _flatten_taxonomy ─────────────────────────────────────────────────────────


def test_flatten_taxonomy_with_depth_offset(simple_taxonomy, tmp_path):
    fp = tmp_path / "a.ttl"
    lines = _flatten_taxonomy(
        simple_taxonomy,
        file_path=fp,
        scheme_depth=1,
        scheme_prefix="    ",
        concept_base_depth=1,
    )
    scheme_line = next(l for l in lines if l.is_scheme)
    assert scheme_line.depth == 1
    assert scheme_line.prefix == "    "
    assert scheme_line.file_path == fp


# ── flatten_tree (workspace) ──────────────────────────────────────────────────


def test_flatten_tree_single_file_workspace(simple_taxonomy, tmp_path):
    fp = tmp_path / "a.ttl"
    ws = TaxonomyWorkspace({fp: simple_taxonomy})
    lines = flatten_tree(ws)
    # Single-file workspace: no file node
    assert not any(l.is_file for l in lines)
    assert any(l.is_scheme for l in lines)


def test_flatten_tree_multi_file_workspace(simple_taxonomy, tmp_path):
    fp1 = tmp_path / "a.ttl"
    fp2 = tmp_path / "b.ttl"

    # Build a second minimal taxonomy
    t2 = Taxonomy()
    s2 = ConceptScheme(uri=BASE + "S2", labels=[Label("en", "Second")])
    c2 = Concept(uri=BASE + "X", labels=[Label("en", "X", LabelType.PREF)])
    t2.schemes[s2.uri] = s2
    t2.concepts[c2.uri] = c2
    s2.top_concepts = [c2.uri]
    assign_handles(t2)

    ws = TaxonomyWorkspace({fp1: simple_taxonomy, fp2: t2})
    lines = flatten_tree(ws)
    file_lines = [l for l in lines if l.is_file]
    assert len(file_lines) == 2
    assert file_lines[0].file_path == fp1
    assert file_lines[1].file_path == fp2


def test_flatten_tree_multi_file_folded_file(simple_taxonomy, tmp_path):
    fp1 = tmp_path / "a.ttl"
    fp2 = tmp_path / "b.ttl"

    t2 = Taxonomy()
    s2 = ConceptScheme(uri=BASE + "S2", labels=[Label("en", "Second")])
    t2.schemes[s2.uri] = s2
    assign_handles(t2)

    from ster.nav_logic import _file_sentinel

    ws = TaxonomyWorkspace({fp1: simple_taxonomy, fp2: t2})
    folded = {_file_sentinel(fp1)}
    lines = flatten_tree(ws, folded=folded)
    file_line = next(l for l in lines if l.is_file and l.file_path == fp1)
    assert file_line.is_folded is True
    # No scheme/concept rows from fp1 should appear
    assert not any(l.file_path == fp1 and not l.is_file for l in lines)


# ── _children ─────────────────────────────────────────────────────────────────


def test_children_root(simple_taxonomy):
    kids = _children(simple_taxonomy, None)
    assert BASE + "Top" in kids


def test_children_concept(simple_taxonomy):
    kids = _children(simple_taxonomy, BASE + "Top")
    assert BASE + "Child1" in kids
    assert BASE + "Child2" in kids


def test_children_leaf(simple_taxonomy):
    assert _children(simple_taxonomy, BASE + "Child2") == []


def test_children_missing_uri(simple_taxonomy):
    assert _children(simple_taxonomy, BASE + "Nonexistent") == []


# ── _parent_uri ───────────────────────────────────────────────────────────────


def test_parent_uri_at_root(simple_taxonomy):
    assert _parent_uri(simple_taxonomy, None) is None


def test_parent_uri_top_concept(simple_taxonomy):
    assert _parent_uri(simple_taxonomy, BASE + "Top") is None


def test_parent_uri_child(simple_taxonomy):
    assert _parent_uri(simple_taxonomy, BASE + "Child1") == BASE + "Top"


def test_parent_uri_grandchild(simple_taxonomy):
    assert _parent_uri(simple_taxonomy, BASE + "Grandchild") == BASE + "Child1"


# ── _breadcrumb ───────────────────────────────────────────────────────────────


def test_breadcrumb_root(simple_taxonomy):
    assert _breadcrumb(simple_taxonomy, None) == "/"


def test_breadcrumb_top(simple_taxonomy):
    bc = _breadcrumb(simple_taxonomy, BASE + "Top")
    assert bc.startswith("/")
    assert "[" in bc  # handle notation


def test_breadcrumb_grandchild(simple_taxonomy):
    bc = _breadcrumb(simple_taxonomy, BASE + "Grandchild")
    # Should contain multiple path segments
    assert bc.count("[") >= 3


# ── build_detail_fields ───────────────────────────────────────────────────────


def test_build_detail_fields_missing_uri(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Nonexistent", "en")
    assert fields == []


def test_build_detail_fields_has_uri_field(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    uri_fields = [f for f in fields if f.key == "uri"]
    assert len(uri_fields) == 1
    assert uri_fields[0].value == BASE + "Top"
    assert uri_fields[0].editable is False


def test_build_detail_fields_pref_labels(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    pref_fields = [f for f in fields if f.key.startswith("pref:")]
    assert len(pref_fields) >= 1
    en_field = next(f for f in pref_fields if f.key == "pref:en")
    assert en_field.value == "Top Concept"
    assert en_field.editable is True


def test_build_detail_fields_alt_labels(taxonomy):
    """Use the disk-loaded taxonomy which has altLabel on Child2."""
    fields = build_detail_fields(taxonomy, BASE + "Child2", "en")
    alt_fields = [f for f in fields if f.key.startswith("alt:")]
    assert len(alt_fields) >= 1
    assert alt_fields[0].value == "Second child"


def test_build_detail_fields_definition(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    def_fields = [f for f in fields if f.key.startswith("def:")]
    assert len(def_fields) == 1
    assert def_fields[0].value == "The root."


def test_build_detail_fields_hierarchy_narrower(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    narrower_fields = [f for f in fields if f.key.startswith("narrower:")]
    assert len(narrower_fields) == 2  # Child1, Child2


def test_build_detail_fields_hierarchy_broader(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Child1", "en")
    broader_fields = [f for f in fields if f.key.startswith("broader:")]
    assert len(broader_fields) == 1
    assert BASE + "Top" in broader_fields[0].key


def test_build_detail_fields_actions_present(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    action_fields = [f for f in fields if f.meta.get("type") == "action"]
    action_names = [f.meta.get("action") for f in action_fields]
    assert "add_narrower" in action_names
    assert "delete" in action_names


def test_build_detail_fields_show_mappings(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en", show_mappings=True)
    map_actions = [f for f in fields if f.meta.get("action", "").startswith("map:")]
    assert len(map_actions) >= 1


def test_build_detail_fields_no_mappings_by_default(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en", show_mappings=False)
    map_actions = [f for f in fields if f.meta.get("action", "").startswith("map:")]
    assert len(map_actions) == 0


def test_build_detail_fields_separators(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    sep_fields = [f for f in fields if f.meta.get("type") == "separator"]
    labels = [f.display for f in sep_fields]
    assert "Identity" in labels
    assert "Labels" in labels


# ── build_scheme_fields ───────────────────────────────────────────────────────


def test_build_scheme_fields_no_scheme():
    t = Taxonomy()
    fields = build_scheme_fields(t, "en")
    assert fields == []


def test_build_scheme_fields_has_uri(simple_taxonomy):
    fields = build_scheme_fields(simple_taxonomy, "en")
    uri_fields = [f for f in fields if f.key == "scheme_uri"]
    assert len(uri_fields) == 1
    assert uri_fields[0].value == BASE + "Scheme"


def test_build_scheme_fields_display_lang(simple_taxonomy):
    fields = build_scheme_fields(simple_taxonomy, "fr")
    lang_field = next(f for f in fields if f.key == "display_lang")
    assert lang_field.value == "fr"


def test_build_scheme_fields_title(simple_taxonomy):
    fields = build_scheme_fields(simple_taxonomy, "en")
    title_fields = [f for f in fields if f.key.startswith("title:")]
    assert len(title_fields) >= 1


def test_build_scheme_fields_creator(simple_taxonomy):
    fields = build_scheme_fields(simple_taxonomy, "en")
    creator_fields = [f for f in fields if f.key == "creator"]
    assert len(creator_fields) == 1
    assert creator_fields[0].editable is True


def test_build_scheme_fields_explicit_scheme_uri(simple_taxonomy):
    fields = build_scheme_fields(simple_taxonomy, "en", scheme_uri=BASE + "Scheme")
    assert fields  # Should return fields for the specified scheme


def test_build_scheme_fields_missing_scheme_uri(simple_taxonomy):
    fields = build_scheme_fields(simple_taxonomy, "en", scheme_uri=BASE + "Nonexistent")
    assert fields == []


# ── _available_langs ──────────────────────────────────────────────────────────


def test_available_langs_basic(simple_taxonomy):
    langs = _available_langs(simple_taxonomy)
    assert "en" in langs
    assert "fr" in langs
    assert langs == sorted(langs)


def test_available_langs_empty_taxonomy():
    t = Taxonomy()
    langs = _available_langs(t)
    assert langs == []
