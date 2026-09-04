"""Persistence port backed by ``ster.store`` — the write side of the TUI's
load/operate/save cycle."""

from __future__ import annotations

from pathlib import Path

from ster.model import Taxonomy


class _StorePersistence:
    """Persistence port backed by ster.store (writes the .ttl on commit)."""

    def save(self, taxonomy: Taxonomy, path: Path) -> None:
        from ster import store

        store.save(taxonomy, path)
