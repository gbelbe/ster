"""Predicate → friendly label suggestions, shared by the metadata-catalog widgets."""

from __future__ import annotations

# Common namespaces → prefix, for suggesting a label when registering a predicate.
_KNOWN_PREFIXES: tuple[tuple[str, str], ...] = (
    ("http://purl.org/dc/terms/", "dcterms"),  # NOSONAR - RDF namespace IRI
    ("http://www.w3.org/2002/07/owl#", "owl"),  # NOSONAR - RDF namespace IRI
    ("http://www.w3.org/2000/01/rdf-schema#", "rdfs"),  # NOSONAR - RDF namespace IRI
    ("http://www.w3.org/2004/02/skos/core#", "skos"),  # NOSONAR - RDF namespace IRI
    ("http://purl.org/vocab/vann/", "vann"),  # NOSONAR - RDF namespace IRI
    ("http://xmlns.com/foaf/0.1/", "foaf"),  # NOSONAR - RDF namespace IRI
    ("http://schema.org/", "schema"),  # NOSONAR - RDF namespace IRI
)


def suggest_label(predicate: str) -> str:
    """A friendly ``prefix:local`` label for *predicate*, or its local name."""
    for namespace, prefix in _KNOWN_PREFIXES:
        if predicate.startswith(namespace):
            return f"{prefix}:{predicate[len(namespace) :]}"
    return predicate.rsplit("/", 1)[-1].rsplit("#", 1)[-1] or predicate
