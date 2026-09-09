"""Persistence port implementation shared by every front-end that talks to
:class:`~ster.core.service.TaxonomyService`.

``ster.core.ports.Persistence`` exists precisely so each front-end can inject
its own adapter without the core knowing — but the curses TUI and the HTTP
API (``ster.api``) both just want "write the taxonomy with ``ster.store``",
so that one adapter lives here instead of being redefined per front-end.
``ster.tui.app._persistence`` re-exports this under its historical name so
existing TUI call sites are unaffected.
"""

from __future__ import annotations

from pathlib import Path

from ..model import Taxonomy


class StorePersistence:
    """Persistence port backed by ``ster.store`` (writes the file on commit)."""

    def save(self, taxonomy: Taxonomy, path: Path) -> None:
        from .. import store

        store.save(taxonomy, path)


__all__ = ["StorePersistence"]
