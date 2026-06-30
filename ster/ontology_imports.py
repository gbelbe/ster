"""Lazy discovery of external ontology properties for the relate picker."""

from __future__ import annotations

import hashlib
import urllib.error
import urllib.request
from pathlib import Path

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "ster" / "ontologies"

_LOCAL_PREFIXES = (
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/2004/02/skos/core#",
    "http://www.w3.org/XML/1998/namespace",
)

# Well-known ontologies users commonly import.
# Each entry: (display name, short prefix, namespace URL)
COMMON_ONTOLOGIES: list[tuple[str, str, str]] = [
    ("FOAF (Friend of a Friend)", "foaf", "http://xmlns.com/foaf/0.1/"),
    ("Schema.org", "schema", "https://schema.org/"),
    ("Dublin Core Terms", "dc", "http://purl.org/dc/terms/"),
    ("VOID (Vocabulary of Interlinked Datasets)", "void", "http://rdfs.org/ns/void#"),
    ("DBpedia Ontology", "dbo", "http://dbpedia.org/ontology/"),
    ("OWL-Time", "time", "http://www.w3.org/2006/time#"),
    ("WGS84 Geo", "geo", "http://www.w3.org/2003/01/geo/wgs84_pos#"),
    ("PROV-O", "prov", "http://www.w3.org/ns/prov#"),
    ("SIOC", "sioc", "http://rdfs.org/sioc/ns#"),
    ("GoodRelations", "gr", "http://purl.org/goodrelations/v1#"),
]


# ── URI helpers ───────────────────────────────────────────────────────────────


def namespace_url_from_uri(uri: str) -> str:
    """Derive the ontology document URL (namespace) from a term URI.

    Hash-style: ``http://xmlns.com/foaf/0.1/Person`` → ``http://xmlns.com/foaf/0.1/``
    Slash-style: ``https://schema.org/Person`` → ``https://schema.org/``
    """
    if "#" in uri:
        return uri[: uri.rfind("#") + 1]
    return uri[: uri.rfind("/") + 1]


def _primary_namespace(taxonomy) -> str | None:
    """Return the most-used namespace among locally-declared classes and individuals."""
    counts: dict[str, int] = {}
    for u in list(taxonomy.owl_classes.keys()) + list(taxonomy.owl_individuals.keys()):
        if "://" in u:
            ns = namespace_url_from_uri(u)
            counts[ns] = counts.get(ns, 0) + 1
    return max(counts, key=lambda k: counts[k]) if counts else None


def is_external_uri(uri: str, taxonomy) -> bool:
    """Return True when *uri* belongs to an imported external namespace.

    A URI is external when its namespace appears in ``taxonomy.namespace_bindings``
    but does NOT match the primary local namespace (the most common namespace
    among the taxonomy's own classes and individuals).
    """
    if _is_builtin(uri):
        return False
    ns = namespace_url_from_uri(uri)
    primary = _primary_namespace(taxonomy)
    if primary and ns == primary:
        return False
    return ns in taxonomy.namespace_bindings.values()


def prefix_label(uri: str, taxonomy) -> str:
    """Return a ``foaf:Person``-style label using ``namespace_bindings``.

    Falls back to the local name fragment if no binding is found.
    """
    ns = namespace_url_from_uri(uri)
    local = uri[len(ns) :]
    for pfx, bound_ns in taxonomy.namespace_bindings.items():
        if bound_ns == ns:
            return f"{pfx}:{local}"
    return local


def add_namespace_to_taxonomy(namespace_url: str, prefix: str, taxonomy) -> None:
    """Register *namespace_url* with *prefix* in ``taxonomy.namespace_bindings``."""
    taxonomy.namespace_bindings[prefix] = namespace_url


def suggest_prefix(namespace_url: str) -> str:
    """Derive a short prefix string from a namespace URL.

    ``http://xmlns.com/foaf/0.1/`` → ``foaf``
    ``https://schema.org/``        → ``schema``
    ``http://dbpedia.org/ontology/`` → ``ontology``
    Falls back to ``ext`` if nothing useful is found.
    """
    url = namespace_url.rstrip("/#")
    segments = [s for s in url.replace("://", "/").split("/") if s]
    for seg in reversed(segments[1:]):
        if seg and not seg[0].isdigit() and not seg.startswith("v") and len(seg) > 1:
            return seg.lower()[:12]
    return "ext"


# ── External class/property discovery ────────────────────────────────────────


def find_external_class_refs(taxonomy) -> set[str]:
    """Return URIs of external (non-built-in) classes referenced in *taxonomy*.

    Scans rdfs:subClassOf on classes and rdf:type on individuals.
    """
    refs: set[str] = set()
    local_uris: set[str] = set(taxonomy.owl_classes.keys())

    for _uri, cls in taxonomy.owl_classes.items():
        for parent in cls.sub_class_of:
            if parent not in local_uris and not _is_builtin(parent):
                refs.add(parent)

    for ind in taxonomy.owl_individuals.values():
        for t in ind.types:
            if t not in local_uris and not _is_builtin(t):
                refs.add(t)

    return refs


