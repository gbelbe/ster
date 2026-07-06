"""A curated, offline library of well-known **annotation** properties, searchable by
intent — so authors can find and add descriptive metadata predicates (an image, a
homepage, a definition, a source…) without hunting down URIs, and without accidentally
reaching for a *real* (object/datatype) property.

Everything here is used as an ``owl:AnnotationProperty`` (metadata about an entity),
never a modelled relationship. Change-tracking provenance (who/what/when of edits) is
deliberately excluded — a future PROV-O layer owns that.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CATEGORIES: tuple[str, ...] = (
    "Descriptions",
    "Images & media",
    "Links & URLs",
    "Versioning",
    "Sources & references",
)

# The heuristic shown in the picker so the annotation-vs-real choice is obvious. Lists
# concrete examples of each (kept in sync with the test).
GUIDANCE = (
    "Annotation = describes / documents the entity for humans & tools "
    "(e.g. label, comment, definition, image, homepage, seeAlso, license, source) — "
    "usable on a class or an individual. "
    "Real property = a modelled relationship / attribute a reasoner uses "
    "(e.g. hasParent, partOf, hasAge, temperature, locatedIn). "
    "The same IRI can't be both — if you need the value as modelled data, define a "
    "separate object/datatype property instead."
)


@dataclass(frozen=True)
class LibraryProp:
    """One curated annotation predicate: its URI, prefixed label, a one-line
    description, its category, source ontology, and intent keywords for search."""

    predicate: str
    label: str
    description: str
    category: str
    ontology: str
    keywords: tuple[str, ...] = field(default_factory=tuple)


_RDFS = "http://www.w3.org/2000/01/rdf-schema#"
_SKOS = "http://www.w3.org/2004/02/skos/core#"
_DCT = "http://purl.org/dc/terms/"
_SCHEMA = "https://schema.org/"
_FOAF = "http://xmlns.com/foaf/0.1/"
_OWL = "http://www.w3.org/2002/07/owl#"
_PROV = "http://www.w3.org/ns/prov#"


LIBRARY: tuple[LibraryProp, ...] = (
    # ── Descriptions ──────────────────────────────────────────────────────────
    LibraryProp(
        _RDFS + "comment",
        "rdfs:comment",
        "Human-readable comment / description",
        "Descriptions",
        "rdfs",
        ("comment", "description", "note", "documentation"),
    ),
    LibraryProp(
        _SKOS + "definition",
        "skos:definition",
        "Formal definition of the concept",
        "Descriptions",
        "skos",
        ("definition", "meaning", "description"),
    ),
    LibraryProp(
        _DCT + "description",
        "dcterms:description",
        "A free-text description",
        "Descriptions",
        "dcterms",
        ("description", "summary", "abstract", "about"),
    ),
    LibraryProp(
        _SKOS + "scopeNote",
        "skos:scopeNote",
        "Clarifies the intended scope / usage",
        "Descriptions",
        "skos",
        ("scope", "usage", "note", "guidance"),
    ),
    LibraryProp(
        _SKOS + "example",
        "skos:example",
        "An example of use",
        "Descriptions",
        "skos",
        ("example", "sample", "illustration"),
    ),
    LibraryProp(
        _SKOS + "note",
        "skos:note",
        "A general note",
        "Descriptions",
        "skos",
        ("note", "remark", "comment"),
    ),
    # ── Images & media ────────────────────────────────────────────────────────
    LibraryProp(
        _SCHEMA + "image",
        "schema:image",
        "Image (URL) representing the entity",
        "Images & media",
        "schema.org",
        ("image", "photo", "picture", "thumbnail", "depiction", "illustration", "media"),
    ),
    LibraryProp(
        _FOAF + "depiction",
        "foaf:depiction",
        "An image that depicts the entity",
        "Images & media",
        "foaf",
        ("image", "depiction", "picture", "photo", "media"),
    ),
    LibraryProp(
        _SCHEMA + "video",
        "schema:video",
        "A video (URL) about the entity",
        "Images & media",
        "schema.org",
        ("video", "clip", "movie", "media", "film"),
    ),
    LibraryProp(
        _SCHEMA + "logo",
        "schema:logo",
        "A logo image for the entity",
        "Images & media",
        "schema.org",
        ("logo", "brand", "image", "icon", "media"),
    ),
    # ── Links & URLs ──────────────────────────────────────────────────────────
    LibraryProp(
        _FOAF + "homepage",
        "foaf:homepage",
        "A homepage / webpage for the entity",
        "Links & URLs",
        "foaf",
        ("homepage", "webpage", "website", "url", "page", "link", "web"),
    ),
    LibraryProp(
        _SCHEMA + "url",
        "schema:url",
        "URL of a page describing the entity",
        "Links & URLs",
        "schema.org",
        ("url", "webpage", "website", "link", "page", "web"),
    ),
    LibraryProp(
        _RDFS + "seeAlso",
        "rdfs:seeAlso",
        "A related resource for more information",
        "Links & URLs",
        "rdfs",
        ("seealso", "related", "reference", "link", "more"),
    ),
    # ── Versioning ────────────────────────────────────────────────────────────
    LibraryProp(
        _OWL + "versionInfo",
        "owl:versionInfo",
        "Version label / string",
        "Versioning",
        "owl",
        ("version", "versioninfo", "release"),
    ),
    LibraryProp(
        _OWL + "versionIRI",
        "owl:versionIRI",
        "IRI of this version",
        "Versioning",
        "owl",
        ("version", "versioniri", "release", "iri"),
    ),
    LibraryProp(
        _OWL + "priorVersion",
        "owl:priorVersion",
        "The previous version's IRI",
        "Versioning",
        "owl",
        ("version", "prior", "previous", "history"),
    ),
    LibraryProp(
        _OWL + "deprecated",
        "owl:deprecated",
        "Marks the entity as deprecated",
        "Versioning",
        "owl",
        ("deprecated", "obsolete", "retired", "version"),
    ),
    # ── Sources & references (descriptive provenance, NOT edit-tracking) ───────
    LibraryProp(
        _DCT + "source",
        "dcterms:source",
        "The source the content was derived from",
        "Sources & references",
        "dcterms",
        ("source", "origin", "derived", "citation", "reference", "provenance"),
    ),
    LibraryProp(
        _RDFS + "isDefinedBy",
        "rdfs:isDefinedBy",
        "The resource that defines this term",
        "Sources & references",
        "rdfs",
        ("definedby", "defined", "source", "vocabulary", "namespace"),
    ),
    LibraryProp(
        _PROV + "wasDerivedFrom",
        "prov:wasDerivedFrom",
        "A source this entity's content was derived from",
        "Sources & references",
        "prov",
        ("derived", "source", "origin", "provenance", "reference"),
    ),
)


def _blob(prop: LibraryProp) -> str:
    return " ".join(
        (prop.label, prop.description, prop.category, prop.ontology, *prop.keywords)
    ).lower()


def all_props() -> list[LibraryProp]:
    """Every curated property, in display order."""
    return list(LIBRARY)


def get(predicate: str) -> LibraryProp | None:
    """The library entry for *predicate*, or ``None``."""
    return next((p for p in LIBRARY if p.predicate == predicate), None)


def search(query: str) -> list[LibraryProp]:
    """Properties whose label / description / keywords / category / ontology contain
    *query* (case-insensitive). An empty query returns everything."""
    q = query.strip().lower()
    if not q:
        return all_props()
    return [p for p in LIBRARY if q in _blob(p)]


def by_category() -> dict[str, list[LibraryProp]]:
    """The library grouped by category (in ``CATEGORIES`` order)."""
    grouped: dict[str, list[LibraryProp]] = {c: [] for c in CATEGORIES}
    for prop in LIBRARY:
        grouped[prop.category].append(prop)
    return {c: props for c, props in grouped.items() if props}
