"""The semantic core: two graphs in, a set of change operations out.

Pure — no git, no files, no I/O — so the whole vocabulary of change is testable
from turtle strings. The engine is rdflib's `graph_diff` over the isomorphic
(blank-node-canonical) form of each graph, which is what makes a re-serialised
file report as unchanged.
"""

from __future__ import annotations

from collections import Counter

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.compare import graph_diff, to_isomorphic
from rdflib.namespace import OWL, RDF, RDFS, SKOS
from rdflib.term import Node

from semanticdiff.rename import detect_renames
from semanticdiff.vocabulary import Change, ChangeKind, ChangeSet, EntityKind

# Predicates whose *object* is also touched by the triple. Adding
# `ex:Vehicle rdfs:subClassOf ex:Product` changes ex:Product too, although
# ex:Product is never a subject of the added triples; without this table the
# sentence "class X gained 2 properties" cannot be produced at all. Kept to
# four entries on purpose — every addition here is a new source of noise.
_OBJECT_ATTRIBUTION: dict[URIRef, tuple[str, str]] = {
    RDFS.subClassOf: ("subclass", "subclasses"),
    SKOS.broader: ("narrower concept", "narrower concepts"),
    RDFS.domain: ("property", "properties"),
    RDFS.range: ("property range", "property ranges"),
}

# Predicates reported as a value transition on the subject: "domain A → B".
_TRANSITIONS: dict[URIRef, str] = {RDFS.domain: "domain", RDFS.range: "range"}

_TYPE_KINDS: dict[URIRef, EntityKind] = {
    OWL.Class: EntityKind.CLASS,
    RDFS.Class: EntityKind.CLASS,
    OWL.ObjectProperty: EntityKind.PROPERTY,
    OWL.DatatypeProperty: EntityKind.PROPERTY,
    OWL.AnnotationProperty: EntityKind.PROPERTY,
    RDF.Property: EntityKind.PROPERTY,
    SKOS.Concept: EntityKind.CONCEPT,
    OWL.Ontology: EntityKind.ONTOLOGY,
    OWL.NamedIndividual: EntityKind.INDIVIDUAL,
}

_LABEL_PREDICATES = (SKOS.prefLabel, RDFS.label)

_DEPRECATED = Literal(True)


def compare(base: Graph, later: Graph) -> ChangeSet:
    """The change operations taking `base` to `later`."""
    _, only_base, only_later = graph_diff(to_isomorphic(base), to_isomorphic(later))
    touched = _touched(only_base) | _touched(only_later) | _changed_owners(base, later)
    changes = (_describe(uri, base, later, only_base, only_later) for uri in sorted(touched))
    return detect_renames(ChangeSet(tuple(c for c in changes if c is not None)))


def _touched(delta: Graph) -> set[URIRef]:
    """Every named entity implicated by the triples in `delta`."""
    touched: set[URIRef] = set()
    for subject, predicate, obj in delta:
        if isinstance(subject, URIRef):
            touched.add(subject)
        if predicate in _OBJECT_ATTRIBUTION and isinstance(obj, URIRef):
            touched.add(obj)
    return touched


def _changed_owners(base: Graph, later: Graph) -> set[URIRef]:
    """Named entities whose blank-node description changed.

    A change inside a blank node — a restriction's cardinality, a member of an
    anonymous union, an item in an RDF list — has a blank node as its subject, so
    subject attribution alone discards it, and the triple joining the owner to the
    blank node does not itself change. The edit would then be reported nowhere at
    all, which a reader cannot tell apart from "nothing changed".

    The blank nodes in the diff cannot be traced back: graph_diff canonicalises
    them, so their identity no longer matches either source graph. Instead each
    entity that owns a blank node has its description (itself plus everything
    reachable through blank nodes) compared between the two revisions.

    Only entities that actually own a blank node are examined, so an ontology
    without any — the common case — pays nothing for this.
    """
    owners = {
        subject
        for graph in (base, later)
        for subject, _, obj in graph
        if isinstance(subject, URIRef) and isinstance(obj, BNode)
    }
    return {uri for uri in owners if not _same_description(base, later, uri)}


def _same_description(base: Graph, later: Graph, uri: URIRef) -> bool:
    """Whether the entity's blank-node closure is the same graph on both sides."""
    return to_isomorphic(base.cbd(uri)) == to_isomorphic(later.cbd(uri))


