"""The show/add/remove/move/subclass/label/define/relate/rename/handles/validate/convert commands."""

from __future__ import annotations

from pathlib import Path
from typing import Final

import typer
from rich.prompt import Confirm

from .. import operations, store
from ..display import console, render_handle_list, render_tree
from ..model import LabelType, Taxonomy

_LIT_FILE: Final = "--file"
_LIT_LANG: Final = "--lang"
_LIT_PARENT: Final = "--parent"
_LIT_HANDLE: Final = "HANDLE"


from . import _app, _export, _file_picker, _taxonomy_io, _viewer

# ──────────────────────────── show ───────────────────────────────────────────


@_app.app.command("show")
def cmd_show(
    file: Path | None = typer.Argument(
        None, help="Taxonomy file (.ttl / .rdf / .jsonld / .trig). Auto-detected if omitted."
    ),
    concept: str | None = typer.Option(
        None,
        "--concept",
        "-c",
        metavar=_LIT_HANDLE,
        help="With --plain, root the printed tree at this concept.",
    ),
    lang: str = typer.Option("en", _LIT_LANG, "-l", help="Label language."),
    handles: bool = typer.Option(
        False, "--handles", "-H", help="Print handle index table then exit."
    ),
    plain: bool = typer.Option(
        False,
        "--plain",
        "-p",
        help="Print static tree and exit (no interactive viewer).",
    ),
    context_files: list[Path] | None = typer.Option(
        None,
        "--context-files",
        "-x",
        help="Load these files read-only alongside FILE (repeatable). "
        "Their entities are visible but locked, and saving never writes to them.",
    ),
) -> None:
    """Open the interactive taxonomy browser (the Textual New-TUI) and commit on exit.

    A mouse- and keyboard-driven tree of classes / individuals / properties with a
    fuzzy search palette (press ``/``) and a live detail panel. Fully editable:
    create / rename / re-link / delete classes, individuals, properties, concepts
    and schemes — every change is validated and saved. Arrow keys move between the
    tree and the detail rows; Enter edits (or runs) the focused row; ``s`` opens the
    SPARQL query screen. On quit, the git commit/push flow runs.

    Pass --plain to print the tree non-interactively and exit.
    """
    taxonomy_file = _file_picker._resolve_file(file)
    taxonomy = _taxonomy_io._load(taxonomy_file)

    if handles:
        console.print(render_handle_list(taxonomy, lang))
        return

    if plain:
        if concept:
            console.print(render_tree(taxonomy, root_handle=concept, lang=lang))
        else:
            console.print(render_tree(taxonomy, lang=lang))
        return

    # No prompt on this path: `ster show file.ttl` names what it wants, so the
    # context is whatever --context-files gave and nothing else.
    _viewer._open_viewer(taxonomy_file, lang=lang, context=list(context_files or []))


# ──────────────────────────── add ────────────────────────────────────────────


