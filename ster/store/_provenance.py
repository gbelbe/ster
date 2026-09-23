"""Which file a statement in the session graph came from.

ster models one flat graph, not named graphs, so the merged graph cannot answer
this by itself. The loader already keeps the answer on the side while merging
read-only context files — which entities a context file defined, and which
extra statements it contributed — because saving needs it to keep each file's
statements in their own file. This reads those same tables.

Anything they do not claim belongs to the editable file, including a statement
both files make: the loader counts that as the editable file's own, and this
agrees with it rather than inventing a second rule.

Blank nodes are the one thing that cannot be looked up: merging mints fresh
ones, so a context file's ``[ ... ]`` never compares equal to the one in the
merged graph. Callers follow a blank node from the statement that owns it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rdflib import URIRef

from ..model import Taxonomy


@dataclass(frozen=True)
class Provenance:
    """The session's files, editable first, and a way to place a statement in one."""

    files: tuple[Path, ...]
    _main: Path | None
    _defined_by: dict[str, Path] = field(repr=False)
    _added_by: dict[tuple, Path] = field(repr=False)

    def file_of(self, triple: tuple) -> Path | None:
        """The file *triple* came from; the editable file unless a context file claims it."""
        subject = triple[0]
        if isinstance(subject, URIRef) and str(subject) in self._defined_by:
            return self._defined_by[str(subject)]
        return self._added_by.get(tuple(triple[:3]), self._main)


def _context_files(taxonomy: Taxonomy) -> list[Path]:
    """Context files in load order, then any the tables name that the list does
    not — a taxonomy built by hand rather than by ``load``."""
    ordered = dict.fromkeys(taxonomy.context_files)
    for table in (
        taxonomy.context_source.values(),
        taxonomy.context_statements,
        taxonomy.context_residue,
    ):
        ordered.update(dict.fromkeys(table))
    return list(ordered)


def provenance(taxonomy: Taxonomy) -> Provenance:
    """Where each of *taxonomy*'s statements came from."""
    main = taxonomy.file_path
    context = _context_files(taxonomy)
    order = {path: rank for rank, path in enumerate(context)}
    added: dict[tuple, Path] = {}
    # setdefault in load order: when two context files add the same statement,
    # the first one loaded keeps it — the same file its blocks appear under first.
    for table in (taxonomy.context_statements, taxonomy.context_residue):
        for path in sorted(table, key=order.__getitem__):
            for triple in table[path]:
                added.setdefault(tuple(triple[:3]), path)
    files = ([main] if main is not None else []) + [p for p in context if p != main]
    return Provenance(
        files=tuple(files),
        _main=main,
        _defined_by=dict(taxonomy.context_source),
        _added_by=added,
    )
