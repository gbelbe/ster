"""Optional dependency guard for the rdfdiff-backed history plugin."""

from __future__ import annotations

import importlib
import importlib.util

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
    """Install *requirement* into the running interpreter (pip, or uv where there is no pip); (ok, output)."""
    from ..dependency import install as _install  # noqa: PLC0415

    return _install(requirement)
