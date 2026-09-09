"""Persistence port backed by ``ster.store`` — the write side of the TUI's
load/operate/save cycle.

The actual implementation now lives in :mod:`ster.core.adapters` (shared with
the HTTP API's mutation endpoints, see docs/architecture/graph-editor.md,
Phase 3) — this module re-exports it under its historical name so every
existing TUI call site (``_StorePersistence()``) is unaffected.
"""

from __future__ import annotations

from ster.core.adapters import StorePersistence as _StorePersistence

__all__ = ["_StorePersistence"]
