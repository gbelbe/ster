"""Which RDF files ster offers when it starts in a folder.

One place for the folder search. It used to be written twice — once for the
home screen, once for the commands that need a file — and two copies of a
search are two answers waiting to disagree.

The top level is always searched. Subfolders are searched one level deep, and
only when asked: a project often keeps its vocabularies in folders of their
own, but anything deeper is more likely to be someone else's tree than part
of this project. Some folders are never searched at all: hidden ones (``.git``,
``.venv``, ``.ster``) and ``node_modules``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

RDF_SUFFIXES: Final = frozenset({".ttl", ".rdf", ".jsonld", ".owl", ".n3", ".trig", ".nt"})
_NEVER_SEARCHED: Final = frozenset({"node_modules", "__pycache__"})


def _rdf_files_in(folder: Path) -> list[Path]:
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    return [path for path in entries if path.is_file() and path.suffix.lower() in RDF_SUFFIXES]


def _searchable_subfolders(root: Path) -> list[Path]:
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    return sorted(
        path
        for path in entries
        if path.is_dir() and not path.name.startswith(".") and path.name not in _NEVER_SEARCHED
    )


def subfolder_rdf_files(root: Path) -> list[Path]:
    """The RDF files exactly one level below *root*, in folders ster searches."""
    return sorted(path for folder in _searchable_subfolders(root) for path in _rdf_files_in(folder))


def discover_rdf_files(root: Path, *, include_subfolders: bool = False) -> list[Path]:
    """*root*'s RDF files, then — when asked — those one level down; each list sorted."""
    top = sorted(_rdf_files_in(root))
    return top + subfolder_rdf_files(root) if include_subfolders else top


def shown(path: Path) -> str:
    """*path* as the user should read it: relative to where ster was started.

    A file in a subfolder shows as ``vocab/gear.ttl``, so two files with the
    same name in different folders can be told apart.
    """
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return path.name
