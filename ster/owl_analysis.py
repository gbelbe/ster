"""Pure OWL/RDFS class analysis — no I/O, no curses dependency.

Mirrors taxonomy_analysis.py but for the owl_classes layer.
Plugged into the same analysis_cache mechanism via a synthetic key.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .model import Taxonomy


@dataclass
class OWLClassStats:
    """Structural and quality statistics for the OWL/RDFS class layer."""

    total_classes: int
    pure_classes: int  # in owl_classes but NOT in concepts (no SKOS counterpart)
    promoted: int  # in both owl_classes AND concepts
    root_classes: int  # no sub_class_of pointing to another known class
    max_depth: int
    missing_label: int  # classes with no rdfs:label
    missing_comment: int  # classes with no rdfs:comment


def compute_owl_analysis(taxonomy: Taxonomy) -> OWLClassStats:
    """Compute OWL class statistics. Pure — safe to call from any context."""
    classes = taxonomy.owl_classes
    if not classes:
        return OWLClassStats(
            total_classes=0,
            pure_classes=0,
            promoted=0,
            root_classes=0,
            max_depth=0,
            missing_label=0,
            missing_comment=0,
        )

    # Build children index within known classes
    children_of: dict[str, list[str]] = {uri: [] for uri in classes}
    roots: list[str] = []
    for uri, cls in classes.items():
        parents_in_graph = [p for p in cls.sub_class_of if p in classes]
        if parents_in_graph:
            for p in parents_in_graph:
                children_of[p].append(uri)
        else:
            roots.append(uri)

    # BFS depth from each root
    depths: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque((r, 0) for r in roots)
    while queue:
        uri, d = queue.popleft()
        if uri in depths:
            continue
        depths[uri] = d
        for child in children_of.get(uri, []):
            if child not in depths:
                queue.append((child, d + 1))

    max_depth = max(depths.values(), default=0)
    promoted = sum(1 for uri in classes if uri in taxonomy.concepts)
    missing_label = sum(1 for cls in classes.values() if not cls.labels)
    missing_comment = sum(1 for cls in classes.values() if not cls.comments)

    return OWLClassStats(
        total_classes=len(classes),
        pure_classes=len(classes) - promoted,
        promoted=promoted,
        root_classes=len(roots),
        max_depth=max_depth,
        missing_label=missing_label,
        missing_comment=missing_comment,
    )
