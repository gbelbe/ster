"""Resolve an entity to a geometry — point, polygon, multipolygon, collection.

:mod:`ster.geo_results` places a row only when it finds a ``wgs:lat`` /
``wgs:long`` pair, so an entity that publishes a boundary cannot be drawn. This
module widens that to any shape, for any ontology, without knowing what the data
is about.

The trick is to key on the **datatype**, not the predicate. GeoSPARQL literals
carry their own type — ``geo:wktLiteral``, ``geo:geoJSONLiteral`` — so a
geometry is recognisable from the literal alone. A registry of predicate names
would be endless (``geo:asWKT``, ``locn:geometry``, ``georss:polygon`` and every
in-house property ever minted); a registry of datatypes is two entries and
catches all of them, including vocabularies written after this code.

Everything is normalised to GeoJSON geometry, which is what the map layer draws
and what Leaflet consumes directly.

Deliberately not supported: GML and KML literals (rare in the SKOS/OWL data ster
edits), and reprojection from anything other than CRS84 / EPSG:4326 — that needs
a projection library, and drawing metres as if they were degrees is worse than
declining to draw at all.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Final

import rdflib
from rdflib.namespace import GEO, XSD

from .model import is_builtin_uri

# The W3C Basic Geo namespace is http, not https — rdflib binds `wgs` to an
# https variant that real data does not use, so this one is spelled out. Flagged
# by clear-text-protocol rules; it is an identifier, never a URL to fetch.
WGS84 = "http://www.w3.org/2003/01/geo/wgs84_pos#"  # NOSONAR - RDF namespace IRI
LAT = rdflib.URIRef(WGS84 + "lat")
LONG = rdflib.URIRef(WGS84 + "long")


def _number(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def coordinates_of(graph: rdflib.Graph, node: rdflib.URIRef) -> tuple[float, float] | None:
    """WGS84 coordinates for *node*, or None when it carries none usable.

    Lives here rather than in geo_results because that module now builds on this
    one: the vocabulary constants belong with the geometry layer, and having them
    in one place is what stops the http/https trap above being re-set twice.
    """
    latitude = graph.value(node, LAT)
    longitude = graph.value(node, LONG)
    if latitude is None or longitude is None:
        return None
    lat, long = _number(str(latitude)), _number(str(longitude))
    if lat is None or long is None:
        return None
    return lat, long


# Literal datatypes that announce a geometry. The whole detection strategy.
WKT_LITERAL = GEO.wktLiteral
GEOJSON_LITERAL = GEO.geoJSONLiteral
GEOMETRY_DATATYPES = frozenset({WKT_LITERAL, GEOJSON_LITERAL})

# Coordinate reference systems whose axis order we can honour without projecting.
# CRS84 is GeoSPARQL's default and is already longitude-latitude, like GeoJSON.
# EPSG:4326 is the same datum with the axes the other way round.
# OGC names its coordinate reference systems with http IRIs, and a WKT literal
# carries the name verbatim: "<http://www.opengis.net/def/crs/OGC/1.3/CRS84>
# POINT(...)". These are matched against that text, never fetched — spelling
# them https would simply stop them matching any real literal.
_CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"  # NOSONAR - CRS identifier
_EPSG_4326 = "http://www.opengis.net/def/crs/EPSG/0/4326"  # NOSONAR - CRS identifier
_LAT_FIRST_CRS = frozenset({_EPSG_4326})
_KNOWN_CRS = frozenset({_CRS84, *_LAT_FIRST_CRS})

# WKT tags mapped to their GeoJSON type name.
_WKT_TYPES = {
    "POINT": "Point",
    "LINESTRING": "LineString",
    "POLYGON": "Polygon",
    "MULTIPOINT": "MultiPoint",
    "MULTILINESTRING": "MultiLineString",
    "MULTIPOLYGON": "MultiPolygon",
    "GEOMETRYCOLLECTION": "GeometryCollection",
}
# How many levels of list wrap the coordinate pairs of each type.
_NESTING = {
    "Point": 0,
    "LineString": 1,
    "MultiPoint": 1,
    "Polygon": 2,
    "MultiLineString": 2,
    "MultiPolygon": 3,
}


@dataclass(frozen=True)
class Geometry:
    """A resolved geometry: its GeoJSON, its kind, and a point standing for it.

    *centroid* is (lat, long) — the order the map layer and the clustering
    control already use — so a shape can be grouped alongside plain points
    instead of dropping out of the feature.
    """

    geojson: dict
    centroid: tuple[float, float]

    @property
    def kind(self) -> str:
        return str(self.geojson.get("type", ""))


# ── WKT → GeoJSON ─────────────────────────────────────────────────────────────


def _split_crs(wkt: str) -> tuple[str | None, str]:
    """Separate an optional ``<crs-uri>`` prefix from the geometry text."""
    text = wkt.strip()
    if not text.startswith("<"):
        return None, text
    closing = text.find(">")
    if closing == -1:
        return None, text
    return text[1:closing].strip(), text[closing + 1 :].strip()


def _numbers(chunk: str) -> list[float] | None:
    """One coordinate: the first two ordinates, ignoring any Z or M."""
    parts = chunk.replace(",", " ").split()
    try:
        values = [float(p) for p in parts[:2]]
    except ValueError:
        return None
    return values if len(values) == 2 else None


def _parse_coords(body: str, depth: int, lat_first: bool) -> object | None:
    """Parse WKT coordinate text *depth* levels of parentheses deep."""
    body = body.strip()
    if depth == 0:
        pair = _numbers(body.strip("()"))
        if pair is None:
            return None
        return [pair[1], pair[0]] if lat_first else pair
    if not (body.startswith("(") and body.endswith(")")):
        return None
    parts = _split_top_level(body[1:-1])
    if not parts:
        return None
    out = []
    for part in parts:
        child = _parse_coords(part, depth - 1, lat_first)
        if child is None:
            return None
        out.append(child)
    return out


def _split_top_level(text: str) -> list[str]:
    """Split on commas that are not inside parentheses."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _tag_and_body(text: str) -> tuple[str, str] | None:
    """The WKT type tag and its parenthesised body, dropping any Z/M marker."""
    opening = text.find("(")
    if opening == -1:
        return None
    head = text[:opening].strip().upper().split()
    if not head:
        return None
    return head[0], text[opening:].strip()


