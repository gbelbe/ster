"""One entity's own RDF, serialised as Turtle — what the source pane reads from.

The pane answers "what does this thing actually look like in the file", so the
unit is the entity, not the document: a tree selection names one subject, and
what comes back has to fit a pane beside the tree.

**What counts as the entity's source.** Its own triples, plus the blank nodes it
owns — a blank node is not addressable on its own, so cutting the closure there
would print ``[ ]`` and lose everything inside it. Then, separately, the triples
that point *at* it. That second half is what makes the pane worth opening on a
graph rather than a file: ``ant:depot`` says nothing about belonging to a
dossier, because that fact is written on the dossier. But it is also the
unbounded half — a hub entity can be the object of thousands of triples — so it
is capped, and the cap is counted rather than trailing off.

**One block per file.** A session can merge read-only context files into the
editable one, and the merged graph no longer says which file said what. Given a
:class:`~ster.store.Provenance`, each half is split into one block per file,
editable file first. A block holds only statements that are really in that
file: headings, counts and notes are the pane's to draw, in its own style,
never Turtle comments that would read as if the file contained them. The
``@prefix`` lines the blocks need are written once, above them all — per
block, they outnumbered the statements — so a block parses with those
prefixes, and the copied pane as a whole is one valid document.

Pure functions over an :class:`rdflib.Graph`: no widget, no Textual, no theme,
so the same call serves the pane, a test, and anything later that wants an
entity's Turtle.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import rdflib

if TYPE_CHECKING:
    from .store import Provenance

# How many inbound triples the pane will print. Past this it is no longer
# context, it is a second document: nobody reads the four-hundredth thing that
# references a class, and the pane that tried to show them stops being openable
# on a real ontology.
MAX_INCOMING: Final[int] = 40

# How far the blank-node closure follows. A list or an address nests a few deep;
# a cycle through blank nodes would otherwise not terminate.
_BNODE_DEPTH: Final[int] = 8

_FileOf = Callable[[tuple], "Path | None"]


def _no_file(_triple: tuple) -> Path | None:
    return None


@dataclass(frozen=True)
class FileBlock:
    """The statements one file makes, as standalone Turtle. *file* is None when
    the caller gave no provenance to place them with."""

    file: Path | None
    turtle: str


@dataclass(frozen=True)
class EntitySource:
    """An entity's Turtle: its own statements, then what points at it, by file."""

    own: tuple[FileBlock, ...] = ()
    pointing: tuple[FileBlock, ...] = ()
    incoming: int = 0
    omitted: int = 0
    # The ``@prefix`` lines every block needs, written once rather than per
    # block: repeated, they outnumbered the statements they were there to spell.
    prefixes: str = ""

    @property
    def text(self) -> str:
        """The prefixes, then every block's Turtle — one document, what copying yields."""
        blocks = [block.turtle for block in (*self.own, *self.pointing)]
        return "\n\n".join([self.prefixes, *blocks] if blocks else [])


def _closure(
    graph: rdflib.Graph, node: rdflib.term.Node, depth: int, file_of: _FileOf
) -> list[tuple[tuple, Path | None]]:
    """*node*'s triples, each with its file, following blank-node objects down to *depth*.

    A blank node's statements take the file of the statement that reached it:
    merging re-mints blank nodes, so they cannot be looked up by themselves,
    and a ``[ ... ]`` is written in the same file as the statement holding it.
    """
    found: list[tuple[tuple, Path | None]] = []
    seen: set[rdflib.term.Node] = set()

    def walk(subject: rdflib.term.Node, left: int, inherited: Path | None) -> None:
        if subject in seen or left < 0:
            return
        seen.add(subject)
        for predicate, obj in graph.predicate_objects(subject):
            triple = (subject, predicate, obj)
            file = inherited if isinstance(subject, rdflib.BNode) else file_of(triple)
            found.append((triple, file))
            if isinstance(obj, rdflib.BNode):
                walk(obj, left - 1, file)

    walk(node, depth, None)
    return found


def _turtle(source: rdflib.Graph, triples: list[tuple]) -> tuple[list[str], str]:
    """*triples* as Turtle, split into its ``@prefix`` lines and its statements.

    Every namespace is bound but rdflib writes only the ``@prefix`` lines the
    triples use, so the lines returned are exactly what the statements need.
    """
    out = rdflib.Graph()
    for prefix, namespace in source.namespaces():
        out.bind(prefix, namespace, replace=True)
    for triple in triples:
        out.add(triple)
    lines = str(out.serialize(format="turtle")).strip().splitlines()
    directives = [line for line in lines if line.startswith("@prefix")]
    body = "\n".join(line for line in lines if not line.startswith("@prefix")).strip()
    return directives, body


def _blocks(
    source: rdflib.Graph,
    placed: list[tuple[tuple, Path | None]],
    files: Sequence[Path],
    prefixes: set[str],
) -> tuple[FileBlock, ...]:
    """One block per file, in *files* order; a file *files* does not list goes last.

    Each block's ``@prefix`` lines are added to *prefixes* instead of kept.
    """
    by_file: dict[Path | None, list[tuple]] = {}
    for triple, file in placed:
        by_file.setdefault(file, []).append(triple)
    rank = {file: index for index, file in enumerate(files)}
    blocks = []
    for file in sorted(by_file, key=lambda file: rank.get(file, len(rank))):  # type: ignore[arg-type]
        directives, body = _turtle(source, by_file[file])
        prefixes.update(directives)
        blocks.append(FileBlock(file, body))
    return tuple(blocks)


def entity_source(
    graph: rdflib.Graph,
    uri: str,
    *,
    provenance: Provenance | None = None,
    max_incoming: int = MAX_INCOMING,
) -> EntitySource:
    """*uri*'s Turtle: its own statements, then what points at it, each by file.

    The inbound cap is applied before grouping, so it bounds the pane as a
    whole rather than each file's share of it.
    """
    node = rdflib.URIRef(uri)
    file_of = provenance.file_of if provenance is not None else _no_file
    files = provenance.files if provenance is not None else ()
    own = _closure(graph, node, _BNODE_DEPTH, file_of)
    inbound = sorted(
        ((s, p, o) for s, p, o in graph.triples((None, None, node)) if s != node),
        key=lambda t: (str(t[0]), str(t[1])),
    )
    shown = [(triple, file_of(triple)) for triple in inbound[:max_incoming]]
    prefixes: set[str] = set()
    return EntitySource(
        own=_blocks(graph, own, files, prefixes),
        pointing=_blocks(graph, shown, files, prefixes),
        incoming=len(inbound),
        omitted=len(inbound) - len(shown),
        prefixes="\n".join(sorted(prefixes)),
    )
