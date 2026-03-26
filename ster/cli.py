"""Typer CLI — load, operate, save pattern for every mutating command."""
from __future__ import annotations
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from . import store, operations
from .display import render_tree, render_concept_detail, render_handle_list, console
from .exceptions import SkostaxError
from .model import LabelType, Taxonomy

app = typer.Typer(
    name="ster",
    help="Interactive SKOS taxonomy editor.",
    no_args_is_help=True,
)
err = Console(stderr=True)

_TAXONOMY_SUFFIXES = {".ttl", ".rdf", ".jsonld", ".owl", ".n3"}
_TAXONOMY_GLOBS = ("*.ttl", "*.rdf", "*.jsonld", "*.owl", "*.n3")

_session_file: Path | None = None  # in-process cache


# ──────────────────────────── session / file resolution ──────────────────────

def _session_cache_path() -> Path:
    """Return a per-CWD temp file used to persist the selected taxonomy file."""
    cwd_hash = hashlib.md5(str(Path.cwd()).encode()).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"ster_{cwd_hash}"


def _load_session() -> Path | None:
    p = _session_cache_path()
    if p.exists():
        try:
            data = json.loads(p.read_text())
            f = Path(data["file"])
            if f.exists():
                return f
        except Exception:
            pass
    return None


def _save_session(path: Path) -> None:
    _session_cache_path().write_text(json.dumps({"file": str(path.resolve())}))


def _resolve_file(path: Optional[Path]) -> Path:
    """Return the taxonomy file to operate on.

    Priority:
      1. Explicit --file argument.
      2. In-process session cache (_session_file).
      3. Persisted session cache (temp file keyed on CWD).
      4. Auto-discovery: single file → confirm; multiple → interactive picker.
    """
    global _session_file

    if path is not None:
        _session_file = path
        _save_session(path)
        return path

    if _session_file is not None:
        return _session_file

    saved = _load_session()
    if saved is not None:
        _session_file = saved
        return _session_file

    # Discover taxonomy files in CWD
    found: list[Path] = []
    for pattern in _TAXONOMY_GLOBS:
        found.extend(Path.cwd().glob(pattern))
    found = sorted(set(found))

    if not found:
        err.print("[red]No taxonomy file found in the current directory.[/red]")
        err.print("[dim]Pass --file <path> or run 'ster init' to create one.[/dim]")
        raise typer.Exit(1)

    if len(found) == 1:
        console.print(f"[dim]Auto-detected:[/dim] [bold]{found[0].name}[/bold]")
        if not Confirm.ask("Use this file for this session?", default=True):
            raise typer.Abort()
        _save_session(found[0])
        _session_file = found[0]
        return _session_file

    selected = _pick_file(found)
    _save_session(selected)
    _session_file = selected
    return _session_file


def _pick_file(files: list[Path]) -> Path:
    """Interactive file picker with optional Tab completion."""
    console.print("\n[bold]Multiple taxonomy files found:[/bold]\n")
    for i, f in enumerate(files, 1):
        console.print(f"  [cyan]{i:>2}[/cyan]  {f.name}")
    console.print()

    # Enable readline tab completion where available (Unix/macOS)
    try:
        import readline
        names = [f.name for f in files]

        def _completer(text: str, state: int) -> str | None:
            matches = [n for n in names if n.lower().startswith(text.lower())]
            return matches[state] if state < len(matches) else None

        readline.set_completer(_completer)
        readline.parse_and_bind("tab: complete")
    except ImportError:
        pass

    while True:
        choice = Prompt.ask("Select file [bold](number or filename, Tab to complete)[/bold]")
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(files):
                return files[idx]
            err.print(f"[red]Enter a number between 1 and {len(files)}.[/red]")
            continue
        matches = [f for f in files if f.name == choice or f.name.startswith(choice)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            err.print(f"[yellow]Ambiguous — {[f.name for f in matches]}. Be more specific.[/yellow]")
        else:
            err.print(f"[red]{choice!r} not found.[/red]")


# ──────────────────────────── helpers ────────────────────────────────────────

def _load(path: Path) -> Taxonomy:
    try:
        return store.load(path)
    except Exception as exc:
        err.print(f"[red]Cannot load {path}: {exc}[/red]")
        raise typer.Exit(1)


def _save(taxonomy: Taxonomy, path: Path) -> None:
    try:
        store.save(taxonomy, path)
        console.print(f"[green]✓ Saved[/green] {path}")
    except Exception as exc:
        err.print(f"[red]Cannot save {path}: {exc}[/red]")
        raise typer.Exit(1)


def _resolve(taxonomy: Taxonomy, ref: str) -> str:
    try:
        return operations.resolve(taxonomy, ref)
    except SkostaxError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


def _run(fn, *args, **kwargs):
    """Call an operations function, converting SkostaxError to a clean exit."""
    try:
        return fn(*args, **kwargs)
    except SkostaxError as exc:
        err.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


# ──────────────────────────── show ───────────────────────────────────────────

@app.command("show")
def cmd_show(
    concept: Optional[str] = typer.Option(
        None, "--concept", "-c", metavar="HANDLE",
        help="Show subtree rooted at this concept.",
    ),
    detail: bool = typer.Option(False, "--detail", "-d", help="Show full concept detail."),
    lang: str = typer.Option("en", "--lang", "-l", help="Label language."),
    handles: bool = typer.Option(False, "--handles", "-H", help="Print handle index table."),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Taxonomy file (.ttl / .rdf / .jsonld)."),
) -> None:
    """Display the taxonomy tree (or a subtree)."""
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)

    if handles:
        console.print(render_handle_list(taxonomy, lang))
        return

    if concept:
        uri = _resolve(taxonomy, concept)
        if detail:
            console.print(render_concept_detail(taxonomy, uri, lang))
        else:
            console.print(render_tree(taxonomy, root_handle=concept, lang=lang))
            console.print(render_concept_detail(taxonomy, uri, lang))
    else:
        console.print(render_tree(taxonomy, lang=lang))


