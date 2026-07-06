"""Optional-dependency guard for the semanticlint plugin.

``semanticlint`` is an *optional* dependency (``ster[semanticlint]``): the plugin,
not core ster, owns it. Nothing here imports the library at module load; callers ask
:func:`is_installed` first and only import the runner/checks when it returns True.
:func:`install` shells out to pip on demand (used by the config tab's Install button).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys

# The pip requirement the plugin needs; kept in sync with the registry spec.
REQUIREMENT = "semanticlint>=0.2"


def is_installed() -> bool:
    """True when the ``semanticlint`` library is importable in the current env."""
    return importlib.util.find_spec("semanticlint") is not None


def install(requirement: str = REQUIREMENT) -> tuple[bool, str]:
    """Pip-install *requirement* into the running interpreter. Returns (ok, output)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", requirement],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr)
