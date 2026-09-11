"""Taxonomy → Graph: serialize entities (schemes, concepts, classes, properties,
individuals, the ontology node) back into rdflib triples — the inverse of ._from_graph."""

from __future__ import annotations

from rdflib import RDF, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, FOAF, OWL, RDFS, SKOS, XSD

from .. import workspace_ops
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
)
from ._constants import NOTE_PROPERTY_URI, SCHEMA, VANN, VOID
from ._normalize import _bind_namespace, _concept_scheme_uri


def _annotation_object(a: OntologyAnnotation) -> URIRef | Literal:
    """Render an :class:`OntologyAnnotation` back into an rdflib object."""
    if a.is_iri:
        return URIRef(a.value)
    if a.datatype:
        return Literal(a.value, datatype=URIRef(a.datatype))
    return Literal(a.value, lang=a.lang or None)


_CONCEPT_LABEL_PREDS = {
    LabelType.PREF: SKOS.prefLabel,
    LabelType.ALT: SKOS.altLabel,
    LabelType.HIDDEN: SKOS.hiddenLabel,
}
_CONCEPT_LIST_PREDS: tuple[tuple[str, URIRef], ...] = (
    ("narrower", SKOS.narrower),
    ("broader", SKOS.broader),
    ("related", SKOS.related),
    *((attr, getattr(SKOS, prop)) for prop, attr in workspace_ops.ATTR.items()),
    ("schema_images", SCHEMA.image),
    ("schema_videos", SCHEMA.video),
    ("schema_urls", SCHEMA.url),
)
_OWL_PROP_TYPE: dict[str, URIRef] = {
    "ObjectProperty": OWL.ObjectProperty,
    "DatatypeProperty": OWL.DatatypeProperty,
    "AnnotationProperty": OWL.AnnotationProperty,
    "Property": RDF.Property,
}


def _serialize_schema_media(g: Graph, ref: URIRef, entity: object) -> None:
    """Emit schema.org image / video / url triples shared by classes, individuals, concepts.

    A picture read from an alternative vocabulary — schema:logo, foaf:depiction,
    wdt:P18 — has already been written back under its own predicate, either from
    the annotations bucket or from an individual's property assertions. Emitting
    it again here would add a schema:image triple the author never wrote, so a
    URL already present on this subject is left alone.
    """
    # Both sources, because serialisation order differs by entity kind: an
    # individual's property assertions land before this runs, a class's
    # annotations after. Checking only the graph made the class case emit a
    # duplicate schema:image beside the schema:logo it had preserved.
    already = {str(o) for _p, o in g.predicate_objects(ref)}
    already |= {str(getattr(a, "value", "")) for a in getattr(entity, "annotations", [])}
    for u in entity.schema_images:  # type: ignore[attr-defined]
        if u not in already:
            g.add((ref, SCHEMA.image, URIRef(u)))
    for u in entity.schema_videos:  # type: ignore[attr-defined]
        if u not in already:
            g.add((ref, SCHEMA.video, URIRef(u)))
    for u in entity.schema_urls:  # type: ignore[attr-defined]
        if u not in already:
            g.add((ref, SCHEMA.url, URIRef(u)))


def _serialize_labels_comments(
    g: Graph, ref: URIRef, labels: list[Label], comments: list[Definition]
) -> None:
    """Emit rdfs:label / rdfs:comment triples shared by classes and properties."""
    for lbl in labels:
        g.add((ref, RDFS.label, Literal(lbl.value, lang=lbl.lang or None)))
    for cmt in comments:
        g.add((ref, RDFS.comment, Literal(cmt.value, lang=cmt.lang or None)))


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
    # Skipped when ster worked the link out rather than read it — see
    # Taxonomy.inferred_top_concepts.
    if concept.top_concept_of and uri not in taxonomy.inferred_top_concepts:
        g.add((ref, SKOS.topConceptOf, URIRef(concept.top_concept_of)))
    _serialize_concept_literals(g, ref, concept)
    for attr, pred in _CONCEPT_LIST_PREDS:
        for u in getattr(concept, attr):
            g.add((ref, pred, URIRef(u)))
    if concept.focus:
        g.add((ref, FOAF.focus, URIRef(concept.focus)))
    # The generic bucket, exactly as classes/properties/schemes do: every
    # predicate ster does not model goes back out as it came in.
    for a in concept.annotations:
        g.add((ref, URIRef(a.predicate), _annotation_object(a)))


