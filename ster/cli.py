"""Typer CLI — load, operate, save pattern for every mutating command."""
from __future__ import annotations
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm

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
    file: Path = typer.Argument(..., help="Taxonomy file (.ttl / .rdf / .jsonld)"),
    concept: Optional[str] = typer.Option(
        None, "--concept", "-c", metavar="HANDLE",
        help="Show subtree rooted at this concept."
    ),
    detail: bool = typer.Option(False, "--detail", "-d", help="Show full concept detail."),
    lang: str = typer.Option("en", "--lang", "-l", help="Label language."),
    handles: bool = typer.Option(False, "--handles", "-H", help="Print handle index table."),
) -> None:
    """Display the taxonomy tree (or a subtree)."""
    taxonomy = _load(file)

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
    file: Path = typer.Argument(..., help="Taxonomy file"),
    name: str = typer.Argument(
        ...,
        help="Local name or full URI for the new concept. "
             "A local name (e.g. 'SpadeRudder') is automatically expanded "
             "with the taxonomy's base URI.",
    ),
    parent: Optional[str] = typer.Option(
        None, "--parent", "-p", metavar="HANDLE|NAME",
        help="Parent concept handle or name (omit for primary scheme top level)."
    ),
    en: Optional[str] = typer.Option(None, "--en", help="English preferred label."),
    fr: Optional[str] = typer.Option(None, "--fr", help="French preferred label."),
    def_en: Optional[str] = typer.Option(None, "--def-en", help="English definition."),
    def_fr: Optional[str] = typer.Option(None, "--def-fr", help="French definition."),
    lang: str = typer.Option("en", "--lang", "-l", help="Display language for confirmation."),
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
        err.print("[red]Provide at least one label: --en or --fr[/red]")
        raise typer.Exit(1)

    definitions: dict[str, str] = {}
    if def_en:
        definitions["en"] = def_en
    if def_fr:
        definitions["fr"] = def_fr

    taxonomy = _load(file)
    uri = _run(operations.expand_uri, taxonomy, name)
    concept = _run(operations.add_concept, taxonomy, uri, labels, parent, definitions or None)
    console.print(f"[green]Added[/green]  [{taxonomy.uri_to_handle(uri)}]  {concept.pref_label(lang)}  [dim]({uri})[/dim]")
    _save(taxonomy, file)


# ──────────────────────────── remove ─────────────────────────────────────────

