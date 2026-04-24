"""Tests for CLI helper functions and file resolution."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import click.exceptions
import pytest
from typer.testing import CliRunner

import ster.cli as cli_module
from ster.cli import (
    _humanize,
    _load_session,
    _make_taxonomy_commit_msg,
    _newer,
    _parse_changelog_section,
    _resolve_file,
    _save_session,
    app,
)

_runner = CliRunner()


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


# ── _newer ────────────────────────────────────────────────────────────────────


def test_newer_greater():
    assert _newer("0.3.2", "0.3.1") is True


def test_newer_equal():
    assert _newer("0.3.1", "0.3.1") is False


def test_newer_less():
    assert _newer("0.3.0", "0.3.1") is False


def test_newer_major():
    assert _newer("1.0.0", "0.9.9") is True


def test_newer_minor():
    assert _newer("0.4.0", "0.3.9") is True


def test_newer_invalid_string():
    # Falls back to (0,) — neither is newer
    assert _newer("bad", "0.1.0") is False


# ── _parse_changelog_section ──────────────────────────────────────────────────

_SAMPLE_CHANGELOG = """\
## Changelog

### 0.3.2
- Fix the Escape key in graph viz
- Root OWL classes are now visually distinct
- Removed Generate Browsable Website option

### 0.3.1
- Animate AI suggestion spinners
- Handle missing Ollama gracefully
"""


def test_parse_changelog_found():
    result = _parse_changelog_section(_SAMPLE_CHANGELOG, "0.3.2")
    assert "Escape" in result
    assert "Root OWL" in result
    assert "Removed" in result


def test_parse_changelog_stops_at_next_header():
    result = _parse_changelog_section(_SAMPLE_CHANGELOG, "0.3.2")
    assert "Animate" not in result


def test_parse_changelog_max_bullets():
    long_desc = "### 1.0.0\n" + "\n".join(f"- Item {i}" for i in range(10))
    result = _parse_changelog_section(long_desc, "1.0.0", max_bullets=3)
    assert "Item 0" in result
    assert "Item 1" in result
    assert "Item 2" in result
    assert "more" in result  # truncation indicator


def test_parse_changelog_not_found():
    result = _parse_changelog_section(_SAMPLE_CHANGELOG, "9.9.9")
    assert result == ""


def test_parse_changelog_strips_markdown():
    desc = "### 0.1.0\n- **Bold** and `code` text\n"
    result = _parse_changelog_section(desc, "0.1.0")
    assert "**" not in result
    assert "`" not in result
    assert "Bold" in result
    assert "code" in result


def test_parse_changelog_exact_max_no_ellipsis():
    desc = "### 1.0.0\n- A\n- B\n- C\n"
    result = _parse_changelog_section(desc, "1.0.0", max_bullets=3)
    assert "more" not in result


# ── _check_new_version ────────────────────────────────────────────────────────


def test_check_new_version_uses_cache(tmp_path, monkeypatch):
    cache = tmp_path / "version_cache.json"
    from datetime import datetime

    data = {
        "checked": datetime.now().isoformat(),
        "latest": "99.0.0",
        "notes": "· big update",
    }
    cache.write_text(json.dumps(data))
    monkeypatch.setattr(cli_module, "_VERSION_CACHE", cache)
    monkeypatch.setattr(cli_module, "_VERSION", "0.1.0")

    result = cli_module._check_new_version()
    assert result is not None
    assert result[0] == "99.0.0"
    assert "big update" in result[1]


def test_check_new_version_no_update_when_same(tmp_path, monkeypatch):
    cache = tmp_path / "version_cache.json"
    from datetime import datetime

    data = {"checked": datetime.now().isoformat(), "latest": "0.3.1", "notes": ""}
    cache.write_text(json.dumps(data))
    monkeypatch.setattr(cli_module, "_VERSION_CACHE", cache)
    monkeypatch.setattr(cli_module, "_VERSION", "0.3.1")

    result = cli_module._check_new_version()
    assert result is None


def test_check_new_version_stale_cache(tmp_path, monkeypatch):
    cache = tmp_path / "version_cache.json"
    from datetime import datetime, timedelta

    old = datetime.now() - timedelta(hours=24)
    data = {"checked": old.isoformat(), "latest": "99.0.0", "notes": ""}
    cache.write_text(json.dumps(data))
    monkeypatch.setattr(cli_module, "_VERSION_CACHE", cache)
    monkeypatch.setattr(cli_module, "_VERSION", "0.1.0")

    # Stale cache → background fetch launched, but no cached result returned
    with patch("threading.Thread") as mock_thread:
        mock_thread.return_value = MagicMock()
        result = cli_module._check_new_version()
    # Stale → no cached result served (fresh fetch pending)
    assert result is None


# ── _load / _save / _resolve / _run error paths ───────────────────────────────


def test_load_bad_file_exits(tmp_path):
    bad = tmp_path / "bad.ttl"
    bad.write_text("NOT TURTLE @@@@")
    with pytest.raises((SystemExit, click.exceptions.Exit)):
        cli_module._load(bad)


def test_save_unwritable_exits(tmp_path, monkeypatch):
    import ster.store as _store

    monkeypatch.setattr(_store, "save", lambda t, p: (_ for _ in ()).throw(OSError("disk full")))
    from ster.model import Taxonomy

    with pytest.raises((SystemExit, click.exceptions.Exit)):
        cli_module._save(Taxonomy(), tmp_path / "out.ttl")


def test_resolve_missing_handle_exits(simple_taxonomy):
    with pytest.raises((SystemExit, click.exceptions.Exit)):
        cli_module._resolve(simple_taxonomy, "NONEXISTENT")


def test_run_converts_skostax_error_to_exit(simple_taxonomy):
    from ster.exceptions import ConceptNotFoundError

    with pytest.raises((SystemExit, click.exceptions.Exit)):
        cli_module._run(lambda: (_ for _ in ()).throw(ConceptNotFoundError("https://x.org/Ghost")))


# ── CLI commands via CliRunner ─────────────────────────────────────────────────
# All commands accept --file so we never rely on session / CWD detection.


def test_cmd_handles(tmp_ttl):
    result = _runner.invoke(app, ["handles", "--file", str(tmp_ttl)])
    assert result.exit_code == 0
    assert "TOP" in result.output.upper() or "Top" in result.output


def test_cmd_validate_clean(tmp_ttl):
    result = _runner.invoke(app, ["validate", "--file", str(tmp_ttl)])
    assert result.exit_code == 0
    assert "No issues" in result.output


def test_cmd_validate_finds_orphan(tmp_path):
    ttl = tmp_path / "orphan.ttl"
    # t:Orphan has skos:broader pointing to a non-existent concept, so it is not
    # auto-promoted to top_concepts but is also unreachable from t:Top.
    ttl.write_text(
        """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix t: <https://example.org/t/> .

