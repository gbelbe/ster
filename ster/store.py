"""RDF persistence layer — translates between rdflib.Graph and Taxonomy."""

from __future__ import annotations

import hashlib
import os
import pickle
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from rdflib import RDF, Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, FOAF, OWL, RDFS, SKOS, XSD
from rdflib.term import Node

from .handles import assign_handles

VOID = Namespace("http://rdfs.org/ns/void#")
SCHEMA = Namespace("https://schema.org/")
VANN = Namespace("http://purl.org/vocab/vann/")

NOTE_PROPERTY_URI = "https://example.org/ontology/kai-internal-knowledge#note"

# Prefixes rdflib injects into every fresh Graph — not declared by the user's file.
# (The empty default ":" is excluded too; "wv" is NOT — it is a real user prefix and
# must round-trip, see _bind_namespace.)
_RDFLIB_DEFAULT_PREFIXES: frozenset[str] = frozenset(
    p for p, _ in Graph().namespace_manager.namespaces()
) | frozenset({""})


from .model import (
    Concept,
    ConceptScheme,
    Definition,
    Label,
    LabelType,
    OntologyAnnotation,
    OWLIndividual,
    OWLProperty,
    RDFClass,
    Taxonomy,
    is_builtin_uri,
)


def _annotation_from(predicate: str, obj: object) -> OntologyAnnotation | None:
    """Build an :class:`OntologyAnnotation` from an rdflib object (None for BNodes)."""
    if isinstance(obj, URIRef):
        return OntologyAnnotation(predicate=predicate, value=str(obj), is_iri=True)
    if isinstance(obj, Literal):
        datatype = str(obj.datatype) if obj.datatype else ""
        return OntologyAnnotation(
            predicate=predicate, value=str(obj), lang=obj.language or "", datatype=datatype
        )
    return None


def _annotation_object(a: OntologyAnnotation) -> URIRef | Literal:
    """Render an :class:`OntologyAnnotation` back into an rdflib object."""
    if a.is_iri:
        return URIRef(a.value)
    if a.datatype:
        return Literal(a.value, datatype=URIRef(a.datatype))
    return Literal(a.value, lang=a.lang or None)


# Scheme predicates already captured as structured fields — excluded from the
# generic annotation store so they are not double-counted.
_SCHEME_STRUCTURAL_PREDICATES: frozenset[str] = frozenset(
    {
        str(RDF.type),
        str(DCTERMS.title),
        str(DCTERMS.description),
        str(DCTERMS.creator),
        str(DCTERMS.created),
        str(DCTERMS.language),
        str(SKOS.hasTopConcept),
        str(VOID.uriSpace),
    }
)

_FORMAT_MAP = {
    ".ttl": "turtle",
    ".nt": "nt",
    ".rdf": "xml",
    ".xml": "xml",
    ".owl": "xml",
    ".n3": "n3",
    ".jsonld": "json-ld",
    ".json": "json-ld",
    ".trig": "trig",
}

_RDFXML_EXTENSIONS = {".rdf", ".xml", ".owl"}

# Dataset (named-graph / quad) serialisations. ster models a single flat graph, so on load
# every named graph and the default graph are merged into one — the entities are viewed
# together, without their graph partition (which ster does not represent).
_DATASET_FORMATS = {"trig"}


def _detect_format(path: Path) -> str:
    fmt = _FORMAT_MAP.get(path.suffix.lower())
    if fmt is None:
        raise ValueError(
            f"Unsupported file extension {path.suffix!r}. Use one of: {', '.join(_FORMAT_MAP)}"
        )
    return fmt


def is_rdfxml_path(path: Path) -> bool:
    """Return True if *path* has an RDF/XML file extension."""
    return path.suffix.lower() in _RDFXML_EXTENSIONS


_SNIFF_BYTES = 512


def _sniff_format(path: Path) -> str | None:
    """Guess RDF serialisation format from the first bytes of *path*."""
    try:
        head = path.read_bytes()[:_SNIFF_BYTES].lstrip()
    except OSError:
        return None
    if head.startswith((b"<?xml", b"<rdf:RDF", b"<owl:")):
        return "xml"
    text = head.decode("utf-8", errors="replace").lstrip()
    if text.startswith(("@prefix", "@base", "PREFIX")):
        return "turtle"
    if text.startswith(("{", "[")):
        return "json-ld"
    return None


def detect_format_mismatch(path: Path) -> tuple[str, str] | None:
    """Return (declared_fmt, actual_fmt) if content format differs from extension, else None."""
    declared = _FORMAT_MAP.get(path.suffix.lower())
    if declared is None:
        return None
    actual = _sniff_format(path)
    if actual and actual != declared:
        return declared, actual
    return None


def file_hash(path: Path) -> str:
    """Return an MD5 hex digest of *path*'s content (for change detection)."""
    return hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest()


_LINE_RE = re.compile(r"\bline\s+(\d+)\b", re.IGNORECASE)
_EXCERPT_PREFIX = "  → "
# Keep total formatted line ("  → <content>") within 120 chars
_MAX_LINE_LEN = 120 - len(_EXCERPT_PREFIX)  # 116


