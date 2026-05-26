"""Unit tests for scripts/release.sh guard-rail checks."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

_SCRIPT = Path(__file__).parents[2] / "scripts" / "release.sh"


def _run(root: Path, version: str = "0.4.99") -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "RELEASE_ROOT": str(root)}
    return subprocess.run(
        ["bash", str(_SCRIPT), version],
        env=env,
        capture_output=True,
        text=True,
    )


def _fresh_sentinel(root: Path) -> None:
    (root / ".ci-passed").write_text("2026-05-26T10:00:00Z\n")


def _release_notes(root: Path, content: str = "- Feature A\n") -> None:
    (root / "RELEASE_NOTES.md").write_text(content)


# ── guard: CI sentinel ────────────────────────────────────────────────────────


def test_blocked_when_no_ci_sentinel(tmp_path: Path) -> None:
    _release_notes(tmp_path)
    result = _run(tmp_path)
    assert result.returncode != 0
    assert "CI" in result.stderr


def test_blocked_when_stale_ci_sentinel(tmp_path: Path) -> None:
    sentinel = tmp_path / ".ci-passed"
    sentinel.write_text("old\n")
    os.utime(sentinel, (time.time() - 7200,) * 2)
    _release_notes(tmp_path)
    result = _run(tmp_path)
    assert result.returncode != 0
    assert "CI" in result.stderr or "stale" in result.stderr.lower()


# ── guard: RELEASE_NOTES.md ───────────────────────────────────────────────────


def test_blocked_when_no_release_notes(tmp_path: Path) -> None:
    _fresh_sentinel(tmp_path)
    result = _run(tmp_path)
    assert result.returncode != 0
    assert "RELEASE_NOTES" in result.stderr


def test_blocked_when_release_notes_empty(tmp_path: Path) -> None:
    _fresh_sentinel(tmp_path)
    (tmp_path / "RELEASE_NOTES.md").write_text("   \n")
    result = _run(tmp_path)
    assert result.returncode != 0
    assert "RELEASE_NOTES" in result.stderr


# ── guard: version argument ───────────────────────────────────────────────────


def test_blocked_when_no_version_argument(tmp_path: Path) -> None:
    env = {**os.environ, "RELEASE_ROOT": str(tmp_path)}
    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_blocked_when_invalid_version(tmp_path: Path) -> None:
    _fresh_sentinel(tmp_path)
    _release_notes(tmp_path)
    env = {**os.environ, "RELEASE_ROOT": str(tmp_path)}
    result = subprocess.run(
        ["bash", str(_SCRIPT), "not-a-version"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
