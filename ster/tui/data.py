"""Pure taxonomy → view-model adapters for the Textual spike.

No Textual imports here — these are plain functions over ``Taxonomy`` so they
can be unit-tested without a terminal. The Textual layer (``app.py``) turns
their output into ``Tree`` nodes, a detail panel, and the search palette.
"""

from __future__ import annotations

from ster.model import Taxonomy

# Clean geometric glyphs per node kind (monospace-friendly; sharper than emoji).
ICON = {
    "class": "●",
    "individual": "⬥",
    "property": "■",
    "concept": "●",
    "scheme": "◉",
    "section": "▸",
}


def _local(uri: str) -> str:
    return uri.rstrip("/#").rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def languages_in_use(tax: Taxonomy) -> list[str]:
    """Sorted language codes that appear on any label across the taxonomy."""
    langs: set[str] = set()
    stores = (tax.owl_classes, tax.owl_individuals, tax.owl_properties, tax.concepts, tax.schemes)
    for store in stores:
        for entity in store.values():
            for label in getattr(entity, "labels", []):
                if label.lang:
                    langs.add(label.lang)
    return sorted(langs)


def label_of(tax: Taxonomy, uri: str, lang: str = "en") -> str:
    """Best human label for *uri* across every layer, falling back to local name."""
    sources = (
        (tax.owl_classes, lambda e: e.label(lang)),
        (tax.owl_individuals, lambda e: e.label(lang)),
        (tax.owl_properties, lambda e: e.label(lang)),
        (tax.concepts, lambda e: e.pref_label(lang)),
        (tax.schemes, lambda e: e.title(lang)),
    )
    for container, get in sources:
        entity = container.get(uri)
        if entity is not None:
            return get(entity) or _local(uri)
    return _local(uri)


def node_name(tax: Taxonomy, uri: str, lang: str, kind: str) -> str:
    """Tree-leaf display text: a property's local name (e.g. ``hasOwner``), and the
    human label for every other kind. Properties are shown by name, not rdfs:label."""
    if kind == "property":
        prop = tax.owl_properties.get(uri)
        if prop is not None:
            return prop.local_name
    return label_of(tax, uri, lang)


def kind_of(tax: Taxonomy, uri: str) -> str:
    if uri in tax.owl_classes:
        return "class"
    if uri in tax.owl_individuals:
        return "individual"
    if uri in tax.owl_properties:
        return "property"
    if uri in tax.schemes:
        return "scheme"
    if uri in tax.concepts:
        return "concept"
    return "section"


# ── hierarchy walkers ─────────────────────────────────────────────────────────


def _by_label(tax: Taxonomy, uris: list[str], lang: str) -> list[str]:
    return sorted(uris, key=lambda u: label_of(tax, u, lang).lower())


def class_roots(tax: Taxonomy, lang: str = "en") -> list[str]:
    """Top-level OWL classes — those with no superclass that is itself a class."""
    roots = [
        uri
        for uri, c in tax.owl_classes.items()
        if not any(p in tax.owl_classes for p in c.sub_class_of)
    ]
    return _by_label(tax, roots, lang)


def subclasses(tax: Taxonomy, uri: str, lang: str = "en") -> list[str]:
    kids = [u for u, c in tax.owl_classes.items() if uri in c.sub_class_of and u != uri]
    return _by_label(tax, kids, lang)


def individuals_of(tax: Taxonomy, class_uri: str, lang: str = "en") -> list[str]:
    inds = [u for u, ind in tax.owl_individuals.items() if class_uri in ind.types]
    return _by_label(tax, inds, lang)


def untyped_individuals(tax: Taxonomy, lang: str = "en") -> list[str]:
    inds = [
        u
        for u, ind in tax.owl_individuals.items()
        if not any(t in tax.owl_classes for t in ind.types)
    ]
    return _by_label(tax, inds, lang)


def properties(tax: Taxonomy, lang: str = "en") -> list[str]:
    return _by_label(tax, list(tax.owl_properties), lang)


