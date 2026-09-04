"""Low-level ``git`` subprocess wrapper shared by every manager mixin.

Kept as a separate module (rather than folded into a mixin) so tests can patch
the actual call site: every mixin reaches these through ``_subprocess._git(...)``
/ ``_subprocess._git_available()`` — a qualified attribute access resolved at
call time — rather than a bare name copied in at import time, so
``patch("ster.git.manager._subprocess._git", ...)`` reliably intercepts calls
made from any mixin, not just this module.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _git_available() -> bool:
    try:
        r = subprocess.run(["git", "--version"], capture_output=True)
        return r.returncode == 0
    except FileNotFoundError:
        return False
