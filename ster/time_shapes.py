"""Resolve an entity to its moments in time — instants and intervals.

:mod:`ster.geo_shapes` keys on the literal's *datatype*, and that works because a
``geo:wktLiteral`` carries its own completeness: the literal alone is a shape.
The same trick applied to time gets you halfway and then lies. ``xsd:date``
announces that a value is a date; it says nothing about the date's *role*, and a
role is what an interval is made of.

Measured on a real file before this module was written: 47 dated entities, of
which 6 carried two dates each. Exactly one of those six was an interval. The
other five paired a document's own date with the date it was consulted — a PLU
approved in 2022 and read in 2026 is not a four-year event, it is two unrelated
instants. A rule that guesses intervals from adjacency would have drawn five
bars out of six wrong.

So: **datatypes place a point, declarations make a span.** Anything with a
temporal datatype becomes an instant. An interval exists only where the pair of
predicates is stated — by a standard vocabulary, or by the file itself:

.. code-block:: turtle

    ant:Delai st:interval [ st:from ant:debuteLe ; st:to ant:expireLe ] .

Deliberately not supported: ``xsd:duration`` and ``xsd:time`` without a date
(a length with no anchor cannot be placed on an axis), and OWL-Time's
``time:hasBeginning``/``hasEnd`` when they point at ``time:Instant`` nodes
rather than literals — that indirection is worth adding the day a file needs it,
and guessing at it now would be code with no data behind it.

Pure functions over an :class:`rdflib.Graph`, no UI and no transport, so the
TUI, the HTTP layer and the tests share one implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import rdflib
from rdflib.namespace import OWL, RDF, RDFS, XSD

from .viz_shared import (
    image_of,
    label_of,
    local_name,
    most_specific_types,
    reachable_inward,
)

# The vocabulary a file uses to declare its own interval pairs. Same shape as
# geo_shapes' STER_MAP: which spans exist is a property of the data, so it is
# read from the file rather than configured in ster.
STER_TIME = rdflib.Namespace("https://ster.dev/ns/time#")
PROV = rdflib.Namespace("http://www.w3.org/ns/prov#")  # NOSONAR - RDF namespace IRI

# Literal datatypes that announce a position on a time axis. Kept to the five
# that can be ordered without interpretation: xsd:time has no date to sit on and
# xsd:duration has no anchor, so neither can be drawn.
TEMPORAL_DATATYPES: Final[frozenset[rdflib.URIRef]] = frozenset(
    {XSD.date, XSD.dateTime, XSD.dateTimeStamp, XSD.gYear, XSD.gYearMonth}
)

# Interval pairs every vocabulary agrees on. Short on purpose: a pair earns its
# place here only when the two predicates mean start and end of *the same*
# thing. dcterms:created/modified are two events in a life, not a span, and
# pairing them would draw a bar across every document ever edited.
#
# schema.org is spelled both ways: the vocabulary moved to https and real files
# carry either, so matching one would silently miss half of them.
_STANDARD_PAIRS: Final[tuple[tuple[str, str], ...]] = (
    ("http://schema.org/startDate", "http://schema.org/endDate"),  # NOSONAR - RDF predicate IRI
    ("https://schema.org/startDate", "https://schema.org/endDate"),
    (
        "http://www.w3.org/ns/prov#startedAtTime",  # NOSONAR - RDF predicate IRI
        "http://www.w3.org/ns/prov#endedAtTime",  # NOSONAR - RDF predicate IRI
    ),
    (
        "http://www.w3.org/2006/time#hasBeginning",  # NOSONAR - RDF predicate IRI
        "http://www.w3.org/2006/time#hasEnd",  # NOSONAR - RDF predicate IRI
    ),
)

# How far a selection may reach for something dated. Three, matching
# geo_shapes.REACH_DEPTH and for the same reason: an entity, its event and that
# event's record is three hops, and beyond it "this thing's dates" stops meaning
# anything. Declared separately so the two are free to diverge.
REACH_DEPTH: Final[int] = 3


@dataclass(frozen=True)
class Moment:
    """One drawable item: an instant, or a span with an end.

    *predicate* is kept because it is the honest grouping key. An entity with a
    publication date and a consultation date has two moments that belong in two
    lanes, and merging them under the entity's name would say the file holds one
    event where it holds two.
    """

    start: str
    end: str | None
    predicate: str
    predicate_label: str

    @property
    def kind(self) -> str:
        return "interval" if self.end else "instant"


def _sort_key(value: str) -> str:
    """Order ISO-8601 forms of different precision against each other.

    ``2026`` must sort before ``2026-08-18``, and lexical order already does
    that for ISO strings — but only once they share a prefix, so a bare year is
    padded rather than parsed. Parsing would mean choosing a month for a year
    that does not have one, and inventing January is how a decade-scale axis
    ends up with every event on New Year's Day.
    """
    return value if len(value) >= 10 else value + "-01-01"[len(value) - 10 :]


def _temporal_literals(graph: rdflib.Graph, node: rdflib.term.Node) -> list[tuple[str, str]]:
    """Every (predicate, ISO value) on *node* whose datatype announces a time."""
    found = []
    for predicate, obj in graph.predicate_objects(node):
        if isinstance(obj, rdflib.Literal) and obj.datatype in TEMPORAL_DATATYPES:
            found.append((str(predicate), str(obj)))
    return found


def declared_pairs(graph: rdflib.Graph) -> frozenset[tuple[str, str]]:
    """Interval pairs the file declares, as ``(start predicate, end predicate)``.

    Read from ``st:interval [ st:from … ; st:to … ]``, on a class or on anything
    else — the subject is not checked, because an ontology that states the pair
    on a property or on itself means the same thing by it, and refusing those
    would be ster insisting on one modelling style.
    """
    cached = getattr(graph, "_ster_interval_pairs", None)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    found = set()
    for _subject, spec in graph.subject_objects(STER_TIME.interval):
        start = graph.value(spec, STER_TIME["from"])
        end = graph.value(spec, STER_TIME.to)
        # Same predicate at both ends is not a span, it is one date written
        # twice — a zero-length bar the reader cannot see and cannot click.
        # Caught here rather than trusted to the author, the way geo_shapes
        # refuses a symmetric property as containment.
        if start is not None and end is not None and str(start) != str(end):
            found.add((str(start), str(end)))
    result = frozenset(found)
    try:
        graph._ster_interval_pairs = result  # type: ignore[attr-defined]
    except AttributeError:  # a graph that refuses attributes — recompute instead
        pass
    return result


def _pairs_for(graph: rdflib.Graph) -> frozenset[tuple[str, str]]:
    return declared_pairs(graph) | frozenset(_STANDARD_PAIRS)


def _label_of_predicate(graph: rdflib.Graph, uri: str) -> str:
    label = graph.value(rdflib.URIRef(uri), RDFS.label)
    if label is not None:
        return str(label)
    return local_name(uri)


def is_provenance(predicate: str) -> bool:
    """Whether a temporal predicate comes from PROV-O.

    Kept apart from :func:`is_annotation_or_provenance` because the two answer
    different questions. Both kinds are *auxiliary* — commentary rather than the
    event — but only provenance says where a fact came from, and the timeline
    colours it on its own so a reader can tell the record from the thing it
    records without reading a single label.
    """
    return predicate.startswith(str(PROV))


def is_annotation_or_provenance(graph: rdflib.Graph, predicate: str) -> bool:
    """Whether a temporal predicate is supporting metadata rather than the event itself."""
    ref = rdflib.URIRef(predicate)
    return is_provenance(predicate) or (ref, RDF.type, OWL.AnnotationProperty) in graph


def moments_of(graph: rdflib.Graph, node: rdflib.term.Node) -> list[Moment]:
    """Every moment *node* carries, spans first, then the instants left over.

    Order matters to the reader, not to the code: a span is the thing an entity
    *is* on a timeline, and the stray dates around it are commentary.
    """
    literals = _temporal_literals(graph, node)
    if not literals:
        return []
    by_predicate: dict[str, str] = {}
    for predicate, value in literals:
        by_predicate.setdefault(predicate, value)

    moments: list[Moment] = []
    consumed: set[str] = set()
    for start_predicate, end_predicate in sorted(_pairs_for(graph)):
        if start_predicate in by_predicate and end_predicate in by_predicate:
            moments.append(
                Moment(
                    start=by_predicate[start_predicate],
                    end=by_predicate[end_predicate],
                    predicate=start_predicate,
                    predicate_label=_label_of_predicate(graph, start_predicate),
                )
            )
            consumed |= {start_predicate, end_predicate}

    for predicate, value in sorted(by_predicate.items()):
        if predicate not in consumed:
            moments.append(
                Moment(
                    start=value,
                    end=None,
                    predicate=predicate,
                    predicate_label=_label_of_predicate(graph, predicate),
                )
            )
    return moments


def is_dated(graph: rdflib.Graph, node: rdflib.term.Node) -> bool:
    """True when *node* can be put on a time axis."""
    return bool(_temporal_literals(graph, node))


def anything_dated(graph: rdflib.Graph) -> bool:
    """Whether this file holds any time at all.

    Asked before the timeline opens rather than after, for the reason
    geo_shapes gives about maps: an empty view reads as a broken feature, and
    the reader cannot tell it apart from one that failed to load.
    """
    return any(
        isinstance(obj, rdflib.Literal) and obj.datatype in TEMPORAL_DATATYPES
        for _s, _p, obj in graph
    )


def dated_from(graph: rdflib.Graph, node: rdflib.URIRef, depth: int = REACH_DEPTH) -> list[str]:
    """The dated entities *node* stands over — itself, and what refers to it.

    Inward only, the same direction and for the same reason as
    :func:`ster.geo_shapes.located_from`: following links outward walks up the
    model and back down somebody else's branch, and a procedure would come back
    owning every date in the file. What points *at* a thing is about that thing.
    """
    return reachable_inward(graph, node, is_dated, depth)


def lane_of(graph: rdflib.Graph, node: rdflib.term.Node) -> tuple[str, str]:
    """The lane an entity belongs in: its most specific class, URI and label.

    Taken from the class rather than from the predicate so that a file gains a
    lane by gaining a class, with no code change here — the same reasoning
    geo_shapes applies to drill levels.
    """
    types = most_specific_types(graph, node)
    if not types:
        return ("", "—")
    uri = types[0]
    label = graph.value(rdflib.URIRef(uri), RDFS.label)
    return (uri, str(label) if label else local_name(uri))


def _note_of(graph: rdflib.Graph, node: rdflib.term.Node) -> str:
    from .store import NOTE_PROPERTY_URI  # noqa: PLC0415

    value = graph.value(node, rdflib.URIRef(NOTE_PROPERTY_URI))
    return str(value) if value is not None else ""


def timeline_items(graph: rdflib.Graph, uris: list[str]) -> list[dict[str, object]]:
    """Every moment of every URI, as the timeline page wants them.

    One item per moment, not per entity: an entity dated twice appears twice, in
    two lanes. That is the shape of the data and hiding it would be a lie the
    reader cannot see through.
    """
    items: list[dict[str, object]] = []
    for uri in uris:
        node = rdflib.URIRef(uri)
        if (node, None, None) not in graph:
            continue
        moments = moments_of(graph, node)
        if not moments:
            continue
        lane_uri, lane_label = lane_of(graph, node)
        label, note = label_of(graph, node), _note_of(graph, node)
        image = image_of(graph, node)
        for index, moment in enumerate(moments):
            items.append(
                {
                    "id": f"{uri}#{index}",
                    "uri": uri,
                    "label": label,
                    "note": note,
                    "image": image,
                    "start": moment.start,
                    "end": moment.end,
                    "kind": moment.kind,
                    "predicate": moment.predicate,
                    "predicateLabel": moment.predicate_label,
                    "auxiliary": is_annotation_or_provenance(graph, moment.predicate),
                    "provenance": is_provenance(moment.predicate),
                    "group": lane_uri or "—",
                    "groupLabel": lane_label,
                    "sort": _sort_key(moment.start),
                }
            )
    items.sort(key=lambda item: str(item["sort"]))
    return items


def span_of(items: list[dict[str, object]]) -> tuple[str, str] | None:
    """Earliest and latest instant across *items*, or None when there are none."""
    if not items:
        return None
    starts = [str(item["sort"]) for item in items]
    ends = [str(item["end"]) for item in items if item.get("end")]
    return (min(starts), max(starts + ends))
