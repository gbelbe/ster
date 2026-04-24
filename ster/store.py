"""RDF persistence layer — translates between rdflib.Graph and Taxonomy."""

from __future__ import annotations

from pathlib import Path

from rdflib import RDF, BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDFS, SKOS, XSD

VOID = Namespace("http://rdfs.org/ns/void#")
SCHEMA = Namespace("https://schema.org/")

from .handles import assign_handles
from .model import (
    Concept,
    ConceptScheme,
    Definition,
    Label,
    LabelType,
    OWLIndividual,
    OWLProperty,
    RDFClass,
    Taxonomy,
    is_builtin_uri,
)

_FORMAT_MAP = {
    ".ttl": "turtle",
    ".rdf": "xml",
    ".xml": "xml",
    ".jsonld": "json-ld",
    ".json": "json-ld",
}


def _detect_format(path: Path) -> str:
    fmt = _FORMAT_MAP.get(path.suffix.lower())
    if fmt is None:
        raise ValueError(
            f"Unsupported file extension {path.suffix!r}. Use one of: {', '.join(_FORMAT_MAP)}"
        )
    return fmt


# ──────────────────────────── public API ─────────────────────────────────────


def load(path: str | Path) -> Taxonomy:
    """Parse a SKOS RDF file and return a fully handle-annotated Taxonomy."""
    path = Path(path)
    fmt = _detect_format(path)
    g = Graph()
    g.parse(str(path), format=fmt)
    taxonomy = graph_to_taxonomy(g)
    taxonomy.file_path = path
    assign_handles(taxonomy)
    return taxonomy


def save(taxonomy: Taxonomy, path: str | Path) -> None:
    """Serialize a Taxonomy back to an RDF file (format detected from extension)."""
    path = Path(path)
    fmt = _detect_format(path)
    g = taxonomy_to_graph(taxonomy)
    g.serialize(destination=str(path), format=fmt)


# ──────────────────────────── conversion ─────────────────────────────────────