t:Scheme a skos:ConceptScheme ; skos:hasTopConcept t:Top .
t:Top a skos:Concept ; skos:inScheme t:Scheme ; skos:topConceptOf t:Scheme ;
      skos:prefLabel "Top"@en .
t:Orphan a skos:Concept ; skos:inScheme t:Scheme ; skos:prefLabel "Orphan"@en ;
         skos:broader t:Ghost .
"""
    )
    result = _runner.invoke(app, ["validate", "--file", str(ttl)])
    assert result.exit_code == 1
    assert "orphan" in result.output.lower() or "issue" in result.output.lower()


def test_cmd_validate_finds_missing_label(tmp_path):
    ttl = tmp_path / "nolabel.ttl"
    ttl.write_text(
        """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix t: <https://example.org/t/> .

t:Scheme a skos:ConceptScheme ; skos:hasTopConcept t:Top .
t:Top a skos:Concept ; skos:inScheme t:Scheme ; skos:topConceptOf t:Scheme .
"""
    )
    result = _runner.invoke(app, ["validate", "--file", str(ttl)])
    assert result.exit_code == 1
    assert "prefLabel" in result.output or "label" in result.output.lower()


def test_cmd_add_creates_concept(tmp_ttl):
    result = _runner.invoke(
        app,
        ["add", "NewWidget", "--en", "New Widget", "--file", str(tmp_ttl)],
    )
    assert result.exit_code == 0, result.output
    assert "Added" in result.output
    assert "New Widget" in result.output


def test_cmd_add_default_label_from_name(tmp_ttl):
    result = _runner.invoke(app, ["add", "MyNewThing", "--file", str(tmp_ttl)])
    assert result.exit_code == 0, result.output
    assert "My New Thing" in result.output


def test_cmd_add_with_parent(tmp_ttl):
    result = _runner.invoke(
        app,
        ["add", "SubWidget", "--en", "Sub Widget", "--parent", "TOP", "--file", str(tmp_ttl)],
    )
    assert result.exit_code == 0, result.output
    assert "Added" in result.output


def test_cmd_add_with_definition(tmp_ttl):
    result = _runner.invoke(
        app,
        [
            "add",
            "DefConcept",
            "--en",
            "Def Concept",
            "--def-en",
            "A definition.",
            "--file",
            str(tmp_ttl),
        ],
    )
    assert result.exit_code == 0, result.output


def test_cmd_remove_with_yes(tmp_ttl):
    result = _runner.invoke(
        app,
        ["remove", "GRA", "--yes", "--file", str(tmp_ttl)],
    )
    assert result.exit_code == 0, result.output
    assert "Removed" in result.output


def test_cmd_remove_cascade(tmp_ttl):
    result = _runner.invoke(
        app,
        ["remove", "CHI", "--cascade", "--yes", "--file", str(tmp_ttl)],
    )
    assert result.exit_code == 0, result.output


def test_cmd_remove_missing_concept(tmp_ttl):
    result = _runner.invoke(app, ["remove", "DOESNOTEXIST", "--yes", "--file", str(tmp_ttl)])
    assert result.exit_code != 0


def test_cmd_label_set_pref(tmp_ttl):
    result = _runner.invoke(
        app,
        ["label", "TOP", "de", "Wurzel", "--file", str(tmp_ttl)],
    )
    assert result.exit_code == 0, result.output
    assert "pref label" in result.output.lower()
    assert "Wurzel" in result.output


def test_cmd_label_set_alt(tmp_ttl):
    result = _runner.invoke(
        app,
        ["label", "TOP", "en", "Root Node", "--alt", "--file", str(tmp_ttl)],
    )
    assert result.exit_code == 0, result.output
    assert "alt label" in result.output.lower()


def test_cmd_define_sets_definition(tmp_ttl):
    result = _runner.invoke(
        app,
        ["define", "CHI2", "en", "The second child concept.", "--file", str(tmp_ttl)],
    )
    assert result.exit_code == 0, result.output
    assert "definition" in result.output.lower()


def test_cmd_relate_add(tmp_ttl):
    result = _runner.invoke(
        app,
        ["relate", "CHI2", "GRA", "--file", str(tmp_ttl)],
    )
    assert result.exit_code == 0, result.output
    assert "Added" in result.output


def test_cmd_relate_remove(tmp_ttl):
    # First add a related link, then remove it
    _runner.invoke(app, ["relate", "CHI2", "GRA", "--file", str(tmp_ttl)])
    result = _runner.invoke(
        app,
        ["relate", "CHI2", "GRA", "--remove", "--file", str(tmp_ttl)],
    )
    assert result.exit_code == 0, result.output
    assert "Removed" in result.output


def test_cmd_rename_changes_uri(tmp_ttl):
    result = _runner.invoke(
        app,
        ["rename", "GRA", "GreatGrandchild", "--file", str(tmp_ttl)],
    )
    assert result.exit_code == 0, result.output
    assert "Renamed" in result.output


def test_cmd_move_to_new_parent(tmp_ttl):
    result = _runner.invoke(
        app,
        ["move", "GRA", "--parent", "CHI2", "--file", str(tmp_ttl)],
    )
    assert result.exit_code == 0, result.output
    assert "Moved" in result.output


def test_cmd_move_to_top_level(tmp_ttl):
    result = _runner.invoke(
        app,
        ["move", "GRA", "--file", str(tmp_ttl)],
    )
    assert result.exit_code == 0, result.output
    assert "Moved" in result.output
    assert "top level" in result.output


# ── cmd_show --plain (non-interactive) ────────────────────────────────────────


def test_cmd_show_plain(tmp_ttl):
    result = _runner.invoke(app, ["show", "--plain", str(tmp_ttl)])
    assert result.exit_code == 0, result.output
    assert "Top" in result.output


def test_cmd_show_plain_with_concept(tmp_ttl):
    result = _runner.invoke(app, ["show", "--plain", "--concept", "TOP", str(tmp_ttl)])
    assert result.exit_code == 0, result.output


def test_cmd_show_handles(tmp_ttl):
    result = _runner.invoke(app, ["show", "--handles", str(tmp_ttl)])
    assert result.exit_code == 0, result.output


# ── _resolve_broken_mappings_at_load ─────────────────────────────────────────


def test_resolve_broken_mappings_no_issues(tmp_ttl):
    from ster.workspace import TaxonomyWorkspace

    workspace = TaxonomyWorkspace.from_files([tmp_ttl])
    # Should silently return when no broken mappings
    cli_module._resolve_broken_mappings_at_load(workspace, [tmp_ttl])


def test_resolve_broken_mappings_no_unloaded_files(tmp_path):
    from ster.workspace import TaxonomyWorkspace

    ttl = tmp_path / "mapped.ttl"
    ttl.write_text(
        """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix t: <https://example.org/t/> .
@prefix other: <https://other.org/> .

t:Scheme a skos:ConceptScheme ; skos:hasTopConcept t:A .
t:A a skos:Concept ; skos:inScheme t:Scheme ; skos:topConceptOf t:Scheme ;
    skos:prefLabel "A"@en ; skos:exactMatch other:B .
"""
    )
    workspace = TaxonomyWorkspace.from_files([ttl])
    # found_files == workspace files → no unloaded files → prints warning, no prompt
    cli_module._resolve_broken_mappings_at_load(workspace, [ttl])


# ── _load_workspace ───────────────────────────────────────────────────────────


def test_load_workspace_returns_workspace(tmp_ttl):
    from ster.workspace import TaxonomyWorkspace

    ws = cli_module._load_workspace([tmp_ttl], [tmp_ttl])
    assert isinstance(ws, TaxonomyWorkspace)
    assert tmp_ttl in ws.taxonomies
