"""Opens the Textual viewer for a taxonomy file, wiring in git tracking."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from .. import ask, store
from ..display import console
from ..model import Taxonomy

if TYPE_CHECKING:
    from ..git.manager import GitManager

from . import _app, _export, _rdfxml, _state
from ._exit import ExitCode

# ──────────────────────────── viewer helper ──────────────────────────────────


def _prewarm_lint(path: Path) -> None:
    """Compute and cache semanticlint before opening the browser, best-effort."""
    try:
        from ..plugins import semanticlint

        if not semanticlint.is_active():
            return
        from ..plugins.semanticlint import config, lint_cache
        from ..plugins.semanticlint.runner import lint_overview

        cfg_hash = lint_cache.config_hash(config.load_config())
        if lint_cache.get_cached(path, cfg_hash) is not None:
            return
        with console.status(f"Checking {path.name}…"):
            lint_cache.get_or_compute(path, cfg_hash, compute=lambda: lint_overview(path))
    except Exception:  # noqa: BLE001 — pre-warming must never block opening the file
        pass


def _start_git_fetch(gm: GitManager) -> threading.Event | None:
    """Prepare configured git and fetch remote changes in the background."""
    if not gm.is_enabled():
        return None
    if not gm.is_configured():
        gm.setup()
    if not gm.is_configured():
        return None

    gm.record_head()
    fetch_event = threading.Event()

    def _do_fetch() -> None:
        try:
            gm.fetch_remote()
        except Exception:
            pass
        finally:
            fetch_event.set()

    threading.Thread(target=_do_fetch, daemon=True).start()
    return fetch_event


def _finish_configured_git(gm: GitManager, fetch_event: threading.Event | None) -> None:
    """Pull fetched changes and push the viewer's edits."""
    from ..git.manager import render_diff

    if fetch_event is not None:
        fetch_event.wait(timeout=15)
        diff = gm.check_and_pull()
        if diff:
            console.print("\n[bold]Changes pulled from remote:[/bold]")
            render_diff(diff)
            console.print()
    try:
        gm.commit_and_push()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        console.print(f"\n[red]Commit error:[/red] {exc}")


def _offer_git_tracking(gm: GitManager, taxonomy: Taxonomy, taxonomy_file: Path) -> None:
    """Offer to configure git after viewing an otherwise unconfigured taxonomy."""
    try:
        want_git = ask.confirm("\nAdd taxonomy to git repository?", default=False)
    except (KeyboardInterrupt, EOFError):
        want_git = False
    if want_git:
        gm.setup()
        if gm.is_configured():
            msg = _export._make_taxonomy_commit_msg(taxonomy, taxonomy_file)
            gm.commit_new_taxonomy(msg)


def _handle_viewer_git(
    gm: GitManager,
    taxonomy: Taxonomy,
    taxonomy_file: Path,
    fetch_event: threading.Event | None,
) -> None:
    """Complete the git flow after the viewer closes."""
    if not gm.is_enabled():
        return
    if gm.is_configured():
        _finish_configured_git(gm, fetch_event)
        return
    _offer_git_tracking(gm, taxonomy, taxonomy_file)


def _is_interactive_terminal() -> bool:
    """True when both halves of the console are a real terminal.

    Either half being a pipe is enough to break Textual's input driver, so this
    deliberately requires both rather than stdin alone.
    """
    import sys

    return sys.stdin.isatty() and sys.stdout.isatty()


def _open_viewer(taxonomy_file: Path, lang: str = "en", context: list[Path] | None = None) -> None:
    """Open the New-TUI for *taxonomy_file* (``ster show``) and handle git on exit.

    *context* names files merged in read-only, so the connected graph is on
    screen while only *taxonomy_file* can be edited.
    """
    from ..git.manager import GitManager
    from ..tui import launch_file

    # Without a terminal the Textual _app.app spins its event loop at ~100% CPU and
    # never exits: the input driver selects on a non-tty stdin that stays readable
    # at EOF, and no quit ever arrives. `ster` in a pipeline hung there until
    # killed, so refuse the launch and say why.
    if not _is_interactive_terminal():
        _app.err.print(
            "[red]The viewer needs an interactive terminal.[/red] "
            "Run ster directly instead of through a pipe, "
            "or use a non-interactive command such as [bold]ster show --help[/bold]."
        )
        # SystemExit, not typer.Exit: the home-screen loop reads typer.Exit as
        # "quit", which would turn this refusal back into a successful exit 0.
        raise SystemExit(ExitCode.USAGE)

    _prewarm_lint(taxonomy_file)
    pre_hash = store.file_hash(taxonomy_file) if _state.converted_from else ""
    gm = GitManager(taxonomy_file)
    fetch_event = _start_git_fetch(gm)
    taxonomy = launch_file(taxonomy_file, source=taxonomy_file.name, lang=lang, context=context)
    if taxonomy is None:
        return

    _handle_viewer_git(gm, taxonomy, taxonomy_file, fetch_event)
    if _state.converted_from:
        _rdfxml._maybe_backconvert(taxonomy_file, pre_hash, _state.converted_from)