@_app.app.command("add")
def cmd_add(
    name: str = typer.Argument(
        ...,
        help="Local name or full URI for the new concept. "
        "A local name (e.g. 'SpadeRudder') is automatically expanded "
        "with the taxonomy's base URI.",
    ),
    parent: str | None = typer.Option(
        None,
        _LIT_PARENT,
        "-p",
        metavar="HANDLE|NAME",
        help="Parent concept handle or name (omit for primary scheme top level).",
    ),
    en: str | None = typer.Option(None, "--en", help="English preferred label."),
    fr: str | None = typer.Option(None, "--fr", help="French preferred label."),
    def_en: str | None = typer.Option(None, "--def-en", help="English definition."),
    def_fr: str | None = typer.Option(None, "--def-fr", help="French definition."),
    lang: str = typer.Option("en", _LIT_LANG, "-l", help="Display language for confirmation."),
    file: Path | None = typer.Option(None, _LIT_FILE, "-f", help=_app._TAXONOMY_FILE_HELP),
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
        labels[lang] = _export._humanize(name)
        console.print(f"[dim]No label provided — using default: {labels[lang]!r}[/dim]")

    definitions: dict[str, str] = {}
    if def_en:
        definitions["en"] = def_en
    if def_fr:
        definitions["fr"] = def_fr

    taxonomy_file = _file_picker._resolve_file(file)
    taxonomy = _taxonomy_io._load(taxonomy_file)
    uri = _taxonomy_io._run(operations.expand_uri, taxonomy, name)
    concept = _taxonomy_io._run(
        operations.add_concept, taxonomy, uri, labels, parent, definitions or None
    )
    console.print(
        f"[green]Added[/green]  [{taxonomy.uri_to_handle(uri)}]  {concept.pref_label(lang)}  [dim]({uri})[/dim]"
    )
    _taxonomy_io._save(taxonomy, taxonomy_file)


# ──────────────────────────── remove ─────────────────────────────────────────


@_app.app.command("remove")
def cmd_remove(
    concept: str = typer.Argument(..., metavar=_LIT_HANDLE, help="Concept handle or URI."),
    cascade: bool = typer.Option(False, "--cascade", help="Also remove all descendants."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    lang: str = typer.Option("en", _LIT_LANG, "-l"),
    file: Path | None = typer.Option(None, _LIT_FILE, "-f", help=_app._TAXONOMY_FILE_HELP),
) -> None:
    """Remove a concept from the taxonomy."""
    taxonomy_file = _file_picker._resolve_file(file)
    taxonomy = _taxonomy_io._load(taxonomy_file)
    uri = _taxonomy_io._resolve(taxonomy, concept)
    c = taxonomy.concepts[uri]

    if not yes:
        msg = f"Remove [bold]{c.pref_label(lang)}[/bold]"
        n_children = len(c.narrower)
        if cascade and n_children:
            msg += f" and its {n_children} child(ren)"
        if not Confirm.ask(msg + "?"):
            raise typer.Abort()

    removed = _taxonomy_io._run(operations.remove_concept, taxonomy, uri, cascade=cascade)
    console.print(f"[green]Removed[/green] {len(removed)} concept(s).")
    _taxonomy_io._save(taxonomy, taxonomy_file)


# ──────────────────────────── move ───────────────────────────────────────────


@_app.app.command("move")
def cmd_move(
    concept: str = typer.Argument(..., metavar=_LIT_HANDLE, help="Concept to move."),
    parent: str | None = typer.Option(
        None,
        _LIT_PARENT,
        "-p",
        metavar=_LIT_HANDLE,
        help="New parent handle (omit to promote to top level).",
    ),
    lang: str = typer.Option("en", _LIT_LANG, "-l"),
    file: Path | None = typer.Option(None, _LIT_FILE, "-f", help=_app._TAXONOMY_FILE_HELP),
) -> None:
    """Move a concept to a new parent."""
    taxonomy_file = _file_picker._resolve_file(file)
    taxonomy = _taxonomy_io._load(taxonomy_file)
    uri = _taxonomy_io._resolve(taxonomy, concept)
    parent_uri = _taxonomy_io._resolve(taxonomy, parent) if parent else None

    _taxonomy_io._run(operations.move_concept, taxonomy, uri, parent_uri)

    dest = (
        taxonomy.concepts[parent_uri].pref_label(lang)
        if parent_uri and parent_uri in taxonomy.concepts
        else "top level"
    )
    console.print(f"[green]Moved[/green]  {taxonomy.concepts[uri].pref_label(lang)}  →  {dest}")
    _taxonomy_io._save(taxonomy, taxonomy_file)


# ──────────────────────────── subclass ───────────────────────────────────────


@_app.app.command("subclass")
def cmd_subclass(
    child: str = typer.Argument(..., help="Class to make a subclass (handle or URI)."),
    parent: str = typer.Option(..., _LIT_PARENT, "-p", help="Parent class (handle or URI)."),
    file: Path | None = typer.Option(None, _LIT_FILE, "-f", help="Taxonomy file (.ttl)."),
) -> None:
    """Add a rdfs:subClassOf link from a class to a parent class.

    Examples:\n
      ster subclass Dog --parent Animal\n
      ster subclass PER --parent ORG\n
    """
    taxonomy_file = _file_picker._resolve_file(file)
    taxonomy = _taxonomy_io._load(taxonomy_file)
    child_uri = _taxonomy_io._resolve(taxonomy, child)
    parent_uri = _taxonomy_io._resolve(taxonomy, parent)
    _taxonomy_io._run(operations.add_subclass_of, taxonomy, child_uri, parent_uri)
    child_cls = taxonomy.owl_classes.get(child_uri)
    parent_cls = taxonomy.owl_classes.get(parent_uri)
    child_label = child_cls.label("en") if child_cls else child_uri
    parent_label = parent_cls.label("en") if parent_cls else parent_uri
    console.print(f"[green]Added[/green] {child_label} subClassOf {parent_label}")
    _taxonomy_io._save(taxonomy, taxonomy_file)


# ──────────────────────────── label ──────────────────────────────────────────


@_app.app.command("label")
def cmd_label(
    concept: str = typer.Argument(..., metavar=_LIT_HANDLE),
    lang: str = typer.Argument(..., help="Language code (en, fr, …)"),
    text: str = typer.Argument(..., help="Label text"),
    alt: bool = typer.Option(False, "--alt", help="Add as alt label (default: pref label)."),
    file: Path | None = typer.Option(None, _LIT_FILE, "-f", help=_app._TAXONOMY_FILE_HELP),
) -> None:
    """Set a preferred or alternative label on a concept."""
    taxonomy_file = _file_picker._resolve_file(file)
    taxonomy = _taxonomy_io._load(taxonomy_file)
    uri = _taxonomy_io._resolve(taxonomy, concept)
    label_type = LabelType.ALT if alt else LabelType.PREF
    _taxonomy_io._run(operations.set_label, taxonomy, uri, lang, text, label_type)
    kind = "alt label" if alt else "pref label"
    console.print(f"[green]Set {kind}[/green]  [{lang}]  {text}")
    _taxonomy_io._save(taxonomy, taxonomy_file)


# ──────────────────────────── define ─────────────────────────────────────────


@_app.app.command("define")
def cmd_define(
    concept: str = typer.Argument(..., metavar=_LIT_HANDLE),
    lang: str = typer.Argument(..., help="Language code"),
    text: str = typer.Argument(..., help="Definition text"),
    file: Path | None = typer.Option(None, _LIT_FILE, "-f", help=_app._TAXONOMY_FILE_HELP),
) -> None:
    """Set a definition on a concept."""
    taxonomy_file = _file_picker._resolve_file(file)
    taxonomy = _taxonomy_io._load(taxonomy_file)
    uri = _taxonomy_io._resolve(taxonomy, concept)
    _taxonomy_io._run(operations.set_definition, taxonomy, uri, lang, text)
    console.print(f"[green]Set definition[/green]  [{lang}]")
    _taxonomy_io._save(taxonomy, taxonomy_file)


# ──────────────────────────── relate ─────────────────────────────────────────


@_app.app.command("relate")
def cmd_relate(
    concept_a: str = typer.Argument(..., metavar="HANDLE_A"),
    concept_b: str = typer.Argument(..., metavar="HANDLE_B"),
    remove: bool = typer.Option(False, "--remove", help="Remove instead of adding."),
    file: Path | None = typer.Option(None, _LIT_FILE, "-f", help=_app._TAXONOMY_FILE_HELP),
) -> None:
    """Add or remove a skos:related link between two concepts."""
    taxonomy_file = _file_picker._resolve_file(file)
    taxonomy = _taxonomy_io._load(taxonomy_file)
    uri_a = _taxonomy_io._resolve(taxonomy, concept_a)
    uri_b = _taxonomy_io._resolve(taxonomy, concept_b)

    if remove:
        _taxonomy_io._run(operations.remove_related, taxonomy, uri_a, uri_b)
        console.print("[green]Removed[/green] related link.")
    else:
        _taxonomy_io._run(operations.add_related, taxonomy, uri_a, uri_b)
        console.print("[green]Added[/green] related link.")
    _taxonomy_io._save(taxonomy, taxonomy_file)


# ──────────────────────────── rename ─────────────────────────────────────────


@_app.app.command("rename")
def cmd_rename(
    concept: str = typer.Argument(
        ..., metavar="HANDLE|NAME", help="Handle or name of concept to rename."
    ),
    new_name: str = typer.Argument(..., help="New local name or full URI."),
    file: Path | None = typer.Option(None, _LIT_FILE, "-f", help=_app._TAXONOMY_FILE_HELP),
) -> None:
    """Change the URI of a concept (updates all cross-references).

    The new name is expanded to a full URI using the taxonomy's base URI.
    You can also pass a full URI directly.
    """
    taxonomy_file = _file_picker._resolve_file(file)
    taxonomy = _taxonomy_io._load(taxonomy_file)
    old_uri = _taxonomy_io._resolve(taxonomy, concept)
    new_uri = _taxonomy_io._run(operations.expand_uri, taxonomy, new_name)
    _taxonomy_io._run(operations.rename_uri, taxonomy, old_uri, new_uri)
    console.print(f"[green]Renamed[/green]  {old_uri}  →  {new_uri}")
    _taxonomy_io._save(taxonomy, taxonomy_file)


# ──────────────────────────── handles ────────────────────────────────────────


@_app.app.command("handles")
def cmd_handles(
    path: Path | None = typer.Argument(None, help=_app._TAXONOMY_FILE_HELP),
    lang: str = typer.Option("en", _LIT_LANG, "-l"),
    file: Path | None = typer.Option(None, _LIT_FILE, "-f", help=_app._TAXONOMY_FILE_HELP),
) -> None:
    """Print the full handle → label → URI index."""
    taxonomy_file = _file_picker._resolve_file(_file_picker._one_file(path, file))
    taxonomy = _taxonomy_io._load(taxonomy_file)
    console.print(render_handle_list(taxonomy, lang))


# ──────────────────────────── validate ───────────────────────────────────────


@_app.app.command("validate")
def cmd_validate(
    path: Path | None = typer.Argument(None, help=_app._TAXONOMY_FILE_HELP),
    lang: str = typer.Option("en", _LIT_LANG, "-l"),
    file: Path | None = typer.Option(None, _LIT_FILE, "-f", help=_app._TAXONOMY_FILE_HELP),
) -> None:
    """Check SKOS integrity: missing labels, orphans, duplicate prefLabels."""
    taxonomy_file = _file_picker._resolve_file(_file_picker._one_file(path, file))
    taxonomy = _taxonomy_io._load(taxonomy_file)
    issues: list[str] = _validate_concept_issues(taxonomy) + _validate_orphan_issues(taxonomy)

    if issues:
        console.print(f"[red]Found {len(issues)} issue(s):[/red]")
        for issue in issues:
            console.print(f"  • {issue}")
        raise typer.Exit(1)
    else:
        console.print(
            f"[green]✓ No issues found.[/green]  {len(taxonomy.concepts)} concepts validated."
        )


def _validate_concept_issues(taxonomy: Taxonomy) -> list[str]:
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
    return issues


def _validate_orphan_issues(taxonomy: Taxonomy) -> list[str]:
    reachable: set[str] = set()
    for scheme in taxonomy.schemes.values():
        for tc in scheme.top_concepts:
            _export._collect_reachable(taxonomy, tc, reachable)
    orphans = [u for u in taxonomy.concepts if u not in reachable]
    issues: list[str] = []
    for uri in orphans:
        handle = taxonomy.uri_to_handle(uri) or "?"
        issues.append(f"[{handle}] {uri}  — orphan (not reachable from any top concept)")
    return issues


# ──────────────────────────── convert ────────────────────────────────────────


@_app.app.command("convert")
def cmd_convert(
    input_file: Path = typer.Argument(..., help="Input RDF file (any supported format)."),
    output: Path | None = typer.Argument(
        None,
        help="Output file path. Format detected from extension. Defaults to input stem + .ttl.",
    ),
) -> None:
    """Convert an RDF file to a different serialisation format.

    Input format is inferred from the file extension (.rdf, .owl, .xml, .ttl, .jsonld, .n3, .nt).
    Output defaults to Turtle (.ttl).

    Examples:\n
      ster convert onto.rdf                # → onto.ttl\n
      ster convert onto.owl                # → onto.ttl\n
      ster convert onto.ttl onto.nt        # → onto.nt (N-Triples)\n
      ster convert onto.ttl onto.rdf       # → onto.rdf (RDF/XML)\n
    """
    try:
        if output is not None:
            out = store.convert(input_file, output)
        else:
            out = store.convert_to_ttl(input_file)
        console.print(f"[green]✓[/green] {input_file.name} → {out.name}")
    except ValueError as exc:
        _app.err.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    except Exception as exc:
        _app.err.print(f"[red]Cannot convert {input_file}: {exc}[/red]")
        raise typer.Exit(1)
