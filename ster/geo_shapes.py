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
from collections.abc import Callable
from dataclasses import dataclass

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
    found = []
    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
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


def place_parent(graph: rdflib.Graph, node: rdflib.URIRef) -> str | None:
    """The place containing *node*, by whichever containment predicate it uses."""
    for predicate in (*_declared_containment(graph), *_STANDARD_WITHIN):
        parent = graph.value(node, rdflib.URIRef(predicate))
        if parent is not None:
            return str(parent)
    return None


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
            {"prop": str(predicate), "label": str(label) if label else name, "value": value}
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
    return sorted(layers, key=lambda layer: str(layer["label"]))


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
        "label": _text(graph, node, RDFS.label) or _local(str(node)),
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
