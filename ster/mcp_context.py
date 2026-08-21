"""Read-only context assembly for the MCP server.

Pure functions over a :class:`~ster.model.Taxonomy` that return plain,
JSON-ready dicts — what an agent needs to answer "what is this ontology, what
am I looking at, and what does it contain?".

Deliberately free of any MCP/protocol import: the protocol lives in
``ster/mcp_server.py``, so everything here is testable without a transport and
without the SDK. Nothing in this module mutates the taxonomy.
"""

from __future__ import annotations

import re
from typing import Any

from .model import Taxonomy, is_builtin_uri

# Entity kinds, in the order a URI is looked up. A dispatch table rather than an
# if/elif chain so adding a kind is one row.
_KINDS: tuple[tuple[str, str], ...] = (
    ("concept", "concepts"),
    ("class", "owl_classes"),
    ("individual", "owl_individuals"),
    ("property", "owl_properties"),
    ("scheme", "schemes"),
)

# Each model class spells its display label differently.
_LABELLERS = {
    "concept": lambda obj, lang: obj.pref_label(lang),
    "class": lambda obj, lang: obj.label(lang),
    "individual": lambda obj, lang: obj.label(lang),
    "property": lambda obj, lang: obj.label(lang),
    "scheme": lambda obj, lang: obj.title(lang),
}

# SPARQL forms that would modify the store. The server is read-only, so these
# are refused before the query ever reaches rdflib.
_WRITE_KEYWORDS = (
    "insert",
    "delete",
    "drop",
    "clear",
    "load",
    "create",
    "add",
    "move",
    "copy",
)


def kind_of(taxonomy: Taxonomy, uri: str) -> str | None:
    """The entity kind for *uri*, or None when the URI is not in the taxonomy."""
    for kind, attr in _KINDS:
        if uri in getattr(taxonomy, attr):
            return kind
    return None


def _obj(taxonomy: Taxonomy, uri: str, kind: str) -> Any:
    attr = next(a for k, a in _KINDS if k == kind)
    return getattr(taxonomy, attr)[uri]


def label_of(taxonomy: Taxonomy, uri: str, lang: str = "en") -> str:
    """Display label for *uri*, falling back to its local name."""
    kind = kind_of(taxonomy, uri)
    if kind is None:
        return uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    return _LABELLERS[kind](_obj(taxonomy, uri, kind), lang)


def _ref(taxonomy: Taxonomy, uri: str, lang: str) -> dict[str, str]:
    """A compact {uri, label} pointer — how neighbours are reported."""
    return {"uri": uri, "label": label_of(taxonomy, uri, lang)}


def parents_of(taxonomy: Taxonomy, uri: str, kind: str) -> list[str]:
    """Broader concepts (SKOS) or superclasses (OWL); built-ins excluded."""
    if kind == "concept":
        return list(taxonomy.concepts[uri].broader)
    if kind == "class":
        return [p for p in taxonomy.owl_classes[uri].sub_class_of if not is_builtin_uri(p)]
    return []


def children_of(taxonomy: Taxonomy, uri: str, kind: str) -> list[str]:
    """Narrower concepts (SKOS) or direct subclasses (OWL)."""
    if kind == "concept":
        return list(taxonomy.concepts[uri].narrower)
    if kind == "class":
        return [u for u, cls in taxonomy.owl_classes.items() if uri in cls.sub_class_of]
    return []


def ancestors_of(taxonomy: Taxonomy, uri: str) -> list[str]:
    """Root-first ancestor chain for *uri*, excluding *uri* itself.

    Cycle-safe: a taxonomy with a broader-loop stops instead of hanging.
    """
    chain: list[str] = []
    seen: set[str] = {uri}
    current = uri
    while True:
        kind = kind_of(taxonomy, current)
        parents = parents_of(taxonomy, current, kind) if kind else []
        nxt = next((p for p in parents if p not in seen), None)
        if nxt is None:
            break
        chain.append(nxt)
        seen.add(nxt)
        current = nxt
    return list(reversed(chain))


def _texts(items: list[Any], lang: str) -> list[str]:
    """Values of Label/Definition entries, preferring *lang* but never empty-handed."""
    preferred = [i.value for i in items if i.lang == lang and i.value]
    return preferred or [i.value for i in items if i.value]


def _descriptions(obj: Any, lang: str) -> list[str]:
    """skos:definition or rdfs:comment text, whichever the entity carries."""
    return _texts(getattr(obj, "definitions", None) or getattr(obj, "comments", []) or [], lang)


