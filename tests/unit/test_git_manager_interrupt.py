"""Unit tests: GitManager public methods handle KeyboardInterrupt gracefully."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ster.git.manager import GitManager


@pytest.fixture()
def mgr(tmp_path: Path) -> GitManager:
    taxonomy = tmp_path / "test.ttl"
    taxonomy.touch()
    m = GitManager(taxonomy)
    m._cfg = {
        "repo_path": str(tmp_path),
        "remote_url": "https://example.com/repo.git",
        "main_branch": "main",
    }
    return m


def test_check_and_pull_returns_none_on_keyboard_interrupt(mgr: GitManager) -> None:
    with patch("ster.git.manager._git", side_effect=KeyboardInterrupt):
        result = mgr.check_and_pull()
    assert result is None


def test_pre_edit_check_returns_none_on_keyboard_interrupt(mgr: GitManager) -> None:
    with patch("ster.git.manager._git", side_effect=KeyboardInterrupt):
        result = mgr.pre_edit_check()
    assert result is None


def test_fetch_remote_returns_none_on_keyboard_interrupt(mgr: GitManager) -> None:
    with patch("ster.git.manager._git", side_effect=KeyboardInterrupt):
        mgr.fetch_remote()  # returns None implicitly — must not raise
