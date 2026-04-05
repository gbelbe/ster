"""Tests for CLI helper functions and file resolution."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import ster.cli as cli_module
from ster.cli import (
    _humanize,
    _load_session,
    _make_taxonomy_commit_msg,
    _resolve_file,
    _save_session,
)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("SpadeRudder", "Spade Rudder"),
        ("trimTabOnRudder", "Trim Tab On Rudder"),
        ("HTTP", "HTTP"),
        ("myConceptName", "My Concept Name"),
        ("https://example.org/ns/SpadeRudder", "Spade Rudder"),
        ("https://example.org/ns#SpadeRudder", "Spade Rudder"),
        ("SimpleName", "Simple Name"),
        ("alreadylower", "Alreadylower"),
    ],
)
def test_humanize(name, expected):
    assert _humanize(name) == expected


# ── session persistence ───────────────────────────────────────────────────────


def test_save_and_load_session(tmp_path, monkeypatch):
    """Session file survives a save/load round-trip."""
    cache = tmp_path / "ster_session"
    monkeypatch.setattr("ster.cli._session_cache_path", lambda: cache)

    taxonomy_file = tmp_path / "vocab.ttl"
    taxonomy_file.write_text("")

    _save_session(taxonomy_file)
    loaded = _load_session()
    assert loaded == taxonomy_file.resolve()


def test_load_session_missing_file_returns_none(tmp_path, monkeypatch):
    """If the saved path no longer exists, _load_session returns None."""
    cache = tmp_path / "ster_session"
    cache.write_text(json.dumps({"file": str(tmp_path / "gone.ttl")}))
    monkeypatch.setattr("ster.cli._session_cache_path", lambda: cache)

    assert _load_session() is None


def test_load_session_missing_cache_returns_none(tmp_path, monkeypatch):
    """No cache file → _load_session returns None."""
    monkeypatch.setattr("ster.cli._session_cache_path", lambda: tmp_path / "nope")
    assert _load_session() is None


# ── _resolve_file ─────────────────────────────────────────────────────────────


def test_resolve_file_explicit_path(tmp_path, monkeypatch):
    """Explicit path is returned immediately and saved as session."""
    monkeypatch.setattr(cli_module, "_session_file", None)
    cache = tmp_path / "cache"
    monkeypatch.setattr("ster.cli._session_cache_path", lambda: cache)

    f = tmp_path / "test.ttl"
    f.write_text("")
    result = _resolve_file(f)
    assert result == f


def test_resolve_file_uses_in_process_cache(tmp_path, monkeypatch):
    """If _session_file is already set, it is returned without I/O."""
    cached = tmp_path / "cached.ttl"
    cached.write_text("")
    monkeypatch.setattr(cli_module, "_session_file", cached)

    # Even if a different file is around, the cache wins
    result = _resolve_file(None)
    assert result == cached


def test_resolve_file_single_auto_detect(tmp_path, monkeypatch):
    """Single taxonomy file → confirm prompt → used for session."""
    monkeypatch.setattr(cli_module, "_session_file", None)
    cache = tmp_path / "cache"
    monkeypatch.setattr("ster.cli._session_cache_path", lambda: cache)
    monkeypatch.chdir(tmp_path)

    f = tmp_path / "vocab.ttl"
    f.write_text("")

    with patch("ster.cli.Confirm.ask", return_value=True):
        result = _resolve_file(None)

    assert result == f
    assert _load_session() == f.resolve()


def test_resolve_file_no_files_exits(tmp_path, monkeypatch):
    """No taxonomy files in CWD → Exit(1)."""
    monkeypatch.setattr(cli_module, "_session_file", None)
    monkeypatch.setattr("ster.cli._session_cache_path", lambda: tmp_path / "cache")
    monkeypatch.chdir(tmp_path)

    import click

    with pytest.raises((SystemExit, click.exceptions.Exit)):
        _resolve_file(None)


# ── _pick_file_interactive ────────────────────────────────────────────────────

from ster.cli import _GIT_LOG_SENTINEL, _pick_file_interactive


def test_pick_file_numeric_selection(tmp_path):
    """Typing a valid number returns the corresponding file."""
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    with patch("ster.cli.Prompt.ask", return_value="1"):
        result = _pick_file_interactive(files)
    assert result == files[0]


def test_pick_file_numeric_create_returns_none(tmp_path):
    """Selecting the 'create new' number returns None."""
    files = [tmp_path / "a.ttl"]
    create_idx = str(len(files) + 1)
    with patch("ster.cli.Prompt.ask", return_value=create_idx):
        result = _pick_file_interactive(files)
    assert result is None


def test_pick_file_log_sentinel(tmp_path):
    """Selecting the log option returns _GIT_LOG_SENTINEL."""
    files = [tmp_path / "a.ttl"]
    log_idx = str(len(files) + 1)  # log is before create when show_log_option=True
    with patch("ster.cli.Prompt.ask", return_value=log_idx):
        result = _pick_file_interactive(files, show_log_option=True)
    assert result == _GIT_LOG_SENTINEL


def test_pick_file_create_with_log_option(tmp_path):
    """With log option, create is index len+2."""
    files = [tmp_path / "a.ttl"]
    create_idx = str(len(files) + 2)
    with patch("ster.cli.Prompt.ask", return_value=create_idx):
        result = _pick_file_interactive(files, show_log_option=True)
    assert result is None


def test_pick_file_filename_match(tmp_path):
    """Typing a filename prefix returns the matching file."""
    files = [tmp_path / "vocab.ttl", tmp_path / "other.ttl"]
    with patch("ster.cli.Prompt.ask", return_value="vocab.ttl"):
        result = _pick_file_interactive(files)
    assert result == files[0]


def test_pick_file_preselect_enter_returns_preselect(tmp_path):
    """Empty input with a preselected file returns the preselect."""
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    with patch("ster.cli.Prompt.ask", return_value=""):
        result = _pick_file_interactive(files, preselect=files[1])
    assert result == files[1]


def test_pick_file_invalid_then_valid(tmp_path):
    """Invalid input is retried; valid number ultimately returns file."""
    files = [tmp_path / "a.ttl"]
    with patch("ster.cli.Prompt.ask", side_effect=["99", "1"]):
        result = _pick_file_interactive(files)
    assert result == files[0]


def test_pick_file_ambiguous_prefix_retries(tmp_path):
    """Ambiguous prefix shows warning and retries."""
    files = [tmp_path / "vocab1.ttl", tmp_path / "vocab2.ttl"]
    with patch("ster.cli.Prompt.ask", side_effect=["vocab", "1"]):
        result = _pick_file_interactive(files)
    assert result == files[0]


def test_pick_file_keyboard_interrupt_exits(tmp_path):
    """KeyboardInterrupt raises typer.Exit(0)."""
    import typer

    files = [tmp_path / "a.ttl"]
    with (
        patch("ster.cli.Prompt.ask", side_effect=KeyboardInterrupt),
        pytest.raises((SystemExit, typer.Exit)),
    ):
        _pick_file_interactive(files)


def test_pick_file_not_found_prefix_retries(tmp_path):
    """Unknown prefix shows error and retries until valid input."""
    files = [tmp_path / "vocab.ttl"]
    with patch("ster.cli.Prompt.ask", side_effect=["zzz", "1"]):
        result = _pick_file_interactive(files)
    assert result == files[0]


# ── _arrow_file_picker ────────────────────────────────────────────────────────

from ster.cli import _arrow_file_picker


def _run_picker(files, item_values, initial_sel, input_bytes, preselect=None):
    """Helper: run _arrow_file_picker with mocked stdin/stdout."""
    import io

    # Build a fake stdin with a .buffer that serves raw bytes
    fake_buf = io.BytesIO(input_bytes)
    fake_stdin = MagicMock()
    fake_stdin.isatty.return_value = True
    fake_stdin.fileno.return_value = 0
    fake_stdin.buffer = fake_buf

    fake_stdout = io.StringIO()

    with (
        patch("sys.stdin", fake_stdin),
        patch("sys.stdout.isatty", return_value=True),
        patch("sys.stdout.write", side_effect=lambda s: fake_stdout.write(s)),
        patch("sys.stdout.flush", return_value=None),
        patch("tty.setraw", return_value=None),
        patch("termios.tcgetattr", return_value=[]),
        patch("termios.tcsetattr", return_value=None),
    ):
        return _arrow_file_picker(
            files,
            item_values,
            initial_sel,
            preselect,
            False,
            None,
            len(files) + 1,
        )


def test_arrow_picker_enter_selects_initial(tmp_path):
    """Pressing Enter immediately returns the initial selection."""
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    item_values = files + [None]
    result = _run_picker(files, item_values, 0, b"\r")
    assert result == files[0]


def test_arrow_picker_down_then_enter(tmp_path):
    """Arrow-down moves selection then Enter confirms."""
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    item_values = files + [None]
    down = b"\x1b[B"
    result = _run_picker(files, item_values, 0, down + b"\r")
    assert result == files[1]


def test_arrow_picker_down_wraps(tmp_path):
    """Arrow-down wraps from last item to first."""
    files = [tmp_path / "a.ttl"]
    item_values = files + [None]
    down = b"\x1b[B"  # goes to create new
    down2 = b"\x1b[B"  # wraps back to first
    result = _run_picker(files, item_values, 0, down + down2 + b"\r")
    assert result == files[0]


def test_arrow_picker_up_wraps(tmp_path):
    """Arrow-up from first item wraps to last."""
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    item_values = files + [None]
    up = b"\x1b[A"
    result = _run_picker(files, item_values, 0, up + b"\r")
    assert result is None  # wrapped to "create new" (last item)


def test_arrow_picker_type_number(tmp_path):
    """Typing a digit auto-selects that item."""
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    item_values = files + [None]
    result = _run_picker(files, item_values, 0, b"2\r")
    assert result == files[1]


def test_arrow_picker_type_number_create(tmp_path):
    """Typing the create-new number returns None."""
    files = [tmp_path / "a.ttl"]
    item_values = files + [None]
    result = _run_picker(files, item_values, 0, b"2\r")
    assert result is None


def test_arrow_picker_backspace_clears_typed(tmp_path):
    """Backspace removes the last typed character."""
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    item_values = files + [None]
    # type "2", backspace, type "1", Enter → should select item 1
    result = _run_picker(files, item_values, 0, b"2\x7f1\r")
    assert result == files[0]


def test_arrow_picker_ctrl_c_raises(tmp_path):
    """Ctrl+C raises KeyboardInterrupt."""
    import pytest

    files = [tmp_path / "a.ttl"]
    item_values = files + [None]
    with pytest.raises(KeyboardInterrupt):
        _run_picker(files, item_values, 0, b"\x03")


def test_arrow_picker_preselect_is_initial(tmp_path):
    """Initial selection matches the preselected file."""
    files = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    item_values = files + [None]
    # Enter immediately with initial_sel=1 → returns files[1]
    result = _run_picker(files, item_values, 1, b"\r", preselect=files[1])
    assert result == files[1]


# ── _GIT_LOG_SENTINEL ─────────────────────────────────────────────────────────


def test_git_log_sentinel_is_path():
    assert isinstance(_GIT_LOG_SENTINEL, Path)


def test_git_log_sentinel_unique():
    """Sentinel should not match any real taxonomy file name."""
    assert _GIT_LOG_SENTINEL.suffix not in {".ttl", ".rdf", ".jsonld", ".owl", ".n3"}


# ── _multi_file_picker input-flush regression ─────────────────────────────────


def test_multi_file_picker_flushes_stdin_before_reading(tmp_path, monkeypatch):
    """Stray bytes buffered from a previous curses session are discarded before
    the picker starts reading.

    Regression: pressing Escape twice quickly in the tree view left a \\x1b byte
    in the OS input buffer.  _multi_file_picker read it, blocked on the next
    byte, consumed the user's Enter as the continuation, and then exited as
    _QUIT_SENTINEL — terminating the program instead of opening the tree view.
    """
    import sys
    import io

    termios = pytest.importorskip("termios")
    pytest.importorskip("tty")  # skip on Windows
    from ster.cli import _multi_file_picker

    found = [tmp_path / "a.ttl", tmp_path / "b.ttl"]
    flush_calls: list[int] = []

    class _FakeBuffer:
        def read(self, n: int) -> bytes:
            return b"\r"  # simulate Enter → picker exits immediately

    class _FakeSysStdin:
        def isatty(self) -> bool:
            return True

        def fileno(self) -> int:
            return 0

        buffer = _FakeBuffer()

    class _FakeSysStdout:
        def isatty(self) -> bool:
            return True

        def write(self, s: str) -> None:
            pass

        def flush(self) -> None:
            pass

    monkeypatch.setattr(termios, "tcgetattr", lambda fd: [])
    monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, attrs: None)
    monkeypatch.setattr(termios, "tcflush", lambda fd, queue: flush_calls.append(queue))
    monkeypatch.setattr("tty.setraw", lambda fd: None)
    monkeypatch.setattr(sys, "stdin", _FakeSysStdin())
    monkeypatch.setattr(sys, "stdout", _FakeSysStdout())

    _multi_file_picker(found)

    assert termios.TCIFLUSH in flush_calls


# ── _collect_reachable ────────────────────────────────────────────────────────


def test_collect_reachable(simple_taxonomy):
    """_collect_reachable visits all descendants without revisiting."""
    from ster.cli import _collect_reachable

    visited: set[str] = set()
    _collect_reachable(simple_taxonomy, BASE + "Top", visited)
    assert BASE + "Top" in visited
    assert BASE + "Child" in visited


# ── _make_taxonomy_commit_msg ─────────────────────────────────────────────────

BASE = "https://example.org/test/"


@pytest.fixture
def simple_taxonomy_for_cli():
    from ster.handles import assign_handles
    from ster.model import ConceptScheme, Label, Taxonomy

    t = Taxonomy()
    s = ConceptScheme(
        uri=BASE + "Scheme",
        labels=[Label(lang="en", value="My Taxonomy")],
        base_uri=BASE,
        creator="Alice",
        created="2026-01-01",
        languages=["en", "fr"],
    )
    t.schemes[s.uri] = s
    assign_handles(t)
    return t


def test_make_taxonomy_commit_msg_first_line(simple_taxonomy_for_cli, tmp_path):
    f = tmp_path / "vocab.ttl"
    msg = _make_taxonomy_commit_msg(simple_taxonomy_for_cli, f)
    assert msg.startswith('feat: create taxonomy "My Taxonomy"')


def test_make_taxonomy_commit_msg_contains_file(simple_taxonomy_for_cli, tmp_path):
    f = tmp_path / "vocab.ttl"
    msg = _make_taxonomy_commit_msg(simple_taxonomy_for_cli, f)
    assert "vocab.ttl" in msg


def test_make_taxonomy_commit_msg_contains_base_uri(simple_taxonomy_for_cli, tmp_path):
    f = tmp_path / "vocab.ttl"
    msg = _make_taxonomy_commit_msg(simple_taxonomy_for_cli, f)
    assert BASE in msg


def test_make_taxonomy_commit_msg_contains_languages(simple_taxonomy_for_cli, tmp_path):
    f = tmp_path / "vocab.ttl"
    msg = _make_taxonomy_commit_msg(simple_taxonomy_for_cli, f)
    assert "en" in msg and "fr" in msg


def test_make_taxonomy_commit_msg_contains_creator(simple_taxonomy_for_cli, tmp_path):
    f = tmp_path / "vocab.ttl"
    msg = _make_taxonomy_commit_msg(simple_taxonomy_for_cli, f)
    assert "Alice" in msg


def test_make_taxonomy_commit_msg_no_scheme(tmp_path):
    """Falls back to file stem when taxonomy has no scheme."""
    from ster.model import Taxonomy

    t = Taxonomy()
    f = tmp_path / "fallback.ttl"
    msg = _make_taxonomy_commit_msg(t, f)
    assert 'feat: create taxonomy "fallback"' in msg


BASE = "https://example.org/test/"


@pytest.fixture
def simple_taxonomy():
    """Minimal in-memory taxonomy for CLI tests."""
    from ster.handles import assign_handles
    from ster.model import Concept, ConceptScheme, Label, Taxonomy

    t = Taxonomy()
    scheme = ConceptScheme(
        uri=BASE + "Scheme",
        labels=[Label(lang="en", value="Test")],
        top_concepts=[BASE + "Top"],
        base_uri=BASE,
    )
    top = Concept(
        uri=BASE + "Top", labels=[Label(lang="en", value="Top")], narrower=[BASE + "Child"]
    )
    child = Concept(
        uri=BASE + "Child", labels=[Label(lang="en", value="Child")], broader=[BASE + "Top"]
    )
    t.schemes[scheme.uri] = scheme
    t.concepts[top.uri] = top
    t.concepts[child.uri] = child
    assign_handles(t)
    return t
