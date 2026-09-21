"""Finding temporal data in SPARQL results, without knowing the vocabulary.

Two ways a row gets a date, and the second is the one that matters in practice:
a query written for something else — ``SELECT ?action ?label`` — returns no date
column at all, and every one of those actions has a deadline in the graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import rdflib

from ster import time_results

NS = "https://example.org/time#"


@dataclass
class _Result:
    """The shape time_results reads off a QueryResult, and nothing more."""

    columns: list[str]
    rows: list[list[str]]
    error: str = ""
    query_type: str = "SELECT"
    extra: dict = field(default_factory=dict)


def _graph(turtle: str) -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(
        data="@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        f"@prefix ex: <{NS}> .\n" + turtle,
        format="turtle",
    )
    return graph


def test_a_stated_date_column_is_believed() -> None:
    result = _Result(columns=["name", "date"], rows=[["Dépôt", "2026-08-18"]])
    points = time_results.timeline(rdflib.Graph(), result)
    assert [(p.start, p.label) for p in points] == [("2026-08-18", "Dépôt")]


def test_a_start_and_end_column_make_a_span() -> None:
    result = _Result(
        columns=["label", "start", "end"], rows=[["Délai", "2026-08-18", "2026-09-18"]]
    )
    point = time_results.timeline(rdflib.Graph(), result)[0]
    assert (point.start, point.end) == ("2026-08-18", "2026-09-18")


def test_french_column_names_work_too() -> None:
    result = _Result(columns=["nom", "debut", "fin"], rows=[["Délai", "2026-08-18", "2026-09-18"]])
    assert time_results.timeline(rdflib.Graph(), result)[0].end == "2026-09-18"


def test_a_row_with_no_date_column_is_dated_through_its_entity() -> None:
    """The case that makes the feature usable: the query never mentioned time."""
    graph = _graph(
        f'<{NS}act> rdfs:label "Envoyer le courrier" ; <{NS}due> "2026-09-16"^^xsd:date .'
    )
    result = _Result(columns=["thing", "name"], rows=[[NS + "act", "Envoyer le courrier"]])
    points = time_results.timeline(graph, result)
    assert [(p.start, p.uri) for p in points] == [("2026-09-16", NS + "act")]


def test_a_row_whose_entity_has_no_date_is_dropped() -> None:
    graph = _graph(f'<{NS}act> rdfs:label "Sans date" .')
    result = _Result(columns=["thing"], rows=[[NS + "act"]])
    assert time_results.timeline(graph, result) == []
    assert not time_results.has_timedata(graph, result)


def test_an_errored_result_places_nothing() -> None:
    result = _Result(columns=["date"], rows=[["2026-08-18"]], error="boom")
    assert time_results.timeline(rdflib.Graph(), result) == []


def test_result_uris_are_distinct_and_in_first_seen_order() -> None:
    result = _Result(
        columns=["a", "b"],
        rows=[[NS + "x", NS + "y"], [NS + "x", "plain text"]],
    )
    assert time_results.result_uris(result) == [NS + "x", NS + "y"]


def test_a_datetime_cell_is_recognised_down_to_the_day() -> None:
    result = _Result(columns=["date"], rows=[["2026-09-15T19:33:12"]])
    assert time_results.timeline(rdflib.Graph(), result)[0].start == "2026-09-15"


def test_a_non_date_in_a_date_column_places_nothing() -> None:
    result = _Result(columns=["date"], rows=[["bientôt"]])
    assert time_results.timeline(rdflib.Graph(), result) == []
