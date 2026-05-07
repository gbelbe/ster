"""Pure OWL/RDFS ontology analysis — no I/O, no curses dependency.

Architecture
------------
Adding a new quality check is a one-step operation: implement a function
matching OntologyIssueDetector and append it to ONTOLOGY_ISSUE_DETECTORS.
No other code needs to change.

Data flow
---------
    compute_ontology_analysis(taxonomy)
        ├─ _build_class_hierarchy()    → depths, children_of, roots
        ├─ _compute_property_fill()    → dict[prop_uri → float]
        ├─ _compute_class_metrics()    → list[ClassMetrics]
        ├─ _compute_level_summaries()  → list[LevelSummary]
        ├─ _compute_ontology_stats()   → OntologyStats
        └─ ONTOLOGY_ISSUE_DETECTORS[*]() + fill-rate issues → list[Issue]

Backward compat
---------------
OWLClassStats + compute_owl_analysis() are kept unchanged for existing callers.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from .analysis_base import (
    _SEVERITY_RANK,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    Issue,
    pct,
)
from .model import Taxonomy

# Alias — OntologyIssue and Issue are the same type; both names are public.
OntologyIssue = Issue

# ── Issue display names ───────────────────────────────────────────────────────

ONTOLOGY_ISSUE_DISPLAY_NAMES: dict[str, str] = {
    "class_missing_label": "No rdfs:label",
    "class_missing_comment": "No rdfs:comment",
    "individual_missing_label": "Individual no label",
    "individual_no_type": "Individual untyped",
    "property_missing_label": "Property no label",
    "property_missing_domain": "No rdfs:domain",
    "property_missing_range": "No rdfs:range",
    "property_low_fill": "Low property fill",
}

PROPERTY_FILL_THRESHOLD: float = 0.80

# ── Backward-compat flat stats ────────────────────────────────────────────────


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


# ── Rich analysis types ───────────────────────────────────────────────────────


@dataclass
class ClassMetrics:
    """Per-class quality snapshot."""

    class_uri: str
    depth: int
    n_individuals: int  # direct rdf:type members (not transitive)
    has_label: bool
    has_comment: bool
    property_fill: dict[str, float] = field(default_factory=dict)  # prop_uri → 0.0–1.0


@dataclass
class LevelSummary:
    """Aggregate quality metrics for one depth level of the class hierarchy."""

    depth: int
    n_classes: int
    label_pct: int  # % classes with ≥1 rdfs:label
    comment_pct: int  # % classes with ≥1 rdfs:comment
    n_individuals: int  # total direct members across all classes at this depth
    individual_label_pct: int  # % of those individuals with ≥1 rdfs:label


@dataclass
class OntologyStats:
    """Global counts and coverage percentages for the whole ontology."""

    # Classes
    total_classes: int
    root_classes: int
    max_depth: int
    label_pct: int  # % classes with ≥1 rdfs:label
    comment_pct: int  # % classes with ≥1 rdfs:comment
    # Individuals
    total_individuals: int
    individual_label_pct: int  # % individuals with ≥1 rdfs:label
    individual_typed_pct: int  # % individuals with ≥1 known rdf:type
    # Properties
    total_properties: int
    property_label_pct: int  # % properties with rdfs:label
    property_with_domain_pct: int
    property_with_range_pct: int


@dataclass
class OntologyAnalysis:
    """Full analysis result for one ontology."""

    stats: OntologyStats
    class_metrics: list[ClassMetrics]
    level_summaries: list[LevelSummary]  # sorted by depth
    issues: list[Issue]  # sorted by severity then message
    property_fill_global: dict[str, float]  # prop_uri → fill rate (only props with domain)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _effective_types(taxonomy: Taxonomy, type_uris: list[str]) -> set[str]:
    """Return the transitive superclasses of the given types within known classes."""
    effective: set[str] = set()
    queue = list(type_uris)
    while queue:
        uri = queue.pop()
        if uri in effective:
            continue
        effective.add(uri)
        cls = taxonomy.owl_classes.get(uri)
        if cls:
            queue.extend(cls.sub_class_of)
    return effective


def _build_class_hierarchy(
    taxonomy: Taxonomy,
) -> tuple[dict[str, list[str]], list[str], dict[str, int]]:
    """Return (children_of, roots, depths) for the class hierarchy."""
    classes = taxonomy.owl_classes
    children_of: dict[str, list[str]] = {uri: [] for uri in classes}
    roots: list[str] = []
    for uri, cls in classes.items():
        parents_in_graph = [p for p in cls.sub_class_of if p in classes]
        if parents_in_graph:
            for p in parents_in_graph:
                children_of[p].append(uri)
        else:
            roots.append(uri)
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
    return children_of, roots, depths


def _compute_property_fill(taxonomy: Taxonomy) -> dict[str, float]:
    """Fill rate for each property that has rdfs:domain and at least one domain individual.

    fill = |domain_individuals with ≥1 valid P assertion| / |domain_individuals|
    A "valid" assertion is one whose target individual's types intersect rdfs:range
    (or any target if the property has no range restriction).
    Properties with no domain, or whose domain has no individuals, are omitted.
    """
    result: dict[str, float] = {}
    for p_uri, prop in taxonomy.owl_properties.items():
        if not prop.domains:
            continue
        domain_set = set(prop.domains)
        domain_inds = [
            ind_uri
            for ind_uri, ind in taxonomy.owl_individuals.items()
            if _effective_types(taxonomy, ind.types) & domain_set
        ]
        if not domain_inds:
            continue
        range_set: set[str] | None = set(prop.ranges) if prop.ranges else None
        filled = 0
        for ind_uri in domain_inds:
            ind = taxonomy.owl_individuals[ind_uri]
            for pv_prop_uri, val_uri in ind.property_values:
                if pv_prop_uri != p_uri:
                    continue
                if range_set is None:
                    filled += 1
                    break
                val_ind = taxonomy.owl_individuals.get(val_uri)
                if val_ind and _effective_types(taxonomy, val_ind.types) & range_set:
                    filled += 1
                    break
        result[p_uri] = filled / len(domain_inds)
    return result


def _compute_class_metrics(
    taxonomy: Taxonomy,
    depths: dict[str, int],
    property_fill: dict[str, float],
) -> list[ClassMetrics]:
    direct_count: dict[str, int] = {}
    for ind in taxonomy.owl_individuals.values():
        for t in ind.types:
            if t in taxonomy.owl_classes:
                direct_count[t] = direct_count.get(t, 0) + 1

    prop_fill_by_class: dict[str, dict[str, float]] = {}
    for p_uri, fill in property_fill.items():
        prop = taxonomy.owl_properties.get(p_uri)
        if not prop:
            continue
        for domain_uri in prop.domains:
            if domain_uri in taxonomy.owl_classes:
                prop_fill_by_class.setdefault(domain_uri, {})[p_uri] = fill

    return [
        ClassMetrics(
            class_uri=cls_uri,
            depth=depths.get(cls_uri, 0),
            n_individuals=direct_count.get(cls_uri, 0),
            has_label=bool(cls.labels),
            has_comment=bool(cls.comments),
            property_fill=prop_fill_by_class.get(cls_uri, {}),
        )
        for cls_uri, cls in taxonomy.owl_classes.items()
    ]


def _compute_level_summaries(
    taxonomy: Taxonomy,
    class_metrics: list[ClassMetrics],
) -> list[LevelSummary]:
    by_depth: dict[int, list[ClassMetrics]] = {}
    for cm in class_metrics:
        by_depth.setdefault(cm.depth, []).append(cm)

    summaries: list[LevelSummary] = []
    for depth in sorted(by_depth):
        cms = by_depth[depth]
        n_classes = len(cms)
        labeled = sum(1 for cm in cms if cm.has_label)
        commented = sum(1 for cm in cms if cm.has_comment)

        depth_class_uris = {cm.class_uri for cm in cms}
        depth_inds = [
            ind
            for ind in taxonomy.owl_individuals.values()
            if any(t in depth_class_uris for t in ind.types)
        ]
        n_inds = len(depth_inds)
        ind_labeled = sum(1 for ind in depth_inds if ind.labels)

        summaries.append(
            LevelSummary(
                depth=depth,
                n_classes=n_classes,
                label_pct=pct(labeled, n_classes),
                comment_pct=pct(commented, n_classes),
                n_individuals=n_inds,
                individual_label_pct=pct(ind_labeled, n_inds),
            )
        )
    return summaries


def _compute_ontology_stats(
    taxonomy: Taxonomy,
    class_metrics: list[ClassMetrics],
    roots: list[str],
    depths: dict[str, int],
) -> OntologyStats:
    total_classes = len(class_metrics)
    labeled_cls = sum(1 for cm in class_metrics if cm.has_label)
    commented_cls = sum(1 for cm in class_metrics if cm.has_comment)
    max_depth = max(depths.values(), default=0)

    individuals = list(taxonomy.owl_individuals.values())
    total_inds = len(individuals)
    ind_labeled = sum(1 for ind in individuals if ind.labels)
    ind_typed = sum(1 for ind in individuals if any(t in taxonomy.owl_classes for t in ind.types))

    properties = list(taxonomy.owl_properties.values())
    total_props = len(properties)
    prop_labeled = sum(1 for p in properties if p.labels)
    prop_with_domain = sum(1 for p in properties if p.domains)
    prop_with_range = sum(1 for p in properties if p.ranges)

    return OntologyStats(
        total_classes=total_classes,
        root_classes=len(roots),
        max_depth=max_depth,
        label_pct=pct(labeled_cls, total_classes),
        comment_pct=pct(commented_cls, total_classes),
        total_individuals=total_inds,
        individual_label_pct=pct(ind_labeled, total_inds),
        individual_typed_pct=pct(ind_typed, total_inds),
        total_properties=total_props,
        property_label_pct=pct(prop_labeled, total_props),
        property_with_domain_pct=pct(prop_with_domain, total_props),
        property_with_range_pct=pct(prop_with_range, total_props),
    )


# ── Issue detectors ───────────────────────────────────────────────────────────

OntologyIssueDetector = Callable[[Taxonomy], list[Issue]]


def _detect_class_missing_label(taxonomy: Taxonomy) -> list[Issue]:
    return [
        Issue("class_missing_label", SEVERITY_ERROR, uri, f"No rdfs:label  [{cls.local_name}]")
        for uri, cls in taxonomy.owl_classes.items()
        if not cls.labels
    ]


def _detect_class_missing_comment(taxonomy: Taxonomy) -> list[Issue]:
    return [
        Issue("class_missing_comment", SEVERITY_INFO, uri, f"No rdfs:comment  [{cls.local_name}]")
        for uri, cls in taxonomy.owl_classes.items()
        if not cls.comments
    ]


def _detect_individual_missing_label(taxonomy: Taxonomy) -> list[Issue]:
    return [
        Issue(
            "individual_missing_label",
            SEVERITY_WARNING,
            uri,
            f"No rdfs:label  [{ind.local_name}]",
        )
        for uri, ind in taxonomy.owl_individuals.items()
        if not ind.labels
    ]


def _detect_individual_no_type(taxonomy: Taxonomy) -> list[Issue]:
    return [
        Issue(
            "individual_no_type",
            SEVERITY_WARNING,
            uri,
            f"No known rdf:type  [{ind.local_name}]",
        )
        for uri, ind in taxonomy.owl_individuals.items()
        if not any(t in taxonomy.owl_classes for t in ind.types)
    ]


def _detect_property_missing_label(taxonomy: Taxonomy) -> list[Issue]:
    return [
        Issue(
            "property_missing_label",
            SEVERITY_WARNING,
            uri,
            f"No rdfs:label  [{prop.local_name}]",
        )
        for uri, prop in taxonomy.owl_properties.items()
        if not prop.labels
    ]


def _detect_property_missing_domain(taxonomy: Taxonomy) -> list[Issue]:
    return [
        Issue(
            "property_missing_domain",
            SEVERITY_WARNING,
            uri,
            f"No rdfs:domain  [{prop.local_name}]",
        )
        for uri, prop in taxonomy.owl_properties.items()
        if not prop.domains
    ]


def _detect_property_missing_range(taxonomy: Taxonomy) -> list[Issue]:
    return [
        Issue(
            "property_missing_range",
            SEVERITY_WARNING,
            uri,
            f"No rdfs:range  [{prop.local_name}]",
        )
        for uri, prop in taxonomy.owl_properties.items()
        if not prop.ranges
    ]


ONTOLOGY_ISSUE_DETECTORS: list[OntologyIssueDetector] = [
    _detect_class_missing_label,
    _detect_class_missing_comment,
    _detect_individual_missing_label,
    _detect_individual_no_type,
    _detect_property_missing_label,
    _detect_property_missing_domain,
    _detect_property_missing_range,
]

# ── Entry points ──────────────────────────────────────────────────────────────


def compute_ontology_analysis(taxonomy: Taxonomy) -> OntologyAnalysis:
    """Compute full ontology analysis. Pure, safe (detectors are wrapped)."""
    if not taxonomy.owl_classes and not taxonomy.owl_individuals and not taxonomy.owl_properties:
        empty_stats = OntologyStats(
            total_classes=0,
            root_classes=0,
            max_depth=0,
            label_pct=0,
            comment_pct=0,
            total_individuals=0,
            individual_label_pct=0,
            individual_typed_pct=0,
            total_properties=0,
            property_label_pct=0,
            property_with_domain_pct=0,
            property_with_range_pct=0,
        )
        return OntologyAnalysis(
            stats=empty_stats,
            class_metrics=[],
            level_summaries=[],
            issues=[],
            property_fill_global={},
        )

    _children_of, roots, depths = _build_class_hierarchy(taxonomy)
    property_fill = _compute_property_fill(taxonomy)
    class_metrics = _compute_class_metrics(taxonomy, depths, property_fill)
    level_summaries = _compute_level_summaries(taxonomy, class_metrics)
    stats = _compute_ontology_stats(taxonomy, class_metrics, roots, depths)

    issues: list[Issue] = []
    for detector in ONTOLOGY_ISSUE_DETECTORS:
        try:
            issues.extend(detector(taxonomy))
        except Exception:
            pass

    # Fill-rate issues use pre-computed rates to avoid double computation
    for p_uri, fill in property_fill.items():
        if fill < PROPERTY_FILL_THRESHOLD:
            prop = taxonomy.owl_properties.get(p_uri)
            lbl = prop.local_name if prop else p_uri
            pct_val = int(fill * 100)
            issues.append(
                Issue(
                    "property_low_fill",
                    SEVERITY_WARNING,
                    p_uri,
                    f"Fill: {pct_val}%  [{lbl}]",
                    extra={"fill_rate": fill},
                )
            )

    issues.sort(key=lambda i: (_SEVERITY_RANK.get(i.severity, 99), i.message))

    return OntologyAnalysis(
        stats=stats,
        class_metrics=class_metrics,
        level_summaries=level_summaries,
        issues=issues,
        property_fill_global=property_fill,
    )


def compute_owl_analysis(taxonomy: Taxonomy) -> OWLClassStats:
    """Backward-compat flat stats. Use compute_ontology_analysis() for full analysis."""
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
    _children_of, roots, depths = _build_class_hierarchy(taxonomy)
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
