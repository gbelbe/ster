"""Payload builder for the treemap taxonomy view.

Reduces a SKOS taxonomy to a lightweight hierarchy suitable for a d3-hierarchy
treemap: schemes, concept tree, depth, and descendant counts. Detail (labels,
definitions, relations) stays on the existing on-demand detail-panel channel —
this payload only carries what is needed to lay out and label tiles.

A concept reachable as ``narrower`` from more than one parent keeps only the
first parent encountered by the traversal below (deterministic scheme /
top-concept / narrower list order) — full DAG handling (multi-parent
indicator, cycle detection) is out of scope for this increment.
"""

from __future__ import annotations

from collections import deque

from .model import Taxonomy

# Synthetic scheme URI grouping concepts unreachable from any real scheme's
# top concepts. Never collides with a real URI (not a valid http(s) scheme URI).
NO_SCHEME_URI = "urn:ster:no-scheme"
_NO_SCHEME_TITLE = "(no scheme)"


def has_taxonomy(taxonomy: Taxonomy) -> bool:
    """True when the taxonomy carries any SKOS content."""
    return bool(taxonomy.schemes or taxonomy.concepts)


def is_skos_only(taxonomy: Taxonomy) -> bool:
    """True when the taxonomy has SKOS content and no OWL content at all."""
    return has_taxonomy(taxonomy) and not (
        taxonomy.owl_classes or taxonomy.owl_individuals or taxonomy.owl_properties
    )


def _bfs_assign(
    taxonomy: Taxonomy,
    root_uris: list[str],
    scheme_uri: str,
    depth_of: dict[str, int],
    parent_of: dict[str, str],
    children_of: dict[str, list[str]],
    scheme_of: dict[str, str],
) -> None:
    """Assign depth/parent/children for every concept reachable from *root_uris*.

    Each concept is assigned exactly once, at first discovery (``depth_of`` is
    the visited set) — a concept re-encountered via a second parent later in
    the traversal is skipped, which is what makes the resulting ``children_of``
    a tree by construction (first-parent-wins, no cycles possible).
    """
    queue: deque[tuple[str, str | None, int]] = deque(
        (uri, None, 0) for uri in root_uris if uri in taxonomy.concepts
    )
    while queue:
        uri, parent, depth = queue.popleft()
        if uri in depth_of:
            continue
        depth_of[uri] = depth
        scheme_of[uri] = scheme_uri
        children_of.setdefault(uri, [])
        if parent is not None:
            parent_of[uri] = parent
            children_of.setdefault(parent, []).append(uri)
        for child in taxonomy.concepts[uri].narrower:
            if child in taxonomy.concepts and child not in depth_of:
                queue.append((child, uri, depth + 1))


def _orphan_roots(taxonomy: Taxonomy, orphans: list[str]) -> list[str]:
    """Orphans not referenced as ``narrower`` by another orphan — safe roots
    for a forward (non-cyclic) traversal of the leftover concepts."""
    orphan_set = set(orphans)
    referenced = {
        child for uri in orphans for child in taxonomy.concepts[uri].narrower if child in orphan_set
    }
    return [u for u in orphans if u not in referenced]


def build_taxonomy_treemap(taxonomy: Taxonomy) -> dict:
    """Build the treemap payload: schemes, concept tree, depth, descendant counts.

    Concepts unreachable from any scheme's top concepts are grouped under a
    synthetic ``"(no scheme)"`` root, created only when at least one such
    orphan exists — an empty or pure-OWL taxonomy produces no synthetic root.
    """
    depth_of: dict[str, int] = {}
    parent_of: dict[str, str] = {}
    children_of: dict[str, list[str]] = {}
    scheme_of: dict[str, str] = {}
    schemes_out: list[dict] = []

    for scheme_uri, scheme in taxonomy.schemes.items():
        roots = [u for u in scheme.top_concepts if u in taxonomy.concepts]
        _bfs_assign(taxonomy, roots, scheme_uri, depth_of, parent_of, children_of, scheme_of)
        schemes_out.append({"uri": scheme_uri, "title": scheme.title("en"), "roots": roots})

    orphans = [uri for uri in taxonomy.concepts if uri not in depth_of]
    if orphans:
        orphan_roots = _orphan_roots(taxonomy, orphans)
        _bfs_assign(
            taxonomy, orphan_roots, NO_SCHEME_URI, depth_of, parent_of, children_of, scheme_of
        )

        # A pure cycle among orphans has no reference-free entry point — force
        # each remaining concept to surface as its own root rather than drop it.
        stray = [uri for uri in taxonomy.concepts if uri not in depth_of]
        if stray:
            _bfs_assign(taxonomy, stray, NO_SCHEME_URI, depth_of, parent_of, children_of, scheme_of)
            orphan_roots = [*orphan_roots, *stray]

        schemes_out.append({"uri": NO_SCHEME_URI, "title": _NO_SCHEME_TITLE, "roots": orphan_roots})

    root_uris = [uri for s in schemes_out for uri in s["roots"]]
    descendant_count = _post_order_descendant_counts(children_of, root_uris)

    nodes = {
        uri: {
            "label": taxonomy.concepts[uri].pref_label("en"),
            "depth": depth_of[uri],
            "parent": parent_of.get(uri),
            "children": children_of.get(uri, []),
            "descendantCount": descendant_count.get(uri, 0),
            "schemeUri": scheme_of[uri],
        }
        for uri in depth_of
    }
    return {"schemes": schemes_out, "nodes": nodes}


def _post_order_descendant_counts(
    children_of: dict[str, list[str]], root_uris: list[str]
) -> dict[str, int]:
    """Bottom-up descendant count over the (acyclic-by-construction) ``children_of``
    tree, computed iteratively to avoid recursion-depth issues on deep trees.
    """
    counts: dict[str, int] = {}
    for root in root_uris:
        if root not in counts:
            _accumulate_descendant_counts(root, children_of, counts)
    return counts


def _accumulate_descendant_counts(
    root: str, children_of: dict[str, list[str]], counts: dict[str, int]
) -> None:
    """Iterative post-order walk of *root*'s subtree, filling *counts* in place.

    Carries a defensive guard against a cycle slipping through ``children_of``:
    a node re-visited while still being expanded stops there instead of looping.
    """
    stack: list[tuple[str, bool]] = [(root, False)]
    expanding: set[str] = set()
    while stack:
        uri, ready = stack.pop()
        if uri in counts:
            continue
        if ready:
            counts[uri] = sum(1 + counts.get(child, 0) for child in children_of.get(uri, []))
            expanding.discard(uri)
        elif uri in expanding:
            counts[uri] = 0  # defensive: unreachable given children_of's construction
        else:
            expanding.add(uri)
            stack.append((uri, True))
            stack.extend(
                (child, False) for child in children_of.get(uri, []) if child not in counts
            )