def format_parse_error(exc: Exception, path: Path) -> str:
    """Return a human-readable description of a parse error, including the bad line.

    Extracts the line number from the exception message (rdflib, lxml, and most
    other RDF parsers embed "line N" in their error text), reads that line from
    *path*, and formats a three-line message:

        Syntax error in <filename> at line N
          → <content of the offending line, trimmed to 120 chars>
          <original exception text>
    """
    msg = str(exc)
    match = _LINE_RE.search(msg)
    line_no: int | None = int(match.group(1)) if match else None

    line_content: str | None = None
    if line_no is not None:
        try:
            file_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            if 1 <= line_no <= len(file_lines):
                raw = file_lines[line_no - 1]
                line_content = raw if len(raw) <= _MAX_LINE_LEN else raw[: _MAX_LINE_LEN - 1] + "…"
        except OSError:
            pass

    parts: list[str] = []
    if line_no is not None:
        parts.append(f"Syntax error in {path.name} at line {line_no}")
    else:
        parts.append(f"Cannot load {path.name}")
    if line_content is not None:
        parts.append(f"  → {line_content}")
    parts.append(f"  {msg}")
    return "\n".join(parts)


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

    # Speed up parsing of large files if pyoxigraph is installed.
    # rdflib 7.0+ supports store="Oxigraph" which uses a fast Rust-based parser.
    try:
        g = Graph(store="Oxigraph")
    except Exception:  # noqa: BLE001
        # Fall back to default rdflib store (e.g. PluginException, ImportError, ValueError)
        g = Graph()

    g.parse(str(path), format=fmt)
    return g


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


def convert(input_path: Path, output_path: Path) -> Path:
    """Load *input_path* and serialise to *output_path* (formats from extensions)."""
    out_fmt = _detect_format(output_path)
    g = _parse_graph(input_path)
    g.serialize(destination=str(output_path), format=out_fmt)
    return output_path


def convert_to_ttl(input_path: Path, output_path: Path | None = None) -> Path:
    """Convert *input_path* to Turtle, writing to *output_path* (default: same stem + .ttl)."""
    if output_path is None:
        output_path = input_path.with_suffix(".ttl")
    return convert(input_path, output_path)


def _bin_cache_dir() -> Path:
    """Return the directory for binary taxonomy caches."""
    return Path.home() / ".cache" / "ster" / "bin_cache"


def _get_bin_cache_path(path: Path) -> Path:
    """Return a unique, safe cache path for the Given RDF file."""
    # Keyed by absolute path hash to avoid collisions and keep it house-trained
    abs_path = str(path.resolve())
    h = hashlib.md5(abs_path.encode(), usedforsecurity=False).hexdigest()[:16]
    # Use stem to keep it somewhat readable in the cache dir
    return _bin_cache_dir() / f"{path.stem}_{h}.pickle"


def _is_cache_valid(cache_path: Path, source_path: Path) -> bool:
    """Return True if the binary cache is fresh and secure."""
    if not cache_path.is_file() or cache_path.is_symlink():
        return False

    try:
        cache_stat = cache_path.stat()
        if cache_stat.st_mtime <= source_path.stat().st_mtime:
            return False

        # Security: ensure the cache belongs to the current user (owner-only)
        if hasattr(os, "getuid") and cache_stat.st_uid != os.getuid():
            return False
    except OSError:
        return False

    return True


def _try_load_cache(cache_path: Path, source_path: Path) -> Taxonomy | None:
    """Attempt to load the taxonomy from the binary cache."""
    try:
        with open(cache_path, "rb") as f:
            # Local trusted cache generated by the tool itself for ~40x speedup.
            # S301 is waived because we verify file ownership and use a private
            # subdirectory in the user's home folder.
            taxonomy = pickle.load(f)  # noqa: S301
        taxonomy.file_path = source_path
        return taxonomy
    except (pickle.UnpicklingError, EOFError, AttributeError, ImportError, OSError):
        return None


def _try_save_cache(cache_path: Path, taxonomy: Taxonomy) -> None:
    """Save the taxonomy to the binary cache with restrictive permissions."""
    try:
        # Ensure private directory (u+rwx)
        cache_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Create file with restrictive permissions (u+rw)
        fd = os.open(cache_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode=0o600)
        with os.fdopen(fd, "wb") as f:
            # S301 is waived because we verify file ownership and use a private
            # subdirectory in the user's home folder.
            pickle.dump(taxonomy, f, protocol=pickle.HIGHEST_PROTOCOL)
    except (pickle.PicklingError, OSError):
        pass


# ──────────────────────────── public API ─────────────────────────────────────


