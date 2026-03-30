"""Tests for ster/git_log_logic.py — pure functions, no curses, no subprocess."""

from __future__ import annotations

from ster.git_log_logic import (
    ConceptChange,
    FieldDiff,
    LogEntry,
    _concept_field_diffs,
    _parse_log,
    _subtree_has_change,
    build_diff_taxonomy,
    compute_auto_fold,
    compute_taxonomy_diff,
)
from ster.handles import assign_handles
from ster.model import Concept, ConceptScheme, Definition, Label, LabelType, Taxonomy

SEP = "\x1f"
BASE = "https://example.org/test/"


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_log_line(full: str, short: str, subject: str, author: str, date: str, refs: str) -> str:
    return f"{SEP}{full}{SEP}{short}{SEP}{subject}{SEP}{author}{SEP}{date}{SEP}{refs}"


def _make_taxonomy(concepts: list[tuple[str, str, list[str]]]) -> Taxonomy:
    """Build a simple taxonomy. Each tuple: (uri_suffix, pref_label, alt_labels)."""
    t = Taxonomy()
    s = ConceptScheme(uri=BASE + "S", labels=[Label("en", "Test")])
    t.schemes[s.uri] = s
    for suffix, label, alts in concepts:
        uri = BASE + suffix
        labels = [Label("en", label, LabelType.PREF)]
        labels += [Label("en", a, LabelType.ALT) for a in alts]
        c = Concept(uri=uri, labels=labels)
        t.concepts[uri] = c
        s.top_concepts.append(uri)
    assign_handles(t)
    return t


# ── FieldDiff.status ──────────────────────────────────────────────────────────


def test_field_diff_status_added():
    assert FieldDiff("altLabel[en]", "", "synonym").status == "added"


def test_field_diff_status_removed():
    assert FieldDiff("altLabel[en]", "old", "").status == "removed"


def test_field_diff_status_changed():
    assert FieldDiff("prefLabel[en]", "Old", "New").status == "changed"


# ── _parse_log ────────────────────────────────────────────────────────────────


def test_parse_log_valid_single():
    line = _make_log_line("a" * 40, "aaaaaaa", "Initial commit", "Alice", "2024-01-15", "HEAD -> main")
    entries = _parse_log(line)
    assert len(entries) == 1
    e = entries[0]
    assert e.full_hash == "a" * 40
    assert e.short_hash == "aaaaaaa"
    assert e.subject == "Initial commit"
    assert e.author == "Alice"
    assert e.date == "2024-01-15"
    assert e.refs == "HEAD -> main"


def test_parse_log_empty_string():
    assert _parse_log("") == []


def test_parse_log_malformed_too_few_fields():
    bad = f"{SEP}abc123{SEP}abc"  # only 2 fields after leading SEP
    assert _parse_log(bad) == []


def test_parse_log_multiple_commits():
    lines = [
        _make_log_line("a" * 40, "aaaaaaa", "A", "Alice", "2024-01-15", "HEAD"),
        _make_log_line("b" * 40, "bbbbbbb", "B", "Bob", "2024-01-14", ""),
        _make_log_line("c" * 40, "ccccccc", "C", "Carol", "2024-01-13", ""),
    ]
    entries = _parse_log("\n".join(lines))
    assert len(entries) == 3
    assert [e.author for e in entries] == ["Alice", "Bob", "Carol"]


def test_parse_log_skips_lines_without_sep():
    regular = "just a plain line"
    commit = _make_log_line("a" * 40, "aaaaaaa", "Msg", "Alice", "2024-01-01", "")
    entries = _parse_log("\n".join([regular, commit]))
    assert len(entries) == 1


def test_parse_log_refs_stripped():
    line = _make_log_line("c" * 40, "ccccccc", "Msg", "Carol", "2024-01-10", "  tag: v1.0  ")
    entries = _parse_log(line)
    assert entries[0].refs == "tag: v1.0"


def test_parse_log_strips_control_chars():
    # Subject with an embedded escape sequence (e.g. cursor-key artifact)
    subject_with_control = "Fix thing\x1b[A"
    line = _make_log_line("a" * 40, "aaaaaaa", subject_with_control, "Alice", "2024-01-01", "")
    entries = _parse_log(line)
    assert "\x1b" not in entries[0].subject


# ── _concept_field_diffs ──────────────────────────────────────────────────────


def test_concept_field_diffs_no_change():
    c = Concept(uri=BASE + "C", labels=[Label("en", "Same", LabelType.PREF)])
    assert _concept_field_diffs(c, c) == []


def test_concept_field_diffs_pref_label_changed():
    before = Concept(uri=BASE + "C", labels=[Label("en", "Old", LabelType.PREF)])
    after = Concept(uri=BASE + "C", labels=[Label("en", "New", LabelType.PREF)])
    diffs = _concept_field_diffs(before, after)
    assert len(diffs) == 1
    assert diffs[0].label == "prefLabel[en]"
    assert diffs[0].before == "Old"
    assert diffs[0].after == "New"


