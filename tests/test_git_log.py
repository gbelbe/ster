"""Tests for ster/git_log.py — pure-function and mocked-subprocess coverage."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from ster.git_log import (
    ConceptChange,
    FieldDiff,
    GitLogViewer,
    LogEntry,
    _do_restore,
    _do_revert,
    _fetch_diff,
    _parse_log,
    build_diff_taxonomy,
    compute_auto_fold,
    compute_taxonomy_diff,
    find_repo_root,
)
from ster.handles import assign_handles
from ster.model import Concept, ConceptScheme, Label, LabelType, Taxonomy

SEP = "\x1f"
BASE = "https://example.org/test/"


# ── helpers ───────────────────────────────────────────────────────────────────


def _completed(stdout="", returncode=0):
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.stdout = stdout
    r.returncode = returncode
    r.stderr = ""
    return r


def _make_log_line(full: str, short: str, subject: str, author: str, date: str, refs: str) -> str:
    return f"{SEP}{full}{SEP}{short}{SEP}{subject}{SEP}{author}{SEP}{date}{SEP}{refs}"


# ── LogEntry ──────────────────────────────────────────────────────────────────


def test_log_entry_fields():
    e = LogEntry(
        full_hash="abcdef1234567890abcdef1234567890abcdef12",
        short_hash="abcdef1",
        subject="Fix the bug",
        author="Alice",
        date="2024-01-15",
        refs="HEAD -> main",
    )
    assert e.full_hash.startswith("abcdef")
    assert e.subject == "Fix the bug"
    assert e.date == "2024-01-15"
    assert e.author == "Alice"


# ── FieldDiff ─────────────────────────────────────────────────────────────────


def test_field_diff_status_added():
    assert FieldDiff("altLabel[en]", "", "synonym").status == "added"


def test_field_diff_status_removed():
    assert FieldDiff("altLabel[en]", "old", "").status == "removed"


def test_field_diff_status_changed():
    assert FieldDiff("prefLabel[en]", "Old", "New").status == "changed"


# ── _parse_log ────────────────────────────────────────────────────────────────


def test_parse_log_single_commit():
    line = _make_log_line(
        "a" * 40, "aaaaaaa", "Initial commit", "Alice", "2024-01-15", "HEAD -> main"
    )
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


def test_parse_log_line_with_too_few_parts_skipped():
    bad = f"{SEP}abc123{SEP}abc"  # only 2 fields after leading SEP
    assert _parse_log(bad) == []


def test_parse_log_refs_stripped():
    line = _make_log_line("c" * 40, "ccccccc", "Msg", "Carol", "2024-01-10", "  tag: v1.0  ")
    entries = _parse_log(line)
    assert entries[0].refs == "tag: v1.0"


def test_parse_log_multiple_commits():
    lines = [
        _make_log_line("a" * 40, "aaaaaaa", "A", "Alice", "2024-01-15", "HEAD"),
        _make_log_line("b" * 40, "bbbbbbb", "B", "Bob", "2024-01-14", ""),
        _make_log_line("c" * 40, "ccccccc", "C", "Carol", "2024-01-13", ""),
    ]
    entries = _parse_log("\n".join(lines))
    assert len(entries) == 3
    assert [e.author for e in entries] == ["Alice", "Bob", "Carol"]


def test_parse_log_skips_non_sep_lines():
    """Lines without SEP (e.g. any stray text) are ignored."""
    regular = "just a plain line"
    commit = _make_log_line("a" * 40, "aaaaaaa", "Msg", "Alice", "2024-01-01", "")
    entries = _parse_log("\n".join([regular, commit]))
    assert len(entries) == 1


# ── find_repo_root ────────────────────────────────────────────────────────────


def test_find_repo_root_success(tmp_path):
    with patch("ster.git_log._git", return_value=_completed(str(tmp_path) + "\n")) as mock:
        result = find_repo_root(tmp_path)
    assert result == tmp_path
    mock.assert_called_once_with("rev-parse", "--show-toplevel", cwd=tmp_path)


def test_find_repo_root_not_a_repo(tmp_path):
    with patch("ster.git_log._git", return_value=_completed(returncode=128)):
        assert find_repo_root(tmp_path) is None


# ── _do_revert ────────────────────────────────────────────────────────────────


def test_do_revert_success(tmp_path):
    with patch("ster.git_log._git", return_value=_completed("")) as mock:
        ok, msg = _do_revert("abc1234", tmp_path)
    assert ok is True
    assert "abc1234"[:7] in msg
    mock.assert_called_once_with("revert", "--no-edit", "abc1234", cwd=tmp_path)


def test_do_revert_failure(tmp_path):
    r = _completed(stdout="conflict", returncode=1)
    with patch("ster.git_log._git", return_value=r):
        ok, msg = _do_revert("abc1234", tmp_path)
    assert ok is False


def test_do_revert_failure_uses_stderr(tmp_path):
    r = _completed(returncode=1)
    r.stderr = "error message"
    r.stdout = ""
    with patch("ster.git_log._git", return_value=r):
        ok, msg = _do_revert("abc1234", tmp_path)
    assert ok is False
    assert "error message" in msg


# ── _do_restore ───────────────────────────────────────────────────────────────


def test_do_restore_success(tmp_path):
    fp = tmp_path / "vocab.ttl"
    with patch("ster.git_log._git", return_value=_completed("")) as mock:
        ok, msg = _do_restore("abc1234", fp, tmp_path)
    assert ok is True
    assert "vocab.ttl" in msg
    mock.assert_called_once_with("checkout", "abc1234", "--", "vocab.ttl", cwd=tmp_path)


def test_do_restore_file_outside_repo(tmp_path):
    other = Path("/some/other/path/file.ttl")
    with patch("ster.git_log._git", return_value=_completed("")) as mock:
        ok, msg = _do_restore("abc1234", other, tmp_path)
    assert ok is True
    mock.assert_called_once_with("checkout", "abc1234", "--", str(other), cwd=tmp_path)


def test_do_restore_failure(tmp_path):
    fp = tmp_path / "vocab.ttl"
    r = _completed(stdout="err", returncode=1)
    with patch("ster.git_log._git", return_value=r):
        ok, msg = _do_restore("abc1234", fp, tmp_path)
    assert ok is False


# ── _fetch_diff ───────────────────────────────────────────────────────────────


def test_fetch_diff_no_file(tmp_path):
    hdr = _completed("commit abc\nAuthor: Alice\n\n    Subject\n")
    diff = _completed("diff --git a/f b/f\n+new line\n")
    with patch("ster.git_log._git", side_effect=[hdr, diff]):
        lines = _fetch_diff("abc1234", None, tmp_path)
    assert any("commit abc" in l for l in lines)
    assert any("+new line" in l for l in lines)


def test_fetch_diff_with_file(tmp_path):
    fp = tmp_path / "vocab.ttl"
    hdr = _completed("commit abc\n")
    diff = _completed("+line\n")
    with patch("ster.git_log._git", side_effect=[hdr, diff]) as mock:
        _fetch_diff("abc1234", fp, tmp_path)
    diff_args = mock.call_args_list[1][0]
    assert "--" in diff_args and "vocab.ttl" in diff_args


def test_fetch_diff_file_outside_repo(tmp_path):
    other = Path("/absolute/path/file.ttl")
    hdr = _completed("commit abc\n")
    diff = _completed("+line\n")
    with patch("ster.git_log._git", side_effect=[hdr, diff]) as mock:
        _fetch_diff("abc1234", other, tmp_path)
    assert str(other) in mock.call_args_list[1][0]


def test_fetch_diff_header_failure(tmp_path):
    with patch("ster.git_log._git", side_effect=[_completed(returncode=1), _completed("+line\n")]):
        lines = _fetch_diff("abc1234", None, tmp_path)
    assert any("+line" in l for l in lines)


def test_fetch_diff_diff_failure(tmp_path):
    with patch(
        "ster.git_log._git", side_effect=[_completed("commit abc\n"), _completed(returncode=1)]
    ):
        lines = _fetch_diff("abc1234", None, tmp_path)
    assert any("commit abc" in l for l in lines)


# ── compute_taxonomy_diff ─────────────────────────────────────────────────────


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


def test_compute_diff_pref_label_change():
    before = _make_taxonomy([("C", "Old label", [])])
    after = _make_taxonomy([("C", "New label", [])])
    diff = compute_taxonomy_diff(before, after)
    assert diff[BASE + "C"].status == "changed"
    fd = diff[BASE + "C"].field_diffs
    assert any(f.label == "prefLabel[en]" for f in fd)
    changed = next(f for f in fd if f.label == "prefLabel[en]")
    assert changed.before == "Old label"
    assert changed.after == "New label"


def test_compute_diff_alt_label_added():
    before = _make_taxonomy([("C", "Concept", [])])
    after = _make_taxonomy([("C", "Concept", ["synonym"])])
    diff = compute_taxonomy_diff(before, after)
    assert diff[BASE + "C"].status == "changed"
    fd = diff[BASE + "C"].field_diffs
    assert any(f.label == "altLabel[en]" and f.before == "" and f.after == "synonym" for f in fd)


def test_compute_diff_alt_label_removed():
    before = _make_taxonomy([("C", "Concept", ["old-alt"])])
    after = _make_taxonomy([("C", "Concept", [])])
    diff = compute_taxonomy_diff(before, after)
    assert diff[BASE + "C"].status == "changed"
    fd = diff[BASE + "C"].field_diffs
    assert any(f.label == "altLabel[en]" and f.before == "old-alt" and f.after == "" for f in fd)


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


def test_build_diff_taxonomy_deleted_attached_to_parent():
    before = Taxonomy()
    s = ConceptScheme(uri=BASE + "S", labels=[Label("en", "S")])
    parent = Concept(
        uri=BASE + "P", labels=[Label("en", "P", LabelType.PREF)], narrower=[BASE + "C"]
    )
    child = Concept(uri=BASE + "C", labels=[Label("en", "C", LabelType.PREF)], broader=[BASE + "P"])
    before.schemes[s.uri] = s
    before.concepts[parent.uri] = parent
    before.concepts[child.uri] = child
    s.top_concepts = [BASE + "P"]
    assign_handles(before)

    # After: parent exists but child was deleted
    after = Taxonomy()
    s2 = ConceptScheme(uri=BASE + "S", labels=[Label("en", "S")])
    p2 = Concept(uri=BASE + "P", labels=[Label("en", "P", LabelType.PREF)])
    after.schemes[s2.uri] = s2
    after.concepts[p2.uri] = p2
    s2.top_concepts = [BASE + "P"]
    assign_handles(after)

    merged = build_diff_taxonomy(before, after)
    # Deleted child should be re-attached to parent's narrower
    assert BASE + "C" in merged.concepts
    assert BASE + "C" in merged.concepts[BASE + "P"].narrower


# ── compute_auto_fold ─────────────────────────────────────────────────────────


def test_auto_fold_unchanged_subtree():
    t = _make_taxonomy([("P", "Parent", []), ("C", "Child", [])])
    p = t.concepts[BASE + "P"]
    p.narrower = [BASE + "C"]
    t.concepts[BASE + "C"].broader = [BASE + "P"]
    diff = {
        BASE + "P": ConceptChange(BASE + "P", "unchanged"),
        BASE + "C": ConceptChange(BASE + "C", "unchanged"),
    }
    folded = compute_auto_fold(t, diff)
    assert BASE + "P" in folded


def test_auto_fold_changed_subtree_not_folded():
    t = _make_taxonomy([("P", "Parent", []), ("C", "Child", [])])
    p = t.concepts[BASE + "P"]
    p.narrower = [BASE + "C"]
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
    # Leaf has no children so it's not in folded (nothing to fold)
    assert BASE + "C" not in folded


# ── GitLogViewer (non-curses paths) ──────────────────────────────────────────


def test_viewer_init(tmp_path):
    v = GitLogViewer(repo=tmp_path)
    assert v._repo == tmp_path
    assert v._file_path is None
    assert v._entries == []
    assert v._mode == GitLogViewer._NORMAL


def test_viewer_init_with_file(tmp_path):
    f = tmp_path / "vocab.ttl"
    v = GitLogViewer(repo=tmp_path, file_path=f)
    assert v._file_path == f


def test_viewer_run_non_tty_prints_entries(tmp_path, capsys):
    v = GitLogViewer(repo=tmp_path)
    v._entries = [
        LogEntry("a" * 40, "aaaaaaa", "Fix thing", "Alice", "2024-01-15", ""),
        LogEntry("b" * 40, "bbbbbbb", "Add feature", "Bob", "2024-01-14", ""),
    ]
    v.run()
    out = capsys.readouterr().out
    assert "Fix thing" in out
    assert "Alice" in out
    assert "Add feature" in out


def test_viewer_load_log_parses_output(tmp_path):
    line = _make_log_line(
        "a" * 40, "aaaaaaa", "Initial commit", "Alice", "2024-01-15", "HEAD -> main"
    )
    r = _completed(line)
    with patch("ster.git_log._git", return_value=r), patch.object(GitLogViewer, "_load_diff_tree"):
        v = GitLogViewer(repo=tmp_path)
        v._load_log()
    assert len(v._entries) == 1
    e = v._entries[0]
    assert e.subject == "Initial commit"
    assert e.date == "2024-01-15"
    assert e.author == "Alice"


def test_viewer_load_log_git_error(tmp_path):
    r = _completed(stdout="fatal: not a repo", returncode=128)
    r.stderr = "fatal: not a repo"
    with patch("ster.git_log._git", return_value=r):
        v = GitLogViewer(repo=tmp_path)
        v._load_log()
    assert v._entries == []
    assert "git log" in v._status


def test_viewer_load_log_with_file_path(tmp_path):
    fp = tmp_path / "vocab.ttl"
    line = _make_log_line("b" * 40, "bbbbbbb", "Msg", "Bob", "2024-01-14", "")
    r = _completed(line)
    with (
        patch("ster.git_log._git", return_value=r) as mock,
        patch.object(GitLogViewer, "_load_diff_tree"),
    ):
        v = GitLogViewer(repo=tmp_path, file_path=fp)
        v._load_log()
    args = mock.call_args[0]
    assert "--follow" in args and "--" in args and "vocab.ttl" in args


def test_viewer_load_log_file_outside_repo(tmp_path):
    other = Path("/absolute/vocab.ttl")
    line = _make_log_line("c" * 40, "ccccccc", "Msg", "Carol", "2024-01-13", "")
    r = _completed(line)
    with (
        patch("ster.git_log._git", return_value=r) as mock,
        patch.object(GitLogViewer, "_load_diff_tree"),
    ):
        v = GitLogViewer(repo=tmp_path, file_path=other)
        v._load_log()
    assert str(other) in mock.call_args[0]


def test_viewer_load_diff_tree_no_file(tmp_path):
    """Without a file_path, diff tree stays empty."""
    v = GitLogViewer(repo=tmp_path)
    v._entries = [LogEntry("a" * 40, "aaa", "Msg", "Alice", "2024-01-01", "")]
    v._load_diff_tree(0)
    assert v._diff_taxonomy is None
    assert v._diff_flat == []


def test_viewer_load_diff_tree_caches(tmp_path):
    fp = tmp_path / "vocab.ttl"
    v = GitLogViewer(repo=tmp_path, file_path=fp)
    h = "a" * 40
    v._entries = [LogEntry(h, "aaa", "Msg", "Alice", "2024-01-01", "")]

    from ster.model import Taxonomy as T

    fake_t = T()
    fake_st = {}
    with (
        patch("ster.git_log._get_file_at_commit", return_value=None),
        patch("ster.git_log.compute_taxonomy_diff", return_value=fake_st),
        patch("ster.git_log.build_diff_taxonomy", return_value=fake_t),
        patch("ster.git_log.compute_auto_fold", return_value=set()),
    ):
        v._load_diff_tree(0)
        v._load_diff_tree(0)  # second call should use cache

    assert h in v._diff_cache


def test_viewer_load_diff_tree_out_of_bounds(tmp_path):
    v = GitLogViewer(repo=tmp_path)
    v._load_diff_tree(99)  # no entries — should not raise


# ── launch_git_log ────────────────────────────────────────────────────────────


def test_launch_git_log_no_repo(tmp_path):
    from ster.git_log import launch_git_log

    with patch("ster.git_log.find_repo_root", return_value=None):
        launch_git_log(path=tmp_path, repo=None)


def test_launch_git_log_explicit_repo(tmp_path):
    mock_viewer = MagicMock()
    with (
        patch("ster.git_log.find_repo_root") as mock_find,
        patch("ster.git_log.GitLogViewer", return_value=mock_viewer),
    ):
        from ster.git_log import launch_git_log

        launch_git_log(path=None, repo=tmp_path)
    mock_find.assert_not_called()
    mock_viewer.run.assert_called_once()


def test_launch_git_log_file_path(tmp_path):
    fp = tmp_path / "vocab.ttl"
    fp.write_text("")
    mock_viewer = MagicMock()
    with (
        patch("ster.git_log.find_repo_root", return_value=tmp_path),
        patch("ster.git_log.GitLogViewer", return_value=mock_viewer) as MockV,
    ):
        from ster.git_log import launch_git_log

        launch_git_log(path=fp, repo=None)
    MockV.assert_called_once_with(repo=tmp_path, file_path=fp.resolve())
    mock_viewer.run.assert_called_once()


# ── _git ──────────────────────────────────────────────────────────────────────


def test_git_runs_subprocess(tmp_path):
    from ster.git_log import _git

    r = _git("rev-parse", "--show-toplevel", cwd=tmp_path)
    assert hasattr(r, "returncode")
    assert hasattr(r, "stdout")


# ── _get_file_at_commit ───────────────────────────────────────────────────────


def test_get_file_at_commit_success(tmp_path):
    from ster.git_log import _get_file_at_commit

    content = "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
    with patch("ster.git_log._git", return_value=_completed(content)) as mock:
        result = _get_file_at_commit("abc1234", tmp_path / "vocab.ttl", tmp_path)
    assert result == content
    mock.assert_called_once_with("show", "abc1234:vocab.ttl", cwd=tmp_path)


def test_get_file_at_commit_failure(tmp_path):
    from ster.git_log import _get_file_at_commit

    with patch("ster.git_log._git", return_value=_completed(returncode=128)):
        result = _get_file_at_commit("abc1234", tmp_path / "vocab.ttl", tmp_path)
    assert result is None


def test_get_file_at_commit_outside_repo(tmp_path):
    from ster.git_log import _get_file_at_commit

    other = Path("/absolute/path/vocab.ttl")
    with patch("ster.git_log._git", return_value=_completed("content")) as mock:
        _get_file_at_commit("abc1234", other, tmp_path)
    mock.assert_called_once_with("show", "abc1234:/absolute/path/vocab.ttl", cwd=tmp_path)


# ── _load_taxonomy_safe ───────────────────────────────────────────────────────

MINIMAL_TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://example.org/> .

ex:S a skos:ConceptScheme ;
    skos:prefLabel "Test"@en .

ex:C a skos:Concept ;
    skos:inScheme ex:S ;
    skos:prefLabel "Concept"@en .
"""


def test_load_taxonomy_safe_valid():
    from ster.git_log import _load_taxonomy_safe

    result = _load_taxonomy_safe(MINIMAL_TTL, suffix=".ttl")
    assert result is not None
    assert len(result.concepts) >= 1


def test_load_taxonomy_safe_invalid_returns_none():
    from ster.git_log import _load_taxonomy_safe

    result = _load_taxonomy_safe("not valid turtle !!!", suffix=".ttl")
    assert result is None


# ── _diff_status_str ──────────────────────────────────────────────────────────


def test_diff_status_str(tmp_path):
    v = GitLogViewer(repo=tmp_path)
    v._diff_status = {
        BASE + "A": ConceptChange(BASE + "A", "added"),
        BASE + "B": ConceptChange(BASE + "B", "unchanged"),
    }
    result = v._diff_status_str()
    assert result == {BASE + "A": "added", BASE + "B": "unchanged"}
