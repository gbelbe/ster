"""The semanticdiff command line."""

from __future__ import annotations

from pathlib import Path

import typer

from semanticdiff.git_log import RDF_SUFFIXES, GitError, list_tracked
from semanticdiff.history import read_history
from semanticdiff.render.text import render_commits, render_entity, render_summary

app = typer.Typer(
    help="Read a git history of an ontology as semantic change, not as text.",
    no_args_is_help=True,
    add_completion=False,
)

_REPO = typer.Option(Path("."), "--repo", help="Repository to read.")
_FILE = typer.Option(None, "--file", help="Tracked RDF file. Autodetected when omitted.")
_RANGE = typer.Argument("HEAD", help="Revision range, e.g. v0.1..v0.2.")


@app.command()
def log(
    rev_range: str = _RANGE,
    repo: Path = _REPO,
    file: str | None = _FILE,
    text: bool = typer.Option(False, "--text", help="Also print the raw diff hunks."),
) -> None:
    """Summarise every commit in the range as semantic change."""
    path, history = _load(repo, rev_range, file, with_text=text)
    typer.echo(path)
    typer.echo(render_summary(history, rev_range))
    typer.echo("")
    typer.echo(render_commits(history, show_text=text))


@app.command()
def show(
    uri: str = typer.Argument(..., help="Entity to trace, as a CURIE or a full URI."),
    rev_range: str = _RANGE,
    repo: Path = _REPO,
    file: str | None = _FILE,
) -> None:
    """Trace one entity through the history."""
    _, history = _load(repo, rev_range, file, with_text=False)
    typer.echo(render_entity(history, uri))


def _load(repo: Path, rev_range: str, file: str | None, *, with_text: bool) -> tuple[str, list]:
    if not (repo / ".git").exists():
        raise _fail(f"{repo} is not a git repository")
    path = file or _detect(repo)
    try:
        return path, read_history(repo, rev_range, path, with_text=with_text)
    except (GitError, FileNotFoundError) as exc:
        raise _fail(str(exc)) from exc


def _detect(repo: Path) -> str:
    """The repository's one tracked RDF file, or an error naming the alternatives."""
    try:
        tracked = list_tracked(repo)
    except GitError as exc:
        raise _fail(str(exc)) from exc
    candidates = [f for f in tracked if Path(f).suffix.lower() in RDF_SUFFIXES]
    if not candidates:
        raise _fail("no RDF file is tracked in this repository; pass --file")
    if len(candidates) > 1:
        raise _fail(f"several RDF files tracked ({', '.join(candidates)}); pass --file")
    return candidates[0]


def _fail(message: str) -> typer.Exit:
    """Report on stdout and exit non-zero — errors are part of the output, not a traceback."""
    typer.echo(message)
    return typer.Exit(1)


def main() -> None:
    app()
