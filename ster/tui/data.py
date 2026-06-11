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
    if uri in tax.owl_classes:
        return tax.owl_classes[uri].label(lang) or _local(uri)
    if uri in tax.owl_individuals:
        return tax.owl_individuals[uri].label(lang) or _local(uri)
    if uri in tax.owl_properties:
        return tax.owl_properties[uri].label(lang) or _local(uri)
    if uri in tax.concepts:
        return tax.concepts[uri].pref_label(lang) or _local(uri)
    if uri in tax.schemes:
        return tax.schemes[uri].title(lang) or _local(uri)
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


# ── detail panel (progressive disclosure: most important first) ────────────────


def _fact(label: str, value: str) -> str:
    return f"[b]{label}[/b]  {value}" if value else ""


def detail_markup(tax: Taxonomy, uri: str, lang: str = "en") -> str:
    """Rich-markup detail for *uri* — compact, important facts first."""
    kind = kind_of(tax, uri)
    head = f"{ICON.get(kind, '')}  [b]{label_of(tax, uri, lang)}[/b]   [dim]{kind}[/dim]"
    lines = [head, f"[dim]{uri}[/dim]", ""]

    if kind == "class":
        cls = tax.owl_classes[uri]
        if cls.comments:
            lines += [cls.comments[0].value, ""]
        parents = [label_of(tax, p, lang) for p in cls.sub_class_of if p in tax.owl_classes]
        kids = subclasses(tax, uri, lang)
        inds = individuals_of(tax, uri, lang)
        lines += [
            _fact("Subclass of", ", ".join(parents) or "[dim]—[/dim]"),
            _fact(
                "Subclasses",
                f"{len(kids)}"
                + (f"  ({', '.join(label_of(tax, k, lang) for k in kids[:6])})" if kids else ""),
            ),
            _fact("Individuals", ", ".join(label_of(tax, i, lang) for i in inds) or "[dim]—[/dim]"),
        ]
    elif kind == "individual":
        ind = tax.owl_individuals[uri]
        if ind.comments:
            lines += [ind.comments[0].value, ""]
        types = [label_of(tax, t, lang) for t in ind.types]
        lines.append(_fact("Type", ", ".join(types) or "[dim]—[/dim]"))
        for prop_uri, val in ind.property_values:
            lines.append(_fact(label_of(tax, prop_uri, lang), label_of(tax, val, lang)))
        for prop_uri, val, _dt in ind.literal_values:
            lines.append(_fact(label_of(tax, prop_uri, lang), str(val)))
    elif kind == "property":
        p = tax.owl_properties[uri]
        if p.comments:
            lines += [p.comments[0].value, ""]
        lines += [
            _fact("Kind", p.prop_type or "[dim]—[/dim]"),
            _fact(
                "Domain", ", ".join(label_of(tax, d, lang) for d in p.domains) or "[dim]any[/dim]"
            ),
            _fact("Range", ", ".join(label_of(tax, r, lang) for r in p.ranges) or "[dim]any[/dim]"),
        ]
    elif kind == "concept":
        con = tax.concepts[uri]
        if con.definitions:
            lines += [con.definitions[0].value, ""]
        lines.append(_fact("Narrower", f"{len([n for n in con.narrower if n in tax.concepts])}"))
    elif kind == "scheme":
        lines.append(_fact("Top concepts", f"{len(tax.schemes[uri].top_concepts)}"))

    handle = tax.uri_to_handle(uri)
    if handle:
        lines += ["", f"[dim]handle[/dim]  [cyan]{handle}[/cyan]"]
    return "\n".join(line for line in lines if line is not None)
