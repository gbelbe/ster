"""Resolving any entity to its moments — instants, and the spans a file declares.

The rule this module exists to enforce: a temporal datatype places a point, and
only a declared pair of predicates makes a span. Guessing an interval from two
dates sitting on the same entity is what these tests are here to prevent — on
the file this was built against it would have drawn five bars out of six wrong,
pairing each document's own date with the date it was read.
"""

from __future__ import annotations

import rdflib

from ster import time_shapes

NS = "https://example.org/time#"

_PREFIXES = (
    "@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .\n"
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    "@prefix owl:  <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix prov: <http://www.w3.org/ns/prov#> .\n"
    "@prefix st:   <https://ster.dev/ns/time#> .\n"
    f"@prefix ex:   <{NS}> .\n"
)


def _graph(turtle: str) -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(data=_PREFIXES + turtle, format="turtle")
    return graph


def _node(local: str) -> rdflib.URIRef:
    return rdflib.URIRef(NS + local)


# ── detection is by datatype, never by predicate name ─────────────────────────


def test_a_date_on_any_predicate_is_a_moment() -> None:
    graph = _graph('ex:a ex:whenever "2026-08-18"^^xsd:date .')
    moments = time_shapes.moments_of(graph, _node("a"))
    assert [m.start for m in moments] == ["2026-08-18"]
    assert moments[0].kind == "instant"


def test_a_bare_year_is_placeable() -> None:
    graph = _graph('ex:a ex:signed "1977"^^xsd:gYear .')
    assert time_shapes.is_dated(graph, _node("a"))


def test_a_string_that_looks_like_a_date_is_not_one() -> None:
    graph = _graph('ex:a ex:when "2026-08-18" .')
    assert not time_shapes.is_dated(graph, _node("a"))
    assert not time_shapes.anything_dated(graph)


def test_a_duration_is_not_placeable_on_an_axis() -> None:
    graph = _graph('ex:a ex:lasts "P1M"^^xsd:duration .')
    assert not time_shapes.is_dated(graph, _node("a"))


# ── two dates are two instants until the file says otherwise ──────────────────


def test_two_unrelated_dates_stay_two_instants() -> None:
    """The bug this module was written to avoid: a document approved in 2022 and
    read in 2026 is not a four-year event."""
    graph = _graph(
        'ex:plu ex:approved "2022-02-01"^^xsd:date ;\n'
        '       prov:generatedAtTime "2026-09-15"^^xsd:date .'
    )
    moments = time_shapes.moments_of(graph, _node("plu"))
    assert len(moments) == 2
    assert all(m.kind == "instant" for m in moments)


def test_a_declared_pair_makes_one_interval() -> None:
    graph = _graph(
        "ex:Delay st:interval [ st:from ex:startsOn ; st:to ex:endsOn ] .\n"
        'ex:d a ex:Delay ; ex:startsOn "2026-08-18"^^xsd:date ;\n'
        '     ex:endsOn "2026-09-18"^^xsd:date .'
    )
    moments = time_shapes.moments_of(graph, _node("d"))
    assert len(moments) == 1
    assert (moments[0].start, moments[0].end) == ("2026-08-18", "2026-09-18")
    assert moments[0].kind == "interval"


def test_a_standard_pair_needs_no_declaration() -> None:
    graph = _graph(
        'ex:run prov:startedAtTime "2026-09-15T10:00:00"^^xsd:dateTime ;\n'
        '       prov:endedAtTime "2026-09-15T10:05:00"^^xsd:dateTime .'
    )
    moments = time_shapes.moments_of(graph, _node("run"))
    assert [m.kind for m in moments] == ["interval"]


def test_a_pair_pointing_at_itself_is_refused() -> None:
    """A zero-length bar is a date written twice, not a span the reader can see."""
    graph = _graph(
        "ex:Task st:interval [ st:from ex:due ; st:to ex:due ] .\n"
        'ex:t a ex:Task ; ex:due "2026-09-16"^^xsd:date .'
    )
    assert time_shapes.declared_pairs(graph) == frozenset()
    assert [m.kind for m in time_shapes.moments_of(graph, _node("t"))] == ["instant"]