def _serialize_class(g: Graph, uri: str, rdf_class: RDFClass, inferred: set[str]) -> None:
    ref = URIRef(uri)
    # A class the file only mentioned is not declared back into it.
    if uri not in inferred:
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


def _serialize_scheme(g: Graph, uri: str, scheme: ConceptScheme, inferred: set[str]) -> None:
    ref = URIRef(uri)
    g.add((ref, RDF.type, SKOS.ConceptScheme))
    _serialize_scheme_literals(g, ref, scheme)
    _serialize_scheme_relations(g, ref, scheme, inferred)
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


def _serialize_scheme_relations(
    g: Graph, ref: URIRef, scheme: ConceptScheme, inferred: set[str]
) -> None:
    for tc_uri in scheme.top_concepts:
        if tc_uri not in inferred:
            g.add((ref, SKOS.hasTopConcept, URIRef(tc_uri)))


def _serialize_annotations(g: Graph, ref: URIRef, annotations: list[OntologyAnnotation]) -> None:
    for annotation in annotations:
        g.add((ref, URIRef(annotation.predicate), _annotation_object(annotation)))


def _serialize_individual(
    g: Graph, uri: str, individual: OWLIndividual, inferred_named: set[str]
) -> None:
    ref = URIRef(uri)
    # Only when the file said so. Typing an individual by its class alone is
    # legal OWL 2; adding the NamedIndividual declaration is a convention, and
    # conventions are not ster's to assert into someone else's file.
    if uri not in inferred_named:
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


def taxonomy_to_graph(taxonomy: Taxonomy, *, include_context: bool = False) -> Graph:
    """The taxonomy as RDF. Context files are excluded unless asked for.

    Two callers want two different graphs and the difference is not cosmetic.
    *Writing* one file must never emit another file's entities — that is the
    backstop described in ``_model_to_graph``. *Reading* the whole session — the
    map, a SPARQL query — wants everything the user can see, or half the graph
    goes missing and no amount of correct geometry puts it on screen.

    Defaulting to False keeps the dangerous direction the one you have to ask
    for by name.
    """
    g = _model_to_graph(taxonomy, include_context=include_context)
    # What the model could not describe, put back exactly as it came in.
    for triple in taxonomy.residue:
        g.add(triple)
    if include_context:
        for triples in taxonomy.context_residue.values():
            for triple in triples:
                g.add(triple)
    return g


def full_graph(taxonomy: Taxonomy) -> Graph:
    """Everything the session holds, context included — for reading, never writing.

    Memoised on the taxonomy object, which is exactly the right lifetime: a
    mutation swaps in a new Taxonomy and a file-watch reload builds another, so
    a stale graph cannot outlive the model it came from. Rebuilding costs ~180ms
    on an 18k-triple ontology and the map asks for it on every pan, so the cache
    is not an optimisation but the difference between usable and not.
    """
    cached = getattr(taxonomy, "_ster_full_graph", None)
    if cached is not None:
        return cached  # type: ignore[return-value]
    g = taxonomy_to_graph(taxonomy, include_context=True)
    try:
        taxonomy._ster_full_graph = g  # type: ignore[attr-defined]
    except AttributeError:  # a model that refuses attributes — recompute instead
        pass
    return g


def _model_to_graph(taxonomy: Taxonomy, *, include_context: bool = False) -> Graph:
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

    # `own` filters out anything merged from a read-only context file. This is
    # the backstop the whole feature rests on: an edit that slips past the UI
    # guard is merely not persisted, whereas serialising a context entity here
    # would silently absorb another file into this one.
    def own(registry: dict) -> list:
        if include_context:
            return list(registry.items())
        return [(u, e) for u, e in registry.items() if u not in taxonomy.context_source]

    for uri, scheme in own(taxonomy.schemes):
        _serialize_scheme(g, uri, scheme, taxonomy.inferred_top_concepts)

    # ── Concepts ─────────────────────────────────────────────────────────────
    for uri, concept in own(taxonomy.concepts):
        _serialize_concept(g, uri, concept, taxonomy)

    # ── OWL/RDFS Classes ─────────────────────────────────────────────────────
    for uri, rdf_class in own(taxonomy.owl_classes):
        _serialize_class(g, uri, rdf_class, taxonomy.inferred_classes)

    for uri, individual in own(taxonomy.owl_individuals):
        _serialize_individual(g, uri, individual, taxonomy.inferred_named_individuals)

    # ── OWL Properties ────────────────────────────────────────────────────────
    for uri, prop in own(taxonomy.owl_properties):
        _serialize_property(g, uri, prop)

    _serialize_ontology(g, taxonomy)

    return g
