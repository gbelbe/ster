"""Graph → Taxonomy: build entities (classes, properties, concepts, schemes,
individuals, the ontology node) from an indexed RDF graph."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from rdflib import RDF, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, FOAF, OWL, RDFS, SKOS
from rdflib.term import Node

from ..model import (
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
from ._constants import _RDFLIB_DEFAULT_PREFIXES, NOTE_PROPERTY_URI, SCHEMA, VOID
from ._graph_io import _graph_index, _Index
from ._normalize import _normalize_hierarchy

_LIT_LANGUAGE: Final = "language"


_ENTITY_ANNOTATION_SKIP: frozenset[str] = frozenset({str(RDF.type)})
_CONCEPT_ANNOTATION_SKIP: frozenset[str] = frozenset({str(SKOS.inScheme)})
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


def _lang_label(o: object, label_type: LabelType = LabelType.PREF) -> Label:
    return Label(lang=getattr(o, _LIT_LANGUAGE, None) or "", value=str(o), type=label_type)


def _lang_def(o: object) -> Definition:
    return Definition(lang=getattr(o, _LIT_LANGUAGE, None) or "", value=str(o))


def _append_uri_ref(target: list[str], o: object, *, skip_builtin: bool = False) -> None:
    """Append ``str(o)`` to *target* when *o* is a URIRef (optionally skipping builtins)."""
    if isinstance(o, URIRef):
        s = str(o)
        if not (skip_builtin and is_builtin_uri(s)):
            target.append(s)


def _set_note(entity: object, o: object) -> None:
    if isinstance(o, Literal):
        entity.note = str(o)  # type: ignore[attr-defined]


def _dispatch_predicates(
    triples: list[tuple[Node, Node]],
    handlers: dict[str, Callable[[object], None]],
    annotations: list[OntologyAnnotation] | None = None,
    skip: frozenset[str] = frozenset(),
) -> None:
    """Apply ``handlers[predicate](object)`` over a subject's triples. A predicate with
    no handler is captured into *annotations* (the generic bucket) when given — every
    descriptive predicate the structured fields don't model, so it round-trips.

    *skip* names predicates that have no handler and must still not be captured,
    because serialisation derives them rather than storing them."""
    for p, o in triples:
        ps = str(p)
        handler = handlers.get(ps)
        if handler is not None:
            handler(o)
        elif annotations is not None and ps not in _ENTITY_ANNOTATION_SKIP and ps not in skip:
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
    _dispatch_predicates(
        triples, handlers, annotations=c.annotations, skip=_CONCEPT_ANNOTATION_SKIP
    )
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
            lang = getattr(o, _LIT_LANGUAGE, "")
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


def _load_classes(
    taxonomy: Taxonomy,
    index: dict[str, list[tuple[Node, Node]]],
    subjects_by_type: dict[str, list[str]],
    class_refs: set[str],
) -> None:
    class_uris = {
        uri
        for type_uri in (str(RDFS.Class), str(OWL.Class))
        for uri in subjects_by_type.get(type_uri, [])
        if not is_builtin_uri(uri)
    }
    class_uris.update(uri for uri in class_refs if not is_builtin_uri(uri))
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


def _taxonomy_from_index(parsed: _Index, ns_graph: Graph) -> Taxonomy:
    """Build the taxonomy from an index, whichever parser produced it.

    Split out of :func:`graph_to_taxonomy` so the native parser can feed the same
    logic without materialising an rdflib Graph — building one would reintroduce
    exactly the per-triple cost the native path exists to avoid. *ns_graph* only
    has to carry namespace bindings, never triples.
    """
    index, subjects_by_type, class_refs = parsed
    taxonomy = Taxonomy()
    for uri in subjects_by_type.get(str(SKOS.ConceptScheme), []):
        taxonomy.schemes[uri] = _parse_scheme(uri, index.get(uri, []))
    for uri in subjects_by_type.get(str(SKOS.Concept), []):
        taxonomy.concepts[uri] = _parse_concept(uri, index.get(uri, []))
    _load_classes(taxonomy, index, subjects_by_type, class_refs)
    if ontology_uris := subjects_by_type.get(str(OWL.Ontology), []):
        _load_ontology_node(taxonomy, ontology_uris[0], index.get(ontology_uris[0], []))
    _load_properties(taxonomy, index, subjects_by_type)
    _load_individuals(taxonomy, index, subjects_by_type)
    _normalize_hierarchy(taxonomy)
    _capture_namespaces(ns_graph, taxonomy)
    return taxonomy


def graph_to_taxonomy(g: Graph) -> Taxonomy:
    return _taxonomy_from_index(_graph_index(g), g)
