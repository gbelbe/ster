"""Tests for CLI helper functions and file resolution."""
from __future__ import annotations
import json
import pytest
from pathlib import Path
from unittest.mock import patch
from ster.cli import _humanize, _resolve_file, _save_session, _load_session, _session_cache_path
import ster.cli as cli_module


@pytest.mark.parametrize("name,expected", [
    ("SpadeRudder", "Spade Rudder"),
    ("trimTabOnRudder", "Trim Tab On Rudder"),
    ("HTTP", "HTTP"),
    ("myConceptName", "My Concept Name"),
    ("https://example.org/ns/SpadeRudder", "Spade Rudder"),
    ("https://example.org/ns#SpadeRudder", "Spade Rudder"),
    ("SimpleName", "Simple Name"),
    ("alreadylower", "Alreadylower"),
])
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
