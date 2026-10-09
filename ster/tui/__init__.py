"""``ster.tui`` — the Textual ontology browser & editor (the "New-TUI").

A modern, mouse- and keyboard-driven tree browser/editor for taxonomies, reached
via ``ster show`` or the home-screen menu. It reuses ``ster.store`` + the model
and renders through Textual; pure view-model adapters live in :mod:`ster.tui.data`
(no Textual import) so they stay terminal-free and easily testable.
"""

from __future__ import annotations

from pathlib import Path

from ster.model import Taxonomy
from ster.sparql_endpoint import EndpointSource


def launch(
    taxonomy: Taxonomy,
    source: str = "ontology",
    lang: str = "en",
    path: Path | None = None,
    open_query: bool = False,
) -> None:
    """Open the Textual ontology browser for *taxonomy* (blocks until quit).

    When *path* is given, edits commit there via ``TaxonomyService``; without it
    the browser is read-only. ``open_query`` opens straight into the SPARQL screen.
    """
    from ._run import run_app
    from .app import OntologyApp

    run_app(
        OntologyApp(
            taxonomy,
            source=source,
            lang=lang,
            path=path,
            open_query=open_query,
        )
    )


def launch_file(
    path: str | Path,
    source: str | None = None,
    lang: str = "en",
    open_query: bool = False,
    context: list[Path] | None = None,
) -> Taxonomy | None:
    """Open one Textual app that loads *path* and then becomes the browser.

    *context* names files merged in read-only, so the connected graph is visible
    while only *path* stays editable.
    """
    from ._run import run_app
    from .app import OntologyApp

    path = Path(path)
    app = OntologyApp(
        None,
        source=source or path.name,
        lang=lang,
        path=path,
        open_query=open_query,
        progressive_startup=True,
        context=context,
    )
    run_app(app)
    return app.tax if app._loaded_successfully else None


def launch_endpoint(source: EndpointSource, lang: str = "en") -> None:
    """Open the read-only browser on a SPARQL endpoint's snapshot (blocks until quit).

    The fetch runs inside the app's own loading screen, so its spinner animates
    while the endpoint answers; ``R`` fetches again.
    """
    from ster.sparql_endpoint import loader_for

    from ._run import run_app
    from .app import OntologyApp

    run_app(
        OntologyApp(
            None,
            source=source.url,
            lang=lang,
            progressive_startup=True,
            loader=loader_for(source),
        )
    )
