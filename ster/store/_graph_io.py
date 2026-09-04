"""Low-level RDF-graph parsing and indexing.

Two parallel paths build the same ``_Index`` (subject → [(predicate, object)],
rdf:type → [subjects], URIs implied to be classes): a fast native path via
pyoxigraph (:func:`_native_index`) and a generic rdflib-graph walk
(:func:`_graph_index`), used when pyoxigraph is unavailable or unmapped for the
format. :func:`_parse_graph`/:func:`_parse_into` build a plain rdflib Graph for
callers (e.g. format conversion) that need one directly."""

from __future__ import annotations

from pathlib import Path

from rdflib import RDF, BNode, Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDFS
from rdflib.term import Node

from ._format import _SNIFF_BYTES, _detect_format, _sniff_format

_Index = tuple[dict[str, list[tuple[Node, Node]]], dict[str, list[str]], set[str]]
_OX_FORMATS = {"turtle": "TURTLE", "nt": "N_TRIPLES", "xml": "RDF_XML"}
_DATASET_FORMATS = {"trig"}


def _parse_into(fmt: str, path: Path) -> Graph:
    """Parse *path* as *fmt* into a single Graph. Dataset formats (TriG) are read into a
    Dataset and every graph — named + default — merged, since ster models one flat graph."""
    if fmt in _DATASET_FORMATS:
        ds = Dataset()
        ds.parse(str(path), format=fmt)
        g = Graph()
        for s, p, o, _ctx in ds.quads((None, None, None, None)):
            g.add((s, p, o))
        return g

    g = Graph()
    g.parse(str(path), format=fmt)
    return g


def _ox_term(term: object) -> Node:
    """Convert one pyoxigraph term to its rdflib equivalent."""
    kind = type(term).__name__
    value = term.value  # type: ignore[attr-defined]
    if kind == "NamedNode":
        return URIRef(value)
    if kind == "BlankNode":
        return BNode(value)
    # A language-tagged literal also reports rdf:langString as its datatype;
    # rdflib refuses both at once, so the language tag wins.
    if lang := getattr(term, "language", None):
        return Literal(value, lang=lang)
    datatype = getattr(term, "datatype", None)
    return Literal(value, datatype=URIRef(datatype.value) if datatype else None)


def _xmlns_prefixes(path: Path) -> dict[str, str] | None:
    """Prefix bindings declared in an RDF/XML document, or None if unsafe to read.

    pyoxigraph's RDF/XML parser does not report xmlns declarations, so they are
    read with expat, which streams the document without building a tree — on a
    32MB file that costs 0.9s against 8.1s for a full rdflib parse.

    Entity-expansion attacks ("billion laughs") need a DTD to declare the
    entities, so a document carrying one is refused outright and the caller falls
    back to rdflib rather than this reader seeing it. A DOCTYPE is only legal
    before the root element, so the head of the file is the whole search space.
    """
    import xml.etree.ElementTree as ET  # noqa: PLC0415

    try:
        if b"<!DOCTYPE" in path.read_bytes()[:_SNIFF_BYTES]:
            return None
    except OSError:
        return None

    found: dict[str, str] = {}
    try:
        # No DTD, so entity expansion cannot be triggered; external entities are
        # not resolved by ElementTree in any case.
        for _event, (prefix, uri) in ET.iterparse(str(path), events=("start-ns",)):  # noqa: S314
            found.setdefault(prefix, uri)
    except ET.ParseError:
        return None
    return found


def _bindings_graph(prefixes: dict[str, str]) -> Graph:
    """An empty Graph carrying *prefixes*, for :func:`_capture_namespaces`.

    Replaying them through rdflib's namespace manager keeps its disambiguation —
    a file binding ``geo:`` to wgs84 becomes ``geo1`` because rdflib reserves
    ``geo`` for GeoSPARQL — so the native path reports exactly what rdflib would.
    """
    g = Graph()
    for prefix, uri in prefixes.items():
        g.namespace_manager.bind(prefix, Namespace(uri), replace=False)
    return g