def wkt_to_geojson(wkt: str) -> dict | None:
    """Convert a WKT literal to a GeoJSON geometry, or None when it cannot be drawn.

    Returns None rather than raising: these strings come from whatever file the
    user opened, and one malformed literal must not take the map down.
    """
    crs, text = _split_crs(wkt)
    if crs is not None and crs not in _KNOWN_CRS:
        return None  # a projected system: declining beats misplacing by a continent
    lat_first = crs in _LAT_FIRST_CRS
    parsed = _tag_and_body(text)
    if parsed is None:
        return None
    tag, body = parsed
    kind = _WKT_TYPES.get(tag)
    if kind is None:
        return None
    if kind == "GeometryCollection":
        return _collection(body, lat_first)
    coordinates = _parse_coords(body, _NESTING[kind], lat_first)
    if coordinates is None:
        return None
    return {"type": kind, "coordinates": coordinates}


def _collection(body: str, lat_first: bool) -> dict | None:
    """A GEOMETRYCOLLECTION: parse each member, keep the ones that survive."""
    if not (body.startswith("(") and body.endswith(")")):
        return None
    members = []
    for part in _split_top_level(body[1:-1]):
        member = wkt_to_geojson(f"<{_EPSG_4326}> {part}" if lat_first else part)
        if member is not None:
            members.append(member)
    if not members:
        return None
    return {"type": "GeometryCollection", "geometries": members}


# ── centroid ──────────────────────────────────────────────────────────────────


def _positions(node: object) -> list[list[float]]:
    """Every [lon, lat] pair inside a nested GeoJSON coordinate structure."""
    if isinstance(node, list) and node and isinstance(node[0], int | float):
        return [[float(node[0]), float(node[1])]] if len(node) >= 2 else []
    if isinstance(node, list):
        return [pos for child in node for pos in _positions(child)]
    return []


def _centroid_of(geojson: dict) -> tuple[float, float] | None:
    """The mean of a geometry's positions, as (lat, long).

    Deliberately the average of the vertices rather than the area centroid: the
    only use is a representative point for clustering and zoomed-out display, and
    an exact centroid would need real geometry code for no visible gain.
    """
    if geojson.get("type") == "GeometryCollection":
        positions = [
            p for g in geojson.get("geometries", []) for p in _positions(g.get("coordinates"))
        ]
    else:
        positions = _positions(geojson.get("coordinates"))
    if not positions:
        return None
    # A closed ring repeats its first vertex as its last. Counting that corner
    # twice drags the mean towards it — France came out on its south-west corner
    # rather than its middle, which is where the cluster dot would have landed.
    unique = [list(pos) for pos in {(p[0], p[1]) for p in positions}]
    longitude = sum(p[0] for p in unique) / len(unique)
    latitude = sum(p[1] for p in unique) / len(unique)
    return latitude, longitude


# ── resolution ────────────────────────────────────────────────────────────────


def _geojson_from_literal(literal: rdflib.Literal) -> dict | None:
    """Read a geometry out of a literal whose datatype says it holds one."""
    if literal.datatype == WKT_LITERAL:
        return wkt_to_geojson(str(literal))
    try:
        parsed = json.loads(str(literal))
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) and "type" in parsed else None


def _literal_on(graph: rdflib.Graph, node: rdflib.term.Node) -> dict | None:
    """The first drawable geometry literal directly on *node*, whatever the predicate."""
    for _p, obj in graph.predicate_objects(node):
        if isinstance(obj, rdflib.Literal) and obj.datatype in GEOMETRY_DATATYPES:
            geometry = _geojson_from_literal(obj)
            if geometry is not None:
                return geometry
    return None


def _geometry_nodes(graph: rdflib.Graph, node: rdflib.URIRef) -> list[rdflib.term.Node]:
    """Geometry nodes for *node*, the author's default first."""
    default = list(graph.objects(node, GEO.hasDefaultGeometry))
    others = [g for g in graph.objects(node, GEO.hasGeometry) if g not in default]
    return [*default, *others]


