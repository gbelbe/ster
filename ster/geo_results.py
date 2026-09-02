"""Find geographic data in SPARQL results — for any ontology, not one vocabulary.

A result is *mappable* when at least one row can be placed on the earth. Two
things count, in this order:

1. bare ``?lat`` / ``?long`` columns, because the query said the coordinates
   outright and should be believed;
2. a URI-valued cell whose entity carries ``wgs:lat`` / ``wgs:long``.

Only `W3C Basic Geo <http://www.w3.org/2003/01/geo/wgs84_pos#>`_ is understood.
That is deliberate: it is a standard vocabulary any ontology can publish, so
nothing here needs to know what the data is *about*. No domain namespace is
referenced anywhere in this module.

Pure functions over an :class:`rdflib.Graph` and a
:class:`~ster.sparql_query.QueryResult`, with no UI or transport concerns, so
the TUI, the HTTP layer and the tests can all share them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import rdflib
from rdflib.namespace import RDFS, SKOS

# geo_results builds on geo_shapes, never the other way round.
from .geo_shapes import coordinates_of as coordinates_of
from .geo_shapes import geometry_of

# Taken from rdflib rather than spelled out: one definition each, no chance of a
# typo, and nothing for static analysis to read as a hard-coded URL.
RDFS_LABEL = RDFS.label
SKOS_BROADER = SKOS.broader
SKOS_PREF_LABEL = SKOS.prefLabel

# Column names taken to hold coordinates outright. Matched case-insensitively.
LAT_COLUMNS = frozenset({"lat", "latitude"})
LONG_COLUMNS = frozenset({"long", "lon", "lng", "longitude"})

# Rows arrive as plain strings (QueryResult normalises every cell), so a cell is
# treated as a URI only when it looks like an absolute one.
_URI_SCHEMES = ("http://", "https://", "urn:")  # NOSONAR - scheme prefixes, not URLs

# How far up skos:broader to offer groupings. A guard against a cyclic scheme
# as much as a limit: no real vocabulary nests this deep.
_MAX_BROADER_LEVELS = 10


@dataclass
class GeoPoint:
    """One located result row."""

    row: int
    lat: float
    long: float
    label: str = ""
    uri: str | None = None
    groups: dict[str, str] = field(default_factory=dict)
    # The entity's full geometry as GeoJSON, when it has one beyond a bare point.
    # lat/long stay the representative point, so clustering and zoomed-out
    # rendering keep working on shapes without knowing anything about them.
    shape: dict | None = None


@dataclass
class ClusterOption:
    """A way of grouping located rows that the result makes available."""

    key: str
    label: str


def _number(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _is_uri(cell: str) -> bool:
    return cell.startswith(_URI_SCHEMES)


def label_of(graph: rdflib.Graph, node: rdflib.URIRef) -> str:
    """The entity's own label, falling back to the local part of its URI."""
    for predicate in (SKOS_PREF_LABEL, RDFS_LABEL):
        value = graph.value(node, predicate)
        if value is not None:
            return str(value)
    text = str(node)
    return text.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _column_indexes(columns: list[str], names: frozenset[str]) -> int | None:
    for index, column in enumerate(columns):
        if column.lower() in names:
            return index
    return None


def _mappable(result: object) -> bool:
    """Only successful SELECT results carry rows worth locating."""
    return (
        not getattr(result, "error", "")
        and getattr(result, "query_type", "SELECT") == "SELECT"
        and bool(getattr(result, "rows", None))
    )


def locate(graph: rdflib.Graph, result: object) -> list[GeoPoint]:
    """Every row of *result* that can be placed, in result order."""
    if not _mappable(result):
        return []

    columns: list[str] = list(result.columns)  # type: ignore[attr-defined]
    lat_column = _column_indexes(columns, LAT_COLUMNS)
    long_column = _column_indexes(columns, LONG_COLUMNS)

    points: list[GeoPoint] = []
    for index, row in enumerate(result.rows):  # type: ignore[attr-defined]
        point = _locate_row(graph, columns, row, index, lat_column, long_column)
        if point is not None:
            points.append(point)
    return points


def _locate_row(
    graph: rdflib.Graph,
    columns: list[str],
    row: list[str],
    index: int,
    lat_column: int | None,
    long_column: int | None,
) -> GeoPoint | None:
    """Place a single row, explicit coordinates first, then entity lookup.

    Two ways of answering one question, tried in order of directness: a row that
    states its own coordinates has already answered it, and only one that does
    not is worth resolving through the graph.
    """
    stated = _from_coordinates(columns, row, index, lat_column, long_column)
    return stated if stated is not None else _from_entity(graph, row, index)