def graph_to_taxonomy(g: Graph) -> Taxonomy:
    taxonomy = Taxonomy()

    # ── Schemes ──────────────────────────────────────────────────────────────
    for s_ref in g.subjects(RDF.type, SKOS.ConceptScheme):
        uri = str(s_ref)
        scheme = ConceptScheme(uri=uri)

        for _, _, o in g.triples((s_ref, DCTERMS.title, None)):
            scheme.labels.append(Label(lang=getattr(o, "language", None) or "", value=str(o)))
        for _, _, o in g.triples((s_ref, DCTERMS.description, None)):
            scheme.descriptions.append(
                Definition(lang=getattr(o, "language", None) or "", value=str(o))
            )
        for _, _, o in g.triples((s_ref, SKOS.hasTopConcept, None)):
            scheme.top_concepts.append(str(o))
        for _, _, o in g.triples((s_ref, DCTERMS.creator, None)):
            scheme.creator = str(o)
        for _, _, o in g.triples((s_ref, DCTERMS.created, None)):
            scheme.created = str(o)
        for _, _, o in g.triples((s_ref, DCTERMS.language, None)):
            scheme.languages.append(str(o))
        for _, _, o in g.triples((s_ref, VOID.uriSpace, None)):
            scheme.base_uri = str(o)

        taxonomy.schemes[uri] = scheme

    # ── Concepts ─────────────────────────────────────────────────────────────
    for c_ref in g.subjects(RDF.type, SKOS.Concept):
        uri = str(c_ref)
        concept = Concept(uri=uri)

        for _, p, o in g.triples((c_ref, None, None)):
            ps = str(p)
            if ps == str(SKOS.prefLabel):
                concept.labels.append(
                    Label(
                        lang=getattr(o, "language", None) or "", value=str(o), type=LabelType.PREF
                    )
                )
            elif ps == str(SKOS.altLabel):
                concept.labels.append(
                    Label(lang=getattr(o, "language", None) or "", value=str(o), type=LabelType.ALT)
                )
            elif ps == str(SKOS.hiddenLabel):
                concept.labels.append(
                    Label(
                        lang=getattr(o, "language", None) or "", value=str(o), type=LabelType.HIDDEN
                    )
                )
            elif ps == str(SKOS.definition):
                concept.definitions.append(
                    Definition(lang=getattr(o, "language", None) or "", value=str(o))
                )
            elif ps == str(SKOS.scopeNote):
                concept.scope_notes.append(
                    Definition(lang=getattr(o, "language", None) or "", value=str(o))
                )
            elif ps == str(SKOS.narrower):
                concept.narrower.append(str(o))
            elif ps == str(SKOS.broader):
                concept.broader.append(str(o))
            elif ps == str(SKOS.related):
                concept.related.append(str(o))
            elif ps == str(SKOS.topConceptOf):
                concept.top_concept_of = str(o)
            elif ps == str(SKOS.broadMatch):
                concept.broad_match.append(str(o))
            elif ps == str(SKOS.narrowMatch):
                concept.narrow_match.append(str(o))
            elif ps == str(SKOS.relatedMatch):
                concept.related_match.append(str(o))
            elif ps == str(SKOS.exactMatch):
                concept.exact_match.append(str(o))
            elif ps == str(SKOS.closeMatch):
                concept.close_match.append(str(o))
            elif ps == str(SCHEMA.image):
                concept.schema_images.append(str(o))
            elif ps == str(SCHEMA.video):
                concept.schema_videos.append(str(o))
            elif ps == str(SCHEMA.url):
                concept.schema_urls.append(str(o))

        taxonomy.concepts[uri] = concept

    # ── RDF/OWL Classes ───────────────────────────────────────────────────────
    # Collect all class URIs: explicitly declared + inferred from usage.
    # Inference covers subClassOf children/parents and property domain/range
    # so that the full class hierarchy is available even when only usage
    # triples are present (no explicit owl:Class declaration).
    all_class_uris: set[str] = set()
    for c_ref in set(g.subjects(RDF.type, RDFS.Class)) | set(g.subjects(RDF.type, OWL.Class)):
        if not isinstance(c_ref, BNode):
            uri = str(c_ref)
            if not is_builtin_uri(uri):
                all_class_uris.add(uri)
    for ref in (
        set(g.subjects(RDFS.subClassOf, None))
        | set(g.objects(None, RDFS.subClassOf))
        | set(g.objects(None, RDFS.domain))
        | set(g.objects(None, RDFS.range))
    ):
        if isinstance(ref, URIRef):
            uri = str(ref)
            if not is_builtin_uri(uri):
                all_class_uris.add(uri)

    # Load graph properties for every class URI in one pass.
    for uri in all_class_uris:
        c_ref = URIRef(uri)
        rdf_class = RDFClass(uri=uri)
        for _, p, o in g.triples((c_ref, None, None)):
            ps = str(p)
            if ps == str(RDFS.label):
                rdf_class.labels.append(
                    Label(lang=getattr(o, "language", None) or "", value=str(o))
                )
            elif ps == str(RDFS.comment):
                rdf_class.comments.append(
                    Definition(lang=getattr(o, "language", None) or "", value=str(o))
                )
            elif ps == str(RDFS.subClassOf) and isinstance(o, URIRef):
                parent = str(o)
                if not is_builtin_uri(parent):
                    rdf_class.sub_class_of.append(parent)
            elif ps == str(OWL.equivalentClass) and isinstance(o, URIRef):
                rdf_class.equivalent_class.append(str(o))
            elif ps == str(OWL.disjointWith) and isinstance(o, URIRef):
                rdf_class.disjoint_with.append(str(o))
            elif ps == str(SCHEMA.image):
                rdf_class.schema_images.append(str(o))
            elif ps == str(SCHEMA.video):
                rdf_class.schema_videos.append(str(o))
            elif ps == str(SCHEMA.url):
                rdf_class.schema_urls.append(str(o))
        taxonomy.owl_classes[uri] = rdf_class

    # ── owl:Ontology ──────────────────────────────────────────────────────────
    for ont_ref in g.subjects(RDF.type, OWL.Ontology):
        if isinstance(ont_ref, BNode):
            continue
        taxonomy.ontology_uri = str(ont_ref)
        for _, _p, o in g.triples((ont_ref, RDFS.label, None)):
            taxonomy.ontology_label = str(o)
            break
        break  # only take the first owl:Ontology

    # ── OWL Properties ────────────────────────────────────────────────────────
    _PROP_TYPE_MAP = {
        str(OWL.ObjectProperty): "ObjectProperty",
        str(OWL.DatatypeProperty): "DatatypeProperty",
        str(OWL.AnnotationProperty): "AnnotationProperty",
        str(RDF.Property): "Property",
    }
    prop_uris: dict[str, str] = {}
    for rdf_type_str, prop_type_name in _PROP_TYPE_MAP.items():
        for p_ref in g.subjects(RDF.type, URIRef(rdf_type_str)):
            if not isinstance(p_ref, BNode):
                uri = str(p_ref)
                if not is_builtin_uri(uri) and uri not in prop_uris:
                    prop_uris[uri] = prop_type_name
    for uri, prop_type_name in prop_uris.items():
        p_ref = URIRef(uri)
        prop = OWLProperty(uri=uri, prop_type=prop_type_name)
        for _, p, o in g.triples((p_ref, None, None)):
            ps = str(p)
            if ps == str(RDFS.label):
                prop.labels.append(Label(lang=getattr(o, "language", None) or "", value=str(o)))
            elif ps == str(RDFS.comment):
                prop.comments.append(
                    Definition(lang=getattr(o, "language", None) or "", value=str(o))
                )
            elif ps == str(RDFS.domain) and isinstance(o, URIRef):
                prop.domains.append(str(o))
            elif ps == str(RDFS.range) and isinstance(o, URIRef):
                prop.ranges.append(str(o))
            elif ps == str(RDFS.subPropertyOf) and isinstance(o, URIRef):
                prop.sub_property_of.append(str(o))
            elif ps == str(OWL.inverseOf) and isinstance(o, URIRef):
                prop.inverse_of.append(str(o))
        taxonomy.owl_properties[uri] = prop

    # ── OWL Individuals ───────────────────────────────────────────────────────
    individual_uris: set[str] = set()
    for s_ref in g.subjects(RDF.type, OWL.NamedIndividual):
        if not isinstance(s_ref, BNode):
            uri = str(s_ref)
            if not is_builtin_uri(uri):
                individual_uris.add(uri)
    for owl_class_uri in taxonomy.owl_classes:
        for s_ref in g.subjects(RDF.type, URIRef(owl_class_uri)):
            if not isinstance(s_ref, BNode):
                uri = str(s_ref)
                if (
                    not is_builtin_uri(uri)
                    and uri not in taxonomy.owl_classes
                    and uri not in taxonomy.concepts
                    and uri not in taxonomy.schemes
                ):
                    individual_uris.add(uri)
    for uri in individual_uris:
        ind_ref = URIRef(uri)
        individual = OWLIndividual(uri=uri)
        for _, p, o in g.triples((ind_ref, None, None)):
            ps = str(p)
            if ps == str(RDFS.label):
                individual.labels.append(
                    Label(lang=getattr(o, "language", None) or "", value=str(o))
                )
            elif ps == str(RDFS.comment):
                individual.comments.append(
                    Definition(lang=getattr(o, "language", None) or "", value=str(o))
                )
            elif ps == str(RDF.type):
                type_uri = str(o)
                if not is_builtin_uri(type_uri):
                    individual.types.append(type_uri)
            elif ps == str(SCHEMA.image):
                individual.schema_images.append(str(o))
            elif ps == str(SCHEMA.video):
                individual.schema_videos.append(str(o))
            elif ps == str(SCHEMA.url):
                individual.schema_urls.append(str(o))
        taxonomy.owl_individuals[uri] = individual

    # ── Object-property assertions on individuals (second pass) ──────────────
    for uri, individual in taxonomy.owl_individuals.items():
        ind_ref = URIRef(uri)
        for prop_uri in taxonomy.owl_properties:
            prop = taxonomy.owl_properties[prop_uri]
            if prop.prop_type not in ("ObjectProperty", "Property"):
                continue
            for obj in g.objects(ind_ref, URIRef(prop_uri)):
                if isinstance(obj, URIRef):
                    val_uri = str(obj)
                    if val_uri in taxonomy.owl_individuals:
                        individual.property_values.append((prop_uri, val_uri))

    # ── Normalize hierarchy (handle graphs that only declare one direction) ──
    _normalize_hierarchy(taxonomy)

    return taxonomy


