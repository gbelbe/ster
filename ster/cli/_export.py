"""The export command: HTML/graph/pyLODE generation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import typer

from .. import ask, store
from ..display import console
from ..model import Taxonomy
from ._exit import ExitCode

_LIT_GREEN: Final = "  [green]✓[/green]  "
_LIT_BOLD: Final = "[/bold]…"
_LIT_RED: Final = "[/red]"
_LIT_YELLOW: Final = "[yellow]"
_LIT_ONTPUB: Final = "ontpub"
_LIT_VOCPUB: Final = "vocpub"


from . import _app, _file_picker, _taxonomy_io

# ──────────────────────────── export ─────────────────────────────────────────


def _browser_url(path: Path) -> str:
    """A file:// URL for *path*, which must be absolute to have one.

    Path.as_uri() raises on a relative path, and the export builds this only to
    open a browser — so `ster export -f x.ttl` wrote every file and then died
    on the last line with a traceback. Resolving first is the whole fix.
    """
    return path.resolve().as_uri()


@_app.app.command("export")
def cmd_export(
    path: Path | None = typer.Argument(None, help="Taxonomy file (.ttl)."),
    file: Path | None = typer.Option(None, "--file", "-f", help="Taxonomy file (.ttl)."),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output directory (default: same folder as taxonomy)."
    ),
    lang: str | None = typer.Option(
        None,
        "--lang",
        "-l",
        help="Comma-separated language codes to generate, e.g. en,fr. Defaults to all languages found.",
    ),
    open_pages: bool = typer.Option(
        True, "--open/--no-open", help="Open the generated documentation in the browser."
    ),
) -> None:
    """Export the taxonomy to a browsable HTML website (requires pyLODE).

    Generates one HTML page per language with a language-switcher bar.

    Examples:\n
      ster export                         # auto-detect languages\n
      ster export --lang en               # English only\n
      ster export --lang en,fr --output ./docs\n
      ster export --no-open                # write the files, open nothing\n
    """
    from ..html_export import detect_profile, generate_html

    taxonomy_file = _file_picker._resolve_file(_file_picker._one_file(path, file))
    output_dir = output or taxonomy_file.parent / "html"
    languages = [lg.strip() for lg in lang.split(",")] if lang else None

    if not _ensure_ontology_uri(taxonomy_file):
        raise typer.Exit(ExitCode.USAGE)

    detected = detect_profile(taxonomy_file)
    chosen_profile = detected if detected != "both" else _LIT_ONTPUB
    if detected == "both":
        console.print(
            f"{_LIT_YELLOW}{taxonomy_file.name}[/yellow] contains both skos:ConceptScheme "
            "and owl:Ontology — using OntPub. Pass --profile vocpub to override."
        )

    console.print(f"[dim]Generating HTML from[/dim] [bold]{taxonomy_file.name}{_LIT_BOLD}")
    try:
        created = generate_html(
            taxonomy_file,
            output_dir,
            languages=languages if chosen_profile == _LIT_VOCPUB else None,
            profile=chosen_profile,  # type: ignore[arg-type]
        )
    except RuntimeError as exc:
        _app.err.print(f"[red]{exc}{_LIT_RED}")
        raise typer.Exit(ExitCode.UNEXPECTED)
    except Exception as exc:
        _app.err.print(f"[red]Export failed: {exc}{_LIT_RED}")
        raise typer.Exit(ExitCode.UNEXPECTED)

    import webbrowser

    for path in created:
        console.print(f"{_LIT_GREEN}{path}")

    if created:
        console.print(
            f"\n[bold]Generated {len(created)} file(s)[/bold] in [cyan]{output_dir}[/cyan]"
        )
        entry = next((p for p in created if "_en" in p.name), created[0])
        # Spelled --open/--no-open to match `ster publish`, which already had it.
        # Without a way to decline, export could not run unattended: it is the
        # documentation build, so a pipeline or a CI job wants the files and not
        # a browser it has no display for.
        if open_pages:
            webbrowser.open(_browser_url(entry))
            console.print(f"  [dim]Opened in browser:[/dim] {entry}")
        else:
            console.print(f"  [dim]Open it with:[/dim] {_browser_url(entry)}")


# ──────────────────────────── internal helpers ───────────────────────────────


def _make_taxonomy_commit_msg(taxonomy: Taxonomy, file_path: Path, lang: str = "en") -> str:
    """Build a descriptive git commit message for a newly tracked taxonomy file."""
    scheme = taxonomy.primary_scheme()
    title = scheme.title(lang) if scheme else file_path.stem
    lines = [f'feat: create taxonomy "{title}"', ""]
    lines.append(f"File: {file_path.name}")
    if scheme:
        if scheme.uri:
            lines.append(f"Scheme URI: {scheme.uri}")
        if scheme.base_uri:
            lines.append(f"Base URI: {scheme.base_uri}")
        if scheme.languages:
            lines.append(f"Languages: {', '.join(sorted(scheme.languages))}")
        if scheme.creator:
            lines.append(f"Creator: {scheme.creator}")
        if scheme.created:
            lines.append(f"Created: {scheme.created}")
    n = len(taxonomy.concepts)
    if n:
        lines.append(f"Concepts: {n}")
    return "\n".join(lines)


def _humanize(name: str) -> str:
    """Convert a camelCase/PascalCase local name to a human-readable label.

    Examples:
        SpadeRudder      → "Spade Rudder"
        trimTabOnRudder  → "Trim Tab On Rudder"
        HTTP             → "HTTP"
    """
    local = name.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", local)
    return spaced[0].upper() + spaced[1:] if spaced else local


def _collect_reachable(taxonomy: Taxonomy, uri: str, visited: set[str]) -> None:
    if uri in visited:
        return
    visited.add(uri)
    concept = taxonomy.concepts.get(uri)
    if concept:
        for child in concept.narrower:
            _collect_reachable(taxonomy, child, visited)


def _run_graph_viz_interactive(files: list[Path]) -> None:
    """Open the graph visualisation for a chosen file."""
    from .. import viz_vowl as _viz

    if not files:
        _app.err.print("[red]No taxonomy files found.[/red]")
        return

    # Pick the file to visualise
    taxonomy_file: Path
    if len(files) == 1:
        taxonomy_file = files[0]
    else:
        console.print()
        for i, f in enumerate(files, 1):
            console.print(f"  [cyan]{i:>2}[/cyan]  {f.name}")
        console.print()
        try:
            choice = ask.text(
                "File to visualise",
                default="1",
            )
        except (KeyboardInterrupt, EOFError):
            console.print(_app._CANCELLED_MESSAGE)
            return
        try:
            idx = int(choice.strip()) - 1
            taxonomy_file = files[idx]
        except (ValueError, IndexError):
            _app.err.print("[red]Invalid choice.[/red]")
            return

    taxonomy = _taxonomy_io._load_safe(taxonomy_file)
    if taxonomy is None:
        return
    console.print(f"\n[dim]Opening graph for[/dim] [bold]{taxonomy_file.name}{_LIT_BOLD}")
    try:
        _free_graph_port()  # a leftover graph process on the port would block the live view
        out = _viz.open_in_browser(taxonomy, taxonomy_file)
        console.print(f"{_LIT_GREEN}{out}")
    except Exception as exc:
        _app.err.print(f"[red]Graph error: {exc}{_LIT_RED}")


def _free_graph_port() -> None:
    """Close a previous graph process still holding the live-server port, so the live
    (interactive) graph can start. No-op when our own server is already live or the
    port is free."""
    from .. import viz_vowl as _viz

    if _viz.is_live_server():
        return
    holder = _viz.port_holder()
    if holder is None:
        return
    pid, _desc = holder
    if _viz.free_port(pid):
        console.print(f"  [dim]Closed a previous graph process (PID {pid}) holding the port.[/dim]")


def _ensure_pylode() -> bool:
    """Return True if pyLODE is importable, offering to install it if not."""
    from ..html_export import is_pylode_available

    if is_pylode_available():
        return True

    console.print("\n[yellow]pyLODE is not installed.[/yellow]")
    try:
        answer = ask.text(
            "Install it now?  [dim](pip install pylode)[/dim]",
            choices=["y", "n"],
            default="y",
        )
    except (KeyboardInterrupt, EOFError):
        return False

    if answer != "y":
        return False

    import importlib
    import shutil
    import subprocess
    import sys

    # uv-managed tool environments don't bundle pip — prefer uv when available.
    uv_bin = shutil.which("uv")
    if uv_bin:
        cmd = [uv_bin, "pip", "install", "--python", sys.executable, "pylode"]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "pylode"]

    with console.status("[dim]Installing pyLODE…[/dim]"):
        result = subprocess.run(cmd, capture_output=True)
    importlib.invalidate_caches()
    if result.returncode != 0:
        _app.err.print("[red]Installation failed.[/red]")
        _app.err.print(result.stderr.decode(errors="replace"))
        return False
    console.print("[green]✓ pyLODE installed.[/green]")
    return True


def _ensure_ontology_uri(taxonomy_file: Path) -> bool:
    """If the file has no owl:Ontology/skos:ConceptScheme URI, prompt for one and save it.

    Returns False if the user cancels or the file cannot be loaded.
    """
    taxonomy = _taxonomy_io._load_safe(taxonomy_file)
    if taxonomy is None:
        return False
    if taxonomy.ontology_uri or taxonomy.schemes:
        return True

    console.print()
    console.print(
        f"{_LIT_YELLOW}{taxonomy_file.name}[/yellow] has no ontology URI (required by pyLODE)."
    )
    stem = re.sub(r"[^a-z0-9]+", "-", taxonomy_file.stem.lower()).strip("-")
    default_name = taxonomy_file.stem.replace("_", " ").replace("-", " ").title()
    default_uri = f"https://example.org/ontology/{stem}"

    try:
        name = ask.text("Ontology name", default=default_name)
        uri = ask.text("Ontology URI", default=default_uri)
    except (KeyboardInterrupt, EOFError):
        console.print(_app._CANCELLED_MESSAGE)
        return False

    if not uri or " " in uri.strip():
        _app.err.print("[red]Invalid URI — spaces are not allowed.[/red]")
        return False

    taxonomy.ontology_uri = uri.strip()
    taxonomy.ontology_label = name.strip() or None
    store.save(taxonomy, taxonomy_file)
    console.print(f"  [green]✓[/green]  Saved ontology URI to {taxonomy_file.name}")
    return True


def _show_html_export_preview(files: list[Path]) -> None:
    from ..html_export import _available_languages, detect_profile

    for taxonomy_file in files:
        detected = detect_profile(taxonomy_file)
        taxonomy = _taxonomy_io._load_safe(taxonomy_file)
        if taxonomy is None:
            continue
        if detected == _LIT_ONTPUB:
            lang_str = "n/a (OWL)"
        else:
            langs = _available_languages(taxonomy)
            lang_str = ", ".join(langs) if langs else "en"
        profile_str = {
            _LIT_VOCPUB: "SKOS/VocPub",
            _LIT_ONTPUB: "OWL/OntPub",
            "both": "SKOS+OWL",
        }.get(detected, detected)
        console.print(
            f"[bold]{taxonomy_file.name}[/bold]  "
            f"[dim]Profile: {profile_str}  Languages: {lang_str}[/dim]"
        )

    console.print()


def _choose_html_profiles(files: list[Path]) -> dict[Path, str] | None:
    from ..html_export import detect_profile

    file_profiles: dict[Path, str] = {}
    for taxonomy_file in files:
        detected = detect_profile(taxonomy_file)
        if detected != "both":
            file_profiles[taxonomy_file] = detected
            continue
        console.print(
            f"{_LIT_YELLOW}{taxonomy_file.name}[/yellow] contains both "
            "skos:ConceptScheme and owl:Ontology declarations."
        )
        try:
            file_profiles[taxonomy_file] = ask.text(
                "  Which profile?", choices=[_LIT_VOCPUB, _LIT_ONTPUB], default=_LIT_ONTPUB
            )
        except (KeyboardInterrupt, EOFError):
            console.print(_app._CANCELLED_MESSAGE)
            return None
    return file_profiles


def _choose_html_languages(
    file_profiles: dict[Path, str],
) -> tuple[bool, list[str] | None]:
    if not any(profile == _LIT_VOCPUB for profile in file_profiles.values()):
        return True, None
    try:
        lang_input = ask.text(
            "Languages to export [dim](comma-separated, Enter for all detected)[/dim]",
            default="",
        )
    except (KeyboardInterrupt, EOFError):
        console.print(_app._CANCELLED_MESSAGE)
        return False, None
    return True, [lg.strip() for lg in lang_input.split(",") if lg.strip()] or None


def _choose_html_output(files: list[Path]) -> Path | None:
    output_dir = files[0].parent / "html"
    console.print()
    try:
        return Path(ask.text("Output directory", default=str(output_dir)).strip())
    except (KeyboardInterrupt, EOFError):
        console.print(_app._CANCELLED_MESSAGE)
        return None


def _html_export_options(
    files: list[Path],
) -> tuple[dict[Path, str], list[str] | None, Path] | None:
    _show_html_export_preview(files)
    file_profiles = _choose_html_profiles(files)
    if file_profiles is None:
        return None
    accepted, languages = _choose_html_languages(file_profiles)
    if not accepted:
        return None
    output_dir = _choose_html_output(files)
    if output_dir is None:
        return None
    return file_profiles, languages, output_dir


def _run_html_export_interactive(files: list[Path]) -> None:
    """Interactive HTML export from the home-screen menu."""
    if not _ensure_pylode():
        return

    from ..html_export import generate_html

    if not files:
        _app.err.print("[red]No taxonomy files selected.[/red]")
        return

    options = _html_export_options(files)
    if options is None:
        return
    file_profiles, languages, output_dir = options

    console.print()
    all_created: list[Path] = []
    for taxonomy_file in files:
        if not _ensure_ontology_uri(taxonomy_file):
            return
        console.print(f"[dim]Generating[/dim] [bold]{taxonomy_file.name}{_LIT_BOLD}")
        chosen_profile = file_profiles[taxonomy_file]
        file_langs = languages if chosen_profile == _LIT_VOCPUB else None
        try:
            created = generate_html(
                taxonomy_file,
                output_dir,
                languages=file_langs,
                profile=chosen_profile,  # type: ignore[arg-type]
            )
            for p in created:
                console.print(f"{_LIT_GREEN}{p}")
            all_created.extend(created)
        except RuntimeError as exc:
            _app.err.print(f"[red]{exc}{_LIT_RED}")
            return
        except Exception as exc:
            _app.err.print(f"[red]Export failed for {taxonomy_file.name}: {exc}{_LIT_RED}")

    if all_created:
        import webbrowser

        console.print(
            f"\n[bold]Done.[/bold]  {len(all_created)} file(s) in [cyan]{output_dir}[/cyan]"
        )
        entry = next((p for p in all_created if "_en" in p.name), all_created[0])
        webbrowser.open(_browser_url(entry))
        console.print(f"  [dim]Opened in browser:[/dim] {entry}")