def _make_ssl_context():
    """Return an SSL context that uses certifi when available, else system default."""
    import ssl

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _cache_file(namespace_url: str, cache_dir: Path) -> Path:
    """The disk-cache path for *namespace_url* (deterministic, slug + md5 key)."""
    key = hashlib.md5(namespace_url.encode(), usedforsecurity=False).hexdigest()[:8]
    slug = namespace_url.replace("https://", "").replace("http://", "").replace("/", "_")
    return cache_dir / f"{slug}{key}.ttl"


def load_cached_ontology(namespace_url: str, cache_dir: Path | None = None):
    """Return the cached rdflib Graph for *namespace_url* if present, else ``None``.

    Reads the disk cache only — never hits the network — so it is safe to call
    synchronously from the UI thread. The cache directory is resolved at call
    time so tests can redirect ``_DEFAULT_CACHE_DIR``.
    """
    import rdflib

    cache_file = _cache_file(namespace_url, cache_dir or _DEFAULT_CACHE_DIR)
    if not cache_file.exists():
        return None
    g = rdflib.Graph()
    g.parse(str(cache_file), format="turtle")
    return g


def fetch_ontology(namespace_url: str, cache_dir: Path = _DEFAULT_CACHE_DIR):
    """Return an rdflib Graph for *namespace_url*, using a disk cache.

    Returns an empty graph if the URL is unreachable.
    """
    import rdflib

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_file(namespace_url, cache_dir)

    if cache_file.exists():
        g = rdflib.Graph()
        g.parse(str(cache_file), format="turtle")
        return g

    g = rdflib.Graph()
    try:
        ctx = _make_ssl_context()
        req = urllib.request.Request(
            namespace_url, headers={"Accept": "text/turtle, application/rdf+xml, */*"}
        )
        with urllib.request.urlopen(req, context=ctx) as resp:
            content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            data = resp.read()

        # Prefer the server-declared format; fall back by trying each in order.
        _CT_MAP = {
            "text/turtle": "turtle",
            "application/rdf+xml": "xml",
            "application/xml": "xml",
            "application/ld+json": "json-ld",
            "text/n3": "n3",
        }
        preferred = _CT_MAP.get(content_type)
        fmt_order = [preferred] if preferred else []
        for f in ("xml", "turtle", "json-ld", "n3"):
            if f not in fmt_order:
                fmt_order.append(f)

        for fmt in fmt_order:
            try:
                g = rdflib.Graph()
                g.parse(data=data, format=fmt)
                if len(g) > 0:
                    break
            except Exception:
                g = rdflib.Graph()
                continue
        if len(g) > 0:
            g.serialize(destination=str(cache_file), format="turtle")
    except (urllib.error.URLError, OSError):
        pass

    return g


def get_properties_for_class(graph, class_uri: str, superclasses: set[str]):
    """Return OWLProperty-like objects from *graph* compatible with *class_uri*.

    Includes properties whose domain matches *class_uri*, any URI in *superclasses*,
    or properties with no declared domain.
    """
    import rdflib

    from .model import Label, OWLProperty

    RDF = rdflib.RDF
    RDFS = rdflib.RDFS
    OWL = rdflib.OWL

    candidate_classes = {class_uri} | superclasses
    props: list[OWLProperty] = []

    prop_uris: set[str] = set()
    for pt in (OWL.ObjectProperty, OWL.DatatypeProperty, RDF.Property):
        for s in graph.subjects(RDF.type, pt):
            prop_uris.add(str(s))

    for p_uri in prop_uris:
        p_node = rdflib.URIRef(p_uri)
        domains = [str(d) for d in graph.objects(p_node, RDFS.domain)]
        if domains and not any(d in candidate_classes for d in domains):
            continue

        labels_raw = list(graph.objects(p_node, RDFS.label))
        labels = [
            Label(lang=getattr(lb, "language", None) or "en", value=str(lb)) for lb in labels_raw
        ]

        prop_type = "ObjectProperty"
        if (p_node, RDF.type, OWL.DatatypeProperty) in graph:
            prop_type = "DatatypeProperty"

        props.append(OWLProperty(uri=p_uri, prop_type=prop_type, labels=labels, domains=domains))

    return props