def taxonomy_to_graph(taxonomy: Taxonomy) -> Graph:
    g = Graph()
    g.bind("skos", SKOS)
    g.bind("dcterms", DCTERMS)
    g.bind("xsd", XSD)
    g.bind("void", VOID)
    g.bind("rdfs", RDFS)
    g.bind("owl", OWL)
    g.bind("schema", SCHEMA)

    # Try to bind a short prefix for the primary namespace
    _bind_namespace(g, taxonomy)

    # ── Schemes ──────────────────────────────────────────────────────────────
    for uri, scheme in taxonomy.schemes.items():
        ref = URIRef(uri)
        g.add((ref, RDF.type, SKOS.ConceptScheme))
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
        for tc_uri in scheme.top_concepts:
            g.add((ref, SKOS.hasTopConcept, URIRef(tc_uri)))

    # ── Concepts ─────────────────────────────────────────────────────────────
    for uri, concept in taxonomy.concepts.items():
        ref = URIRef(uri)
        g.add((ref, RDF.type, SKOS.Concept))

        # inScheme: use topConceptOf if set, otherwise traverse up the hierarchy
        s_uri = _concept_scheme_uri(taxonomy, uri)
        if s_uri:
            g.add((ref, SKOS.inScheme, URIRef(s_uri)))
        else:
            # Orphan concept — add to all schemes as a fallback
            for s_uri in taxonomy.schemes:
                g.add((ref, SKOS.inScheme, URIRef(s_uri)))

        if concept.top_concept_of:
            g.add((ref, SKOS.topConceptOf, URIRef(concept.top_concept_of)))

        _pred_map = {
            LabelType.PREF: SKOS.prefLabel,
            LabelType.ALT: SKOS.altLabel,
            LabelType.HIDDEN: SKOS.hiddenLabel,
        }
        for lbl in concept.labels:
            g.add((ref, _pred_map[lbl.type], Literal(lbl.value, lang=lbl.lang or None)))
        for defn in concept.definitions:
            g.add((ref, SKOS.definition, Literal(defn.value, lang=defn.lang or None)))
        for note in concept.scope_notes:
            g.add((ref, SKOS.scopeNote, Literal(note.value, lang=note.lang or None)))
        for n_uri in concept.narrower:
            g.add((ref, SKOS.narrower, URIRef(n_uri)))
        for b_uri in concept.broader:
            g.add((ref, SKOS.broader, URIRef(b_uri)))
        for r_uri in concept.related:
            g.add((ref, SKOS.related, URIRef(r_uri)))
        for u in concept.broad_match:
            g.add((ref, SKOS.broadMatch, URIRef(u)))
        for u in concept.narrow_match:
            g.add((ref, SKOS.narrowMatch, URIRef(u)))
        for u in concept.related_match:
            g.add((ref, SKOS.relatedMatch, URIRef(u)))
        for u in concept.exact_match:
            g.add((ref, SKOS.exactMatch, URIRef(u)))
        for u in concept.close_match:
            g.add((ref, SKOS.closeMatch, URIRef(u)))
        for u in concept.schema_images:
            g.add((ref, SCHEMA.image, URIRef(u)))
        for u in concept.schema_videos:
            g.add((ref, SCHEMA.video, URIRef(u)))
        for u in concept.schema_urls:
            g.add((ref, SCHEMA.url, URIRef(u)))

    # ── OWL/RDFS Classes ─────────────────────────────────────────────────────
    for uri, rdf_class in taxonomy.owl_classes.items():
        ref = URIRef(uri)
        g.add((ref, RDF.type, OWL.Class))
        for lbl in rdf_class.labels:
            g.add((ref, RDFS.label, Literal(lbl.value, lang=lbl.lang or None)))
        for comment in rdf_class.comments:
            g.add((ref, RDFS.comment, Literal(comment.value, lang=comment.lang or None)))
        for parent_uri in rdf_class.sub_class_of:
            g.add((ref, RDFS.subClassOf, URIRef(parent_uri)))
        for eq_uri in rdf_class.equivalent_class:
            g.add((ref, OWL.equivalentClass, URIRef(eq_uri)))
        for dj_uri in rdf_class.disjoint_with:
            g.add((ref, OWL.disjointWith, URIRef(dj_uri)))
        for u in rdf_class.schema_images:
            g.add((ref, SCHEMA.image, URIRef(u)))
        for u in rdf_class.schema_videos:
            g.add((ref, SCHEMA.video, URIRef(u)))
        for u in rdf_class.schema_urls:
            g.add((ref, SCHEMA.url, URIRef(u)))

    # ── OWL Individuals ───────────────────────────────────────────────────────
    for uri, individual in taxonomy.owl_individuals.items():
        ref = URIRef(uri)
        g.add((ref, RDF.type, OWL.NamedIndividual))
        for type_uri in individual.types:
            g.add((ref, RDF.type, URIRef(type_uri)))
        for lbl in individual.labels:
            g.add((ref, RDFS.label, Literal(lbl.value, lang=lbl.lang or None)))
        for comment in individual.comments:
            g.add((ref, RDFS.comment, Literal(comment.value, lang=comment.lang or None)))
        for prop_uri, val_uri in individual.property_values:
            g.add((ref, URIRef(prop_uri), URIRef(val_uri)))
        for u in individual.schema_images:
            g.add((ref, SCHEMA.image, URIRef(u)))
        for u in individual.schema_videos:
            g.add((ref, SCHEMA.video, URIRef(u)))
        for u in individual.schema_urls:
            g.add((ref, SCHEMA.url, URIRef(u)))

    # ── OWL Properties ────────────────────────────────────────────────────────
    _OWL_PROP_TYPE = {
        "ObjectProperty": OWL.ObjectProperty,
        "DatatypeProperty": OWL.DatatypeProperty,
        "AnnotationProperty": OWL.AnnotationProperty,
        "Property": RDF.Property,
    }
    for uri, prop in taxonomy.owl_properties.items():
        ref = URIRef(uri)
        rdf_type = _OWL_PROP_TYPE.get(prop.prop_type, OWL.ObjectProperty)
        g.add((ref, RDF.type, rdf_type))
        for lbl in prop.labels:
            g.add((ref, RDFS.label, Literal(lbl.value, lang=lbl.lang or None)))
        for cmt in prop.comments:
            g.add((ref, RDFS.comment, Literal(cmt.value, lang=cmt.lang or None)))
        for dom in prop.domains:
            g.add((ref, RDFS.domain, URIRef(dom)))
        for rng in prop.ranges:
            g.add((ref, RDFS.range, URIRef(rng)))
        for sup in prop.sub_property_of:
            g.add((ref, RDFS.subPropertyOf, URIRef(sup)))
        for inv in prop.inverse_of:
            g.add((ref, OWL.inverseOf, URIRef(inv)))

    # ── owl:Ontology ──────────────────────────────────────────────────────────
    if taxonomy.ontology_uri:
        ont_ref = URIRef(taxonomy.ontology_uri)
        g.add((ont_ref, RDF.type, OWL.Ontology))
        if taxonomy.ontology_label:
            g.add((ont_ref, RDFS.label, Literal(taxonomy.ontology_label)))

    return g


