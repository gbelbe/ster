"""RDF persistence layer — translates between rdflib.Graph and Taxonomy."""
from __future__ import annotations
from pathlib import Path

from rdflib import Graph, URIRef, Literal, Namespace, RDF
from rdflib.namespace import SKOS, DCTERMS, XSD

from .model import Concept, ConceptScheme, Definition, Label, LabelType, Taxonomy
from .handles import assign_handles

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
            f"Unsupported file extension {path.suffix!r}. "
            f"Use one of: {', '.join(_FORMAT_MAP)}"
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
            scheme.labels.append(Label(lang=o.language or "", value=str(o)))
        for _, _, o in g.triples((s_ref, DCTERMS.description, None)):
            scheme.descriptions.append(Definition(lang=o.language or "", value=str(o)))
        for _, _, o in g.triples((s_ref, SKOS.hasTopConcept, None)):
            scheme.top_concepts.append(str(o))
        for _, _, o in g.triples((s_ref, DCTERMS.creator, None)):
            scheme.creator = str(o)
        for _, _, o in g.triples((s_ref, DCTERMS.created, None)):
            scheme.created = str(o)
        for _, _, o in g.triples((s_ref, DCTERMS.language, None)):
            scheme.languages.append(str(o))

        taxonomy.schemes[uri] = scheme

    # ── Concepts ─────────────────────────────────────────────────────────────
    for c_ref in g.subjects(RDF.type, SKOS.Concept):
        uri = str(c_ref)
        concept = Concept(uri=uri)

        for _, p, o in g.triples((c_ref, None, None)):
            ps = str(p)
            if ps == str(SKOS.prefLabel):
                concept.labels.append(
                    Label(lang=o.language or "", value=str(o), type=LabelType.PREF)
                )
            elif ps == str(SKOS.altLabel):
                concept.labels.append(
                    Label(lang=o.language or "", value=str(o), type=LabelType.ALT)
                )
            elif ps == str(SKOS.hiddenLabel):
                concept.labels.append(
                    Label(lang=o.language or "", value=str(o), type=LabelType.HIDDEN)
                )
            elif ps == str(SKOS.definition):
                concept.definitions.append(
                    Definition(lang=o.language or "", value=str(o))
                )
            elif ps == str(SKOS.scopeNote):
                concept.scope_notes.append(
                    Definition(lang=o.language or "", value=str(o))
                )
            elif ps == str(SKOS.narrower):
                concept.narrower.append(str(o))
            elif ps == str(SKOS.broader):
                concept.broader.append(str(o))
            elif ps == str(SKOS.related):
                concept.related.append(str(o))
            elif ps == str(SKOS.topConceptOf):
                concept.top_concept_of = str(o)

        taxonomy.concepts[uri] = concept

    # ── Normalize hierarchy (handle graphs that only declare one direction) ──
    _normalize_hierarchy(taxonomy)

    return taxonomy


def taxonomy_to_graph(taxonomy: Taxonomy) -> Graph:
    g = Graph()
    g.bind("skos", SKOS)
    g.bind("dcterms", DCTERMS)
    g.bind("xsd", XSD)

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
        for tc_uri in scheme.top_concepts:
            g.add((ref, SKOS.hasTopConcept, URIRef(tc_uri)))

    # ── Concepts ─────────────────────────────────────────────────────────────
    for uri, concept in taxonomy.concepts.items():
        ref = URIRef(uri)
        g.add((ref, RDF.type, SKOS.Concept))

        # inScheme for all schemes
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

    return g


# ──────────────────────────── helpers ────────────────────────────────────────

def _normalize_hierarchy(taxonomy: Taxonomy) -> None:
    """Ensure both skos:broader and skos:narrower are populated symmetrically."""
    for uri, concept in taxonomy.concepts.items():
        for child_uri in concept.narrower:
            child = taxonomy.concepts.get(child_uri)
            if child and uri not in child.broader:
                child.broader.append(uri)
        for parent_uri in concept.broader:
            parent = taxonomy.concepts.get(parent_uri)
            if parent and uri not in parent.narrower:
                parent.narrower.append(uri)


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
