"""Pure taxonomy → view-model adapters for the Textual spike.

No Textual imports here — these are plain functions over ``Taxonomy`` so they
can be unit-tested without a terminal. The Textual layer (``app.py``) turns
their output into ``Tree`` nodes, a detail panel, and the search palette.
"""

from __future__ import annotations

from ster.model import Taxonomy

# Clean geometric glyphs per node kind (monospace-friendly; sharper than emoji).
ICON = {
    "class": "■",
    "individual": "•",
    "property": "◆",
    "concept": "●",
    "scheme": "◉",
    "section": "▸",
}


def _local(uri: str) -> str:
    return uri.rstrip("/#").rsplit("/", 1)[-1].rsplit("#", 1)[-1]


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
