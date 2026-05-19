"""Ster-specific semanticlint checks registered into the global CheckRegistry."""

from __future__ import annotations

from rdflib import RDF, BNode, Graph, URIRef
from rdflib.namespace import OWL, RDFS, SKOS
from semanticlint.checks.base import Check, CheckConfig, Severity, Violation, VocabType
from semanticlint.checks.registry import CheckRegistry

# Namespaces that are never user-defined — skip them in URI checks.
_SAFE_PREFIXES = (
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2001/XMLSchema#",
    "http://www.w3.org/2004/02/skos/core#",
    "http://xmlns.com/foaf/0.1/",
    "https://schema.org/",
    "http://schema.org/",
)

# rdf:type values that identify user-defined entities
_ENTITY_TYPES = (
    OWL.Class,
    OWL.ObjectProperty,
    OWL.DatatypeProperty,
    OWL.AnnotationProperty,
    OWL.NamedIndividual,
    RDFS.Class,
    RDF.Property,
    SKOS.Concept,
    SKOS.ConceptScheme,
)


def _user_entity_subjects(graph: Graph) -> list[URIRef]:
    """Return every named (non-blank) subject declared as a user-defined entity."""
    seen: set[URIRef] = set()
    for rdf_type in _ENTITY_TYPES:
        for subj in graph.subjects(RDF.type, rdf_type):
            if isinstance(subj, BNode):
                continue
            if not isinstance(subj, URIRef):
                continue
            uri = str(subj)
            if any(uri.startswith(p) for p in _SAFE_PREFIXES):
                continue
            seen.add(subj)
    return list(seen)


@CheckRegistry.register
class FileSchemeURICheck(Check):
    id = "URI001"
    description = (
        "Entity URI uses the file:// scheme — likely a local filesystem path "
        "resolved by rdflib from a relative URI. Replace with a stable http(s):// URI."
    )
    severity = Severity.ERROR
    applies_to = VocabType.RDF | VocabType.OWL | VocabType.SKOS | VocabType.RDFS

    def run(self, graph: Graph, config: CheckConfig) -> list[Violation]:
        return [
            Violation(
                self.id,
                f"Entity URI uses file:// scheme: {subj}",
                self.severity,
                subject=subj,
            )
            for subj in _user_entity_subjects(graph)
            if str(subj).startswith("file:")
        ]


@CheckRegistry.register
class NonHTTPSchemeURICheck(Check):
    id = "URI002"
    description = (
        "Entity URI does not use http:// or https:// — unusual scheme may cause "
        "interoperability issues. Use a stable http(s):// URI."
    )
    severity = Severity.WARNING
    applies_to = VocabType.RDF | VocabType.OWL | VocabType.SKOS | VocabType.RDFS

    def run(self, graph: Graph, config: CheckConfig) -> list[Violation]:
        return [
            Violation(
                self.id,
                f"Entity URI has non-HTTP(S) scheme: {subj}",
                self.severity,
                subject=subj,
            )
            for subj in _user_entity_subjects(graph)
            if not str(subj).startswith(("http://", "https://", "file:"))
            # file: is already covered by URI001 — avoid double-reporting
        ]