def test_concept_field_diffs_alt_label_added():
    before = Concept(uri=BASE + "C", labels=[Label("en", "Concept", LabelType.PREF)])
    after = Concept(
        uri=BASE + "C",
        labels=[Label("en", "Concept", LabelType.PREF), Label("en", "synonym", LabelType.ALT)],
    )
    diffs = _concept_field_diffs(before, after)
    alt_diffs = [d for d in diffs if d.label == "altLabel[en]"]
    assert len(alt_diffs) == 1
    assert alt_diffs[0].before == ""
    assert alt_diffs[0].after == "synonym"


def test_concept_field_diffs_alt_label_removed():
    before = Concept(
        uri=BASE + "C",
        labels=[Label("en", "Concept", LabelType.PREF), Label("en", "old-alt", LabelType.ALT)],
    )
    after = Concept(uri=BASE + "C", labels=[Label("en", "Concept", LabelType.PREF)])
    diffs = _concept_field_diffs(before, after)
    alt_diffs = [d for d in diffs if d.label == "altLabel[en]"]
    assert len(alt_diffs) == 1
    assert alt_diffs[0].before == "old-alt"
    assert alt_diffs[0].after == ""


def test_concept_field_diffs_definition_changed():
    before = Concept(
        uri=BASE + "C",
        labels=[Label("en", "C", LabelType.PREF)],
        definitions=[Definition("en", "Old def")],
    )
    after = Concept(
        uri=BASE + "C",
        labels=[Label("en", "C", LabelType.PREF)],
        definitions=[Definition("en", "New def")],
    )
    diffs = _concept_field_diffs(before, after)
    def_diffs = [d for d in diffs if d.label == "definition[en]"]
    assert len(def_diffs) == 1
    assert def_diffs[0].before == "Old def"
    assert def_diffs[0].after == "New def"


# ── compute_taxonomy_diff ─────────────────────────────────────────────────────


def test_compute_diff_added():
    before = _make_taxonomy([])
    after = _make_taxonomy([("C", "New concept", [])])
    diff = compute_taxonomy_diff(before, after)
    assert diff[BASE + "C"].status == "added"
    assert diff[BASE + "C"].field_diffs == []


def test_compute_diff_removed():
    before = _make_taxonomy([("C", "Old concept", [])])
    after = _make_taxonomy([])
    diff = compute_taxonomy_diff(before, after)
    assert diff[BASE + "C"].status == "removed"


def test_compute_diff_unchanged():
    t = _make_taxonomy([("C", "Same", [])])
    diff = compute_taxonomy_diff(t, t)
    assert diff[BASE + "C"].status == "unchanged"


def test_compute_diff_changed():
    before = _make_taxonomy([("C", "Old label", [])])
    after = _make_taxonomy([("C", "New label", [])])
    diff = compute_taxonomy_diff(before, after)
    assert diff[BASE + "C"].status == "changed"
    fd = diff[BASE + "C"].field_diffs
    assert any(f.label == "prefLabel[en]" for f in fd)


def test_compute_diff_mixed():
    before = _make_taxonomy([("A", "Alpha", []), ("B", "Beta", [])])
    after = _make_taxonomy([("A", "Alpha Changed", []), ("C", "Gamma", [])])
    diff = compute_taxonomy_diff(before, after)
    assert diff[BASE + "A"].status == "changed"
    assert diff[BASE + "B"].status == "removed"
    assert diff[BASE + "C"].status == "added"


# ── build_diff_taxonomy ───────────────────────────────────────────────────────


def test_build_diff_taxonomy_includes_deleted():
    before = _make_taxonomy([("A", "Alpha", []), ("B", "Beta", [])])
    after = _make_taxonomy([("A", "Alpha", [])])
    merged = build_diff_taxonomy(before, after)
    assert BASE + "B" in merged.concepts


def test_build_diff_taxonomy_keeps_after_concepts():
    before = _make_taxonomy([])
    after = _make_taxonomy([("X", "New", [])])
    merged = build_diff_taxonomy(before, after)
    assert BASE + "X" in merged.concepts


def test_build_diff_taxonomy_ghost_attached_to_parent():
    before = Taxonomy()
    s = ConceptScheme(uri=BASE + "S", labels=[Label("en", "S")])
    parent = Concept(
        uri=BASE + "P", labels=[Label("en", "P", LabelType.PREF)], narrower=[BASE + "C"]
    )
    child = Concept(
        uri=BASE + "C", labels=[Label("en", "C", LabelType.PREF)], broader=[BASE + "P"]
    )
    before.schemes[s.uri] = s
    before.concepts[parent.uri] = parent
    before.concepts[child.uri] = child
    s.top_concepts = [BASE + "P"]
    assign_handles(before)

    after = Taxonomy()
    s2 = ConceptScheme(uri=BASE + "S", labels=[Label("en", "S")])
    p2 = Concept(uri=BASE + "P", labels=[Label("en", "P", LabelType.PREF)])
    after.schemes[s2.uri] = s2
    after.concepts[p2.uri] = p2
    s2.top_concepts = [BASE + "P"]
    assign_handles(after)

    merged = build_diff_taxonomy(before, after)
    assert BASE + "C" in merged.concepts
    assert BASE + "C" in merged.concepts[BASE + "P"].narrower


