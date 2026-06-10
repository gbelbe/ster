"""Rich-based screen for managing cached external ontologies."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .ontology_imports import (
    _DEFAULT_CACHE_DIR,
    COMMON_ONTOLOGIES,
    add_namespace_to_taxonomy,
    fetch_ontology,
    namespace_url_from_uri,
    suggest_prefix,
)

console = Console()


def _cached_namespaces() -> list[tuple[str, Path, int]]:
    """Return list of (namespace_url_guess, path, triple_count) from cache."""
    if not _DEFAULT_CACHE_DIR.exists():
        return []
    import rdflib

    rows: list[tuple[str, Path, int]] = []
    for p in sorted(_DEFAULT_CACHE_DIR.glob("*.ttl")):
        try:
            g = rdflib.Graph()
            g.parse(str(p), format="turtle")
            # Derive namespace from first subject URI in graph
            ns_guess = ""
            for s in g.subjects():
                uri = str(s)
                if "://" in uri:
                    ns_guess = namespace_url_from_uri(uri)
                    break
            rows.append((ns_guess or p.stem, p, len(g)))
        except Exception:
            rows.append((p.stem, p, 0))
    return rows


def _print_cache_table(cached: list[tuple[str, Path, int]]) -> None:
    if not cached:
        console.print("[dim]  No ontologies cached yet.[/dim]")
        return
    t = Table(show_header=True, header_style="bold cyan")
    t.add_column("#", style="dim", width=3)
    t.add_column("Namespace", no_wrap=False)
    t.add_column("Triples", justify="right", width=8)
    t.add_column("Cache file", style="dim")
    for i, (ns, path, triples) in enumerate(cached, 1):
        t.add_row(str(i), ns, str(triples), path.name)
    console.print(t)


def run_ext_ontologies_screen(taxonomy=None) -> None:
    """Interactive Rich screen for browsing, adding, and refreshing cached ontologies.

    If *taxonomy* is supplied, newly added namespaces are registered in its
    ``namespace_bindings`` dict.  Pass ``None`` when opening from the main menu
    without a loaded taxonomy.
    """
    console.print()
    console.rule("[bold cyan]🔗  External Ontologies[/bold cyan]")
    console.print()

    while True:
        cached = _cached_namespaces()
        console.print("[bold]Cached ontologies:[/bold]")
        _print_cache_table(cached)
        console.print()
        console.print(
            "  [cyan]N[/cyan]  Add / fetch a new ontology\n"
            "  [cyan]R[/cyan]  Refresh (re-download) a cached ontology\n"
            "  [cyan]D[/cyan]  Delete a cached ontology\n"
            "  [cyan]Q[/cyan]  Back"
        )
        console.print()

        action = Prompt.ask(
            "Action",
            choices=["N", "n", "R", "r", "D", "d", "Q", "q"],
            default="Q",
            show_default=True,
            show_choices=False,
        ).upper()

        if action == "Q":
            break

        if action == "N":
            _action_add(taxonomy)

        elif action == "R":
            if not cached:
                console.print("[yellow]Nothing cached.[/yellow]")
                continue
            _action_refresh(cached)

        elif action == "D":
            if not cached:
                console.print("[yellow]Nothing cached.[/yellow]")
                continue
            _action_delete(cached)

    console.print()


def _action_add(taxonomy) -> None:
    """Prompt the user to pick or enter a namespace, then fetch it."""
    console.print()
    console.print("[bold]Well-known ontologies:[/bold]")
    t = Table(show_header=False)
    t.add_column("#", style="dim", width=3)
    t.add_column("Name")
    t.add_column("Prefix", style="cyan", width=8)
    t.add_column("Namespace", style="dim")
    for i, (ont_name, ont_prefix, ont_ns) in enumerate(COMMON_ONTOLOGIES, 1):
        t.add_row(str(i), ont_name, ont_prefix, ont_ns)
    console.print(t)
    console.print()
    raw = Prompt.ask(
        f"  Pick a number (1–{len(COMMON_ONTOLOGIES)}) or enter a namespace URL directly"
        " (empty = cancel)"
    ).strip()
    if not raw:
        return

    ns_url: str
    prefix: str
    if raw.isdigit():
        idx = int(raw) - 1
        if not (0 <= idx < len(COMMON_ONTOLOGIES)):
            console.print("[red]Invalid selection.[/red]")
            return
        _name, prefix, ns_url = COMMON_ONTOLOGIES[idx]
    else:
        ns_url = raw if raw.endswith(("/", "#")) else raw + "/"
        prefix = suggest_prefix(ns_url)
        custom_prefix = Prompt.ask("  Prefix", default=prefix).strip()
        prefix = custom_prefix or prefix

    console.print(f"\n[dim]Fetching[/dim] [cyan]{ns_url}[/cyan] …")
    g = fetch_ontology(ns_url)
    if len(g) == 0:
        console.print("[red]  Could not fetch or parse the ontology.[/red]")
    else:
        console.print(f"  [green]✓[/green] Cached {len(g)} triples.")
        if taxonomy is not None:
            add_namespace_to_taxonomy(ns_url, prefix, taxonomy)
            console.print(f"  [green]✓[/green] Registered [cyan]{prefix}:[/cyan] in taxonomy.")
    console.print()


def _action_refresh(cached: list[tuple[str, Path, int]]) -> None:
    """Re-download and overwrite a specific cached ontology."""
    console.print()
    raw = Prompt.ask(f"  Refresh which entry (1–{len(cached)}, empty = cancel)").strip()
    if not raw or not raw.isdigit():
        return
    idx = int(raw) - 1
    if not (0 <= idx < len(cached)):
        console.print("[red]Invalid selection.[/red]")
        return
    ns, path, _ = cached[idx]
    if path.exists():
        path.unlink()
        console.print(f"  [dim]Removed old cache for {ns}[/dim]")
    console.print(f"  Fetching [cyan]{ns}[/cyan] …")
    g = fetch_ontology(ns)
    if len(g) == 0:
        console.print("[red]  Could not refresh — keeping old cache if it existed.[/red]")
    else:
        console.print(f"  [green]✓[/green] Refreshed {len(g)} triples.")
    console.print()


def _action_delete(cached: list[tuple[str, Path, int]]) -> None:
    """Delete a cached ontology file from disk."""
    console.print()
    raw = Prompt.ask(f"  Delete which entry (1–{len(cached)}, empty = cancel)").strip()
    if not raw or not raw.isdigit():
        return
    idx = int(raw) - 1
    if not (0 <= idx < len(cached)):
        console.print("[red]Invalid selection.[/red]")
        return
    ns, path, _ = cached[idx]
    if Confirm.ask(f"  Delete cache for [cyan]{ns}[/cyan]?"):
        path.unlink(missing_ok=True)
        console.print("  [green]✓[/green] Deleted.")
    else:
        console.print("  [dim]Cancelled.[/dim]")
    console.print()