def _asserted_centroid(graph: rdflib.Graph, node: rdflib.URIRef) -> tuple[float, float] | None:
    """``geo:hasCentroid`` if the author gave one — their answer beats our average."""
    for centre in graph.objects(node, GEO.hasCentroid):
        geometry = _literal_on(graph, centre)
        if geometry is not None:
            return _centroid_of(geometry)
    return None


def geometry_of(graph: rdflib.Graph, node: rdflib.URIRef) -> Geometry | None:
    """The geometry to draw for *node*, or None when it carries nothing usable.

    The ladder, in order: the author's ``geo:hasDefaultGeometry``, then any other
    ``geo:hasGeometry``, then a geometry literal sitting directly on the entity
    under any predicate at all, then plain ``wgs:lat`` / ``wgs:long``.
    """
    geojson = None
    for candidate in _geometry_nodes(graph, node):
        geojson = _literal_on(graph, candidate)
        if geojson is not None:
            break
    if geojson is None:
        geojson = _literal_on(graph, node)
    if geojson is None:
        coordinates = coordinates_of(graph, node)
        if coordinates is None:
            return None
        latitude, longitude = coordinates
        return Geometry(
            geojson={"type": "Point", "coordinates": [longitude, latitude]},
            centroid=(latitude, longitude),
        )

    centroid = _asserted_centroid(graph, node) or _centroid_of(geojson)
    if centroid is None:
        return None
    return Geometry(geojson=geojson, centroid=centroid)


# ── place hierarchy ───────────────────────────────────────────────────────────
#
# A map that draws one level at a time needs to know which level a place belongs
# to. Taking that from the class hierarchy rather than from names means adding a
# level to an ontology adds a level to the map, with no code change here.

# Containment predicates every vocabulary agrees on. An ontology's own is found
# by _declared_containment below rather than listed here: naming one would mean
# ster knowing a particular ontology, which is the thing this module avoids.
_STANDARD_WITHIN = (
    # Vocabulary IRIs, compared against what the file says — an https variant is
    # a *different* IRI that no real data uses, so it would silently match
    # nothing. rdflib ships exactly that bug for wgs84_pos, which is why WGS84
    # above is spelled out by hand.
    "http://www.w3.org/2004/02/skos/core#broader",  # NOSONAR - RDF predicate IRI
    "http://purl.org/dc/terms/isPartOf",  # NOSONAR - RDF predicate IRI
    "http://www.opengis.net/ont/geosparql#sfWithin",  # NOSONAR - RDF predicate IRI
    "http://www.geonames.org/ontology#parentFeature",  # NOSONAR - RDF predicate IRI
)


def _declared_containment(graph: rdflib.Graph) -> tuple[str, ...]:
    """Object properties whose domain and range are the same class.

    That is what a containment link looks like when an ontology declares its own:
    a place inside a place, an organisation inside an organisation. Inferring it
    beats hard-coding, which would tie this module to one vocabulary — and the
    first version of it did exactly that, naming the demo's own predicate.
    """
    from rdflib.namespace import OWL, RDF, RDFS  # noqa: PLC0415

    cached = getattr(graph, "_ster_containment", None)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    # A symmetric property is never containment, whatever its domain and range
    # say. Containment is antisymmetric by definition — if A contains B then B
    # does not contain A — so a relation that holds both ways cannot be one.
    # Without this, declaring competesWith made the drill-down follow rivalry and
    # gave a business unit a "parent" that was simply its competitor.
    symmetric = set(graph.subjects(RDF.type, OWL.SymmetricProperty))
    found = []
    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
        if prop in symmetric:
            continue
        domains = set(graph.objects(prop, RDFS.domain))
        ranges = set(graph.objects(prop, RDFS.range))
        if domains and domains == ranges:
            found.append(str(prop))
    result = tuple(found)
    try:
        graph._ster_containment = result  # type: ignore[attr-defined]
    except AttributeError:  # a graph that refuses attributes — recompute instead
        pass
    return result


def _containment_classes(graph: rdflib.Graph) -> set[str]:
    """The classes the drill-down is built on: the containment property's own
    domain, plus everything beneath it."""
    from rdflib.namespace import RDFS  # noqa: PLC0415

    roots = {
        str(d)
        for prop in _declared_containment(graph)
        for d in graph.objects(rdflib.URIRef(prop), RDFS.domain)
    }
    seen, frontier = set(roots), list(roots)
    while frontier:
        current = frontier.pop()
        for sub in graph.subjects(RDFS.subClassOf, rdflib.URIRef(current)):
            if str(sub) not in seen:
                seen.add(str(sub))
                frontier.append(str(sub))
    return seen


_LIT_LABEL: Final = "label"
_LIT_VALUES: Final = "values"


def _attaches_to_hierarchy(
    graph: rdflib.Graph, prop: rdflib.term.Node, inside: set[str], rdfs: object
) -> bool:
    """True when *prop* hangs a non-place onto the containment tree.

    Range inside the tree, domain outside it, and the domain's instances must
    actually carry a position — that last test is what separates "is located at"
    from "has something to do with".
    """
    if str(prop) in _declared_containment(graph):
        return False
    domains = {str(d) for d in graph.objects(prop, rdfs.domain)}  # type: ignore[attr-defined]
    ranges = {str(r) for r in graph.objects(prop, rdfs.range)}  # type: ignore[attr-defined]
    if not (domains and ranges) or not ranges <= inside or domains == ranges:
        return False
    return any(_class_is_located(graph, d) for d in domains)