# ──────────────────────────── helpers ────────────────────────────────────────


def _normalize_hierarchy(taxonomy: Taxonomy) -> None:
    """Ensure skos:broader/narrower and skos:topConceptOf/hasTopConcept are symmetric."""
    # 1. Bidirectional broader ↔ narrower
    for uri, concept in taxonomy.concepts.items():
        for child_uri in concept.narrower:
            child = taxonomy.concepts.get(child_uri)
            if child and uri not in child.broader:
                child.broader.append(uri)
        for parent_uri in concept.broader:
            parent = taxonomy.concepts.get(parent_uri)
            if parent and uri not in parent.narrower:
                parent.narrower.append(uri)

    # 2. hasTopConcept → topConceptOf
    for scheme_uri, scheme in taxonomy.schemes.items():
        for tc_uri in scheme.top_concepts:
            tc_concept = taxonomy.concepts.get(tc_uri)
            if tc_concept and tc_concept.top_concept_of is None:
                tc_concept.top_concept_of = scheme_uri

    # 3. topConceptOf → hasTopConcept
    for concept_uri, concept in taxonomy.concepts.items():
        if concept.top_concept_of:
            tc_scheme = taxonomy.schemes.get(concept.top_concept_of)
            if tc_scheme and concept_uri not in tc_scheme.top_concepts:
                tc_scheme.top_concepts.append(concept_uri)

    # 4. Auto-detect: concepts with no broader that aren't yet a top concept
    #    are top concepts of whatever scheme lists them in its hierarchy.
    primary = taxonomy.primary_scheme()
    for concept_uri, concept in taxonomy.concepts.items():
        if concept.broader or concept.top_concept_of:
            continue
        # Check if any scheme lists this concept in its top_concepts (already handled
        # above). If not, assign to the primary scheme as a top concept.
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
    """Attempt to bind a short 'wv' prefix for the primary concept namespace."""
    uris = list(taxonomy.concepts) + list(taxonomy.schemes)
    if not uris:
        return
    # Find the common base by taking the longest common prefix ending in / or #
    first = uris[0]
    for sep in ("#", "/"):
        if sep in first:
            base = first.rsplit(sep, 1)[0] + sep
            if all(u.startswith(base) for u in uris):
                g.bind("wv", Namespace(base))
                return
