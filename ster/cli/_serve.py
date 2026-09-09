"""The init-ci and serve commands."""

from __future__ import annotations

from pathlib import Path

import typer

from ..display import console
from . import _app


@_app.app.command("init-ci")
def cmd_init_ci(
    dest: Path = typer.Argument(Path("."), help="Project root directory (default: current dir)."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
    config: bool = typer.Option(
        True, "--config/--no-config", help="Also write onto-ci.yml config template."
    ),
) -> None:
    """Scaffold a GitHub Actions CI workflow for this taxonomy/ontology project."""
    from ..init_ci import scaffold

    dest = dest.resolve()
    workflow_written, config_written = scaffold(dest, force=force, include_config=config)
    workflow_rel = Path(".github") / "workflows" / "taxonomy-ci.yml"

    if not workflow_written:
        console.print(f"[yellow]already exists:[/yellow] {workflow_rel}")
        console.print("[dim]Use --force to overwrite.[/dim]")
    else:
        console.print(f"[green]created:[/green] {workflow_rel}")
    if config_written:
        console.print("[green]created:[/green] onto-ci.yml")


@_app.app.command("serve")
def cmd_serve(
    file: Path = typer.Argument(..., help="Ontology file (.ttl / .rdf / .jsonld)."),
    host: str | None = typer.Option(None, "--host", help="Bind host."),
    port: int | None = typer.Option(None, "--port", "-p", help="Bind port."),
    context_files: list[Path] | None = typer.Option(
        None,
        "--context-files",
        "-x",
        help="Load these files read-only alongside FILE (repeatable). "
        "Their entities are visible but locked, and saving never writes to them.",
    ),
) -> None:
    """Start the live graph viewer and ontology REST API.

    The browser view auto-refreshes when the file is edited via the ster CLI.
    API docs are available at http://<host>:<port>/docs.

    ``--context-files`` is the same flag, spelled the same way and meaning the
    same thing, as ``ster edit``: one file is writable and the rest are there to
    be seen. An ontology split across files — a vocabulary beside the data that
    uses it, third-party reference data beside your own — is one graph, and the
    map and relation views are only correct when they can see all of it.
    """
    try:
        from ..api_server import serve
    except ImportError:  # fastapi/uvicorn are core deps — only a broken install lands here
        _app.err.print(
            "[red]The graph server (fastapi/uvicorn) failed to import — reinstall ster.[/red]"
        )
        raise typer.Exit(1)
    serve(
        file.resolve(),
        host=host,
        port=port,
        context=[c.resolve() for c in (context_files or [])],
    )


def _open_dev_artifacts_in_browser(
    taxonomy: object, file_path: Path, publish_dir: Path, artifacts: list[Path]
) -> None:
    """Open the freshly-published dev TTL + HTML on the running graph server.

    Ensures the server is up so the pages are served at /ontology/dev/...; if the live
    server can't start (its port is busy) it falls back to opening the files via file://.
    """
    from .. import viz_vowl as _viz
    from ..publish import open_dev_artifacts

    base = _viz.ensure_published_server(taxonomy, file_path)  # type: ignore[arg-type]
    urls = open_dev_artifacts(publish_dir, artifacts, base)
    if not urls:
        return
    if base:
        console.print(f"[green]✓[/green]  Opened dev pages: {'  '.join(urls)}")
    else:
        console.print(
            f"[yellow]![/yellow]  No live server (port busy) — "
            f"opened files directly: {'  '.join(urls)}"
        )