def load(path: str | Path) -> Taxonomy:
    """Parse an RDF file and return a fully handle-annotated Taxonomy.

    Uses a binary cache file in ~/.cache/ster/bin_cache to speed up subsequent
    loads of large files IF the source file hasn't changed. Caching can be
    disabled by setting STER_NO_CACHE=1 in the environment.
    """
    path = Path(path)
    use_cache = os.environ.get("STER_NO_CACHE") != "1"
    cache_path = _get_bin_cache_path(path)

    if use_cache and _is_cache_valid(cache_path, path):
        taxonomy = _try_load_cache(cache_path, path)
        if taxonomy:
            return taxonomy

    g = _parse_graph(path)
    taxonomy = graph_to_taxonomy(g)
    taxonomy.file_path = path
    assign_handles(taxonomy)

    if use_cache:
        _try_save_cache(cache_path, taxonomy)

    return taxonomy


def save(taxonomy: Taxonomy, path: str | Path) -> None:
    """Serialize a Taxonomy back to an RDF file (format detected from extension).

    The write is atomic: the serialized data goes to a sibling temp file that is
    fsync'd and then ``os.replace``-d onto *path*. A crash or a concurrent reader
    never observes a truncated file, and a failed write leaves the previous file
    intact (no partial overwrite, no leftover temp file).
    """
    path = Path(path)
    fmt = _detect_format(path)
    g = taxonomy_to_graph(taxonomy)
    data = g.serialize(format=fmt)
    _atomic_write_text(path, data)


def _atomic_write_text(path: Path, data: str) -> None:
    """Write *data* to *path* atomically via a sibling temp file + os.replace."""
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# ──────────────────────────── conversion ─────────────────────────────────────


def _load_ontology_node(taxonomy: Taxonomy, ont_uri: str, triples: list[tuple[Node, Node]]) -> None:
    """Load the owl:Ontology node into *taxonomy*."""
    taxonomy.ontology_uri = ont_uri
    for p, o in triples:
        if str(p) == str(RDF.type):
            continue
        anno = _annotation_from(str(p), o)
        if anno is not None:
            taxonomy.ontology_annotations.append(anno)
    if taxonomy.ontology_title is None and taxonomy.ontology_label:
        taxonomy.ontology_title = taxonomy.ontology_label
    if taxonomy.ontology_description is None and taxonomy.ontology_label:
        taxonomy.ontology_description = taxonomy.ontology_label


# ── per-entity parsing (dispatch tables keep each helper ≤ complexity 10) ─────


def _lang_label(o: object, label_type: LabelType = LabelType.PREF) -> Label:
    return Label(lang=getattr(o, "language", None) or "", value=str(o), type=label_type)


def _lang_def(o: object) -> Definition:
    return Definition(lang=getattr(o, "language", None) or "", value=str(o))


def _append_uri_ref(target: list[str], o: object, *, skip_builtin: bool = False) -> None:
    """Append ``str(o)`` to *target* when *o* is a URIRef (optionally skipping builtins)."""
    if isinstance(o, URIRef):
        s = str(o)
        if not (skip_builtin and is_builtin_uri(s)):
            target.append(s)


def _set_note(entity: object, o: object) -> None:
    if isinstance(o, Literal):
        entity.note = str(o)  # type: ignore[attr-defined]


# rdf:type carries the entity's own declaration (owl:Class / owl:*Property); it is
# never a descriptive annotation, so the generic catch-all skips it.
_ENTITY_ANNOTATION_SKIP: frozenset[str] = frozenset({str(RDF.type)})


def _dispatch_predicates(
    triples: list[tuple[Node, Node]],
    handlers: dict[str, Callable[[object], None]],
    annotations: list[OntologyAnnotation] | None = None,
) -> None:
    """Apply ``handlers[predicate](object)`` over a subject's triples. A predicate with
    no handler is captured into *annotations* (the generic bucket) when given — every
    descriptive predicate the structured fields don't model, so it round-trips."""
    for p, o in triples:
        ps = str(p)
        handler = handlers.get(ps)
        if handler is not None:
            handler(o)
        elif annotations is not None and ps not in _ENTITY_ANNOTATION_SKIP:
            anno = _annotation_from(ps, o)
            if anno is not None:
                annotations.append(anno)


def _parse_class(uri: str, triples: list[tuple[Node, Node]]) -> RDFClass:
    """Build an :class:`RDFClass` from its triples (structured fields only)."""
    cls = RDFClass(uri=uri)
    handlers: dict[str, Callable[[object], None]] = {
        str(RDFS.label): lambda o: cls.labels.append(_lang_label(o)),
        str(RDFS.comment): lambda o: cls.comments.append(_lang_def(o)),
        str(RDFS.subClassOf): lambda o: _append_uri_ref(cls.sub_class_of, o, skip_builtin=True),
        str(OWL.equivalentClass): lambda o: _append_uri_ref(cls.equivalent_class, o),
        str(OWL.disjointWith): lambda o: _append_uri_ref(cls.disjoint_with, o),
        str(SCHEMA.image): lambda o: cls.schema_images.append(str(o)),
        str(SCHEMA.video): lambda o: cls.schema_videos.append(str(o)),
        str(SCHEMA.url): lambda o: cls.schema_urls.append(str(o)),
        NOTE_PROPERTY_URI: lambda o: _set_note(cls, o),
    }
    _dispatch_predicates(triples, handlers, annotations=cls.annotations)
    return cls