def attachment_predicates(graph: rdflib.Graph) -> tuple[str, ...]:
    """Properties that hang something onto the hierarchy without it being a place.

    Most ontologies model geography as a containment chain and then attach
    something else to the end of it. A store, a warehouse, a building: none is a
    *kind of* city, and subclassing them under the geographic class just to get
    them on a map is modelling for the tool rather than for the truth.

    They say it with a property instead — ``Store --locatedIn--> City`` — and it
    is recognisable from the declaration: the range is inside the containment
    tree and the domain is something else. No vocabulary is named here, so any
    spelling works.

    Pointing into the hierarchy is not enough on its own, though. A business unit
    may name the country it trades in without being anywhere; taking that as a
    location would hang phantom nodes under every country. So the domain must be
    a class whose instances actually carry a position — that is what separates
    "is located at" from "has something to do with".
    """
    from rdflib.namespace import OWL, RDF, RDFS  # noqa: PLC0415

    cached = getattr(graph, "_ster_attachment", None)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    inside = _containment_classes(graph)
    found = []
    if inside:
        found = [
            str(prop)
            for prop in graph.subjects(RDF.type, OWL.ObjectProperty)
            if _attaches_to_hierarchy(graph, prop, inside, RDFS)
        ]
    result = tuple(found)
    try:
        graph._ster_attachment = result  # type: ignore[attr-defined]
    except AttributeError:
        pass
    return result


def _class_is_located(graph: rdflib.Graph, cls: str) -> bool:
    """True when instances of *cls* carry a position of their own.

    Checked against the data rather than assumed from the name: a store has
    coordinates, a business unit does not, and only the first is somewhere.
    """
    from rdflib.namespace import RDF  # noqa: PLC0415

    for i, instance in enumerate(graph.subjects(RDF.type, rdflib.URIRef(cls))):
        if i > 50:  # a sample settles it; scanning every store proves nothing more
            break
        if geometry_of(graph, instance) is not None:  # type: ignore[arg-type]
            return True
    return False


def _node_cache(graph: rdflib.Graph, name: str) -> dict:
    """A per-graph memo dict, created on first use.

    A graph that refuses the attribute — a read-only or proxied store — gets a
    throwaway dict, so the answer is still correct and only the saving is lost.
    """
    cache = getattr(graph, name, None)
    if cache is None:
        cache = {}
        try:
            setattr(graph, name, cache)
        except AttributeError:
            pass
    return cache  # type: ignore[no-any-return]


def place_parent(graph: rdflib.Graph, node: rdflib.URIRef) -> str | None:
    """The place containing *node*, by containment or by attachment.

    Memoised per graph. Building the map asked this 27,928 times for 1,951
    places — fourteen times each — because the level walk, the ancestor chain
    and the facet scan all need it about the same nodes. The predicates it
    checks are already cached; the repetition was the cost.

    Cached on the graph object, like the containment and attachment lookups
    above: a reload builds a new graph, so the cache goes with the old one.
    """
    memo = _node_cache(graph, "_ster_parent")
    key = str(node)
    if key in memo:
        return memo[key]  # type: ignore[no-any-return]
    found = None
    for predicate in (
        *_declared_containment(graph),
        *attachment_predicates(graph),
        *_STANDARD_WITHIN,
    ):
        parent = graph.value(node, rdflib.URIRef(predicate))
        if parent is not None:
            found = str(parent)
            break
    memo[key] = found
    return found


def place_level(graph: rdflib.Graph, node: rdflib.URIRef) -> int:
    """How deep *node* sits in the containment chain — 0 for the broadest.

    The nesting lives in containment, not in the class tree: Continent,
    BusinessArea, Country and City are *siblings* under a common Place class,
    each naming a level rather than being a kind of the one above. So a continent
    is 0, the areas inside it 1, their countries 2, and so on — and an ontology
    that adds a level gets one on the map with no change here.

    See :func:`place_type` for the class, which is what a level is *called*.
    """
    return _containment_depth(graph, node)


def place_type(graph: rdflib.Graph, node: rdflib.URIRef) -> str:
    """The label of *node*'s most specific modelled class — the level's name."""
    from rdflib.namespace import RDF, RDFS  # noqa: PLC0415

    best, best_depth = "", -1
    for cls in graph.objects(node, RDF.type):
        if not isinstance(cls, rdflib.URIRef) or is_builtin_uri(str(cls)):
            continue
        depth = _subclass_depth(graph, cls, RDFS)
        if depth > best_depth:
            label = graph.value(cls, RDFS.label)
            best, best_depth = (str(label) if label else _local(str(cls))), depth
    return best


def _local(uri: str) -> str:
    return uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _subclass_depth(graph: rdflib.Graph, cls: rdflib.URIRef, rdfs: object) -> int:
    """Steps from *cls* up to a class with no modelled superclass."""
    depth, seen, current = 0, {cls}, cls
    while depth < 32:  # a subclass cycle must not hang the request
        parent = next(
            (
                p
                for p in graph.objects(current, rdfs.subClassOf)  # type: ignore[attr-defined]
                if isinstance(p, rdflib.URIRef) and p not in seen
            ),
            None,
        )
        if parent is None:
            return depth
        seen.add(parent)
        current, depth = parent, depth + 1
    return depth


