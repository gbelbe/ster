"""Shared RDF namespaces and cross-cutting constants used across the store package."""

from __future__ import annotations

from rdflib import Graph, Namespace

VOID = Namespace("http://rdfs.org/ns/void#")  # NOSONAR - RDF namespace IRI
SCHEMA = Namespace("https://schema.org/")
VANN = Namespace("http://purl.org/vocab/vann/")  # NOSONAR - RDF namespace IRI

NOTE_PROPERTY_URI = "https://example.org/ontology/kai-internal-knowledge#note"

# ── what counts as a picture ─────────────────────────────────────────────────
# Every vocabulary spells this differently and none of them is wrong, so ster
# reads them all. schema:image is the *canonical* one: it is what ster writes,
# and the only one consumed outright. The alternatives are read for display and
# left in the annotations bucket as well, so a save puts back the predicate the
# author actually chose rather than promoting it to schema:image.
# Bare IRI prefixes, not Namespace objects: `FOAF` is already a Namespace in the
# parsing module and rebinding it turned FOAF.focus into a string attribute
# lookup, which broke 223 tests in one line.
_FOAF_IRI = "http://xmlns.com/foaf/0.1/"  # NOSONAR - RDF namespace IRI
_VCARD_IRI = "http://www.w3.org/2006/vcard/ns#"  # NOSONAR - RDF namespace IRI
_WDT_IRI = "http://www.wikidata.org/prop/direct/"  # NOSONAR - RDF namespace IRI

ALT_IMAGE_PREDICATES = frozenset(
    {
        str(SCHEMA.logo),
        str(SCHEMA.thumbnail),
        str(SCHEMA.thumbnailUrl),
        str(SCHEMA.photo),
        f"{_FOAF_IRI}depiction",
        f"{_FOAF_IRI}img",
        f"{_FOAF_IRI}logo",
        f"{_FOAF_IRI}thumbnail",
        f"{_VCARD_IRI}photo",
        f"{_VCARD_IRI}logo",
        "http://dbpedia.org/ontology/thumbnail",  # NOSONAR - RDF namespace IRI
        f"{_WDT_IRI}P18",  # image
        f"{_WDT_IRI}P154",  # logo image
        f"{_WDT_IRI}P41",  # flag image
    }
)
IMAGE_PREDICATES = ALT_IMAGE_PREDICATES | {str(SCHEMA.image)}

ALT_VIDEO_PREDICATES = frozenset({str(SCHEMA.embedUrl), f"{_WDT_IRI}P10"})
ALT_URL_PREDICATES = frozenset({f"{_FOAF_IRI}homepage", f"{_FOAF_IRI}page", f"{_WDT_IRI}P856"})

# Prefixes rdflib injects into every fresh Graph — not declared by the user's file.
# (The empty default ":" is excluded too; "wv" is NOT — it is a real user prefix and
# must round-trip, see _bind_namespace.)
_RDFLIB_DEFAULT_PREFIXES: frozenset[str] = frozenset(
    p for p, _ in Graph().namespace_manager.namespaces()
) | frozenset({""})