def _parse_property(uri: str, triples: list[tuple[Node, Node]], prop_type_name: str) -> OWLProperty:
    """Build an :class:`OWLProperty` from its triples (structured fields only)."""
    prop = OWLProperty(uri=uri, prop_type=prop_type_name)
    handlers: dict[str, Callable[[object], None]] = {
        str(RDFS.label): lambda o: prop.labels.append(_lang_label(o)),
        str(RDFS.comment): lambda o: prop.comments.append(_lang_def(o)),
        str(RDFS.domain): lambda o: _append_uri_ref(prop.domains, o),
        str(RDFS.range): lambda o: _append_uri_ref(prop.ranges, o),
        str(RDFS.subPropertyOf): lambda o: _append_uri_ref(prop.sub_property_of, o),
        str(OWL.inverseOf): lambda o: _append_uri_ref(prop.inverse_of, o),
        NOTE_PROPERTY_URI: lambda o: _set_note(prop, o),
    }
    _dispatch_predicates(triples, handlers, annotations=prop.annotations)
    return prop


def _parse_concept(uri: str, triples: list[tuple[Node, Node]]) -> Concept:
    """Build a :class:`Concept` from its triples (structured fields only)."""
    c = Concept(uri=uri)
    handlers: dict[str, Callable[[object], None]] = {
        str(SKOS.prefLabel): lambda o: c.labels.append(_lang_label(o, LabelType.PREF)),
        str(SKOS.altLabel): lambda o: c.labels.append(_lang_label(o, LabelType.ALT)),
        str(SKOS.hiddenLabel): lambda o: c.labels.append(_lang_label(o, LabelType.HIDDEN)),
        str(SKOS.definition): lambda o: c.definitions.append(_lang_def(o)),
        str(SKOS.scopeNote): lambda o: c.scope_notes.append(_lang_def(o)),
        str(SKOS.narrower): lambda o: c.narrower.append(str(o)),
        str(SKOS.broader): lambda o: c.broader.append(str(o)),
        str(SKOS.related): lambda o: c.related.append(str(o)),
        str(SKOS.topConceptOf): lambda o: setattr(c, "top_concept_of", str(o)),
        str(SKOS.broadMatch): lambda o: c.broad_match.append(str(o)),
        str(SKOS.narrowMatch): lambda o: c.narrow_match.append(str(o)),
        str(SKOS.relatedMatch): lambda o: c.related_match.append(str(o)),
        str(SKOS.exactMatch): lambda o: c.exact_match.append(str(o)),
        str(SKOS.closeMatch): lambda o: c.close_match.append(str(o)),
        str(FOAF.focus): lambda o: setattr(c, "focus", str(o)),
        str(SCHEMA.image): lambda o: c.schema_images.append(str(o)),
        str(SCHEMA.video): lambda o: c.schema_videos.append(str(o)),
        str(SCHEMA.url): lambda o: c.schema_urls.append(str(o)),
    }
    _dispatch_predicates(triples, handlers)
    return c


def _parse_scheme(uri: str, triples: list[tuple[Node, Node]]) -> ConceptScheme:
    """Build a :class:`ConceptScheme` from its triples (structured fields only)."""
    scheme = ConceptScheme(uri=uri)
    handlers: dict[str, Callable[[object], None]] = {
        str(DCTERMS.title): lambda o: scheme.labels.append(_lang_label(o)),
        str(DCTERMS.description): lambda o: scheme.descriptions.append(_lang_def(o)),
        str(SKOS.hasTopConcept): lambda o: scheme.top_concepts.append(str(o)),
        str(DCTERMS.creator): lambda o: setattr(scheme, "creator", str(o)),
        str(DCTERMS.created): lambda o: setattr(scheme, "created", str(o)),
        str(DCTERMS.language): lambda o: scheme.languages.append(str(o)),
        str(VOID.uriSpace): lambda o: setattr(scheme, "base_uri", str(o)),
    }
    _dispatch_predicates(triples, handlers, annotations=scheme.annotations)
    return scheme