def _containment_depth(graph: rdflib.Graph, node: rdflib.URIRef) -> int:
    """Steps up the containment chain — the fallback when nothing is typed."""
    depth, seen, current = 0, {str(node)}, node
    while depth < 32:  # a malformed cycle must not hang the request
        parent = place_parent(graph, current)
        if parent is None or parent in seen:
            return depth
        seen.add(parent)
        current, depth = rdflib.URIRef(parent), depth + 1
    return depth


def place_ancestors(graph: rdflib.Graph, node: rdflib.URIRef) -> list[str]:
    """Every place containing *node*, nearest first.

    Sent to the map so it can tell what sits inside what. The client cannot walk
    this itself: a level that carries no geometry is never drawn, so the chain it
    can see has holes exactly where a grouping tier sits.
    """
    chain: list[str] = []
    seen = {str(node)}
    current = node
    while len(chain) < 32:  # a containment cycle must not hang the request
        parent = place_parent(graph, current)
        if parent is None or parent in seen:
            break  # reached the top, or come back round to somewhere we have been
        chain.append(parent)
        seen.add(parent)
        current = rdflib.URIRef(parent)
    return chain


# Coordinates and geometry are already on the map; totalling them would be
# meaningless, so they never count as figures.
_NON_FIGURE_LOCALS = frozenset({"lat", "long", "lng", "latitude", "longitude"})

# A figure must be *declared* numeric, not merely parse as one. A founding year
# stored as a plain string reads as 1091 and was being added to a turnover; so
# would a postcode or a product code. Requiring the datatype means the ontology
# decides what is a quantity.
_NUMERIC_DATATYPES = frozenset(
    str(XSD[name])
    for name in (
        "integer",
        "decimal",
        "float",
        "double",
        "long",
        "int",
        "short",
        "nonNegativeInteger",
        "positiveInteger",
        "unsignedInt",
        "unsignedLong",
    )
)


def numeric_literals(graph: rdflib.Graph, node: rdflib.URIRef) -> list[dict[str, object]]:
    """The node's numeric literal properties, with the label to show them under.

    Sent with each place so the map can total a branch — a country's turnover is
    the sum of its stores', and no triple anywhere states it. Anything that does
    not parse as a number is skipped rather than guessed at.
    """
    from rdflib.namespace import RDFS  # noqa: PLC0415

    figures: list[dict[str, object]] = []
    for predicate, obj in graph.predicate_objects(node):
        if not isinstance(obj, rdflib.Literal):
            continue
        name = str(predicate).rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        if name.lower() in _NON_FIGURE_LOCALS or str(obj.datatype) not in _NUMERIC_DATATYPES:
            continue
        try:
            value = float(str(obj))
        except (TypeError, ValueError):
            continue
        label = graph.value(predicate, RDFS.label)
        figures.append(
            {"prop": str(predicate), _LIT_LABEL: str(label) if label else name, "value": value}
        )
    return figures


# ── overlay layers ────────────────────────────────────────────────────────────
#
# Which layers a map can show is a property of the data, not of ster: a retail
# ontology wants rainfall, a rail one wants track diagrams. They are declared in
# the file and read from it, the same way the drill levels are.

STER_MAP = rdflib.Namespace("https://ster.dev/ns/map#")


def map_layers(graph: rdflib.Graph) -> list[dict[str, object]]:
    """Overlay tile layers the file declares, by label.

    A declaration without a usable tile URL is skipped rather than half-offered:
    a menu entry that cannot draw is worse than no entry.
    """
    from rdflib.namespace import RDF  # noqa: PLC0415

    layers = []
    for node in graph.subjects(RDF.type, STER_MAP.MapLayer):
        url = _usable_url(graph.value(node, STER_MAP.tileUrl))
        if url is not None:
            layers.append(_layer_record(graph, node, url))
    return sorted(layers, key=lambda layer: str(layer[_LIT_LABEL]))


def _usable_url(raw: object) -> str | None:
    """A tile URL ster is willing to request, or None.

    Restricted to http(s): these strings come from whatever file was opened, and
    neither a ``javascript:`` URL nor a ``file://`` one belongs in a tile request.
    """
    if raw is None:
        return None
    url = _fill_placeholders(str(raw))
    # A scheme allow-list, not a connection: this is the check that keeps
    # javascript: and file:// out of a tile request.
    if url is None or not url.lower().startswith(("http://", "https://")):  # NOSONAR
        return None
    return url


def _text(
    graph: rdflib.Graph, node: rdflib.term.Node, prop: rdflib.URIRef, default: str = ""
) -> str:
    """A stated literal's text, or the default when the layer does not state it."""
    value = graph.value(node, prop)
    return default if value is None else str(value)


def _opacity(graph: rdflib.Graph, node: rdflib.term.Node) -> float:
    """Opaque unless the layer says otherwise, and unaffected by a bad number."""
    try:
        return float(_text(graph, node, STER_MAP.opacity, "1"))
    except ValueError:
        return 1.0


