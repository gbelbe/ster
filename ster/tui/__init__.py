"""``ster.tui`` — the Textual ontology browser & editor (the "New-TUI").

A modern, mouse- and keyboard-driven tree browser/editor for taxonomies, reached
via ``ster new-tui`` or the home-screen menu. It reuses ``ster.store`` + the model
and renders through Textual; pure view-model adapters live in :mod:`ster.tui.data`
(no Textual import) so they stay terminal-free and easily testable.
"""

from __future__ import annotations

from pathlib import Path

from ster.model import Taxonomy


def launch(
    taxonomy: Taxonomy,
    source: str = "ontology",
    lang: str = "en",
    path: Path | None = None,
) -> None:
    """Open the Textual ontology browser for *taxonomy* (blocks until quit).

    When *path* is given, edits commit there via ``TaxonomyService``; without it
    the browser is read-only.
    """
    from .app import OntologyApp

    OntologyApp(taxonomy, source=source, lang=lang, path=path).run()