def _parse_individual(uri: str, triples: list[tuple[Node, Node]]) -> OWLIndividual:
    """Build an :class:`OWLIndividual` from its triples (structured fields only)."""
    ind = OWLIndividual(uri=uri)
    handlers: dict[str, Callable[[object], None]] = {
        str(RDFS.label): lambda o: ind.labels.append(_lang_label(o)),
        str(RDFS.comment): lambda o: ind.comments.append(_lang_def(o)),
        str(SCHEMA.image): lambda o: ind.schema_images.append(str(o)),
        str(SCHEMA.video): lambda o: ind.schema_videos.append(str(o)),
        str(SCHEMA.url): lambda o: ind.schema_urls.append(str(o)),
        NOTE_PROPERTY_URI: lambda o: _set_note(ind, o),
    }

    def _type_handler(o: object) -> None:
        tu = str(o)
        if not is_builtin_uri(tu):
            ind.types.append(tu)

    handlers[str(RDF.type)] = _type_handler

    def _generic_handler(p_str: str, o: object) -> None:
        if isinstance(o, URIRef):
            ind.property_values.append((p_str, str(o)))
        elif isinstance(o, Literal):
            lang = getattr(o, "language", "")
            dt = str(o.datatype) if o.datatype else ""
            ind.literal_values.append((p_str, str(o), f"@{lang}" if lang else dt))

    # Individuals catch *everything* else as property assertions.
    for p, o in triples:
        ps = str(p)
        handler = handlers.get(ps)
        if handler:
            handler(o)
        elif ps not in _ENTITY_ANNOTATION_SKIP:
            _generic_handler(ps, o)

    return ind


def _graph_index(g: Graph) -> tuple[dict[str, list[tuple[Node, Node]]], dict[str, list[str]]]:
    index: dict[str, list[tuple[Node, Node]]] = {}
    subjects_by_type: dict[str, list[str]] = {}
    for s, p, o in g:
        if isinstance(s, URIRef):
            subject = str(s)
            index.setdefault(subject, []).append((p, o))
            if p == RDF.type:
                subjects_by_type.setdefault(str(o), []).append(subject)
    return index, subjects_by_type


def _load_classes(
    g: Graph,
    taxonomy: Taxonomy,
    index: dict[str, list[tuple[Node, Node]]],
    subjects_by_type: dict[str, list[str]],
) -> None:
    class_uris = {
        uri
        for type_uri in (str(RDFS.Class), str(OWL.Class))
        for uri in subjects_by_type.get(type_uri, [])
        if not is_builtin_uri(uri)
    }
    for refs in (
        g.subjects(RDFS.subClassOf, None),
        g.objects(None, RDFS.subClassOf),
        g.objects(None, RDFS.domain),
        g.objects(None, RDFS.range),
    ):
        class_uris.update(
            str(ref) for ref in refs if isinstance(ref, URIRef) and not is_builtin_uri(str(ref))
        )
    for uri in class_uris:
        taxonomy.owl_classes[uri] = _parse_class(uri, index.get(uri, []))


def _load_properties(
    taxonomy: Taxonomy,
    index: dict[str, list[tuple[Node, Node]]],
    subjects_by_type: dict[str, list[str]],
) -> None:
    property_types = {
        str(OWL.ObjectProperty): "ObjectProperty",
        str(OWL.DatatypeProperty): "DatatypeProperty",
        str(OWL.AnnotationProperty): "AnnotationProperty",
        str(RDF.Property): "Property",
    }
    for type_uri, property_type in property_types.items():
        for uri in subjects_by_type.get(type_uri, []):
            if not is_builtin_uri(uri) and uri not in taxonomy.owl_properties:
                taxonomy.owl_properties[uri] = _parse_property(
                    uri, index.get(uri, []), property_type
                )


def _load_individuals(
    taxonomy: Taxonomy,
    index: dict[str, list[tuple[Node, Node]]],
    subjects_by_type: dict[str, list[str]],
) -> None:
    individual_uris = _individual_uris(taxonomy, subjects_by_type)
    for uri in individual_uris:
        taxonomy.owl_individuals[uri] = _parse_individual(uri, index.get(uri, []))


def _individual_uris(taxonomy: Taxonomy, subjects_by_type: dict[str, list[str]]) -> set[str]:
    individual_uris = {
        uri for uri in subjects_by_type.get(str(OWL.NamedIndividual), []) if not is_builtin_uri(uri)
    }
    known_classes = set(taxonomy.owl_classes)
    for type_uri, uris in subjects_by_type.items():
        if type_uri not in known_classes:
            continue
        individual_uris.update(
            uri
            for uri in uris
            if not is_builtin_uri(uri)
            and uri not in taxonomy.owl_classes
            and uri not in taxonomy.concepts
            and uri not in taxonomy.schemes
        )
    return individual_uris


def _capture_namespaces(g: Graph, taxonomy: Taxonomy) -> None:
    for raw_prefix, raw_ns in g.namespace_manager.namespaces():
        prefix, namespace = str(raw_prefix), str(raw_ns)
        if prefix not in _RDFLIB_DEFAULT_PREFIXES:
            taxonomy.namespace_bindings[prefix] = namespace


def graph_to_taxonomy(g: Graph) -> Taxonomy:
    taxonomy = Taxonomy()
    index, subjects_by_type = _graph_index(g)
    for uri in subjects_by_type.get(str(SKOS.ConceptScheme), []):
        taxonomy.schemes[uri] = _parse_scheme(uri, index.get(uri, []))
    for uri in subjects_by_type.get(str(SKOS.Concept), []):
        taxonomy.concepts[uri] = _parse_concept(uri, index.get(uri, []))
    _load_classes(g, taxonomy, index, subjects_by_type)
    if ontology_uris := subjects_by_type.get(str(OWL.Ontology), []):
        _load_ontology_node(taxonomy, ontology_uris[0], index.get(ontology_uris[0], []))
    _load_properties(taxonomy, index, subjects_by_type)
    _load_individuals(taxonomy, index, subjects_by_type)
    _normalize_hierarchy(taxonomy)
    _capture_namespaces(g, taxonomy)
    return taxonomy


