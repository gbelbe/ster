"""Optional dependency guard for the rdfdiff-backed history plugin."""

from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys

REQUIREMENT = "rdfdiff>=0.1"


def is_installed() -> bool:
    """True when rdfdiff's stable ``semanticdiff`` import is usable."""
    if importlib.util.find_spec("semanticdiff") is None:
        return False
    try:
        importlib.import_module("semanticdiff")
        return True
    except Exception:  # noqa: BLE001 - any import error makes the plugin unavailable
        return False


def install(requirement: str = REQUIREMENT) -> tuple[bool, str]:
    """Install rdfdiff into ster's interpreter and return its outcome."""
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", requirement],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0, proc.stdout + proc.stderr
