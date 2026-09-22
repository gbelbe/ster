"""One entity's own RDF, serialised as Turtle — what the source pane reads from.

The pane answers "what does this thing actually look like in the file", so the
unit is the entity, not the document: a tree selection names one subject, and
what comes back has to fit a pane beside the tree.

**What counts as the entity's source.** Its own triples, plus the blank nodes it
owns — a blank node is not addressable on its own, so cutting the closure there
would print ``[ ]`` and lose everything inside it. Then, separately and clearly
marked, the triples that point *at* it. That second half is what makes the pane
worth opening on a graph rather than a file: ``ant:depot`` says nothing about
belonging to a dossier, because that fact is written on the dossier. But it is
also the unbounded half — a hub entity can be the object of thousands of
triples — so it is capped, and the cap says so rather than trailing off.

Pure functions over an :class:`rdflib.Graph`: no widget, no Textual, no theme,
so the same call serves the pane, a test, and anything later that wants an
entity's Turtle — this is a way to read the file as code instead of through the
UI, and nothing about it is particular to one view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import rdflib

# How many inbound triples the pane will print. Past this it is no longer
# context, it is a second document: nobody reads the four-hundredth thing that
# references a class, and the pane that tried to show them stops being openable
# on a real ontology.
MAX_INCOMING: Final[int] = 40

# How far the blank-node closure follows. A list or an address nests a few deep;
# a cycle through blank nodes would otherwise not terminate.
_BNODE_DEPTH: Final[int] = 8

_DIRECTIVES: Final[tuple[str, ...]] = ("@prefix", "@base", "PREFIX", "BASE")


def _closure(graph: rdflib.Graph, node: rdflib.term.Node, depth: int) -> list[tuple]:
    """*node*'s triples, following blank-node objects down to *depth*."""
    found: list[tuple] = []
    seen: set[rdflib.term.Node] = set()

    def walk(subject: rdflib.term.Node, left: int) -> None:
        if subject in seen or left < 0:
            return
        seen.add(subject)
        for predicate, obj in graph.predicate_objects(subject):
            found.append((subject, predicate, obj))
            if isinstance(obj, rdflib.BNode):
                walk(obj, left - 1)

    walk(node, depth)
    return found


def _with_prefixes(source: rdflib.Graph, triples: list[tuple]) -> rdflib.Graph:
    """*triples* in a fresh graph that spells URIs the way the source file does."""
    out = rdflib.Graph()
    for prefix, namespace in source.namespaces():
        out.bind(prefix, namespace, replace=True)
    for triple in triples:
        out.add(triple)
    return out


def _turtle(graph: rdflib.Graph) -> str:
    return str(graph.serialize(format="turtle")).strip()


def _strip_directives(turtle: str) -> str:
    """Drop a serialisation's ``@prefix`` header — the document already has one."""
    lines = turtle.splitlines()
    body = [line for line in lines if not line.strip().startswith(_DIRECTIVES)]
    return "\n".join(body).strip()


def _first_statement_line(turtle: str) -> int:
    """1-based line of the first statement, i.e. the first non-directive line."""
    for index, line in enumerate(turtle.splitlines(), start=1):
        stripped = line.strip()
        if stripped and not stripped.startswith(_DIRECTIVES):
            return index
    return 1


@dataclass(frozen=True)
class EntitySource:
    """Turtle for one entity, and where its own statements sit in that text.

    *focus* is a 1-based inclusive line range so the pane can mark the entity's
    own block: the inbound half below it is context, and a reader who cannot see
    the join reads someone else's triples as the entity's own.
    """

    text: str
    focus: tuple[int, int]
    incoming: int = 0
    omitted: int = 0

    @property
    def focus_lines(self) -> set[int]:
        start, end = self.focus
        return set(range(start, end + 1))


def entity_source(
    graph: rdflib.Graph, uri: str, *, max_incoming: int = MAX_INCOMING
) -> EntitySource:
    """*uri*'s Turtle: its own statements, then what points at it.

    An entity with no triples at all still returns a readable note rather than
    an empty pane: an empty pane reads as a broken feature, and the reader
    cannot tell it apart from one that failed to load.
    """
    node = rdflib.URIRef(uri)
    own = _closure(graph, node, _BNODE_DEPTH)
    inbound = [(s, p, o) for s, p, o in graph.triples((None, None, node)) if s != node]
    inbound.sort(key=lambda t: (str(t[0]), str(t[1])))

    if not own and not inbound:
        return EntitySource(text=f"# {uri}\n# not in the graph", focus=(1, 2))

    head = _turtle(_with_prefixes(graph, own)) if own else f"# {uri}\n# no statements of its own"
    start = _first_statement_line(head)
    text = head
    end = len(head.splitlines())

    shown = inbound[:max_incoming]
    if shown:
        body = _strip_directives(_turtle(_with_prefixes(graph, list(shown))))
        omitted = len(inbound) - len(shown)
        note = f"# {len(inbound)} statements point here"
        if omitted:
            note += f" — {len(shown)} shown, {omitted} omitted"
        text = f"{head}\n\n{note}\n{body}"
    return EntitySource(
        text=text,
        focus=(start, end),
        incoming=len(inbound),
        omitted=max(0, len(inbound) - len(shown)),
    )