# ── per-entity serialization (kept small so taxonomy_to_graph stays under the ratchet) ──


def _serialize_schema_media(g: Graph, ref: URIRef, entity: object) -> None:
    """Emit schema.org image / video / url triples shared by classes, individuals, concepts."""
    for u in entity.schema_images:  # type: ignore[attr-defined]
        g.add((ref, SCHEMA.image, URIRef(u)))
    for u in entity.schema_videos:  # type: ignore[attr-defined]
        g.add((ref, SCHEMA.video, URIRef(u)))
    for u in entity.schema_urls:  # type: ignore[attr-defined]
        g.add((ref, SCHEMA.url, URIRef(u)))


def _serialize_labels_comments(
    g: Graph, ref: URIRef, labels: list[Label], comments: list[Definition]
) -> None:
    """Emit rdfs:label / rdfs:comment triples shared by classes and properties."""
    for lbl in labels:
        g.add((ref, RDFS.label, Literal(lbl.value, lang=lbl.lang or None)))
    for cmt in comments:
        g.add((ref, RDFS.comment, Literal(cmt.value, lang=cmt.lang or None)))


_CONCEPT_LABEL_PREDS = {
    LabelType.PREF: SKOS.prefLabel,
    LabelType.ALT: SKOS.altLabel,
    LabelType.HIDDEN: SKOS.hiddenLabel,
}

# Concept list-valued predicates, as (attribute, RDF predicate) — a table so the
# serialiser is one loop instead of a dozen near-identical ones.
_CONCEPT_LIST_PREDS: tuple[tuple[str, URIRef], ...] = (
    ("narrower", SKOS.narrower),
    ("broader", SKOS.broader),
    ("related", SKOS.related),
    ("broad_match", SKOS.broadMatch),
    ("narrow_match", SKOS.narrowMatch),
    ("related_match", SKOS.relatedMatch),
    ("exact_match", SKOS.exactMatch),
    ("close_match", SKOS.closeMatch),
    ("schema_images", SCHEMA.image),
    ("schema_videos", SCHEMA.video),
    ("schema_urls", SCHEMA.url),
)


def _serialize_concept_scheme(g: Graph, ref: URIRef, taxonomy: Taxonomy, uri: str) -> None:
    """Emit a concept's ``skos:inScheme`` — its own scheme, or all schemes if orphaned."""
    s_uri = _concept_scheme_uri(taxonomy, uri)  # topConceptOf if set, else traverse up
    if s_uri:
        g.add((ref, SKOS.inScheme, URIRef(s_uri)))
    else:  # orphan concept — add to all schemes as a fallback
        for scheme_uri in taxonomy.schemes:
            g.add((ref, SKOS.inScheme, URIRef(scheme_uri)))


def _serialize_concept_literals(g: Graph, ref: URIRef, concept: Concept) -> None:
    """Emit a concept's language-tagged literals: labels, definitions, scope notes."""
    for lbl in concept.labels:
        g.add((ref, _CONCEPT_LABEL_PREDS[lbl.type], Literal(lbl.value, lang=lbl.lang or None)))
    for defn in concept.definitions:
        g.add((ref, SKOS.definition, Literal(defn.value, lang=defn.lang or None)))
    for note in concept.scope_notes:
        g.add((ref, SKOS.scopeNote, Literal(note.value, lang=note.lang or None)))


def _serialize_concept(g: Graph, uri: str, concept: Concept, taxonomy: Taxonomy) -> None:
    """Emit a Concept's triples — the inverse of :func:`_parse_concept`."""
    ref = URIRef(uri)
    g.add((ref, RDF.type, SKOS.Concept))
    _serialize_concept_scheme(g, ref, taxonomy, uri)
    if concept.top_concept_of:
        g.add((ref, SKOS.topConceptOf, URIRef(concept.top_concept_of)))
    _serialize_concept_literals(g, ref, concept)
    for attr, pred in _CONCEPT_LIST_PREDS:
        for u in getattr(concept, attr):
            g.add((ref, pred, URIRef(u)))
    if concept.focus:
        g.add((ref, FOAF.focus, URIRef(concept.focus)))


def _serialize_class(g: Graph, uri: str, rdf_class: RDFClass) -> None:
    ref = URIRef(uri)
    g.add((ref, RDF.type, OWL.Class))
    _serialize_labels_comments(g, ref, rdf_class.labels, rdf_class.comments)
    for parent_uri in rdf_class.sub_class_of:
        g.add((ref, RDFS.subClassOf, URIRef(parent_uri)))
    for eq_uri in rdf_class.equivalent_class:
        g.add((ref, OWL.equivalentClass, URIRef(eq_uri)))
    for dj_uri in rdf_class.disjoint_with:
        g.add((ref, OWL.disjointWith, URIRef(dj_uri)))
    _serialize_schema_media(g, ref, rdf_class)
    if rdf_class.note:
        g.add((ref, URIRef(NOTE_PROPERTY_URI), Literal(rdf_class.note)))
    for a in rdf_class.annotations:
        g.add((ref, URIRef(a.predicate), _annotation_object(a)))