def _native_index(fmt: str, path: Path) -> tuple[_Index, Graph] | None:
    """Parse *path* in Rust into ster's index, or None to use the rdflib path.

    None means "this parser cannot do it" — an unmapped format, a missing
    pyoxigraph, or bytes it rejects — never a hard failure, so a file that only
    rdflib's more lenient reader accepts still opens.
    """
    ox_format = _OX_FORMATS.get(fmt)
    if ox_format is None:
        return None
    try:
        import pyoxigraph  # noqa: PLC0415
    except ImportError:
        return None

    index: dict[str, list[tuple[Node, Node]]] = {}
    subjects_by_type: dict[str, list[str]] = {}
    class_refs: set[str] = set()
    try:
        with path.open("rb") as handle:
            parser = pyoxigraph.parse(handle, format=getattr(pyoxigraph.RdfFormat, ox_format))
            for quad in parser:
                _index_quad(quad, index, subjects_by_type, class_refs)
            prefixes = dict(parser.prefixes)
    except Exception:  # noqa: BLE001 — any parse failure falls back to rdflib
        return None

    if fmt == "xml":
        # Losing the bindings would silently change what ster round-trips, so an
        # unreadable header sends the whole load back to rdflib.
        if (xml_prefixes := _xmlns_prefixes(path)) is None:
            return None
        prefixes = xml_prefixes
    return (index, subjects_by_type, class_refs), _bindings_graph(prefixes)


def _index_quad(
    quad: object,
    index: dict[str, list[tuple[Node, Node]]],
    subjects_by_type: dict[str, list[str]],
    class_refs: set[str],
) -> None:
    """Fold one pyoxigraph quad into the index, mirroring :func:`_graph_index`."""
    subject, predicate, obj = quad.subject, quad.predicate, quad.object  # type: ignore[attr-defined]
    p = _ox_term(predicate)
    o = _ox_term(obj)
    s = _ox_term(subject)
    _note_class_ref(class_refs, p, s, o)
    if type(subject).__name__ != "NamedNode":
        return
    uri = subject.value  # type: ignore[attr-defined]
    index.setdefault(uri, []).append((p, o))
    if p == RDF.type:
        subjects_by_type.setdefault(str(o), []).append(uri)


def _note_class_ref(refs: set[str], p: Node, s: Node, o: Node) -> None:
    """Record URIs that a schema predicate implies are classes.

    Collected while indexing so the caller never needs to re-scan the graph, and
    so blank-node subjects (which the index skips) still contribute their objects.
    """
    if p == RDFS.subClassOf:
        if isinstance(s, URIRef):
            refs.add(str(s))
        if isinstance(o, URIRef):
            refs.add(str(o))
    elif p in (RDFS.domain, RDFS.range) and isinstance(o, URIRef):
        refs.add(str(o))


def _graph_index(g: Graph) -> _Index:
    index: dict[str, list[tuple[Node, Node]]] = {}
    subjects_by_type: dict[str, list[str]] = {}
    class_refs: set[str] = set()
    for s, p, o in g:
        _note_class_ref(class_refs, p, s, o)
        if isinstance(s, URIRef):
            subject = str(s)
            index.setdefault(subject, []).append((p, o))
            if p == RDF.type:
                subjects_by_type.setdefault(str(o), []).append(subject)
    return index, subjects_by_type, class_refs


def _parse_graph(path: Path) -> Graph:
    """Parse *path* into a Graph, falling back to sniffed format if extension-based parse fails."""
    fmt = _detect_format(path)
    try:
        return _parse_into(fmt, path)
    except Exception as exc:
        sniffed = _sniff_format(path)
        if sniffed and sniffed != fmt:
            return _parse_into(sniffed, path)
        raise exc