def _layer_record(graph: rdflib.Graph, node: rdflib.term.Node, url: str) -> dict[str, object]:
    """One menu entry, from a declaration already known to carry a usable URL."""
    from rdflib.namespace import RDFS  # noqa: PLC0415

    # Naming WMS layers is what makes it a WMS request. Most public geodata —
    # national weather services, environment agencies, INSPIRE — publishes this
    # way rather than as {z}/{x}/{y} tiles.
    wms_layers = graph.value(node, STER_MAP.wmsLayers)
    return {
        _LIT_LABEL: _text(graph, node, RDFS.label) or _local(str(node)),
        "url": url,
        "attribution": _text(graph, node, STER_MAP.attribution),
        "opacity": _opacity(graph, node),
        "kind": "wms" if wms_layers is not None else "tile",
        "wmsLayers": _text(graph, node, STER_MAP.wmsLayers),
        "wmsFormat": _text(graph, node, STER_MAP.wmsFormat, "image/png"),
        # Transparent by default: an opaque overlay hides the basemap and
        # everything the query drew underneath it.
        "wmsTransparent": _text(graph, node, STER_MAP.wmsTransparent, "true").lower().strip()
        != "false",
        "legendUrl": _legend_url(graph.value(node, STER_MAP.legendUrl), url, wms_layers),
        "legendScale": _legend_scale(graph.value(node, STER_MAP.legendScale)),
        "legendUnit": _text(graph, node, STER_MAP.legendUnit),
    }


# A layer that needs an API key names the environment variable holding it, never
# the key itself: an ontology gets committed and shared, and a key written into
# one is published with it.
_PLACEHOLDER = re.compile(r"\{(env|date):([^{}]*)\}")


def _env_value(name: str) -> str | None:
    """The named variable, or None when it is unset."""
    return os.environ.get(name) or None


_DATE_OFFSET = re.compile(r"^([+-])(\d{1,3})d$")


def _date_value(spec: str) -> str | None:
    """An ISO date a stated number of days from today, e.g. ``+2d``.

    Open geodata is nearly always served against a time dimension, and a date
    written into the ontology is right for one day. Stating the offset instead
    keeps a layer working: a 24-hour accumulation, for instance, has nothing to
    show until 24 hours into the forecast, so it must be asked for ahead.
    """
    match = _DATE_OFFSET.match(spec.strip())
    if match is None:
        return None
    days = int(match.group(2)) * (-1 if match.group(1) == "-" else 1)
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


# A layer may need a key or a date that does not belong in a shared file: the
# ontology names what it wants and ster resolves it, so a committed file never
# carries a secret and never carries a date that goes stale.
_RESOLVERS: dict[str, Callable[[str], str | None]] = {"env": _env_value, "date": _date_value}


def _fill_placeholders(url: str) -> str | None:
    """Substitute ``{env:NAME}`` and ``{date:+Nd}``, or None if one cannot be.

    An unfillable placeholder drops the layer rather than yielding a broken URL:
    absent from the menu is honest, whereas an entry that fails on every tile
    looks like ster itself is broken. Tile placeholders — ``{z}``, ``{x}``,
    ``{y}`` — are not addressed here and pass through to Leaflet untouched.
    """
    if not any(f"{{{kind}:" in url for kind in _RESOLVERS):
        return url
    missing = False

    def swap(match: re.Match[str]) -> str:
        nonlocal missing
        value = _RESOLVERS[match.group(1)](match.group(2))
        if value is None:
            missing = True
            return ""
        return value

    filled = _PLACEHOLDER.sub(swap, url)
    # A malformed placeholder survives the regex untouched; leaving it in would
    # send "{date:soon}" to the tile server, so treat it as unfillable too.
    if missing or any(f"{{{kind}:" in filled for kind in _RESOLVERS):
        return None
    return filled


def _legend_url(stated: object, endpoint: str, wms_layers: object) -> str:
    """Where to find the colour scale for a layer.

    A stated legend wins — that is the author's answer. Otherwise a WMS one is
    derived from GetLegendGraphic, which is part of the standard, so a server
    that paints the map in meaningful colours can be asked what they mean. Tile
    services have no equivalent, so they get none rather than a guess.
    """
    from urllib.parse import quote, urlencode  # noqa: PLC0415

    if stated is not None:
        text = _fill_placeholders(str(stated)) or ""
        # Allow-list again, as in _usable_url — vetting a URL, not opening one.
        return text if text and text.lower().startswith(("http://", "https://")) else ""  # NOSONAR
    if wms_layers is None:
        return ""
    joiner = "&" if "?" in endpoint else "?"
    query = urlencode(
        {
            "service": "WMS",
            "version": "1.3.0",
            "request": "GetLegendGraphic",
            "format": "image/png",
            "layer": str(wms_layers),
        },
        quote_via=quote,
    )
    return f"{endpoint}{joiner}{query}"