_OWL_PROP_TYPE: dict[str, URIRef] = {
    "ObjectProperty": OWL.ObjectProperty,
    "DatatypeProperty": OWL.DatatypeProperty,
    "AnnotationProperty": OWL.AnnotationProperty,
    "Property": RDF.Property,
}


def _serialize_property(g: Graph, uri: str, prop: OWLProperty) -> None:
    ref = URIRef(uri)
    g.add((ref, RDF.type, _OWL_PROP_TYPE.get(prop.prop_type, OWL.ObjectProperty)))
    _serialize_labels_comments(g, ref, prop.labels, prop.comments)
    for dom in prop.domains:
        g.add((ref, RDFS.domain, URIRef(dom)))
    for rng in prop.ranges:
        g.add((ref, RDFS.range, URIRef(rng)))
    for sup in prop.sub_property_of:
        g.add((ref, RDFS.subPropertyOf, URIRef(sup)))
    for inv in prop.inverse_of:
        g.add((ref, OWL.inverseOf, URIRef(inv)))
    if prop.note:
        g.add((ref, URIRef(NOTE_PROPERTY_URI), Literal(prop.note)))
    for a in prop.annotations:
        g.add((ref, URIRef(a.predicate), _annotation_object(a)))


def _serialize_scheme(g: Graph, uri: str, scheme: ConceptScheme) -> None:
    ref = URIRef(uri)
    g.add((ref, RDF.type, SKOS.ConceptScheme))
    _serialize_scheme_literals(g, ref, scheme)
    _serialize_scheme_relations(g, ref, scheme)
    _serialize_annotations(g, ref, scheme.annotations)


def _serialize_scheme_literals(g: Graph, ref: URIRef, scheme: ConceptScheme) -> None:
    for lbl in scheme.labels:
        g.add((ref, DCTERMS.title, Literal(lbl.value, lang=lbl.lang or None)))
    for desc in scheme.descriptions:
        g.add((ref, DCTERMS.description, Literal(desc.value, lang=desc.lang or None)))
    if scheme.creator:
        g.add((ref, DCTERMS.creator, Literal(scheme.creator)))
    if scheme.created:
        g.add((ref, DCTERMS.created, Literal(scheme.created, datatype=XSD.date)))
    for lang in scheme.languages:
        g.add((ref, DCTERMS.language, Literal(lang)))
    if scheme.base_uri:
        g.add((ref, VOID.uriSpace, Literal(scheme.base_uri)))


def _serialize_scheme_relations(g: Graph, ref: URIRef, scheme: ConceptScheme) -> None:
    for tc_uri in scheme.top_concepts:
        g.add((ref, SKOS.hasTopConcept, URIRef(tc_uri)))


def _serialize_annotations(g: Graph, ref: URIRef, annotations: list[OntologyAnnotation]) -> None:
    for annotation in annotations:
        g.add((ref, URIRef(annotation.predicate), _annotation_object(annotation)))


def _serialize_individual(g: Graph, uri: str, individual: OWLIndividual) -> None:
    ref = URIRef(uri)
    g.add((ref, RDF.type, OWL.NamedIndividual))
    for type_uri in individual.types:
        g.add((ref, RDF.type, URIRef(type_uri)))
    _serialize_labels_comments(g, ref, individual.labels, individual.comments)
    _serialize_individual_values(g, ref, individual)
    _serialize_schema_media(g, ref, individual)
    if individual.note:
        g.add((ref, URIRef(NOTE_PROPERTY_URI), Literal(individual.note)))


def _serialize_individual_values(g: Graph, ref: URIRef, individual: OWLIndividual) -> None:
    for prop_uri, value_uri in individual.property_values:
        g.add((ref, URIRef(prop_uri), URIRef(value_uri)))
    for prop_uri, value, lang_or_datatype in individual.literal_values:
        if lang_or_datatype.startswith("@"):
            literal = Literal(value, lang=lang_or_datatype[1:] or None)
        elif lang_or_datatype:
            literal = Literal(value, datatype=URIRef(lang_or_datatype))
        else:
            literal = Literal(value)
        g.add((ref, URIRef(prop_uri), literal))


def _serialize_ontology(g: Graph, taxonomy: Taxonomy) -> None:
    if not taxonomy.ontology_uri:
        return
    ref = URIRef(taxonomy.ontology_uri)
    g.add((ref, RDF.type, OWL.Ontology))
    for annotation in taxonomy.ontology_annotations:
        g.add((ref, URIRef(annotation.predicate), _annotation_object(annotation)))


