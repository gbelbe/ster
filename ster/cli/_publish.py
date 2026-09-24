"""The publish command and its interactive dev/stable-channel flows."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, Final

import typer
from rich.console import Console

from .. import ask
from ..display import console
from ._exit import ExitCode

_LIT_DIM: Final = "[/dim]"
_LIT_PATCH: Final = "patch"


from . import _app, _file_picker, _serve


def _menu_action_for_key(ch: bytes, stream: BinaryIO) -> str:
    """Map a raw keypress (with continuation bytes from *stream*) to a menu action.

    Returns one of: 'up', 'down', 'select', 'quit', 'none'.
    """
    if ch in (b"\r", b"\n"):
        return "select"
    if ch == b"\x03":  # Ctrl+C
        return "quit"
    if ch != b"\x1b":  # not an escape sequence
        return "none"
    if stream.read(1) != b"[":
        return "quit"  # plain Esc
    code = stream.read(1)
    if code == b"A":
        return "up"
    if code == b"B":
        return "down"
    return "none"


def _render_publish_menu(labels: list[str], sel: int, first: bool) -> None:  # pragma: no cover
    """Redraw the publish menu in place (raw-terminal ANSI)."""
    import sys

    inv, r, b, d = _app._ANSI_INVERSE, _app._ANSI_RESET, _app._ANSI_BOLD, _app._ANSI_DIM
    clear, nl = _app._CLEAR_LINE, "\r\n"
    if not first:
        sys.stdout.write(f"\033[{len(labels) + 1}A")
    for i, lab in enumerate(labels):
        if i == sel:
            sys.stdout.write(f"{clear}  {b}{inv} {lab} {r}{nl}")
        else:
            sys.stdout.write(f"{clear}    {lab}{nl}")
    sys.stdout.write(f"{clear}  {d}↑↓ navigate  Enter select  Esc back{r}{nl}")
    sys.stdout.flush()


def _arrow_menu_select(labels: list[str]) -> int | None:  # pragma: no cover
    """Raw-terminal arrow menu over *labels*; return the chosen index or None."""
    import sys
    import termios
    import tty

    if not labels:
        return None
    n, sel = len(labels), 0
    _render_publish_menu(labels, sel, first=True)
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            action = _menu_action_for_key(sys.stdin.buffer.read(1), sys.stdin.buffer)
            if action == "up":
                sel = (sel - 1) % n
            elif action == "down":
                sel = (sel + 1) % n
            elif action == "select":
                return sel
            elif action == "quit":
                return None
            _render_publish_menu(labels, sel, first=False)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\r\n")
        sys.stdout.flush()


def _select_publish_target(files: list[Path]) -> tuple[Path, object] | None:  # pragma: no cover
    """Pick a file, load it, and run pre-flight; return (path, taxonomy) or None."""
    from ..publish import PublishError, pre_flight
    from ..store import load as _load_tax

    if not files:
        _app.err.print("[red]No taxonomy files found. Open a taxonomy file first.[/red]")
        return None
    if len(files) == 1:
        taxonomy_file = files[0]
    else:
        console.print("[bold]Select a file to publish:[/bold]")
        for i, f in enumerate(files, 1):
            console.print(f"  [cyan]{i}[/cyan]  {f.name}")
        try:
            idx = int(ask.text("File number", default="1")) - 1
            taxonomy_file = files[max(0, min(idx, len(files) - 1))]
        except (ValueError, KeyboardInterrupt):
            return None
    try:
        taxonomy = _load_tax(taxonomy_file)
    except Exception as e:
        _app.err.print(f"[red]Failed to load {taxonomy_file.name}:[/red] {e}")
        return None
    try:
        pre_flight(taxonomy)
    except PublishError as e:
        _app.err.print(f"[red]Publish blocked:[/red] {e}")
        return None
    return taxonomy_file, taxonomy


def _publish_stable_flow(taxonomy_file: Path, publish_dir: Path) -> None:  # pragma: no cover
    """Prompt for a semver bump, run the git-tag-driven release, print results."""
    from ..git.manager import GitManager
    from ..publish import perform_stable_release

    console.print(
        "[bold]Release type[/bold] (Semantic Versioning):\n"
        "  [cyan]major[/cyan] — incompatible API changes\n"
        "  [cyan]minor[/cyan] — backward-compatible new functionality\n"
        "  [cyan]patch[/cyan] — backward-compatible bug fixes"
    )
    try:
        bump = ask.text("Bump", choices=["major", "minor", _LIT_PATCH], default=_LIT_PATCH)
    except (KeyboardInterrupt, EOFError):
        return
    result = perform_stable_release(taxonomy_file, publish_dir, bump, GitManager(taxonomy_file))
    console.print(
        f"[green]✓[/green]  Published [bold]{result.version_str}[/bold], "
        f"tagged [bold]{result.tag}[/bold] ({len(result.artifacts)} files)"
    )
    if result.pushed:
        console.print(f"[dim]Pushed the commit and tag {result.tag} to origin.[/dim]")
    else:
        console.print(
            f"[dim]No remote configured — push manually: "
            f"git push && git push origin {result.tag}{_LIT_DIM}"
        )


def mcp_connection_info(base_url: str, token: str) -> tuple[str, str]:
    """Return (endpoint, config_snippet) for an MCP client.

    The snippet is the ``mcpServers`` object every MCP-capable client reads —
    the endpoint is plain JSON-RPC over HTTP with a bearer token, so nothing
    here is specific to one vendor's CLI.
    """
    endpoint = f"{base_url.rstrip('/')}/mcp"
    snippet = json.dumps(
        {
            "mcpServers": {
                "ster": {
                    "type": "http",
                    "url": endpoint,
                    "headers": {"Authorization": f"Bearer {token}"},
                }
            }
        },
        indent=2,
    )
    return endpoint, snippet


def _print_mcp_connection(endpoint: str, token: str, snippet: str, copied: bool) -> None:
    """Show the endpoint, how to connect, and whether the copy landed."""
    console.print()
    console.print(f"  [bold]MCP endpoint[/bold]   [cyan]{endpoint}[/cyan]")
    console.print("  [bold]Transport[/bold]      HTTP (JSON-RPC 2.0)")
    console.print(f"  [bold]Auth header[/bold]    Authorization: Bearer {token}")
    console.print()
    console.print("  Point any MCP-capable agent at it — add this to its config:")
    console.print()
    # markup=False throughout: these lines carry a URL, a token and JSON, and a
    # "[" anywhere in them would otherwise be parsed as a Rich tag. It is also what
    # keeps the trailing "\" below intact — Rich reads "\[" as an escaped bracket,
    # so the continuation backslash used to be swallowed and "[/dim]" printed as
    # text, leaving a command that could not be pasted.
    for line in snippet.splitlines():
        console.print(f"    {line}", style="dim", markup=False)
    console.print()
    console.print("  Claude Code, for example:")
    console.print(
        f"    claude mcp add --transport http ster {endpoint} \\", style="dim", markup=False
    )
    console.print(
        '      --header "Authorization: Bearer $(cat ~/.config/ster/api_token)"',
        style="dim",
        markup=False,
    )
    console.print()
    if copied:
        console.print("  [green]✓[/green] endpoint copied to clipboard")
    else:
        console.print("  [yellow]![/yellow] could not reach the clipboard — copy the URL above")
    console.print()


def _pause_until_acknowledged(
    read: Callable[[str], object] | None = None, is_tty: bool | None = None
) -> None:
    """Hold the screen until the reader is done with what was just printed.

    Returning to the home menu reprints the banner and the action list — about 30
    lines — directly over whatever an action left on screen. Without this pause a
    25-line block like the MCP connection details is gone before it can be read on
    any terminal shorter than 55 rows.

    Skipped when there is no terminal: a piped or scripted run has nobody to press
    Enter, and waiting would hang it.
    """
    import sys

    if is_tty is None:
        is_tty = sys.stdin.isatty() and sys.stdout.isatty()
    if not is_tty:
        return
    reader = read if read is not None else input
    try:
        reader("  Press Enter to return to the menu… ")
    except (EOFError, KeyboardInterrupt):
        console.print()


def _run_mcp_connect_interactive(files: list[Path]) -> None:  # pragma: no cover - interactive tty
    """Start the live server if needed, then show and copy the MCP endpoint.

    The endpoint only exists while the server runs, so this starts it rather
    than reporting that it is down.
    """
    from ..api_server import load_token
    from ..tui.clipboard import copy_to_system_clipboard
    from ..viz_vowl import ensure_published_server

    if not files:
        _app.err.print("[red]No taxonomy files found.[/red]")
        return
    taxonomy_file = _file_picker._pick_file(files)

    from .. import store

    console.print(f"\n  Starting the ster server for [bold]{taxonomy_file.name}[/bold]…")
    base_url = ensure_published_server(store.load(taxonomy_file), taxonomy_file)
    if not base_url:
        _app.err.print(
            "[red]The server could not start — reinstall ster so fastapi/uvicorn are present.[/red]"
        )
        return

    endpoint, snippet = mcp_connection_info(base_url, load_token())
    _print_mcp_connection(endpoint, load_token(), snippet, copy_to_system_clipboard(endpoint))
    _pause_until_acknowledged()


def _run_publish_interactive(files: list[Path]) -> None:  # pragma: no cover - interactive tty
    """Interactive Linked Data Publish & Version screen from the home-screen menu."""
    import webbrowser

    from rich.panel import Panel

    from .. import viz_vowl as _viz
    from ..publish import build_publish_menu, discover_published_pages

    console.print()

    target = _select_publish_target(files)
    if target is None:
        return
    taxonomy_file, taxonomy = target

    console.print(
        Panel(
            f"[bold]📦 Linked Data Publish & Version[/bold]\n"
            f"[dim]File: {taxonomy_file}[/dim]\n"
            f"[dim]Ontology URI: {taxonomy.ontology_uri}{_LIT_DIM}"  # type: ignore[attr-defined]
            + (
                f"\n[dim]Current version: {taxonomy.version_info}{_LIT_DIM}"  # type: ignore[attr-defined]
                if taxonomy.version_info  # type: ignore[attr-defined]
                else ""
            ),
            border_style="green",
        )
    )

    publish_dir = taxonomy_file.parent / "ontology"
    base_url = _viz.ensure_published_server(taxonomy, taxonomy_file)  # type: ignore[arg-type]

    while True:
        pages = discover_published_pages(publish_dir)
        rows = build_publish_menu(pages, base_url, publish_dir)
        console.print()
        sel = _arrow_menu_select([row.label for row in rows])
        if sel is None:
            return
        row = rows[sel]
        if row.action == "back":  # explicit "← Back to menu" row (Esc does the same)
            return
        if row.action == "publish_stable":
            _publish_stable_flow(taxonomy_file, publish_dir)
        elif row.url:
            webbrowser.open(row.url)
            console.print(f"[green]✓[/green]  Opened {row.url}")


@_app.app.command("publish")
def cmd_publish(
    path: Path = typer.Argument(..., help="Taxonomy file to publish."),
    bump: str = typer.Option(
        _LIT_PATCH,
        "--bump",
        "-b",
        help="Semver bump for the stable release: major, minor, or patch.",
    ),
    channel: str = typer.Option("stable", "--channel", "-c", help="Channel: stable or dev."),
    publish_dir: Path = typer.Option(
        Path("ontology"), "--dir", "-d", help="Directory to write artifacts."
    ),
    open_pages: bool = typer.Option(
        True, "--open/--no-open", help="Open the published dev pages in the browser (dev channel)."
    ),
) -> None:
    """Publish a new versioned release of the ontology.

    Stable channel: reads the latest ``<stem>/vX.Y.Z`` ontology tag, applies the
    bump, stamps the version into the file, commits, tags, and writes
    ontology/v{version}/ + ontology/latest/.
    Dev channel:    writes ontology/dev/ (overwrites, no history).
    """

    from ..publish import PublishError, pre_flight
    from ..store import load

    _con = Console()

    if not path.exists():
        _app.err.print(f"[red]File not found:[/red] {path}")
        raise typer.Exit(ExitCode.FILE)

    taxonomy = load(path)

    try:
        pre_flight(taxonomy)
    except PublishError as e:
        _app.err.print(f"[red]Publish blocked:[/red] {e}")
        raise typer.Exit(ExitCode.PROBLEMS)

    if channel == "dev":
        _publish_dev_channel(path, taxonomy, publish_dir, open_pages, _con)
    else:
        _publish_stable_channel(path, bump, publish_dir, _con)


def _publish_dev_channel(
    path: Path, taxonomy: object, publish_dir: Path, open_pages: bool, con: object
) -> None:
    """Write the dev channel from the file's current version (no tag, no commit)."""
    from ..publish import _git_short_sha, _today_str, build_version_string, write_dev_artifacts

    vi = taxonomy.version_info  # type: ignore[attr-defined]
    base = vi.split("+")[0] if vi and "+" in vi else (vi or "0.1.0")
    version_str = build_version_string(base, _today_str(), _git_short_sha(path.parent))
    con.print(f"Publishing dev channel → [bold]{version_str}[/bold]")  # type: ignore[attr-defined]
    artifacts = write_dev_artifacts(path, publish_dir, version_str)
    con.print(  # type: ignore[attr-defined]
        f"[green]Written {len(artifacts)} artifact(s) → {publish_dir / 'dev'}[/green]"
    )
    if open_pages:
        _serve._open_dev_artifacts_in_browser(taxonomy, path, publish_dir, artifacts)


def _publish_stable_channel(path: Path, bump: str, publish_dir: Path, con: object) -> None:
    """Run the git-tag-driven stable release and report what it published/pushed."""
    from ..git.manager import GitManager
    from ..publish import perform_stable_release, semver_bump_from_choice

    try:
        kind = semver_bump_from_choice(bump)
    except ValueError as e:
        _app.err.print(f"[red]{e}[/red]")
        raise typer.Exit(ExitCode.USAGE)

    result = perform_stable_release(path, publish_dir, kind, GitManager(path))
    con.print(  # type: ignore[attr-defined]
        f"[green]✓[/green] Published [bold]{result.version_str}[/bold], "
        f"tagged [bold]{result.tag}[/bold] ({len(result.artifacts)} files)"
    )
    for a in result.artifacts:
        con.print(f"  {a}")  # type: ignore[attr-defined]
    if result.pushed:
        con.print(  # type: ignore[attr-defined]
            f"[dim]Pushed the commit and tag {result.tag} to origin.[/dim]"
        )
    else:
        con.print(  # type: ignore[attr-defined]
            f"[dim]No remote configured — push manually: "
            f"git push && git push origin {result.tag}{_LIT_DIM}"
        )
