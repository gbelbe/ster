"""Unit tests for scripts/pre-push.sh sentinel enforcement."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

_HOOK = Path(__file__).parents[2] / "scripts" / "pre-push.sh"


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CI_HOOK_ROOT": str(root)}
    return subprocess.run(["bash", str(_HOOK)], env=env, capture_output=True, text=True)


def test_blocked_when_no_sentinel(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert result.returncode == 1
    assert "CI has not been run" in result.stderr


def test_allowed_when_fresh_sentinel(tmp_path: Path) -> None:
    (tmp_path / ".ci-passed").write_text("2026-05-24T16:00:00Z\n")
    result = _run(tmp_path)
    assert result.returncode == 0


def test_blocked_when_stale_sentinel(tmp_path: Path) -> None:
    sentinel = tmp_path / ".ci-passed"
    sentinel.write_text("2026-05-24T16:00:00Z\n")
    stale_mtime = time.time() - 7200
    os.utime(sentinel, (stale_mtime, stale_mtime))

    result = _run(tmp_path)
    assert result.returncode == 1
    assert "CI result is stale" in result.stderr