@app.command("remove")
def cmd_remove(
    file: Path = typer.Argument(..., help="Taxonomy file"),
    concept: str = typer.Argument(..., metavar="HANDLE", help="Concept handle or URI."),
    cascade: bool = typer.Option(False, "--cascade", help="Also remove all descendants."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    lang: str = typer.Option("en", "--lang", "-l"),
) -> None:
    """Remove a concept from the taxonomy."""
    taxonomy = _load(file)
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
    _save(taxonomy, file)


# ──────────────────────────── move ───────────────────────────────────────────

@app.command("move")
def cmd_move(
    file: Path = typer.Argument(..., help="Taxonomy file"),
    concept: str = typer.Argument(..., metavar="HANDLE", help="Concept to move."),
    parent: Optional[str] = typer.Option(
        None, "--parent", "-p", metavar="HANDLE",
        help="New parent handle (omit to promote to top level)."
    ),
    lang: str = typer.Option("en", "--lang", "-l"),
) -> None:
    """Move a concept to a new parent."""
    taxonomy = _load(file)
    uri = _resolve(taxonomy, concept)
    parent_uri = _resolve(taxonomy, parent) if parent else None

    _run(operations.move_concept, taxonomy, uri, parent_uri)

    dest = taxonomy.concepts[parent_uri].pref_label(lang) if parent_uri and parent_uri in taxonomy.concepts else "top level"
    console.print(f"[green]Moved[/green]  {taxonomy.concepts[uri].pref_label(lang)}  →  {dest}")
    _save(taxonomy, file)


# ──────────────────────────── label ──────────────────────────────────────────

@app.command("label")
def cmd_label(
    file: Path = typer.Argument(..., help="Taxonomy file"),
    concept: str = typer.Argument(..., metavar="HANDLE"),
    lang: str = typer.Argument(..., help="Language code (en, fr, …)"),
    text: str = typer.Argument(..., help="Label text"),
    alt: bool = typer.Option(False, "--alt", help="Add as alt label (default: pref label)."),
) -> None:
    """Set a preferred or alternative label on a concept."""
    taxonomy = _load(file)
    uri = _resolve(taxonomy, concept)
    label_type = LabelType.ALT if alt else LabelType.PREF
    _run(operations.set_label, taxonomy, uri, lang, text, label_type)
    kind = "alt label" if alt else "pref label"
    console.print(f"[green]Set {kind}[/green]  [{lang}]  {text}")
    _save(taxonomy, file)


# ──────────────────────────── define ─────────────────────────────────────────

@app.command("define")
def cmd_define(
    file: Path = typer.Argument(..., help="Taxonomy file"),
    concept: str = typer.Argument(..., metavar="HANDLE"),
    lang: str = typer.Argument(..., help="Language code"),
    text: str = typer.Argument(..., help="Definition text"),
) -> None:
    """Set a definition on a concept."""
    taxonomy = _load(file)
    uri = _resolve(taxonomy, concept)
    _run(operations.set_definition, taxonomy, uri, lang, text)
    console.print(f"[green]Set definition[/green]  [{lang}]")
    _save(taxonomy, file)


# ──────────────────────────── relate ─────────────────────────────────────────

@app.command("relate")
def cmd_relate(
    file: Path = typer.Argument(..., help="Taxonomy file"),
    concept_a: str = typer.Argument(..., metavar="HANDLE_A"),
    concept_b: str = typer.Argument(..., metavar="HANDLE_B"),
    remove: bool = typer.Option(False, "--remove", help="Remove instead of adding."),
) -> None:
    """Add or remove a skos:related link between two concepts."""
    taxonomy = _load(file)
    uri_a = _resolve(taxonomy, concept_a)
    uri_b = _resolve(taxonomy, concept_b)

    if remove:
        _run(operations.remove_related, taxonomy, uri_a, uri_b)
        console.print("[green]Removed[/green] related link.")
    else:
        _run(operations.add_related, taxonomy, uri_a, uri_b)
        console.print("[green]Added[/green] related link.")
    _save(taxonomy, file)


# ──────────────────────────── rename ─────────────────────────────────────────

@app.command("rename")
def cmd_rename(
    file: Path = typer.Argument(..., help="Taxonomy file"),
    concept: str = typer.Argument(..., metavar="HANDLE|NAME", help="Handle or name of concept to rename."),
    new_name: str = typer.Argument(..., help="New local name or full URI."),
) -> None:
    """Change the URI of a concept (updates all cross-references).

    The new name is expanded to a full URI using the taxonomy's base URI.
    You can also pass a full URI directly.
    """
    taxonomy = _load(file)
    old_uri = _resolve(taxonomy, concept)
    new_uri = _run(operations.expand_uri, taxonomy, new_name)
    _run(operations.rename_uri, taxonomy, old_uri, new_uri)
    console.print(f"[green]Renamed[/green]  {old_uri}  →  {new_uri}")
    _save(taxonomy, file)


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
    console.print(
        f"\n[bold green]Taxonomy created![/bold green]  "
        f"Start adding concepts with:\n\n"
        f"  [cyan]ster add {result.file_path} <uri> --parent <handle> --en 'Label'[/cyan]\n"
        f"  [cyan]ster show {result.file_path}[/cyan]"
    )


# ──────────────────────────── handles ────────────────────────────────────────

@app.command("handles")
def cmd_handles(
    file: Path = typer.Argument(..., help="Taxonomy file"),
    lang: str = typer.Option("en", "--lang", "-l"),
) -> None:
    """Print the full handle → label → URI index."""
    taxonomy = _load(file)
    console.print(render_handle_list(taxonomy, lang))


# ──────────────────────────── validate ───────────────────────────────────────

@app.command("validate")
def cmd_validate(
    file: Path = typer.Argument(..., help="Taxonomy file"),
    lang: str = typer.Option("en", "--lang", "-l"),
) -> None:
    """Check SKOS integrity: missing labels, orphans, duplicate prefLabels."""
    taxonomy = _load(file)
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
