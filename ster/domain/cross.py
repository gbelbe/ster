"""Cross-layer rename front + URI resolution.

Detects which layer(s) own a URI and dispatches counting/renaming into the SKOS
and OWL layers. Part of the domain layer (docs/architecture/module-layout.md):
reached through ``ster.operations``, never imported directly by a front-end.
"""

from __future__ import annotations

from ..exceptions import ConceptNotFoundError, HandleNotFoundError, URIAlreadyExistsError
from ..handles import assign_handles
from ..model import Label, LabelType, OntologyAnnotation, OWLIndividual, RDFClass, Taxonomy
from .owl import (
    _scrub_class_references,
    count_owl_uri_references,
    rename_owl_uri,
    set_individual_property_value,
)
from .skos import count_concept_uri_references, rename_uri

# Dublin Core "subject" — the standard predicate for "this resource is *about* this
# concept". Tagging an individual with a concept indexes the instance without touching
# its rdf:type (SKOS's core subject-indexing use).
DCT_SUBJECT = "http://purl.org/dc/terms/subject"


def tag_individual_with_concept(taxonomy: Taxonomy, ind_uri: str, concept_uri: str) -> None:
    """Add a ``dct:subject`` → *concept* link to an individual (idempotent). No-op unless
    both the individual and the concept exist — so a bulk tag silently skips bad targets."""
    if ind_uri not in taxonomy.owl_individuals or concept_uri not in taxonomy.concepts:
        return
    set_individual_property_value(taxonomy, ind_uri, DCT_SUBJECT, concept_uri)


def link_concept_to_class(taxonomy: Taxonomy, concept_uri: str, class_uri: str) -> None:
    """Link a concept to an *existing* OWL class via ``foaf:focus`` — "this concept
    corresponds to that class" (the standards-clean SKOS↔OWL bridge; VIAF pattern). The
    class's individuals then surface under the concept. No-op unless both exist."""
    if concept_uri not in taxonomy.concepts or class_uri not in taxonomy.owl_classes:
        return
    taxonomy.concepts[concept_uri].focus = class_uri


def unlink_concept_from_class(taxonomy: Taxonomy, concept_uri: str) -> None:
    """Remove a concept's ``foaf:focus`` link (the inverse of :func:`link_concept_to_class`).
    Non-destructive: the class and its individuals are untouched. No-op unless *concept_uri*
    is a linked concept."""
    concept = taxonomy.concepts.get(concept_uri)
    if concept is not None:
        concept.focus = None


def promote_concept_to_class(taxonomy: Taxonomy, uri: str) -> None:
    """Give a ``skos:Concept`` an ``owl:Class`` facet (punning). No-op unless *uri*
    is a concept that is not already a class.

    The concept keeps every SKOS relation; the new class carries the concept's
    prefLabels as ``rdfs:label`` so its display name survives (``label_of`` reads
    the class facet first). The OWL hierarchy is intentionally left empty — the
    SKOS ``broader`` spine stays authoritative; subclasses are added deliberately.
    """
    concept = taxonomy.concepts.get(uri)
    if concept is None or uri in taxonomy.owl_classes:
        return
    taxonomy.owl_classes[uri] = RDFClass(
        uri=uri,
        labels=[Label(lbl.lang, lbl.value) for lbl in concept.labels if lbl.type == LabelType.PREF],
    )


def demote_pun_to_concept(taxonomy: Taxonomy, uri: str) -> None:
    """Remove a pun's ``owl:Class`` facet, leaving the ``skos:Concept``. No-op unless
    *uri* is a pun (both a concept and a class).

    Non-destructive and integrity-preserving: subclasses re-root (their now-dangling
    ``subClassOf`` link to *uri* is dropped, along with any property domain/range use),
    and individuals typed as *uri* drop that type but are kept.
    """
    if uri not in taxonomy.concepts or uri not in taxonomy.owl_classes:
        return
    del taxonomy.owl_classes[uri]
    _scrub_class_references(taxonomy, uri)
    for ind in taxonomy.owl_individuals.values():
        if uri in ind.types:
            ind.types.remove(uri)


def resolve(taxonomy: Taxonomy, handle_or_name: str) -> str:
    """Resolve a handle, local name, or full URI to a URI.

    Resolution order:
      1. Full URI (contains "://") — verified against known concepts/schemes.
      2. Handle (case-insensitive lookup in handle_index).
      3. Local name (matched against concept.local_name).

    Raises HandleNotFoundError if nothing matches.
    """
    uri = taxonomy.resolve(handle_or_name)
    if uri is None:
        raise HandleNotFoundError(handle_or_name)
    return uri


def expand_uri(taxonomy: Taxonomy, name_or_uri: str) -> str:
    """Return a full URI for a local name, expanding with the taxonomy's base URI.

    If name_or_uri already contains "://" it is returned as-is.
    Otherwise, the taxonomy's base URI is prepended.
    """
    if "://" in name_or_uri:
        return name_or_uri
    base = taxonomy.base_uri()
    if not base:
        raise HandleNotFoundError(
            f"Cannot expand {name_or_uri!r}: no base URI configured. "
            "Use a full URI or run 'ster init' to set one."
        )
    return base + name_or_uri


