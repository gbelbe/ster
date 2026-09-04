"""``ster.tui`` — the Textual ontology browser & editor (the "New-TUI").

A modern, mouse- and keyboard-driven tree browser/editor for taxonomies, reached
via ``ster show`` or the home-screen menu. It reuses ``ster.store`` + the model
and renders through Textual; pure view-model adapters live in :mod:`ster.tui.data`
(no Textual import) so they stay terminal-free and easily testable.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ster.model import Taxonomy

if TYPE_CHECKING:
    from ster.workspace import TaxonomyWorkspace


def launch(
    taxonomy: Taxonomy,
    source: str = "ontology",
    lang: str = "en",
    path: Path | None = None,
    open_query: bool = False,
    workspace: TaxonomyWorkspace | None = None,
) -> None:
    """Open the Textual ontology browser for *taxonomy* (blocks until quit).

    When *path* is given, edits commit there via ``TaxonomyService``; without it
    the browser is read-only. ``open_query`` opens straight into the SPARQL screen.
    """
    from .app import OntologyApp

    OntologyApp(
        taxonomy,
        source=source,
        lang=lang,
        path=path,
        open_query=open_query,
        workspace=workspace,
    ).run()