def suggest_external_properties(
    taxonomy, individual_types: list[str], cache_dir: Path = _DEFAULT_CACHE_DIR
):
    """Return a merged list of OWLProperty objects for *individual_types*.

    Combines local taxonomy properties (filtered by domain) with properties
    discovered from lazily-fetched external ontologies.  Uses an inlined
    _effective_types to avoid a circular import with nav.logic.
    """
    from .model import OWLProperty

    seen_uris: set[str] = set()
    result: list[OWLProperty] = []

    eff = _effective_types_inline(taxonomy, individual_types)

    for p_uri, prop in taxonomy.owl_properties.items():
        if prop.prop_type not in ("ObjectProperty", "DatatypeProperty", "Property"):
            continue
        if prop.domains and not any(t in prop.domains for t in eff):
            continue
        seen_uris.add(p_uri)
        result.append(prop)

    ext_refs = find_external_class_refs(taxonomy)
    fetched_ns: set[str] = set()

    for ext_uri in ext_refs:
        ns = namespace_url_from_uri(ext_uri)
        if ns in fetched_ns:
            continue
        fetched_ns.add(ns)
        g = fetch_ontology(ns, cache_dir=cache_dir)
        if len(g) == 0:
            continue
        ext_supers: set[str] = set()
        for uri in ext_refs:
            if namespace_url_from_uri(uri) == ns:
                ext_supers.add(uri)
        for p in get_properties_for_class(g, ext_uri, superclasses=ext_supers):
            if p.uri not in seen_uris:
                seen_uris.add(p.uri)
                result.append(p)

    return result


# ── annotation-property verification ──────────────────────────────────────────
# Predicates that are annotation properties by definition in widely-used
# vocabularies — accepted without a per-ontology lookup. The long tail is covered
# by checking an imported ontology's own `rdf:type owl:AnnotationProperty`.

_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_SKOS = "http://www.w3.org/2004/02/skos/core#"
_OWL = "http://www.w3.org/2002/07/owl#"
_DCT = "http://purl.org/dc/terms/"
_DC = "http://purl.org/dc/elements/1.1/"
_FOAF = "http://xmlns.com/foaf/0.1/"
_VANN = "http://purl.org/vocab/vann/"
_SCHEMA = "https://schema.org/"

WELL_KNOWN_ANNOTATION_PROPS: frozenset[str] = frozenset(
    {
        *(f"{_RDFS}{p}" for p in ("label", "comment", "seeAlso", "isDefinedBy")),
        *(
            f"{_SKOS}{p}"
            for p in (
                "note",
                "scopeNote",
                "definition",
                "example",
                "editorialNote",
                "changeNote",
                "historyNote",
                "prefLabel",
                "altLabel",
                "hiddenLabel",
                "notation",
            )
        ),
        *(
            f"{_OWL}{p}"
            for p in (
                "versionInfo",
                "deprecated",
                "priorVersion",
                "backwardCompatibleWith",
                "incompatibleWith",
            )
        ),
        *(
            f"{_DCT}{p}"
            for p in (
                "title",
                "description",
                "creator",
                "contributor",
                "publisher",
                "created",
                "modified",
                "date",
                "source",
                "license",
                "rights",
                "subject",
                "language",
                "identifier",
                "abstract",
                "bibliographicCitation",
            )
        ),
        *(f"{_DC}{p}" for p in ("title", "description", "creator", "subject", "rights")),
        *(f"{_FOAF}{p}" for p in ("depiction", "homepage", "name", "page", "logo", "maker")),
        *(
            f"{_VANN}{p}"
            for p in ("preferredNamespacePrefix", "preferredNamespaceUri", "example", "usageNote")
        ),
        *(f"{_SCHEMA}{p}" for p in ("image", "description", "name", "sameAs", "url")),
    }
)


def _external_is_annotation_property(taxonomy, predicate: str) -> bool:
    """True when *predicate* is declared ``owl:AnnotationProperty`` in an imported
    (cached) external ontology — i.e. one bound in ``namespace_bindings``."""
    import rdflib

    ns = namespace_url_from_uri(predicate)
    if ns not in set(taxonomy.namespace_bindings.values()):
        return False
    g = load_cached_ontology(ns)
    if g is None:
        return False
    return (rdflib.URIRef(predicate), rdflib.RDF.type, rdflib.OWL.AnnotationProperty) in g


def is_annotation_property(taxonomy, predicate: str) -> bool:
    """Whether *predicate* is (known to be) an annotation property.

    True when it is declared ``owl:AnnotationProperty`` in the local ontology, is a
    well-known annotation predicate, or is declared ``owl:AnnotationProperty`` in an
    imported (cached) external ontology. Otherwise False — the caller warns and may
    declare it locally.
    """
    prop = taxonomy.owl_properties.get(predicate)
    if prop is not None and prop.prop_type == "AnnotationProperty":
        return True
    if predicate in WELL_KNOWN_ANNOTATION_PROPS:
        return True
    return _external_is_annotation_property(taxonomy, predicate)


# ── Private helpers ───────────────────────────────────────────────────────────


def _effective_types_inline(taxonomy, individual_types: list[str]) -> set[str]:
    """Walk rdfs:subClassOf upward, returning all reachable class URIs.

    Inlined here to avoid a circular import with nav.logic.
    """
    result: set[str] = set()

    def _walk(uri: str) -> None:
        if uri in result:
            return
        result.add(uri)
        cls = taxonomy.owl_classes.get(uri)
        if cls:
            for parent in cls.sub_class_of:
                _walk(parent)

    for t in individual_types:
        _walk(t)
    return result


def _is_builtin(uri: str) -> bool:
    return any(uri.startswith(p) for p in _LOCAL_PREFIXES)