# ──────────────────────── common rename front ────────────────────────────────
# The generic flow — detect the layer(s) owning a URI, count affected
# statements, and rename — is identical for SKOS and OWL.  These dispatchers
# hide the SKOS-vs-OWL specifics so callers (e.g. the viewer) stay layer-
# agnostic; a node promoted to both layers is handled in both.


def _owns_owl(taxonomy: Taxonomy, uri: str) -> bool:
    return (
        uri in taxonomy.owl_classes
        or uri in taxonomy.owl_individuals
        or uri in taxonomy.owl_properties
    )


def _language_literal_lists(taxonomy: Taxonomy) -> list[list]:
    """Every language-tagged literal list (labels / comments / definitions /
    scope-notes / descriptions) across all entities — the things a language tag
    can appear on."""
    lists: list[list] = []
    for cls in taxonomy.owl_classes.values():
        lists += [cls.labels, cls.comments]
    for prop in taxonomy.owl_properties.values():
        lists += [prop.labels, prop.comments]
    for ind in taxonomy.owl_individuals.values():
        lists += [ind.labels, ind.comments]
    for concept in taxonomy.concepts.values():
        lists += [concept.labels, concept.definitions, concept.scope_notes]
    for scheme in taxonomy.schemes.values():
        lists += [scheme.labels, scheme.descriptions]
    return lists


def language_in_use(taxonomy: Taxonomy, lang: str) -> bool:
    """True if any language-tagged literal anywhere carries *lang*."""
    return any(item.lang == lang for lst in _language_literal_lists(taxonomy) for item in lst)


def remove_language(taxonomy: Taxonomy, lang: str) -> int:
    """Strip every language-tagged literal in *lang* across all entities.

    Removes labels, comments, definitions, scope notes and scheme descriptions
    tagged *lang*. Returns the number of literals removed.
    """
    removed = 0
    for lst in _language_literal_lists(taxonomy):
        kept = [item for item in lst if item.lang != lang]
        removed += len(lst) - len(kept)
        lst[:] = kept  # mutate in place — the entity holds this exact list
    return removed


def count_uri_references(taxonomy: Taxonomy, uri: str) -> int:
    """Total statements affected by renaming *uri*, across every layer it owns.

    Dispatches to :func:`count_concept_uri_references` and/or
    :func:`count_owl_uri_references`; a promoted node sums both.
    """
    total = 0
    if uri in taxonomy.concepts:
        total += count_concept_uri_references(taxonomy, uri)
    if _owns_owl(taxonomy, uri):
        total += count_owl_uri_references(taxonomy, uri)
    return total


# URI-valued list fields, per layer. Named here rather than spelled out inline so
# the retarget walk covers the same reference sites the rename paths do.
_CONCEPT_LINK_FIELDS = (
    "broader",
    "narrower",
    "related",
    "broad_match",
    "narrow_match",
    "related_match",
    "exact_match",
    "close_match",
)
_CLASS_LINK_FIELDS = ("sub_class_of", "equivalent_class", "disjoint_with")
_PROPERTY_LINK_FIELDS = ("domains", "ranges", "sub_property_of", "inverse_of")


def retarget_uri_references(taxonomy: Taxonomy, old_uri: str, new_uri: str) -> int:
    """Point every reference to *old_uri* at *new_uri*; return how many changed.

    For a URI that is *referenced* but never defined — a typo'd ``skos:broader``
    target, say.  :func:`rename_entity_uri` cannot help there: it renames an
    entity and raises :class:`ConceptNotFoundError` when there is none, yet a
    dangling link is the likeliest way a malformed URI reaches a file at all.

    Nothing is created.  If *new_uri* names no entity either, the link is still
    dangling, only spelled correctly — repairing the spelling and choosing a real
    target are separate decisions, and this makes the first without guessing at
    the second.
    """
    changed = _retarget_annotations(taxonomy.ontology_annotations, old_uri, new_uri)
    for scheme in taxonomy.schemes.values():
        changed += _retarget_list(scheme.top_concepts, old_uri, new_uri)
        changed += _retarget_annotations(scheme.annotations, old_uri, new_uri)
    for concept in taxonomy.concepts.values():
        changed += _retarget_fields(concept, _CONCEPT_LINK_FIELDS, old_uri, new_uri)
        for attr in ("top_concept_of", "focus"):
            if getattr(concept, attr) == old_uri:
                setattr(concept, attr, new_uri)
                changed += 1
    for cls in taxonomy.owl_classes.values():
        changed += _retarget_fields(cls, _CLASS_LINK_FIELDS, old_uri, new_uri)
        changed += _retarget_annotations(cls.annotations, old_uri, new_uri)
    for prop in taxonomy.owl_properties.values():
        changed += _retarget_fields(prop, _PROPERTY_LINK_FIELDS, old_uri, new_uri)
        changed += _retarget_annotations(prop.annotations, old_uri, new_uri)
    for individual in taxonomy.owl_individuals.values():
        changed += _retarget_individual(individual, old_uri, new_uri)
    return changed