_HEX_COLOUR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _legend_scale(stated: object) -> list[dict[str, object]]:
    """Parse ``"-30:#7a0177, 0:#c7e9b4, 40:#b10026"`` into ordered ramp stops.

    A WMS legend image lists every bucket its style defines, which for a field
    like temperature is a strip too tall to read. Stating the ramp as a handful
    of value/colour pairs gives both the gradient and its tick labels from one
    line, small enough to sit on the map.

    Every stop must parse: these values become a CSS gradient, so a half-read
    ramp would be drawn wrong and an unvetted one would be a way into the style
    sheet. Anything malformed falls back to the server's own legend image.
    """
    if stated is None:
        return []
    stops: list[dict[str, object]] = []
    for chunk in str(stated).split(","):
        value, _, colour = chunk.strip().partition(":")
        colour = colour.strip()
        if not _HEX_COLOUR.match(colour):
            return []
        try:
            stops.append({"value": float(value.strip()), "color": colour})
        except ValueError:
            return []
    # One stop is a colour, not a ramp: a gradient needs somewhere to run to.
    if len(stops) < 2:
        return []
    return sorted(stops, key=lambda stop: stop["value"])  # type: ignore[arg-type,return-value]


# How far to follow a relation before giving up. Three is enough to reach the
# far side of the usual shape — a shop names its operator, the operator its
# owner, the owner its format — without wandering into unrelated parts of a
# densely linked graph. It is a constant because the right depth is a judgement,
# not a fact.
FACET_DEPTH = 3

# Provenance says how we know a thing, not what it is, so it makes a poor filter:
# an ontology that records its sources properly would otherwise offer "filter by
# which sitemap this came from" beside "filter by brand". Excluding the vocabulary
# is general — PROV-O is a W3C standard, not one ontology's private choice.
_METADATA_NAMESPACES = (
    "http://www.w3.org/ns/prov#",  # NOSONAR
    "http://purl.org/dc/terms/",  # NOSONAR
    "http://purl.org/dc/elements/1.1/",  # NOSONAR
    "http://www.w3.org/ns/dcat#",  # NOSONAR
)


def _symmetric_predicates(graph: rdflib.Graph) -> frozenset[str]:
    """Properties declared owl:SymmetricProperty, cached per graph.

    Through _node_cache rather than its own attribute dance: the fallback for a
    graph that refuses attributes is already written there, and once was enough.
    """
    from rdflib.namespace import OWL, RDF  # noqa: PLC0415

    cache = _node_cache(graph, "_ster_symmetric")
    found = cache.get("declared")
    if found is None:
        found = cache["declared"] = frozenset(
            str(p) for p in graph.subjects(RDF.type, OWL.SymmetricProperty)
        )
    return found  # type: ignore[no-any-return]


def _facet_values_from(
    graph: rdflib.Graph,
    current: rdflib.term.Node,
    containment: set[str],
    seen: set[str],
) -> Iterator[tuple[rdflib.URIRef, list[str]]]:
    """Entities one hop from *current* that are facet values, with their classes.

    Everything that disqualifies a target lives here — containment, metadata,
    already seen, untyped, or a place the drill-down already draws — so the walk
    itself reads as a walk.
    """
    from rdflib.namespace import RDF  # noqa: PLC0415

    # Containment is the drill-down and is covered by it. A symmetric property is
    # a peer link, and a facet says what this place *is*, not what its rivals
    # are — following competesWith dragged the rival's owner, brand and format
    # back onto every store, so a Leroy Merlin shop listed Kingfisher among its
    # groups and filtering by owner selected everything.
    skip = containment | _symmetric_predicates(graph)
    for predicate, target in graph.predicate_objects(current):
        if str(predicate) in skip or not isinstance(target, rdflib.URIRef):
            continue
        if str(predicate).startswith(_METADATA_NAMESPACES):
            continue
        key = str(target)
        if key in seen or (target, RDF.type, None) not in graph:
            continue
        seen.add(key)
        # A place is already on the map; it is a destination, not a facet.
        if place_parent(graph, target) is not None or _has_children(graph, target):
            continue
        classes = [
            c for c in _facet_classes(graph, target) if not c.startswith(_METADATA_NAMESPACES)
        ]
        if classes:
            yield target, classes


def facets_of(
    graph: rdflib.Graph, node: rdflib.URIRef, depth: int = FACET_DEPTH
) -> dict[str, list[str]]:
    """What this place *is*, as opposed to where it is — grouped by class.

    A map of places answers half the question. The other half lives on entities
    the map never draws: which chain runs this shop, which group owns it, what
    format it trades as. Those are facets, and which exist is a property of the
    ontology rather than of ster — so they are discovered, never configured.

    The rule: follow object properties that are not containment, and stop at
    anything that is itself a place, since the drill-down already covers those.
    Whatever remains is a facet, keyed by its own most specific class.
    """

    containment = set(_declared_containment(graph)) | set(_STANDARD_WITHIN)
    found: dict[str, set[str]] = {}
    seen = {str(node)}
    frontier = [node]
    for _ in range(depth):
        nxt = []
        for current in frontier:
            for target, classes in _facet_values_from(graph, current, containment, seen):
                for cls in classes:
                    found.setdefault(cls, set()).add(str(target))
                nxt.append(target)
        frontier = nxt
        if not frontier:
            break
    return {k: sorted(v) for k, v in found.items()}