# The three OWL property kinds, in display order; anything else is "untyped".
PROPERTY_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("ObjectProperty", "Object Properties"),
    ("DatatypeProperty", "Datatype Properties"),
    ("AnnotationProperty", "Annotation Properties"),
)
UNTYPED_PROPERTIES_TITLE = "Untyped Properties"


def _local_property_buckets(tax: Taxonomy, lang: str) -> dict[str, list[str]]:
    """Locally-declared properties bucketed by group title (label-sorted)."""
    titles = dict(PROPERTY_CATEGORIES)
    buckets: dict[str, list[str]] = {title: [] for _, title in PROPERTY_CATEGORIES}
    buckets[UNTYPED_PROPERTIES_TITLE] = []
    for uri in properties(tax, lang):
        title = titles.get(tax.owl_properties[uri].prop_type, UNTYPED_PROPERTIES_TITLE)
        buckets[title].append(uri)
    return buckets


def _external_property_buckets(tax: Taxonomy, lang: str) -> dict[str, list[str]]:
    """Predicates *used* on the ontology header but never declared as properties,
    bucketed by group: annotation predicates → Annotation, the rest → Untyped."""
    from ster.ontology_imports import is_annotation_property

    declared = set(tax.owl_properties)
    seen: set[str] = set()
    used: list[str] = []
    for a in tax.ontology_annotations:
        if a.predicate not in declared and a.predicate not in seen:
            seen.add(a.predicate)
            used.append(a.predicate)
    buckets: dict[str, list[str]] = {}
    annotation_title = dict(PROPERTY_CATEGORIES)["AnnotationProperty"]
    for uri in _by_label(tax, used, lang):
        title = annotation_title if is_annotation_property(tax, uri) else UNTYPED_PROPERTIES_TITLE
        buckets.setdefault(title, []).append(uri)
    return buckets


def property_groups(tax: Taxonomy, lang: str = "en") -> list[tuple[str, list[str], list[str]]]:
    """Each property group as ``(title, local_uris, external_uris)``.

    *local* are properties declared in this file (bucketed by their OWL kind);
    *external* are predicates merely *used* on the ontology header (e.g.
    ``dcterms:creator``) that were never declared. The three OWL groups always
    appear (possibly with both lists empty); the trailing "Untyped Properties"
    group appears only when it holds something.
    """
    local = _local_property_buckets(tax, lang)
    external = _external_property_buckets(tax, lang)
    ordered = [title for _, title in PROPERTY_CATEGORIES] + [UNTYPED_PROPERTIES_TITLE]
    result: list[tuple[str, list[str], list[str]]] = []
    for title in ordered:
        loc, ext = local[title], external.get(title, [])
        if title == UNTYPED_PROPERTIES_TITLE and not loc and not ext:
            continue
        result.append((title, loc, ext))
    return result


def scheme_roots(tax: Taxonomy, lang: str = "en") -> list[str]:
    return _by_label(tax, list(tax.schemes), lang)


def concept_children(tax: Taxonomy, uri: str, lang: str = "en") -> list[str]:
    if uri in tax.schemes:
        kids = list(tax.schemes[uri].top_concepts)
    else:
        c = tax.concepts.get(uri)
        kids = list(c.narrower) if c else []
    return _by_label(tax, [u for u in kids if u in tax.concepts], lang)


# ── search index (for the command palette) ────────────────────────────────────


def search_rows(tax: Taxonomy, lang: str = "en") -> list[tuple[str, str, str]]:
    """``(label, uri, kind)`` for every browsable entity, sorted by label."""
    rows: list[tuple[str, str, str]] = []
    for uri in tax.owl_classes:
        rows.append((label_of(tax, uri, lang), uri, "class"))
    for uri in tax.owl_individuals:
        rows.append((label_of(tax, uri, lang), uri, "individual"))
    for uri in tax.owl_properties:
        rows.append((label_of(tax, uri, lang), uri, "property"))
    for uri in tax.concepts:
        rows.append((label_of(tax, uri, lang), uri, "concept"))
    return sorted(rows, key=lambda r: r[0].lower())
