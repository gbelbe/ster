"""The init-ci and serve commands."""

from __future__ import annotations

from pathlib import Path

import typer

from ..display import console
from ..project import Project
from . import _app
from ._exit import ExitCode


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


def _warn_about_other_servers() -> None:
    """Name any other ``ster serve`` already running, and which build it is.

    Reports, deliberately; it does not stop them. Two installs commonly coexist
    — a ``uv tool`` copy and a project venv, the latter often editable and
    tracking whichever branch is checked out — and a server started from one
    keeps serving its own build until stopped. Updating the other install then
    looks like it did nothing, which is doubly confusing because the version
    string *did* change.

    Killing them on launch was the obvious fix and the wrong one: running
    several servers over different ontologies on different ports is a normal
    thing to do, and a new window silently closing the one you were reading is
    worse than the confusion it prevents. Naming them costs a line and leaves
    the choice where it belongs.
    """
    from ..viz_vowl import other_ster_servers  # noqa: PLC0415

    others = other_ster_servers()
    if not others:
        return
    console.print(
        f"[yellow]![/yellow]  {len(others)} other ster server(s) already running. "
        "They keep serving the build they were started from:"
    )
    for pid, command in others:
        console.print(f"     [dim]PID {pid}[/dim]  {command[:96]}")
    console.print("     [dim]Stop them with:[/dim] pkill -f 'ster serve'")


def _require_explicit_context(file: Path, context_files: list[Path] | None) -> None:
    """Reject ambiguous project loads unless serve names the context explicitly."""
    if context_files:
        return
    project = Project.load(file.parent)
    if project is None:
        return
    remembered = project.remembered_context(file)
    candidates = [*project.resolved_files(), *remembered]
    unique = list(dict.fromkeys(path.resolve() for path in candidates))
    if len(unique) <= 1:
        return
    names = ", ".join(str(path) for path in unique)
    raise typer.BadParameter(
        "This project contains multiple ontology files, but no context files were "
        "provided. Choose one writable FILE and pass the others explicitly with "
        f"--context-files/-x. Candidates: {names}"
    )


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
        raise typer.Exit(ExitCode.UNEXPECTED)
    _warn_about_other_servers()
    _require_explicit_context(file.resolve(), context_files)
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
