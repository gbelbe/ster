"""Metadata-quality coverage for the ontology overview.

Pure functions: given the annotation-property catalogs configured in the config
panel, report how completely the ontology header and the entities populate them.
Drives the overview's "Metadata coverage" rows and the label-coverage metric.

An entity's *used predicates* combine its structured fields (mapped back to their
predicate URIs) with its generic bucket — ``annotations`` on classes/properties,
``property_values`` / ``literal_values`` on individuals — so a configured
predicate counts as present wherever it actually appears.
"""

from __future__ import annotations

from .model import Taxonomy

RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
RDFS_COMMENT = "http://www.w3.org/2000/01/rdf-schema#comment"
SKOS_PREFLABEL = "http://www.w3.org/2004/02/skos/core#prefLabel"
SCHEMA_IMAGE = "https://schema.org/image"
SCHEMA_VIDEO = "https://schema.org/video"
SCHEMA_URL = "https://schema.org/url"
NOTE = "https://example.org/ontology/kai-internal-knowledge#note"

# Predicates the "labelled" coverage metric accepts (rdfs:label and skos:prefLabel —
# the latter usable on any entity when configured, not just the SKOS layer).
LABEL_PREDICATES: frozenset[str] = frozenset({RDFS_LABEL, SKOS_PREFLABEL})


def _structured_predicates(entity: object) -> set[str]:
    """Predicate URIs implied by an entity's structured fields (label, comment, …)."""
    preds: set[str] = set()
    pairs = (
        ("labels", RDFS_LABEL),
        ("comments", RDFS_COMMENT),
        ("schema_images", SCHEMA_IMAGE),
        ("schema_videos", SCHEMA_VIDEO),
        ("schema_urls", SCHEMA_URL),
    )
    for attr, predicate in pairs:
        if getattr(entity, attr, None):
            preds.add(predicate)
    if getattr(entity, "note", ""):
        preds.add(NOTE)
    return preds


def entity_predicates(entity: object) -> set[str]:
    """Every predicate URI actually used on *entity*, regardless of entity kind."""
    preds = _structured_predicates(entity)
    for a in getattr(entity, "annotations", []):  # classes / properties
        preds.add(a.predicate)
    for pred, _value in getattr(entity, "property_values", []):  # individuals (IRI-valued)
        preds.add(pred)
    for literal in getattr(entity, "literal_values", []):  # individuals (literal-valued)
        preds.add(literal[0])
    return preds


def is_labelled(entity: object) -> bool:
    """True when *entity* carries an rdfs:label or a skos:prefLabel."""
    return bool(getattr(entity, "labels", None)) or bool(
        LABEL_PREDICATES & entity_predicates(entity)
    )


def _catalog_predicates(catalog: list[tuple[str, str]] | None) -> set[str]:
    return {predicate for predicate, _label in (catalog or [])}


def ontology_metadata_pct(taxonomy: Taxonomy, catalog: list[tuple[str, str]] | None) -> int | None:
    """Percent of the configured ontology-metadata predicates present on the header,
    or None when nothing is configured."""
    configured = _catalog_predicates(catalog)
    if not configured:
        return None
    present = {a.predicate for a in taxonomy.ontology_annotations}
    return round(100 * len(configured & present) / len(configured))


def _entity_fill(entity: object, configured: set[str]) -> float:
    return len(entity_predicates(entity) & configured) / len(configured)


def entity_metadata_pct(taxonomy: Taxonomy, catalog: list[tuple[str, str]] | None) -> int | None:
    """Average per-entity fill of the configured entity-metadata predicates across all
    classes, properties and individuals, or None when nothing is configured / present."""
    configured = _catalog_predicates(catalog)
    entities = [
        *taxonomy.owl_classes.values(),
        *taxonomy.owl_properties.values(),
        *taxonomy.owl_individuals.values(),
    ]
    if not configured or not entities:
        return None
    return round(100 * sum(_entity_fill(e, configured) for e in entities) / len(entities))


def overview_coverage(
    taxonomy: Taxonomy,
    ontology_catalog: list[tuple[str, str]] | None,
    entity_catalog: list[tuple[str, str]] | None,
) -> dict[str, int | None]:
    """The two overview coverage percentages (``None`` when not computable)."""
    return {
        "ontology_pct": ontology_metadata_pct(taxonomy, ontology_catalog),
        "entity_pct": entity_metadata_pct(taxonomy, entity_catalog),
    }