def test_a_half_stated_span_stays_an_instant() -> None:
    graph = _graph(
        "ex:Delay st:interval [ st:from ex:startsOn ; st:to ex:endsOn ] .\n"
        'ex:d a ex:Delay ; ex:startsOn "2026-08-18"^^xsd:date .'
    )
    assert [m.kind for m in time_shapes.moments_of(graph, _node("d"))] == ["instant"]


# ── reach: a thing's dates include those of what points at it ─────────────────


def test_reach_is_inward_not_outward() -> None:
    graph = _graph(
        'ex:event ex:on "2026-08-18"^^xsd:date ; ex:of ex:procedure .\n'
        "ex:procedure ex:concerns ex:parcel .\n"
        'ex:parcel ex:surveyed "1810-01-01"^^xsd:date .'
    )
    reached = time_shapes.dated_from(graph, _node("procedure"))
    assert NS + "event" in reached
    # The parcel is downstream of the procedure, so its date is not the
    # procedure's — following links outward is how a selection ends up owning
    # every date in the file.
    assert NS + "parcel" not in reached


# ── lanes and items ───────────────────────────────────────────────────────────


def test_the_lane_is_the_most_specific_class() -> None:
    graph = _graph(
        "ex:Event a owl:Class ; rdfs:label 'Event' .\n"
        "ex:Deposit a owl:Class ; rdfs:subClassOf ex:Event ; rdfs:label 'Deposit' .\n"
        'ex:e a ex:Event, ex:Deposit ; ex:on "2026-08-18"^^xsd:date .'
    )
    assert time_shapes.lane_of(graph, _node("e")) == (NS + "Deposit", "Deposit")


def test_one_item_per_moment_not_per_entity() -> None:
    graph = _graph(
        'ex:doc rdfs:label "Notice" ; ex:issued "2026-02-01"^^xsd:date ;\n'
        '       prov:generatedAtTime "2026-09-15"^^xsd:date .'
    )
    items = time_shapes.timeline_items(graph, [NS + "doc"])
    assert len(items) == 2
    assert {item["label"] for item in items} == {"Notice"}
    assert {item["id"] for item in items} == {NS + "doc#0", NS + "doc#1"}


def test_provenance_and_annotation_moments_are_marked_auxiliary() -> None:
    graph = _graph(
        "ex:annotated a owl:AnnotationProperty .\n"
        'ex:doc ex:published "2026-02-01"^^xsd:date ;\n'
        '       ex:annotated "2026-09-15"^^xsd:date ;\n'
        '       prov:generatedAtTime "2026-09-16"^^xsd:date .'
    )
    items = time_shapes.timeline_items(graph, [NS + "doc"])
    by_predicate = {item["predicate"]: item["auxiliary"] for item in items}
    assert by_predicate[NS + "published"] is False
    assert by_predicate[NS + "annotated"] is True
    assert by_predicate["http://www.w3.org/ns/prov#generatedAtTime"] is True


def test_only_prov_moments_are_marked_provenance() -> None:
    """An annotation is auxiliary too, but it is not provenance and is not coloured as such."""
    graph = _graph(
        "ex:annotated a owl:AnnotationProperty .\n"
        'ex:doc ex:published "2026-02-01"^^xsd:date ;\n'
        '       ex:annotated "2026-09-15"^^xsd:date ;\n'
        '       prov:generatedAtTime "2026-09-16"^^xsd:date .'
    )
    items = time_shapes.timeline_items(graph, [NS + "doc"])
    by_predicate = {item["predicate"]: item["provenance"] for item in items}
    assert by_predicate[NS + "published"] is False
    assert by_predicate[NS + "annotated"] is False
    assert by_predicate["http://www.w3.org/ns/prov#generatedAtTime"] is True


def test_items_are_ordered_and_span_covers_them() -> None:
    graph = _graph('ex:a ex:on "2026-08-18"^^xsd:date .\nex:b ex:on "1977"^^xsd:gYear .')
    items = time_shapes.timeline_items(graph, [NS + "a", NS + "b"])
    assert [item["start"] for item in items] == ["1977", "2026-08-18"]
    assert time_shapes.span_of(items) == ("1977-01-01", "2026-08-18")


def test_an_unknown_uri_is_skipped_not_invented() -> None:
    graph = _graph('ex:a ex:on "2026-08-18"^^xsd:date .')
    assert time_shapes.timeline_items(graph, ["https://example.org/absent"]) == []
