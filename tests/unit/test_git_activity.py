"""Test git.manager.file_activity against a real temp repo."""

from __future__ import annotations

import subprocess

from ster.git.manager import file_activity


def _git(repo, *args):  # noqa: ANN001
    subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True)


def test_file_activity_counts_commits(tmp_path) -> None:
    repo = tmp_path
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.org")
    _git(repo, "config", "user.name", "Tester")
    f = repo / "o.ttl"
    f.write_text("v1", encoding="utf-8")
    _git(repo, "add", "o.ttl")
    _git(repo, "commit", "-m", "one")
    f.write_text("v2", encoding="utf-8")
    _git(repo, "commit", "-am", "two")

    activity = file_activity(f)
    assert activity is not None
    assert activity["total"] == 2
    assert activity["last_month"] == 2  # both just committed
    assert activity["last"].count("-") == 2  # ISO date YYYY-MM-DD


def test_file_activity_none_outside_repo(tmp_path) -> None:
    f = tmp_path / "loose.ttl"
    f.write_text("x", encoding="utf-8")
    assert file_activity(f) is None  # not tracked in any repo