def _retarget_annotations(annotations: list[OntologyAnnotation], old_uri: str, new_uri: str) -> int:
    """Retarget the generic annotation triples, as predicate or as IRI object.

    These matter more than they look: a pun's class facet parks every predicate it
    does not model — ``skos:broader`` included — in this list, so a link repaired
    only on the concept was serialised straight back out from the class and the
    error returned on the next open.

    A literal is left alone even when its text is exactly the URI. A note that
    *mentions* a bad URI is prose, and rewriting prose is not this function's job.
    """
    changed = 0
    for annotation in annotations:
        if annotation.predicate == old_uri:
            annotation.predicate = new_uri
            changed += 1
        if annotation.is_iri and annotation.value == old_uri:
            annotation.value = new_uri
            changed += 1
    return changed


def _retarget_individual(individual: OWLIndividual, old_uri: str, new_uri: str) -> int:
    """Retarget an individual's types and its assertions, as predicate or as object."""
    changed = _retarget_list(individual.types, old_uri, new_uri)
    for index, (prop, target) in enumerate(individual.property_values):
        if old_uri not in (prop, target):
            continue
        individual.property_values[index] = (
            new_uri if prop == old_uri else prop,
            new_uri if target == old_uri else target,
        )
        changed += 1
    for index, (prop, value, kind) in enumerate(individual.literal_values):
        if prop == old_uri:
            individual.literal_values[index] = (new_uri, value, kind)
            changed += 1
    return changed


def _retarget_fields(entity: object, fields: tuple[str, ...], old_uri: str, new_uri: str) -> int:
    """Retarget *old_uri* across several URI-list attributes of one entity."""
    return sum(_retarget_list(getattr(entity, f), old_uri, new_uri) for f in fields)


def _retarget_list(values: list[str], old_uri: str, new_uri: str) -> int:
    """Replace *old_uri* in *values* in place; return how many entries changed."""
    changed = 0
    for index, value in enumerate(values):
        if value == old_uri:
            values[index] = new_uri
            changed += 1
    return changed


def rename_entity_uri(taxonomy: Taxonomy, old_uri: str, new_uri: str) -> None:
    """Rename *old_uri* to *new_uri* in every layer that owns it.

    Performs a single unified collision check (raising
    :class:`URIAlreadyExistsError` if *new_uri* is already taken in any layer)
    before delegating to the SKOS-specialized :func:`rename_uri` and/or the
    OWL-specialized :func:`rename_owl_uri`.  Raises
    :class:`ConceptNotFoundError` when *old_uri* exists in no layer.
    """
    in_concepts = old_uri in taxonomy.concepts
    in_owl = _owns_owl(taxonomy, old_uri)
    if not in_concepts and not in_owl:
        raise ConceptNotFoundError(old_uri)

    if new_uri in taxonomy.concepts or _owns_owl(taxonomy, new_uri):
        raise URIAlreadyExistsError(new_uri)

    if in_concepts:
        rename_uri(taxonomy, old_uri, new_uri)
    if in_owl:
        rename_owl_uri(taxonomy, old_uri, new_uri)

    assign_handles(taxonomy)


# ──────────────────────── schema.org media (image/video/url) ──────────────────
# A cross-layer concern: concepts, OWL classes, and individuals all carry
# schema_images / schema_videos / schema_urls lists.

_SCHEMA_MEDIA_KINDS = {"image", "video", "url"}


def _schema_media_entity(taxonomy: Taxonomy, uri: str) -> object | None:
    """The concept/class/individual identified by *uri* (schema media lives on these)."""
    return (
        taxonomy.concepts.get(uri)
        or taxonomy.owl_classes.get(uri)
        or taxonomy.owl_individuals.get(uri)
    )


def add_schema_media(taxonomy: Taxonomy, uri: str, kind: str, url: str) -> None:
    """Append a schema:image/video/url *url* to *uri* (dedup; no-op on bad uri/kind)."""
    entity = _schema_media_entity(taxonomy, uri)
    if entity is None or kind not in _SCHEMA_MEDIA_KINDS:
        return
    lst: list[str] = getattr(entity, f"schema_{kind}s")
    if url not in lst:
        lst.append(url)


def remove_schema_media(taxonomy: Taxonomy, uri: str, kind: str, url: str) -> None:
    """Remove a schema:image/video/url *url* from *uri* (no-op on bad uri/kind/url)."""
    entity = _schema_media_entity(taxonomy, uri)
    if entity is None or kind not in _SCHEMA_MEDIA_KINDS:
        return
    lst: list[str] = getattr(entity, f"schema_{kind}s")
    if url in lst:
        lst.remove(url)
