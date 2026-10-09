"""``ster show --endpoint`` and the home-menu entry: open a SPARQL endpoint, read-only."""

from __future__ import annotations

from pathlib import Path

import typer

from .. import ask
from ..display import console
from ..sparql_endpoint import (
    DEFAULT_TIMEOUT,
    EndpointError,
    EndpointSource,
    NotRdfError,
    load,
    save_limit,
    saved_limit,
)
from . import _app
from ._exit import ExitCode

_LIT_RED_CLOSE = "[/red]"
_SOURCES = ("default", "graph", "query")


def parse_headers(raw: list[str] | None) -> tuple[tuple[str, str], ...]:
    """``["Name: value", …]`` as header pairs; a malformed one is a usage error."""
    pairs = []
    for item in raw or []:
        name, sep, value = item.partition(":")
        if not sep or not name.strip():
            raise EndpointError(f"A header must look like 'Name: value', not {item!r}.")
        pairs.append((name.strip(), value.strip()))
    return tuple(pairs)


def query_text(arg: str | None) -> str | None:
    """*arg* as a query: the contents of that file when it names one, else the text itself."""
    if arg is None:
        return None
    path = Path(arg)
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    except OSError:
        pass
    return arg


def build_source(
    url: str,
    graph: str | None,
    query: str | None,
    limit: int | None,
    headers: list[str] | None,
    timeout: float | None = None,
) -> EndpointSource:
    """The :class:`EndpointSource` for these options; invalid ones exit with a usage error."""
    try:
        return EndpointSource(
            url,
            graph=graph,
            query=query_text(query),
            limit=limit if limit is not None else saved_limit(),
            headers=parse_headers(headers),
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
        )
    except EndpointError as exc:
        _app.err.print(f"[red]{exc}{_LIT_RED_CLOSE}")
        raise typer.Exit(ExitCode.USAGE) from None


def show(
    source: EndpointSource, lang: str, *, plain: bool, handles: bool, concept: str | None
) -> None:
    """Open *source* in the browser, or print it (``--plain`` / ``--handles``) and exit."""
    if plain or handles:
        _print_snapshot(source, lang, handles=handles, concept=concept)
        return
    from ._viewer import _is_interactive_terminal

    if not _is_interactive_terminal():
        _app.err.print(
            "[red]The viewer needs an interactive terminal.[/red] "
            "Use --plain to print the tree instead."
        )
        raise SystemExit(ExitCode.USAGE)
    from ..tui import launch_endpoint

    launch_endpoint(source, lang=lang)


def _print_snapshot(
    source: EndpointSource, lang: str, *, handles: bool, concept: str | None
) -> None:
    from ..display import render_handle_list, render_tree

    try:
        with console.status(f"Fetching from {source.shown}…"):
            snapshot = load(source)
    except EndpointError as exc:
        _app.err.print(f"[red]{exc}{_LIT_RED_CLOSE}")
        # Not-RDF is the answer's fault (4, like a bad file); the rest is reachability (3).
        raise typer.Exit(
            ExitCode.INVALID_RDF if isinstance(exc, NotRdfError) else ExitCode.FILE
        ) from None
    if snapshot.empty:
        _app.err.print("[yellow]The endpoint answered, but with no triples.[/yellow]")
    if snapshot.truncated:
        _app.err.print(
            f"[yellow]Row limit ({source.limit:,}) reached; the data is cut short. "
            "Raise it with --limit.[/yellow]"
        )
    if handles:
        console.print(render_handle_list(snapshot.taxonomy, lang))
    elif concept:
        console.print(render_tree(snapshot.taxonomy, root_handle=concept, lang=lang))
    else:
        console.print(render_tree(snapshot.taxonomy, lang=lang))


def run_endpoint_interactive() -> None:  # pragma: no cover - interactive tty
    """The home-menu flow: ask for the endpoint, what to read from it, and the row limit."""
    console.print("\n[bold]Open a SPARQL endpoint[/bold] [dim](read-only)[/dim]\n")
    try:
        url = ask.text("Endpoint URL").strip()
        what = ask.text(
            "Read the [bold]default[/bold] graph, a named [bold]graph[/bold], or your own "
            "[bold]query[/bold]?",
            choices=list(_SOURCES),
            default="default",
        )
        graph = ask.text("Named graph IRI").strip() if what == "graph" else None
        query = (
            ask.text("CONSTRUCT query (or a .rq file path)").strip() if what == "query" else None
        )
        limit = int(ask.text("Row limit", default=str(saved_limit())).strip())
        header = ask.text("Header, e.g. 'Authorization: Bearer …' (blank for none)", default="")
    except (KeyboardInterrupt, EOFError):
        return
    except ValueError:
        _app.err.print("[red]The row limit must be a whole number.[/red]")
        return
    try:
        source = build_source(url, graph, query, limit, [header] if header.strip() else None)
    except typer.Exit:
        return
    save_limit(limit)
    show(source, "en", plain=False, handles=False, concept=None)
