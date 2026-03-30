"""Rich-based display layer — returns renderables, no direct console.print calls."""

from __future__ import annotations

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .model import LabelType, Taxonomy

# ──────────────────────────── tree rendering ─────────────────────────────────


def render_tree(
    taxonomy: Taxonomy,
    root_handle: str | None = None,
    lang: str = "en",
) -> Tree | Panel:
    """Render the taxonomy as a rich Tree.

    If root_handle is given, renders the subtree rooted at that concept.
    Otherwise renders the full taxonomy from all top concepts.
    """
    if root_handle:
        root_uri = taxonomy.resolve(root_handle)
        if root_uri is None:
            return Panel(f"[red]Handle not found: {root_handle!r}[/red]")
        concept = taxonomy.concepts.get(root_uri)
        if concept is None:
            return Panel(f"[red]Not a concept: {root_uri!r}[/red]")
        handle = taxonomy.uri_to_handle(root_uri) or "?"
        node_label = _concept_text(handle, concept.pref_label(lang))
        root = Tree(node_label)
        _add_children(root, taxonomy, root_uri, lang, visited={root_uri})
        return root

    # Full tree
    scheme = taxonomy.primary_scheme()
    scheme_title = scheme.title(lang) if scheme else "Taxonomy"
    root = Tree(Text(scheme_title, style="bold cyan"))
    visited: set[str] = set()
    top_concepts = scheme.top_concepts if scheme else []
    for tc_uri in top_concepts:
        _add_node(root, taxonomy, tc_uri, lang, visited)
    # Orphan concepts
    orphans = [u for u in taxonomy.concepts if u not in visited]
    if orphans:
        orphan_node = root.add(Text("(orphans)", style="dim"))
        for uri in orphans:
            _add_node(orphan_node, taxonomy, uri, lang, visited)
    return root


def _add_node(
    parent: Tree,
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    visited: set[str],
) -> None:
    if uri in visited:
        parent.add(Text(f"↺ {uri}", style="dim red"))
        return
    concept = taxonomy.concepts.get(uri)
    if concept is None:
        parent.add(Text(f"[missing: {uri}]", style="dim yellow"))
        return
    handle = taxonomy.uri_to_handle(uri) or "?"
    label = _concept_text(handle, concept.pref_label(lang))
    node = parent.add(label)
    visited.add(uri)
    _add_children(node, taxonomy, uri, lang, visited)


def _add_children(
    node: Tree,
    taxonomy: Taxonomy,
    uri: str,
    lang: str,
    visited: set[str],
) -> None:
    concept = taxonomy.concepts.get(uri)
    if concept:
        for child_uri in concept.narrower:
            _add_node(node, taxonomy, child_uri, lang, visited)


def _concept_text(handle: str, label: str) -> Text:
    t = Text()
    t.append(f"[{handle}]", style="bold yellow")
    t.append("  ")
    t.append(label)
    return t


# ──────────────────────────── concept detail ─────────────────────────────────


def render_concept_detail(taxonomy: Taxonomy, uri: str, lang: str = "en") -> Panel:
    """Render a detailed panel for a single concept."""
    concept = taxonomy.concepts.get(uri)
    if concept is None:
        return Panel(f"[red]Concept not found: {uri!r}[/red]")

    handle = taxonomy.uri_to_handle(uri) or "?"
    title = f"[bold cyan][{handle}] {concept.pref_label(lang)}[/bold cyan]"
    lines: list[str] = []

    lines.append(f"[dim]URI:[/dim]  {uri}")

    # Labels grouped by type
    pref = [(lbl.lang, lbl.value) for lbl in concept.labels if lbl.type == LabelType.PREF]
    alt = [(lbl.lang, lbl.value) for lbl in concept.labels if lbl.type == LabelType.ALT]
    if pref:
        lines.append("\n[bold]Preferred labels[/bold]")
        for lg, val in sorted(pref):
            lines.append(f"  [{lg}]  {val}")
    if alt:
        lines.append("\n[bold]Alt labels[/bold]")
        for lg, val in sorted(alt):
            lines.append(f"  [{lg}]  {val}")

    # Definitions
    if concept.definitions:
        lines.append("\n[bold]Definitions[/bold]")
        for defn in sorted(concept.definitions, key=lambda d: d.lang):
            lines.append(f"  [{defn.lang}]  {defn.value}")

    # Hierarchy
    def _fmt(u: str) -> str:
        c = taxonomy.concepts.get(u)
        h = taxonomy.uri_to_handle(u) or "?"
        lbl = c.pref_label(lang) if c else u
        return f"  [{h}]  {lbl}"

    if concept.broader:
        lines.append("\n[bold]Broader[/bold]")
        for u in concept.broader:
            lines.append(_fmt(u))
    if concept.narrower:
        lines.append("\n[bold]Narrower[/bold]")
        for u in concept.narrower:
            lines.append(_fmt(u))
    if concept.related:
        lines.append("\n[bold]Related[/bold]")
        for u in concept.related:
            lines.append(_fmt(u))

    return Panel("\n".join(lines), title=title, border_style="cyan")


# ──────────────────────────── handle list ────────────────────────────────────


def render_handle_list(taxonomy: Taxonomy, lang: str = "en") -> Table:
    """Render a table of all handles with their labels and URIs."""
    table = Table(title="Handle index", box=box.SIMPLE_HEAD)
    table.add_column("Handle", style="bold yellow", no_wrap=True)
    table.add_column("Label", style="white")
    table.add_column("URI", style="dim")

    for handle in sorted(taxonomy.handle_index):
        uri = taxonomy.handle_index[handle]
        if uri in taxonomy.concepts:
            label = taxonomy.concepts[uri].pref_label(lang)
        elif uri in taxonomy.schemes:
            label = taxonomy.schemes[uri].title(lang)
        else:
            label = ""
        table.add_row(handle, label, uri)

    return table


# ──────────────────────────── console singleton ──────────────────────────────

console = Console()
