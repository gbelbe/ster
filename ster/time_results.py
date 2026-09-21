"""Find temporal data in SPARQL results — for any ontology, not one vocabulary.

A result is *timeable* when at least one row can be put on an axis. Two things
count, in this order:

1. a column that holds a date outright, because the query said so and should be
   believed — ``?date``, ``?start``, ``?when`` and their usual spellings;
2. a URI-valued cell whose entity carries a temporal literal, resolved through
   :mod:`ster.time_shapes`.

The second is what makes the view usable on an ordinary query: ``SELECT ?action
?label`` returns no dates at all, and yet every one of those actions has a
deadline in the graph. Asking the reader to add the date column by hand would be
asking them to know the vocabulary before they can look at it.

time_results builds on time_shapes, never the other way round — the same
layering as geo_results over geo_shapes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import rdflib

from .time_shapes import is_dated, moments_of
from .viz_shared import is_uri as is_uri
from .viz_shared import label_of as label_of

# Column names taken to hold a date outright, matched case-insensitively. Both
# languages of the files ster is used on, because a French ontology writes
# ?debut and an English one ?start and neither should have to translate.
START_COLUMNS = frozenset(
    {"date", "start", "startdate", "begin", "from", "when", "time", "debut", "début", "datedebut"}
)
END_COLUMNS = frozenset({"end", "enddate", "to", "until", "finish", "fin", "datefin"})

# ISO-8601 down to the day, with anything after it (a time, a zone) ignored for
# the purposes of recognising the cell. Deliberately not a parser: this decides
# whether a string is a date, and time_shapes decides what it means.
_ISO = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?")


@dataclass
class TimePoint:
    """One timed result row."""

    row: int
    start: str
    end: str | None = None
    label: str = ""
    uri: str | None = None


def _iso(cell: str) -> str | None:
    match = _ISO.match(cell.strip()) if cell else None
    return match.group(0) if match else None


def _column_index(columns: list[str], names: frozenset[str]) -> int | None:
    for index, column in enumerate(columns):
        if column.lower() in names:
            return index
    return None


def _timeable(result: object) -> bool:
    """Only successful SELECT results carry rows worth dating."""
    return (
        not getattr(result, "error", "")
        and getattr(result, "query_type", "SELECT") == "SELECT"
        and bool(getattr(result, "rows", None))
    )


def timeline(graph: rdflib.Graph, result: object) -> list[TimePoint]:
    """Every row of *result* that can be placed on an axis, in result order."""
    if not _timeable(result):
        return []
    columns: list[str] = list(result.columns)  # type: ignore[attr-defined]
    start_column = _column_index(columns, START_COLUMNS)
    end_column = _column_index(columns, END_COLUMNS)
    points: list[TimePoint] = []
    for index, row in enumerate(result.rows):  # type: ignore[attr-defined]
        point = _stated(columns, row, index, start_column, end_column) or _from_entity(
            graph, row, index
        )
        if point is not None:
            points.append(point)
    return points


def _stated(
    columns: list[str],
    row: list[str],
    index: int,
    start_column: int | None,
    end_column: int | None,
) -> TimePoint | None:
    """A row placed by its own date columns."""
    if start_column is None or start_column >= len(row):
        return None
    start = _iso(row[start_column])
    if start is None:
        return None
    end = _iso(row[end_column]) if end_column is not None and end_column < len(row) else None
    return TimePoint(row=index, start=start, end=end, label=_row_label(columns, row))


def _from_entity(graph: rdflib.Graph, row: list[str], index: int) -> TimePoint | None:
    """A row placed by the first URI in it the graph gives a moment."""
    for cell in row:
        if not is_uri(cell):
            continue
        node = rdflib.URIRef(cell)
        moments = moments_of(graph, node)
        if not moments:
            continue
        first = moments[0]
        return TimePoint(
            row=index,
            start=first.start,
            end=first.end,
            label=label_of(graph, node),
            uri=cell,
        )
    return None


def _row_label(columns: list[str], row: list[str]) -> str:
    """First non-date, non-URI cell — the closest thing to a name."""
    for column, cell in zip(columns, row, strict=False):
        name = column.lower()
        if name in START_COLUMNS or name in END_COLUMNS:
            continue
        if cell and not is_uri(cell):
            return cell
    return ""


def result_uris(result: object) -> list[str]:
    """Every distinct URI in *result*, in first-seen order.

    What the page sends to ``/api/timeline``: resolving moments needs the graph,
    and the graph lives on the server. The same division of labour as the map,
    where the page sends URIs to ``/api/locate`` rather than trying to parse WKT
    in JavaScript.
    """
    if not _timeable(result):
        return []
    seen: list[str] = []
    known: set[str] = set()
    for row in result.rows:  # type: ignore[attr-defined]
        for cell in row:
            if is_uri(cell) and cell not in known:
                known.add(cell)
                seen.append(cell)
    return seen


def has_timedata(graph: rdflib.Graph, result: object) -> bool:
    """True when at least one row of *result* can be put on a timeline."""
    return bool(timeline(graph, result))


def dated_count(graph: rdflib.Graph, result: object) -> int:
    """How many rows can be placed — what the status line reports."""
    return len(timeline(graph, result))


def entities_dated(graph: rdflib.Graph, uris: list[str]) -> list[str]:
    """Those *uris* the graph can date, in the order given."""
    return [uri for uri in uris if is_dated(graph, rdflib.URIRef(uri))]
