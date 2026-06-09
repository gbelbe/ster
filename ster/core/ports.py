"""Ports — the interfaces the core depends on, injected by each adapter.

The service decides *what* must happen; adapters supply *how*. Keeping these as
Protocols lets the curses TUI, the HTTP API, and tests inject different
implementations (real persistence, fakes, etc.) without the core knowing.

Only :class:`Persistence` is needed for the first slice; ``VersionControl`` and
``EventSink`` join when the ``_save_file`` fan-out is extracted (Phase 4).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..model import Taxonomy
from ..validator import ValidationIssue


class Persistence(Protocol):
    """Durably write a taxonomy to a file (implementations must be atomic)."""

    def save(self, taxonomy: Taxonomy, path: Path) -> None: ...


class Validator(Protocol):
    """Return the consistency issues found in *taxonomy* (read-only)."""

    def check(self, taxonomy: Taxonomy) -> tuple[ValidationIssue, ...]: ...


class Workspace(Protocol):
    """The minimal authority the service reads/swaps taxonomies through."""

    taxonomies: dict[Path, Taxonomy]