def entity(taxonomy: Taxonomy, uri: str, lang: str = "en") -> dict[str, Any]:
    """Full detail for one *uri*.

    Unknown URIs return an ``error`` payload rather than raising — an agent
    guessing a URI should get a usable answer, not a protocol-level failure.
    """
    kind = kind_of(taxonomy, uri)
    if kind is None:
        return {"error": "unknown_uri", "uri": uri}
    obj = _obj(taxonomy, uri, kind)
    return {
        "uri": uri,
        "kind": kind,
        "label": _LABELLERS[kind](obj, lang),
        "labels": _texts(getattr(obj, "labels", []), lang),
        "descriptions": _descriptions(obj, lang),
        "parents": [_ref(taxonomy, p, lang) for p in parents_of(taxonomy, uri, kind)],
        "children": [_ref(taxonomy, c, lang) for c in children_of(taxonomy, uri, kind)],
        "types": list(getattr(obj, "types", [])),
    }


def overview(taxonomy: Taxonomy, lang: str = "en") -> dict[str, Any]:
    """Orientation: what this file is and how much of each thing it holds."""
    return {
        "ontology_uri": taxonomy.ontology_uri,
        "title": taxonomy.ontology_title,
        "file": str(taxonomy.file_path) if taxonomy.file_path else None,
        "counts": {
            "schemes": len(taxonomy.schemes),
            "concepts": len(taxonomy.concepts),
            "classes": len(taxonomy.owl_classes),
            "individuals": len(taxonomy.owl_individuals),
            "properties": len(taxonomy.owl_properties),
        },
        "schemes": [_ref(taxonomy, u, lang) for u in taxonomy.schemes],
        "languages": languages_in(taxonomy),
    }


def languages_in(taxonomy: Taxonomy) -> list[str]:
    """Every language tag appearing on a concept or class label, sorted."""
    langs: set[str] = set()
    for concept in taxonomy.concepts.values():
        langs.update(lbl.lang for lbl in concept.labels if lbl.lang)
    for cls in taxonomy.owl_classes.values():
        langs.update(lbl.lang for lbl in cls.labels if lbl.lang)
    return sorted(langs)


def search(
    taxonomy: Taxonomy, query: str, limit: int = 20, lang: str = "en"
) -> list[dict[str, str]]:
    """Case-insensitive label substring search across every entity kind."""
    needle = query.strip().lower()
    if not needle:
        return []
    hits: list[dict[str, str]] = []
    for kind, attr in _KINDS:
        for uri in getattr(taxonomy, attr):
            label = _LABELLERS[kind](_obj(taxonomy, uri, kind), lang)
            if needle in label.lower() or needle in uri.lower():
                hits.append({"uri": uri, "label": label, "kind": kind})
                if len(hits) >= limit:
                    return hits
    return hits


def current_context(
    taxonomy: Taxonomy, selected_uri: str | None, lang: str = "en"
) -> dict[str, Any]:
    """What the user is looking at right now.

    With no live selection — no TUI attached, or nothing focused yet — this
    degrades to the file overview rather than erroring, so the tool is always
    answerable.
    """
    if selected_uri is None or kind_of(taxonomy, selected_uri) is None:
        return {"focused": None, "overview": overview(taxonomy, lang)}
    return {
        "focused": entity(taxonomy, selected_uri, lang),
        "ancestors": [_ref(taxonomy, a, lang) for a in ancestors_of(taxonomy, selected_uri)],
        "siblings": [_ref(taxonomy, s, lang) for s in siblings_of(taxonomy, selected_uri)],
        "overview": overview(taxonomy, lang),
    }


def siblings_of(taxonomy: Taxonomy, uri: str) -> list[str]:
    """Entities sharing a parent with *uri* (excluding *uri*)."""
    kind = kind_of(taxonomy, uri)
    if kind is None:
        return []
    out: list[str] = []
    for parent in parents_of(taxonomy, uri, kind):
        out.extend(s for s in children_of(taxonomy, parent, kind) if s != uri and s not in out)
    return out


def is_read_only_sparql(query: str) -> bool:
    """False when *query* contains a SPARQL Update form.

    Keyword-based on purpose: the server must refuse writes before rdflib parses
    anything. Matching is word-boundary anchored so a URI or a label containing
    e.g. "created" is not mistaken for a CREATE.
    """
    stripped = re.sub(r"#[^\n]*", " ", query)  # drop comments
    stripped = re.sub(r"[\"'][^\"']*[\"']", " ", stripped)  # drop string literals
    stripped = re.sub(r"<[^>]*>", " ", stripped)  # drop URIs
    return not any(re.search(rf"\b{kw}\b", stripped, flags=re.IGNORECASE) for kw in _WRITE_KEYWORDS)


def run_sparql(taxonomy: Taxonomy, query: str) -> dict[str, Any]:
    """Run a read-only SPARQL query against the taxonomy's source file."""
    if not is_read_only_sparql(query):
        return {"error": "read_only", "message": "This server accepts SELECT/ASK queries only."}
    if taxonomy.file_path is None:
        return {"error": "no_source_file", "message": "The taxonomy has no file to query."}

    from .sparql_query import run_query  # noqa: PLC0415  (heavy rdflib import)

    result = run_query([taxonomy.file_path], query)
    if result.error:
        return {"error": "query_error", "message": result.error}
    return {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": len(result.rows),
        "query_type": result.query_type,
    }