def _from_coordinates(
    columns: list[str],
    row: list[str],
    index: int,
    lat_column: int | None,
    long_column: int | None,
) -> GeoPoint | None:
    """A row placed by its own latitude and longitude columns."""
    if lat_column is None or long_column is None:
        return None
    lat = _number(row[lat_column]) if lat_column < len(row) else None
    long = _number(row[long_column]) if long_column < len(row) else None
    if lat is None or long is None:
        return None
    return GeoPoint(row=index, lat=lat, long=long, label=_row_label(columns, row))


def _from_entity(graph: rdflib.Graph, row: list[str], index: int) -> GeoPoint | None:
    """A row placed by the first URI in it the graph gives a geometry."""
    for cell in row:
        if not _is_uri(cell):
            continue
        node = rdflib.URIRef(cell)
        geometry = geometry_of(graph, node)
        if geometry is None:
            continue
        latitude, longitude = geometry.centroid
        return GeoPoint(
            row=index,
            lat=latitude,
            long=longitude,
            label=label_of(graph, node),
            uri=cell,
            # A bare point is already carried by lat/long; only a real shape
            # needs the geometry sent to the browser as well.
            shape=None if geometry.kind == "Point" else geometry.geojson,
        )
    return None


def _row_label(columns: list[str], row: list[str]) -> str:
    """First non-coordinate, non-URI cell — the closest thing to a name."""
    for column, cell in zip(columns, row, strict=False):
        if column.lower() in LAT_COLUMNS or column.lower() in LONG_COLUMNS:
            continue
        if cell and not _is_uri(cell):
            return cell
    return ""


def has_geodata(graph: rdflib.Graph, result: object) -> bool:
    """True when at least one row of *result* can be put on a map."""
    return bool(locate(graph, result))


def located_count(graph: rdflib.Graph, result: object) -> int:
    """How many rows can be placed — what the status line reports."""
    return len(locate(graph, result))


def cluster_options(graph: rdflib.Graph, result: object) -> list[ClusterOption]:
    """Ways the located rows could be grouped, discovered from the result itself.

    Two sources, both ontology-neutral: any other URI-valued column the query
    already returned, and the ``skos:broader`` ancestors of the located entities
    where the vocabulary has them.
    """
    points = locate(graph, result)
    if not points:
        return []

    columns: list[str] = list(result.columns)  # type: ignore[attr-defined]
    rows: list[list[str]] = list(result.rows)  # type: ignore[attr-defined]
    locating = {point.uri for point in points if point.uri}

    options: list[ClusterOption] = []
    for index, column in enumerate(columns):
        values = {row[index] for row in rows if index < len(row) and _is_uri(row[index])}
        if values and not values & locating:
            options.append(ClusterOption(key=column, label=column))

    options.extend(_broader_options(graph, points))
    return options


def _parents_of(
    graph: rdflib.Graph, frontier: list[rdflib.URIRef], seen: set[str]
) -> list[rdflib.URIRef]:
    """The next level up, skipping concepts an earlier level already claimed."""
    return [
        parent
        for node in frontier
        for parent in graph.objects(node, SKOS_BROADER)
        if isinstance(parent, rdflib.URIRef) and str(parent) not in seen
    ]


def _level_option(graph: rdflib.Graph, parents: list[rdflib.URIRef], depth: int) -> ClusterOption:
    """Name a broader level after its only member, or after the level itself."""
    label = label_of(graph, parents[0]) if len(parents) == 1 else f"broader level {depth}"
    return ClusterOption(key=f"broader:{depth}", label=label)


def _broader_options(graph: rdflib.Graph, points: list[GeoPoint]) -> list[ClusterOption]:
    """One option per level of skos:broader above the located entities."""
    frontier = [rdflib.URIRef(p.uri) for p in points if p.uri]
    seen: set[str] = set()
    options: list[ClusterOption] = []
    for depth in range(1, _MAX_BROADER_LEVELS + 1):
        parents = _parents_of(graph, frontier, seen)
        if not parents:
            break
        seen.update(str(parent) for parent in parents)
        options.append(_level_option(graph, parents, depth))
        frontier = parents
    return options