# ──────────────────────────── add ────────────────────────────────────────────

@app.command("add")
def cmd_add(
    name: str = typer.Argument(
        ...,
        help="Local name or full URI for the new concept. "
             "A local name (e.g. 'SpadeRudder') is automatically expanded "
             "with the taxonomy's base URI.",
    ),
    parent: Optional[str] = typer.Option(
        None, "--parent", "-p", metavar="HANDLE|NAME",
        help="Parent concept handle or name (omit for primary scheme top level).",
    ),
    en: Optional[str] = typer.Option(None, "--en", help="English preferred label."),
    fr: Optional[str] = typer.Option(None, "--fr", help="French preferred label."),
    def_en: Optional[str] = typer.Option(None, "--def-en", help="English definition."),
    def_fr: Optional[str] = typer.Option(None, "--def-fr", help="French definition."),
    lang: str = typer.Option("en", "--lang", "-l", help="Display language for confirmation."),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Add a new concept to the taxonomy.

    The concept name is expanded to a full URI using the taxonomy's base URI.
    You can also pass a full URI directly.
    """
    labels: dict[str, str] = {}
    if en:
        labels["en"] = en
    if fr:
        labels["fr"] = fr
    if not labels:
        labels[lang] = _humanize(name)
        console.print(f"[dim]No label provided — using default: {labels[lang]!r}[/dim]")

    definitions: dict[str, str] = {}
    if def_en:
        definitions["en"] = def_en
    if def_fr:
        definitions["fr"] = def_fr

    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    uri = _run(operations.expand_uri, taxonomy, name)
    concept = _run(operations.add_concept, taxonomy, uri, labels, parent, definitions or None)
    console.print(f"[green]Added[/green]  [{taxonomy.uri_to_handle(uri)}]  {concept.pref_label(lang)}  [dim]({uri})[/dim]")
    _save(taxonomy, taxonomy_file)


# ──────────────────────────── remove ─────────────────────────────────────────

@app.command("remove")
def cmd_remove(
    concept: str = typer.Argument(..., metavar="HANDLE", help="Concept handle or URI."),
    cascade: bool = typer.Option(False, "--cascade", help="Also remove all descendants."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    lang: str = typer.Option("en", "--lang", "-l"),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Remove a concept from the taxonomy."""
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    uri = _resolve(taxonomy, concept)
    c = taxonomy.concepts[uri]

    if not yes:
        msg = f"Remove [bold]{c.pref_label(lang)}[/bold]"
        n_children = len(c.narrower)
        if cascade and n_children:
            msg += f" and its {n_children} child(ren)"
        if not Confirm.ask(msg + "?"):
            raise typer.Abort()

    removed = _run(operations.remove_concept, taxonomy, uri, cascade=cascade)
    console.print(f"[green]Removed[/green] {len(removed)} concept(s).")
    _save(taxonomy, taxonomy_file)


# ──────────────────────────── move ───────────────────────────────────────────

@app.command("move")
def cmd_move(
    concept: str = typer.Argument(..., metavar="HANDLE", help="Concept to move."),
    parent: Optional[str] = typer.Option(
        None, "--parent", "-p", metavar="HANDLE",
        help="New parent handle (omit to promote to top level).",
    ),
    lang: str = typer.Option("en", "--lang", "-l"),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Move a concept to a new parent."""
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    uri = _resolve(taxonomy, concept)
    parent_uri = _resolve(taxonomy, parent) if parent else None

    _run(operations.move_concept, taxonomy, uri, parent_uri)

    dest = taxonomy.concepts[parent_uri].pref_label(lang) if parent_uri and parent_uri in taxonomy.concepts else "top level"
    console.print(f"[green]Moved[/green]  {taxonomy.concepts[uri].pref_label(lang)}  →  {dest}")
    _save(taxonomy, taxonomy_file)


# ──────────────────────────── label ──────────────────────────────────────────

@app.command("label")
def cmd_label(
    concept: str = typer.Argument(..., metavar="HANDLE"),
    lang: str = typer.Argument(..., help="Language code (en, fr, …)"),
    text: str = typer.Argument(..., help="Label text"),
    alt: bool = typer.Option(False, "--alt", help="Add as alt label (default: pref label)."),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Set a preferred or alternative label on a concept."""
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    uri = _resolve(taxonomy, concept)
    label_type = LabelType.ALT if alt else LabelType.PREF
    _run(operations.set_label, taxonomy, uri, lang, text, label_type)
    kind = "alt label" if alt else "pref label"
    console.print(f"[green]Set {kind}[/green]  [{lang}]  {text}")
    _save(taxonomy, taxonomy_file)


# ──────────────────────────── define ─────────────────────────────────────────

@app.command("define")
def cmd_define(
    concept: str = typer.Argument(..., metavar="HANDLE"),
    lang: str = typer.Argument(..., help="Language code"),
    text: str = typer.Argument(..., help="Definition text"),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Set a definition on a concept."""
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    uri = _resolve(taxonomy, concept)
    _run(operations.set_definition, taxonomy, uri, lang, text)
    console.print(f"[green]Set definition[/green]  [{lang}]")
    _save(taxonomy, taxonomy_file)


# ──────────────────────────── relate ─────────────────────────────────────────

@app.command("relate")
def cmd_relate(
    concept_a: str = typer.Argument(..., metavar="HANDLE_A"),
    concept_b: str = typer.Argument(..., metavar="HANDLE_B"),
    remove: bool = typer.Option(False, "--remove", help="Remove instead of adding."),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Add or remove a skos:related link between two concepts."""
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    uri_a = _resolve(taxonomy, concept_a)
    uri_b = _resolve(taxonomy, concept_b)

    if remove:
        _run(operations.remove_related, taxonomy, uri_a, uri_b)
        console.print("[green]Removed[/green] related link.")
    else:
        _run(operations.add_related, taxonomy, uri_a, uri_b)
        console.print("[green]Added[/green] related link.")
    _save(taxonomy, taxonomy_file)


# ──────────────────────────── rename ─────────────────────────────────────────

@app.command("rename")
def cmd_rename(
    concept: str = typer.Argument(..., metavar="HANDLE|NAME", help="Handle or name of concept to rename."),
    new_name: str = typer.Argument(..., help="New local name or full URI."),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Change the URI of a concept (updates all cross-references).

    The new name is expanded to a full URI using the taxonomy's base URI.
    You can also pass a full URI directly.
    """
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    old_uri = _resolve(taxonomy, concept)
    new_uri = _run(operations.expand_uri, taxonomy, new_name)
    _run(operations.rename_uri, taxonomy, old_uri, new_uri)
    console.print(f"[green]Renamed[/green]  {old_uri}  →  {new_uri}")
    _save(taxonomy, taxonomy_file)


# ──────────────────────────── init (wizard) ──────────────────────────────────

@app.command("init")
def cmd_init(
    file: Optional[Path] = typer.Argument(
        None, help="Output file path (.ttl / .rdf / .jsonld). Prompted if omitted."
    ),
) -> None:
    """Create a new taxonomy via an interactive step-by-step wizard."""
    from . import wizard

    result = wizard.run(default_path=file)
    if result is None:
        raise typer.Exit(0)

    if result.file_path.exists():
        err.print(f"[red]File already exists: {result.file_path}[/red]  Remove it first or choose a different path.")
        raise typer.Exit(1)

    taxonomy = Taxonomy()
    _run(
        operations.create_scheme,
        taxonomy,
        result.base_uri + "scheme",
        result.titles,
        result.descriptions or None,
        result.creator,
        result.created,
        result.languages,
        result.base_uri,        # stored as void:uriSpace for URI auto-expansion
    )
    result.file_path.parent.mkdir(parents=True, exist_ok=True)
    _save(taxonomy, result.file_path)
    # Automatically select the new file for this session
    _save_session(result.file_path)
    console.print(
        f"\n[bold green]Taxonomy created![/bold green]  "
        f"Start adding concepts with:\n\n"
        f"  [cyan]ster add <name> --parent <handle> --en 'Label'[/cyan]\n"
        f"  [cyan]ster show[/cyan]"
    )


# ──────────────────────────── nav (interactive shell) ────────────────────────

@app.command("nav")
def cmd_nav(
    lang: str = typer.Option("en", "--lang", "-l", help="Display language."),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Start an interactive bash-like shell for navigating and editing the taxonomy.

    Inside the shell, use familiar commands:\n
      ls / ls -l    list concepts (arrow keys to navigate, Enter to open)\n
      cd HANDLE     navigate into a concept\n
      cd ..         go up   |   cd /  go to root\n
      pwd           show current breadcrumb path\n
      show          ASCII tree from current location\n
      info          full concept detail\n
      add / mv / rm / label / define   edit the taxonomy\n
      quit / exit   leave the shell\n
    """
    from .nav import TaxonomyShell

    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)

    console.print(
        f"\n[bold cyan]ster nav[/bold cyan]  [dim]{taxonomy_file.name}[/dim]  "
        f"[dim]{len(taxonomy.concepts)} concepts[/dim]\n"
        "[dim]Commands: ls  cd  pwd  show  info  add  mv  rm  label  define  quit[/dim]\n"
    )

    shell = TaxonomyShell(taxonomy, taxonomy_file, lang=lang)
    shell.cmdloop()


# ──────────────────────────── handles ────────────────────────────────────────

@app.command("handles")
def cmd_handles(
    lang: str = typer.Option("en", "--lang", "-l"),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Print the full handle → label → URI index."""
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    console.print(render_handle_list(taxonomy, lang))


# ──────────────────────────── validate ───────────────────────────────────────

@app.command("validate")
def cmd_validate(
    lang: str = typer.Option("en", "--lang", "-l"),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Taxonomy file."),
) -> None:
    """Check SKOS integrity: missing labels, orphans, duplicate prefLabels."""
    taxonomy_file = _resolve_file(file)
    taxonomy = _load(taxonomy_file)
    issues: list[str] = []

    for uri, concept in taxonomy.concepts.items():
        handle = taxonomy.uri_to_handle(uri) or "?"
        pref_langs = [lbl.lang for lbl in concept.labels if lbl.type == LabelType.PREF]
        if not pref_langs:
            issues.append(f"[{handle}] {uri}  — no prefLabel")
        dupes = {lg for lg in pref_langs if pref_langs.count(lg) > 1}
        for lg in dupes:
            issues.append(f"[{handle}]  duplicate prefLabel for lang '{lg}'")
        for ref in concept.narrower + concept.broader + concept.related:
            if ref not in taxonomy.concepts:
                issues.append(f"[{handle}]  broken reference → {ref}")

    # Orphan detection
    reachable: set[str] = set()
    for scheme in taxonomy.schemes.values():
        for tc in scheme.top_concepts:
            _collect_reachable(taxonomy, tc, reachable)
    orphans = [u for u in taxonomy.concepts if u not in reachable]
    for uri in orphans:
        handle = taxonomy.uri_to_handle(uri) or "?"
        issues.append(f"[{handle}] {uri}  — orphan (not reachable from any top concept)")

    if issues:
        console.print(f"[red]Found {len(issues)} issue(s):[/red]")
        for issue in issues:
            console.print(f"  • {issue}")
        raise typer.Exit(1)
    else:
        console.print(f"[green]✓ No issues found.[/green]  {len(taxonomy.concepts)} concepts validated.")


# ──────────────────────────── internal helpers ───────────────────────────────

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


if __name__ == "__main__":
    app()
