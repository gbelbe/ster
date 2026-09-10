"""Why a loaded file produced no entities, and the declarations that would fix it.

ster builds its model by looking subjects up by ``rdf:type`` against a known
vocabulary (see :func:`ster.store._from_graph._taxonomy_from_index`). A file that
types its subjects with a class it never declares matches nothing, so every
triple falls through to :attr:`Taxonomy.residue` and the taxonomy comes out
empty — a successful load of nothing, which the UI used to render as a blank
tree.

One condition catches that whatever its cause: *no entity in any registry*. The
fix is then derived from the residue itself rather than from a catalogue of
known-bad shapes — whichever types were used but never declared are the ones to
declare.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from rdflib import URIRef
from rdflib.namespace import OWL, RDF

from ..model import Taxonomy, is_builtin_uri

#: The taxonomy holds no triples at all.
NO_TRIPLES = "no_triples"
#: The file parsed, but nothing in it matched a type ster models.
NO_RECOGNISED_TYPES = "no_recognised_types"

# Derived from rdflib rather than written out: one source of truth for the
# namespaces, and no clear-text URL literal for Sonar's S5332 to flag.
_RDF_TYPE = str(RDF.type)
_OWL_PREFIX = f"@prefix owl: <{OWL}> ."

_REGISTRIES = ("schemes", "concepts", "owl_classes", "owl_individuals", "owl_properties")


@dataclass(frozen=True)
class Unreadable:
    """A load that produced no entities, and what would make it produce some."""

    reason: str
    total_triples: int
    #: (type URI, how many subjects carry it), commonest first.
    undeclared_types: tuple[tuple[str, int], ...] = ()

    @property
    def fixable(self) -> bool:
        """True when declaring the missing types would give ster something to model."""
        return bool(self.undeclared_types)


def diagnose(taxonomy: Taxonomy) -> Unreadable | None:
    """Why *taxonomy* is empty, or None when it modelled at least one entity."""
    if any(getattr(taxonomy, registry) for registry in _REGISTRIES):
        return None
    residue = taxonomy.residue or []
    if not residue:
        return Unreadable(NO_TRIPLES, 0)
    return Unreadable(NO_RECOGNISED_TYPES, len(residue), _undeclared_types(residue))


def _undeclared_types(residue: list[tuple]) -> tuple[tuple[str, int], ...]:
    """Every named type used by a subject, commonest first.

    Nothing is declared when we get here — a declared class would have landed in
    a registry and short-circuited the diagnosis — so "used" is enough. Builtins
    and blank nodes are skipped: neither is a class the user could declare.
    """
    counts: Counter[str] = Counter(
        str(obj)
        for _subject, predicate, obj in residue
        if str(predicate) == _RDF_TYPE and isinstance(obj, URIRef) and not is_builtin_uri(str(obj))
    )
    return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def declaration_turtle(unreadable: Unreadable | None) -> str:
    """Pasteable Turtle declaring every missing type — empty when there is nothing to fix."""
    if unreadable is None or not unreadable.fixable:
        return ""
    lines = [f"<{uri}> a owl:Class ." for uri, _count in unreadable.undeclared_types]
    return "\n".join([_OWL_PREFIX, *lines])


def type_lines(unreadable: Unreadable | None) -> list[str]:
    """One ``count ×  uri`` line per undeclared type, counts right-aligned.

    The URI ends the line so a terminal (or a Textual Static) that has to fold it
    never breaks a sentence around it, and it stays selectable in one piece.
    """
    if unreadable is None or not unreadable.fixable:
        return []
    width = max(len(str(count)) for _uri, count in unreadable.undeclared_types)
    return [f"{count:>{width}} ×  {uri}" for uri, count in unreadable.undeclared_types]


def describe_unreadable(unreadable: Unreadable | None, name: str) -> str:
    """One line saying what ster read and what it made of it."""
    if unreadable is None:
        return ""
    if unreadable.reason == NO_TRIPLES:
        return f"{name} contains no triples."
    return f"ster read {unreadable.total_triples} triples from {name} but recognised no entity."