def taxonomy_to_graph(taxonomy: Taxonomy) -> Graph:
    g = Graph()
    g.bind("skos", SKOS)
    g.bind("dcterms", DCTERMS)
    g.bind("xsd", XSD)
    g.bind("void", VOID)
    g.bind("rdfs", RDFS)
    g.bind("owl", OWL)
    g.bind("schema", SCHEMA)
    g.bind("vann", VANN)
    g.bind("foaf", FOAF)

    # Re-bind any namespaces captured from the source file (enables round-trip of foaf:, kai:, etc.)
    for prefix, ns in taxonomy.namespace_bindings.items():
        g.bind(prefix, Namespace(ns))

    # Try to bind a short prefix for the primary namespace
    _bind_namespace(g, taxonomy)

    for uri, scheme in taxonomy.schemes.items():
        _serialize_scheme(g, uri, scheme)

    # ── Concepts ─────────────────────────────────────────────────────────────
    for uri, concept in taxonomy.concepts.items():
        _serialize_concept(g, uri, concept, taxonomy)

    # ── OWL/RDFS Classes ─────────────────────────────────────────────────────
    for uri, rdf_class in taxonomy.owl_classes.items():
        _serialize_class(g, uri, rdf_class)

    for uri, individual in taxonomy.owl_individuals.items():
        _serialize_individual(g, uri, individual)

    # ── OWL Properties ────────────────────────────────────────────────────────
    for uri, prop in taxonomy.owl_properties.items():
        _serialize_property(g, uri, prop)

    _serialize_ontology(g, taxonomy)

    return g


# ──────────────────────────── helpers ────────────────────────────────────────


def _normalize_hierarchy(taxonomy: Taxonomy) -> None:
    """Ensure skos:broader/narrower and skos:topConceptOf/hasTopConcept are symmetric."""
    _normalize_concept_links(taxonomy)
    _normalize_scheme_links(taxonomy)
    _assign_orphan_top_concepts(taxonomy)


def _normalize_concept_links(taxonomy: Taxonomy) -> None:
    for uri, concept in taxonomy.concepts.items():
        for child_uri in concept.narrower:
            child = taxonomy.concepts.get(child_uri)
            if child and uri not in child.broader:
                child.broader.append(uri)
        for parent_uri in concept.broader:
            parent = taxonomy.concepts.get(parent_uri)
            if parent and uri not in parent.narrower:
                parent.narrower.append(uri)


def _normalize_scheme_links(taxonomy: Taxonomy) -> None:
    for scheme_uri, scheme in taxonomy.schemes.items():
        for tc_uri in scheme.top_concepts:
            tc_concept = taxonomy.concepts.get(tc_uri)
            if tc_concept and tc_concept.top_concept_of is None:
                tc_concept.top_concept_of = scheme_uri

    for concept_uri, concept in taxonomy.concepts.items():
        if concept.top_concept_of:
            tc_scheme = taxonomy.schemes.get(concept.top_concept_of)
            if tc_scheme and concept_uri not in tc_scheme.top_concepts:
                tc_scheme.top_concepts.append(concept_uri)


def _assign_orphan_top_concepts(taxonomy: Taxonomy) -> None:
    primary = taxonomy.primary_scheme()
    for concept_uri, concept in taxonomy.concepts.items():
        if concept.broader or concept.top_concept_of:
            continue
        in_any_scheme = any(concept_uri in s.top_concepts for s in taxonomy.schemes.values())
        if not in_any_scheme and primary:
            primary.top_concepts.append(concept_uri)
            concept.top_concept_of = primary.uri


def _concept_scheme_uri(
    taxonomy: Taxonomy, uri: str, _visited: frozenset[str] | None = None
) -> str | None:
    """Return the scheme URI for a concept by traversing up to a top concept."""
    if _visited is None:
        _visited = frozenset()
    if uri in _visited:
        return None
    concept = taxonomy.concepts.get(uri)
    if not concept:
        return None
    if concept.top_concept_of:
        return concept.top_concept_of
    _visited = _visited | {uri}
    for parent_uri in concept.broader:
        s = _concept_scheme_uri(taxonomy, parent_uri, _visited)
        if s:
            return s
    return None


def _bind_namespace(g: Graph, taxonomy: Taxonomy) -> None:
    """Bind a short 'wv' fallback prefix for the primary concept namespace —
    unless the user already bound a prefix to it (don't clobber their choice)."""
    uris = list(taxonomy.concepts) + list(taxonomy.schemes)
    if not uris:
        return
    # Find the common base by taking the longest common prefix ending in / or #
    first = uris[0]
    for sep in ("#", "/"):
        if sep in first:
            base = first.rsplit(sep, 1)[0] + sep
            if all(u.startswith(base) for u in uris):
                base_root = base.rstrip("#/")
                if any(ns.rstrip("#/") == base_root for ns in taxonomy.namespace_bindings.values()):
                    return  # a user prefix is already bound to this namespace
                g.bind("wv", Namespace(base))
                return
