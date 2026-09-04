"""Shared RDF namespaces and cross-cutting constants used across the store package."""

from __future__ import annotations

from rdflib import Graph, Namespace

VOID = Namespace("http://rdfs.org/ns/void#")  # NOSONAR - RDF namespace IRI
SCHEMA = Namespace("https://schema.org/")
VANN = Namespace("http://purl.org/vocab/vann/")  # NOSONAR - RDF namespace IRI

NOTE_PROPERTY_URI = "https://example.org/ontology/kai-internal-knowledge#note"

# Prefixes rdflib injects into every fresh Graph — not declared by the user's file.
# (The empty default ":" is excluded too; "wv" is NOT — it is a real user prefix and
# must round-trip, see _bind_namespace.)
_RDFLIB_DEFAULT_PREFIXES: frozenset[str] = frozenset(
    p for p, _ in Graph().namespace_manager.namespaces()
) | frozenset({""})