def _describe(
    uri: URIRef, base: Graph, later: Graph, only_base: Graph, only_later: Graph
) -> Change | None:
    """One change for `uri`, or None when it is only ever referenced, never defined."""
    in_base = (uri, None, None) in base
    in_later = (uri, None, None) in later
    if not in_base and not in_later:
        return None
    source = later if in_later else base
    label, lang = _label(source, uri)
    return Change(
        kind=_kind(uri, base, later, in_base=in_base, in_later=in_later),
        entity=_entity_kind(source, uri),
        uri=str(uri),
        curie=_curie(source, uri),
        label=label,
        label_lang=lang,
        detail=_detail(uri, base, later, only_base, only_later),
        of_class=_of_class(source, uri),
    )


def _kind(uri: URIRef, base: Graph, later: Graph, *, in_base: bool, in_later: bool) -> ChangeKind:
    if not in_base:
        return ChangeKind.ADDED
    if not in_later:
        return ChangeKind.REMOVED
    if (uri, OWL.deprecated, _DEPRECATED) in later and (
        uri,
        OWL.deprecated,
        _DEPRECATED,
    ) not in base:
        return ChangeKind.DEPRECATED
    return ChangeKind.MODIFIED


def _entity_kind(graph: Graph, uri: URIRef) -> EntityKind:
    for type_uri in graph.objects(uri, RDF.type):
        if isinstance(type_uri, URIRef) and (kind := _TYPE_KINDS.get(type_uri)) is not None:
            return kind
    if (uri, RDF.type, None) in graph:
        return EntityKind.INDIVIDUAL
    return EntityKind.OTHER


def _of_class(graph: Graph, uri: URIRef) -> str | None:
    """The class an individual instantiates, as the name a reader should see.

    Sorted so a multi-typed individual always reports the same one, and skipping
    owl:NamedIndividual, which says nothing about what the thing is.
    """
    types = sorted(
        str(t)
        for t in graph.objects(uri, RDF.type)
        if isinstance(t, URIRef) and t != OWL.NamedIndividual and t not in _TYPE_KINDS
    )
    if not types:
        return None
    cls = URIRef(types[0])
    label, _ = _label(graph, cls)
    return label or _curie(graph, cls)


def _label(graph: Graph, uri: URIRef) -> tuple[str | None, str | None]:
    """The entity's preferred label, skos:prefLabel winning over rdfs:label."""
    for predicate in _LABEL_PREDICATES:
        literals = sorted(
            (o for o in graph.objects(uri, predicate) if isinstance(o, Literal)),
            key=lambda lit: (lit.language or "", str(lit)),
        )
        if literals:
            return str(literals[0]), literals[0].language
    return None, None


def _curie(graph: Graph, uri: Node) -> str:
    """The prefixed form, or the full URI when no prefix is bound."""
    try:
        prefix, _, name = graph.namespace_manager.compute_qname(str(uri), generate=False)
    except (KeyError, ValueError):
        return str(uri)
    return f"{prefix}:{name}" if prefix else str(uri)


def _detail(
    uri: URIRef, base: Graph, later: Graph, only_base: Graph, only_later: Graph
) -> tuple[str, ...]:
    return (
        *_transitions(uri, base, later, only_base, only_later),
        *_attributions(uri, only_base, only_later),
    )


def _transitions(
    uri: URIRef, base: Graph, later: Graph, only_base: Graph, only_later: Graph
) -> tuple[str, ...]:
    """Single-valued predicates that moved, read as 'domain ex:Place → ex:Site'."""
    parts = []
    for predicate, name in _TRANSITIONS.items():
        before = list(only_base.objects(uri, predicate))
        after = list(only_later.objects(uri, predicate))
        if len(before) == 1 and len(after) == 1:
            parts.append(f"{name} {_curie(base, before[0])} → {_curie(later, after[0])}")
    return tuple(parts)


def _attributions(uri: URIRef, only_base: Graph, only_later: Graph) -> tuple[str, ...]:
    """What the entity gained or lost through triples pointing at it."""
    gained = _incoming(only_later, uri)
    lost = _incoming(only_base, uri)
    parts = []
    for predicate, (singular, plural) in _OBJECT_ATTRIBUTION.items():
        for sign, counted in (("+", gained), ("-", lost)):
            total = counted[predicate]
            if total:
                parts.append(f"{sign}{total} {singular if total == 1 else plural}")
    return tuple(parts)


def _incoming(delta: Graph, uri: URIRef) -> Counter[Node]:
    return Counter(
        predicate for _, predicate, obj in delta if obj == uri and predicate in _OBJECT_ATTRIBUTION
    )