def test_build_diff_taxonomy_ghost_at_root_when_no_parent():
    before = _make_taxonomy([("A", "Alpha", []), ("B", "Beta", [])])
    # B has no broader — it's a top concept
    before.concepts[BASE + "B"].broader = []

    after = _make_taxonomy([("A", "Alpha", [])])
    merged = build_diff_taxonomy(before, after)
    # Ghost B should appear in scheme's top_concepts
    assert BASE + "B" in merged.concepts
    scheme = merged.primary_scheme()
    assert scheme is not None
    assert BASE + "B" in scheme.top_concepts


# ── _subtree_has_change ───────────────────────────────────────────────────────


def test_subtree_has_change_direct_change():
    t = _make_taxonomy([("P", "Parent", []), ("C", "Child", [])])
    t.concepts[BASE + "P"].narrower = [BASE + "C"]
    diff = {
        BASE + "P": ConceptChange(BASE + "P", "unchanged"),
        BASE + "C": ConceptChange(BASE + "C", "changed"),
    }
    assert _subtree_has_change(t, BASE + "P", diff, set()) is True


def test_subtree_has_change_no_change():
    t = _make_taxonomy([("P", "Parent", []), ("C", "Child", [])])
    t.concepts[BASE + "P"].narrower = [BASE + "C"]
    diff = {
        BASE + "P": ConceptChange(BASE + "P", "unchanged"),
        BASE + "C": ConceptChange(BASE + "C", "unchanged"),
    }
    assert _subtree_has_change(t, BASE + "P", diff, set()) is False


def test_subtree_has_change_circular_reference():
    t = _make_taxonomy([("A", "A", []), ("B", "B", [])])
    # Create a cycle
    t.concepts[BASE + "A"].narrower = [BASE + "B"]
    t.concepts[BASE + "B"].narrower = [BASE + "A"]
    diff = {
        BASE + "A": ConceptChange(BASE + "A", "unchanged"),
        BASE + "B": ConceptChange(BASE + "B", "unchanged"),
    }
    # Should not infinite loop
    result = _subtree_has_change(t, BASE + "A", diff, set())
    assert result is False


def test_subtree_has_change_missing_concept():
    t = _make_taxonomy([])
    diff: dict = {}
    assert _subtree_has_change(t, BASE + "Missing", diff, set()) is False


# ── compute_auto_fold ─────────────────────────────────────────────────────────


def test_auto_fold_unchanged_subtree():
    t = _make_taxonomy([("P", "Parent", []), ("C", "Child", [])])
    t.concepts[BASE + "P"].narrower = [BASE + "C"]
    t.concepts[BASE + "C"].broader = [BASE + "P"]
    diff = {
        BASE + "P": ConceptChange(BASE + "P", "unchanged"),
        BASE + "C": ConceptChange(BASE + "C", "unchanged"),
    }
    folded = compute_auto_fold(t, diff)
    assert BASE + "P" in folded


def test_auto_fold_changed_subtree_not_folded():
    t = _make_taxonomy([("P", "Parent", []), ("C", "Child", [])])
    t.concepts[BASE + "P"].narrower = [BASE + "C"]
    diff = {
        BASE + "P": ConceptChange(BASE + "P", "unchanged"),
        BASE + "C": ConceptChange(BASE + "C", "changed"),
    }
    folded = compute_auto_fold(t, diff)
    assert BASE + "P" not in folded


def test_auto_fold_leaf_never_folded():
    t = _make_taxonomy([("C", "Leaf", [])])
    diff = {BASE + "C": ConceptChange(BASE + "C", "unchanged")}
    folded = compute_auto_fold(t, diff)
    assert BASE + "C" not in folded


def test_auto_fold_scheme_folded_when_all_unchanged():
    t = _make_taxonomy([("C", "Concept", [])])
    diff = {BASE + "C": ConceptChange(BASE + "C", "unchanged")}
    folded = compute_auto_fold(t, diff)
    assert BASE + "S" in folded


def test_auto_fold_scheme_not_folded_when_changed():
    t = _make_taxonomy([("C", "Concept", [])])
    diff = {BASE + "C": ConceptChange(BASE + "C", "added")}
    folded = compute_auto_fold(t, diff)
    assert BASE + "S" not in folded