def _has_children(graph: rdflib.Graph, node: rdflib.term.Node) -> bool:
    """True when something names *node* as its container — so it is a place.

    Memoised for the same reason as :func:`place_parent`: the facet scan asks it
    of every target it reaches, and reaches the same targets from every place.
    """
    memo = _node_cache(graph, "_ster_haschildren")
    key = str(node)
    if key in memo:
        return memo[key]  # type: ignore[no-any-return]
    found = any(
        next(graph.subjects(rdflib.URIRef(predicate), node), None) is not None
        for predicate in (*_declared_containment(graph), *_STANDARD_WITHIN)
    )
    memo[key] = found
    return found


def _superclasses(graph: rdflib.Graph, cls: rdflib.URIRef, rdfs: object) -> set[str]:
    """Every class above *cls*, transitively. Bounded, so a cycle cannot hang."""
    seen: set[rdflib.URIRef] = set()
    frontier = [cls]
    while frontier and len(seen) < 64:
        for parent in graph.objects(frontier.pop(), rdfs.subClassOf):  # type: ignore[attr-defined]
            if isinstance(parent, rdflib.URIRef) and parent not in seen:
                seen.add(parent)
                frontier.append(parent)
    return {str(c) for c in seen}


def _facet_classes(graph: rdflib.Graph, node: rdflib.term.Node) -> list[str]:
    """*node*'s most specific modelled classes — every one, not just the deepest.

    An individual is often classified on more than one axis at once, and the
    axes need not meet: where brands are modelled as classes, a business unit is
    both a BusinessUnit and a LeroyMerlin. Neither subsumes the other, both are
    useful filters, so the entity belongs in both facets. Picking only the
    deepest would silently retire the other menu.

    A class is dropped only when some *other* declared class already implies it,
    since offering Person beside Employee adds a filter that says less.
    """
    from rdflib.namespace import RDF, RDFS  # noqa: PLC0415

    declared = [
        cls
        for cls in graph.objects(node, RDF.type)
        if isinstance(cls, rdflib.URIRef) and not is_builtin_uri(str(cls))
    ]
    implied: set[str] = set()
    for cls in declared:
        implied |= _superclasses(graph, cls, RDFS) - {str(cls)}
    return sorted({str(c) for c in declared} - implied)


def facet_catalogue(graph: rdflib.Graph, uris: list[str]) -> dict[str, dict]:
    """Labels and logos for every facet value reachable from *uris*.

    Sent once beside the places so the menu can draw a button per value without
    a second request. The image is whatever the ontology offers — schema:image,
    schema:logo, foaf:depiction — and is empty when it offers none.
    """
    from rdflib.namespace import RDFS  # noqa: PLC0415

    from .store import IMAGE_PREDICATES  # noqa: PLC0415

    out: dict[str, dict] = {}
    for uri in uris:
        for cls, values in facets_of(graph, rdflib.URIRef(uri)).items():
            entry = out.setdefault(cls, {_LIT_LABEL: _label_of(graph, cls, RDFS), _LIT_VALUES: {}})
            for value in values:
                if value in entry[_LIT_VALUES]:
                    continue
                node = rdflib.URIRef(value)
                image = next(
                    (
                        str(o)
                        for p in IMAGE_PREDICATES
                        for o in graph.objects(node, rdflib.URIRef(p))
                    ),
                    "",
                )
                entry[_LIT_VALUES][value] = {
                    _LIT_LABEL: _label_of(graph, value, RDFS),
                    "image": image,
                }
    return out


def _label_of(graph: rdflib.Graph, uri: str, rdfs: object) -> str:
    label = graph.value(rdflib.URIRef(uri), rdfs.label)  # type: ignore[attr-defined]
    return str(label) if label else _local(uri)


def image_of(graph: rdflib.Graph, node: rdflib.term.Node) -> str:
    """The first picture this entity offers, whatever vocabulary named it."""
    from .store import IMAGE_PREDICATES  # noqa: PLC0415

    return next(
        (str(o) for p in IMAGE_PREDICATES for o in graph.objects(node, rdflib.URIRef(p))),
        "",
    )


def badges_of(graph: rdflib.Graph, uri: str) -> list[dict[str, str]]:
    """Entities that point at this place and carry a picture.

    A polygon says where something is; it does not say who is in it. When an
    ontology links other entities to a place — a business unit to the country it
    trades in, an operator to a region — the map can show their marks on the
    shape itself.

    Discovered rather than configured: anything referencing the place qualifies,
    whatever the property is called. Places are excluded because the drill-down
    already draws them, and an entity with no image is excluded because there
    would be nothing to draw.
    """
    from rdflib.namespace import RDFS  # noqa: PLC0415

    node = rdflib.URIRef(uri)
    found: dict[str, dict[str, str]] = {}
    for subject in graph.subjects(None, node):
        if not isinstance(subject, rdflib.URIRef):
            continue  # a blank node has no identity to show
        key = str(subject)
        if key in found or key == uri:
            continue
        if place_parent(graph, subject) is not None or _has_children(graph, subject):
            continue  # a place: the hierarchy already shows it
        image = image_of(graph, subject)
        if not image:
            continue
        label = graph.value(subject, RDFS.label)
        found[key] = {
            "uri": key,
            _LIT_LABEL: str(label) if label else _local(key),
            "image": image,
        }
    return [found[k] for k in sorted(found)]
