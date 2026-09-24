"""Where the graph's nodes were left, remembered in the project.

Positions used to live in the browser's localStorage. That is per origin, and
ster serves the graph on a new port each launch, so every restart began from a
fresh layout; it was also all-or-nothing, discarded the moment one node was
added. They now live in ``.ster/graph-layout.json`` beside ``project.json``,
committed with the project, keyed by view and then by node URI.

Every write keeps the file true to the model:

- A save **merges** the positions it carries into what is stored, so two tabs,
  or a save covering only the nodes on screen, never erase each other.
- A URI no longer in the model (the entity was deleted) is dropped. A node that
  is merely hidden — collapsed individuals — is still in the model, and keeps
  its position for when it comes back.
- A rename moves the entry to the new URI (:func:`rename_nodes`).

The file is written one node per line, sorted, in whole numbers, so a diff
shows the nodes that moved and a merge conflict is a single readable line.
Anything unreadable is treated as no layout, and the next save rewrites it.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Final

from .model import Taxonomy
from .project import _git_root

ONTOLOGY_VIEW: Final = "ontology"
_FILE_NAME: Final = "graph-layout.json"

Positions = dict[str, tuple[int, int]]


def layout_path(source: Path) -> Path:
    """The layout file for the project *source* belongs to."""
    folder = source.resolve().parent
    root = _git_root(folder) or folder
    return root / ".ster" / _FILE_NAME


def model_uris(taxonomy: Taxonomy) -> set[str]:
    """Every entity a node can stand for; a position for anything else is stale."""
    return {
        *taxonomy.concepts,
        *taxonomy.schemes,
        *taxonomy.owl_classes,
        *taxonomy.owl_properties,
        *taxonomy.owl_individuals,
    }


def _as_point(value: object) -> tuple[int, int] | None:
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(n, int | float) and not isinstance(n, bool) for n in value)
    ):
        return round(value[0]), round(value[1])
    return None


def _read(path: Path) -> dict[str, Positions]:
    """The stored views; a missing or unreadable file reads as none."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    views: dict[str, Positions] = {}
    for view, nodes in raw.items():
        if isinstance(nodes, dict):
            points = {uri: _as_point(xy) for uri, xy in nodes.items()}
            views[view] = {uri: xy for uri, xy in points.items() if xy is not None}
    return views


def _write(path: Path, views: dict[str, Positions]) -> None:
    """One node per line, sorted, whole numbers — see the module docstring."""
    blocks = []
    for view in sorted(views):
        rows = ",\n".join(
            f"    {json.dumps(uri)}: [{x}, {y}]" for uri, (x, y) in sorted(views[view].items())
        )
        blocks.append(
            f"  {json.dumps(view)}: {{\n{rows}\n  }}" if rows else f"  {json.dumps(view)}: {{}}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{\n" + ",\n".join(blocks) + "\n}\n", encoding="utf-8")


def load_positions(source: Path, view: str, taxonomy: Taxonomy) -> Positions:
    """The remembered positions for *view*, for nodes still in *taxonomy*."""
    existing = model_uris(taxonomy)
    stored = _read(layout_path(source)).get(view, {})
    return {uri: xy for uri, xy in stored.items() if uri in existing}


def save_positions(
    source: Path, view: str, positions: dict[str, tuple[float, float]], taxonomy: Taxonomy
) -> None:
    """Merge *positions* into *view*, dropping nodes *taxonomy* no longer has."""
    path = layout_path(source)
    views = _read(path)
    merged = {
        **views.get(view, {}),
        **{uri: (round(x), round(y)) for uri, (x, y) in positions.items()},
    }
    existing = model_uris(taxonomy)
    views[view] = {uri: xy for uri, xy in merged.items() if uri in existing}
    _write(path, views)


def forget_positions(source: Path, view: str) -> None:
    """Drop everything remembered for *view* (the "Reset layout" button)."""
    path = layout_path(source)
    views = _read(path)
    if view in views:
        del views[view]
        _write(path, views)


def rename_nodes(source: Path, renamed: dict[str, str]) -> None:
    """Carry positions over to renamed URIs, in every view. No file, no change.

    Shaped as a TaxonomyService rename listener. It never raises for the disk:
    a rename must not fail because a layout file could not be written.
    """
    path = layout_path(source)
    if not renamed or not path.exists():
        return
    views = _read(path)
    for view, nodes in views.items():
        views[view] = {renamed.get(uri, uri): xy for uri, xy in nodes.items()}
    with contextlib.suppress(OSError):
        _write(path, views)
