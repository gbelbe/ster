"""Pure taxonomy → view-model adapters for the Textual spike.

No Textual imports here — these are plain functions over ``Taxonomy`` so they
can be unit-tested without a terminal. The Textual layer (``app.py``) turns
their output into ``Tree`` nodes, a detail panel, and the search palette.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ster.model import Taxonomy

# Clean geometric glyphs per node kind (monospace-friendly; sharper than emoji).
# Kinds are visually distinct so a merged SKOS+OWL tree stays legible: a filled
# class ● vs a hollow concept ○ vs a punned ◉ (both) vs a diamond individual ◆.
ICON = {
    "class": "●",
    "concept": "○",
    "promoted": "◉",  # a pun — skos:Concept *and* owl:Class
    "individual": "◆",
    "property": "■",
    "scheme": "⬢",
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


# ── integrated (paradigm-agnostic) tree ───────────────────────────────────────
# One tree that merges the SKOS spine and the OWL class hierarchy, so the same
# builder serves a pure ontology, a pure taxonomy, a disjoint mix, or a punned
# mix — no "mode" flag. The SKOS spine is authoritative: a pun (skos:Concept +
# owl:Class) hangs by ``broader``/scheme, and its OWL subclasses are pulled up
# under it (the one-way bridge — subClassOf feeds broader, never the reverse).

# Anchor node for top-level OWL classes and loose (untyped) individuals — the
# implicit ``owl:Thing`` root. A sentinel URI, never a real ontology term.
ONTOLOGY_ROOT = "ster:__owl_thing__"


@dataclass(frozen=True)
class IntegratedTree:
    """A merged SKOS+OWL forest. ``parent`` maps each placed node to its parent
    (another node, a scheme, or :data:`ONTOLOGY_ROOT`); ``children`` is the
    inverse, label-sorted; ``roots`` are the top-level nodes (each scheme, then
    the ontology root when any class/loose individual needs it)."""

    parent: dict[str, str] = field(default_factory=dict)
    children: dict[str, list[str]] = field(default_factory=dict)
    roots: list[str] = field(default_factory=list)


def _concept_parent(tax: Taxonomy, uri: str) -> str:
    """Parent of a concept/pun on the SKOS spine: ``broader`` → scheme → root.
    (``store`` keeps ``top_concept_of`` in sync with scheme membership, so a
    scheme-less loose concept is the only case that reaches the root.)"""
    c = tax.concepts[uri]
    if c.broader:
        return c.broader[0]  # primary parent (polyhierarchy: first wins for now)
    if c.top_concept_of:
        return c.top_concept_of
    return ONTOLOGY_ROOT  # loose concept with no scheme — surfaced, never lost


def effective_parent(tax: Taxonomy, uri: str) -> str:
    """The node's single parent in the integrated tree, agnostic to paradigm.

    Concepts and puns follow the SKOS spine; a *pure* class follows
    ``subClassOf`` (landing under a pun when its superclass is one — the
    bridge); an individual nests under its type. Anything with no home lands on
    :data:`ONTOLOGY_ROOT` so nothing is dropped.
    """
    nt = tax.node_type(uri)
    if nt in ("concept", "promoted"):
        return _concept_parent(tax, uri)
    if nt == "class":
        parents = [p for p in tax.owl_classes[uri].sub_class_of if p in tax.owl_classes]
        return parents[0] if parents else ONTOLOGY_ROOT
    if nt == "individual":
        typed = [t for t in tax.owl_individuals[uri].types if t in tax.owl_classes]
        return typed[0] if typed else ONTOLOGY_ROOT
    return ONTOLOGY_ROOT


def integrated_tree(tax: Taxonomy, lang: str = "en") -> IntegratedTree:
    """Build the merged SKOS+OWL forest for *tax* (see :class:`IntegratedTree`)."""
    # Puns live in ``concepts`` already; add only the *pure* classes on top.
    placed = (
        list(tax.concepts)
        + [u for u in tax.owl_classes if u not in tax.concepts]
        + list(tax.owl_individuals)
    )
    parent = {uri: effective_parent(tax, uri) for uri in placed}
    children: dict[str, list[str]] = defaultdict(list)
    for uri in placed:
        children[parent[uri]].append(uri)
    sorted_children = {p: _by_label(tax, kids, lang) for p, kids in children.items()}

    roots = _by_label(tax, list(tax.schemes), lang)
    if ONTOLOGY_ROOT in children:
        roots.append(ONTOLOGY_ROOT)
    return IntegratedTree(parent=parent, children=sorted_children, roots=roots)


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
