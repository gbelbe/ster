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

**Where to find it.** Each prefix records the files whose blocks use it, and,
given a *locate* function (:mod:`ster.source_lines`), each statement's first
line is marked with the line it starts on in its file — so a reader can go
straight from the pane to the place to fix it.

Pure functions over an :class:`rdflib.Graph`: no widget, no Textual, no theme,
so the same call serves the pane, a test, and anything later that wants an
entity's Turtle.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

import rdflib

from .source_lines import subject_iri

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


# Where a subject starts its statements in a file: ``locate(file, iri)`` → lines.
Locate = Callable[[Path, str], "list[int]"]


@dataclass(frozen=True)
class FileBlock:
    """The statements one file makes, as Turtle. *file* is None when the caller
    gave no provenance to place them with.

    *lines* runs beside the Turtle, one entry per line of it: ``"L42"`` (or
    ``"L5, L40"``) on the line where a statement starts, ``""`` elsewhere. Only
    the first line matters — it is where the reader goes to find the statement.
    """

    file: Path | None
    turtle: str
    lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntitySource:
    """An entity's Turtle: its own statements, then what points at it, by file."""

    own: tuple[FileBlock, ...] = ()
    pointing: tuple[FileBlock, ...] = ()
    incoming: int = 0
    omitted: int = 0
    # Each ``@prefix`` line the blocks need, with the names of the files whose
    # blocks use it — written once rather than per block, most shared first.
    prefix_uses: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def prefixes(self) -> str:
        """The ``@prefix`` lines alone, in the order they are shown."""
        return "\n".join(line for line, _files in self.prefix_uses)

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


@dataclass
class _Assembler:
    """Builds the blocks of one entity's source, remembering which file used
    which prefix along the way so the shared prefix block can say so."""

    graph: rdflib.Graph
    files: Sequence[Path]
    locate: Locate | None
    prefix_files: dict[str, set[Path]] = field(default_factory=dict)

    def _rank(self, file: Path | None) -> int:
        """*files* order; a file it does not list (or none) goes last."""
        order = list(self.files)
        return order.index(file) if file in order else len(order)

    def blocks(self, placed: list[tuple[tuple, Path | None]]) -> tuple[FileBlock, ...]:
        """One block per file, in file order; each block's prefixes are pooled."""
        by_file: dict[Path | None, list[tuple]] = {}
        for triple, file in placed:
            by_file.setdefault(file, []).append(triple)
        blocks = []
        for file in sorted(by_file, key=self._rank):
            directives, body = _turtle(self.graph, by_file[file])
            for line in directives:
                used_by = self.prefix_files.setdefault(line, set())
                if file is not None:
                    used_by.add(file)
            blocks.append(FileBlock(file, body, self._marks(body, file)))
        return tuple(blocks)

    def _marks(self, body: str, file: Path | None) -> tuple[str, ...]:
        """``"L42"`` beside each line where a statement starts, ``""`` elsewhere.

        A statement's first line is the one rdflib writes flush left, starting
        with the subject; the lines under it are indented continuations.
        """
        namespaces = {prefix: str(ns) for prefix, ns in self.graph.namespaces()}
        return tuple(self._mark(line, file, namespaces) for line in body.splitlines())

    def _mark(self, line: str, file: Path | None, namespaces: dict[str, str]) -> str:
        if self.locate is None or file is None or not line or line[0].isspace():
            return ""
        subject = subject_iri(line, namespaces)
        found = self.locate(file, subject) if subject else []
        return ", ".join(f"L{number}" for number in found)

    def prefix_uses(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Each prefix line with its files, most shared first, then by prefix."""
        uses = [
            (line, tuple(file.name for file in sorted(used_by, key=self._rank)))
            for line, used_by in self.prefix_files.items()
        ]
        return tuple(sorted(uses, key=lambda use: (-len(use[1]), use[0])))


def entity_source(
    graph: rdflib.Graph,
    uri: str,
    *,
    provenance: Provenance | None = None,
    locate: Locate | None = None,
    max_incoming: int = MAX_INCOMING,
) -> EntitySource:
    """*uri*'s Turtle: its own statements, then what points at it, each by file.

    The inbound cap is applied before grouping, so it bounds the pane as a
    whole rather than each file's share of it. With *locate*, each statement's
    first line is marked with where it starts in its file.
    """
    node = rdflib.URIRef(uri)
    file_of = provenance.file_of if provenance is not None else _no_file
    assembler = _Assembler(graph, provenance.files if provenance else (), locate)
    own = _closure(graph, node, _BNODE_DEPTH, file_of)
    inbound = sorted(
        ((s, p, o) for s, p, o in graph.triples((None, None, node)) if s != node),
        key=lambda t: (str(t[0]), str(t[1])),
    )
    shown = [(triple, file_of(triple)) for triple in inbound[:max_incoming]]
    own_blocks = assembler.blocks(own)
    pointing_blocks = assembler.blocks(shown)
    return EntitySource(
        own=own_blocks,
        pointing=pointing_blocks,
        incoming=len(inbound),
        omitted=len(inbound) - len(shown),
        prefix_uses=assembler.prefix_uses(),
    )
