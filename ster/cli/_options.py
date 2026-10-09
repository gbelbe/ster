"""Options several commands share, declared once."""

from __future__ import annotations

from pathlib import Path

import typer

CONTEXT_HELP = (
    "Load these files read-only alongside FILE (repeatable). "
    "Their entities are visible but locked, and saving never writes to them."
)


def context_files() -> list[Path] | None:
    """The ``--context-files/-x`` option of every command that opens a graph."""
    return typer.Option(None, "--context-files", "-x", help=CONTEXT_HELP)  # type: ignore[return-value]


def endpoint() -> str | None:
    """``--endpoint/-e``: read a SPARQL endpoint instead of a file."""
    return typer.Option(  # type: ignore[return-value]
        None,
        "--endpoint",
        "-e",
        metavar="URL",
        help="Read a SPARQL endpoint (e.g. GraphDB) instead of a file. Read-only snapshot; "
        "press R in the viewer to fetch again.",
    )


def endpoint_graph() -> str | None:
    return typer.Option(  # type: ignore[return-value]
        None, "--graph", metavar="IRI", help="With --endpoint: read only this named graph."
    )


def endpoint_query() -> str | None:
    return typer.Option(  # type: ignore[return-value]
        None,
        "--query",
        metavar="FILE|TEXT",
        help="With --endpoint: your own CONSTRUCT query, as text or a .rq file.",
    )


def endpoint_limit() -> int | None:
    return typer.Option(  # type: ignore[return-value]
        None,
        "--limit",
        metavar="N",
        help="With --endpoint: row limit for the default/named graph "
        "(default: the last one used, else 100,000).",
    )


def endpoint_header() -> list[str] | None:
    return typer.Option(  # type: ignore[return-value]
        None,
        "--header",
        metavar="'Name: value'",
        help="With --endpoint: an HTTP header such as an Authorization token (repeatable; "
        "never saved).",
    )


def endpoint_timeout() -> float | None:
    return typer.Option(  # type: ignore[return-value]
        None,
        "--timeout",
        metavar="SECONDS",
        help="With --endpoint: give up when the endpoint has not answered, or has not "
        "finished sending, within this long (default: 600).",
    )
