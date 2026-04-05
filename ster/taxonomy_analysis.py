"""Pure taxonomy analysis — no I/O, no curses dependency.

Architecture
------------
Adding a new quality check is a one-step operation: implement a function
matching the ``IssueDetector`` signature and append it to ``ISSUE_DETECTORS``.
No other code needs to change.

Data flow
---------
    analyze_taxonomy(taxonomy)
        └─ analyze_scheme(taxonomy, scheme_uri)
               ├─ get_scheme_concepts()   → concept_uris in scope
               ├─ _compute_stats()        → SchemeStats
               ├─ _compute_completions()  → list[PropertyCompletion]
               └─ ISSUE_DETECTORS[*]()   → list[TaxonomyIssue]
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from .model import LabelType, Taxonomy

# ── Severity constants ────────────────────────────────────────────────────────

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

_SEVERITY_RANK = {SEVERITY_ERROR: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2}

# Human-readable names for each issue key (used by the UI layer)
ISSUE_DISPLAY_NAMES: dict[str, str] = {
    "missing_pref_label": "No prefLabel",
    "missing_pref_label_lang": "prefLabel missing",
    "missing_definition": "No definition",
    "missing_scope_note": "No scopeNote",
    "broken_broader": "Broken broader",
    "broken_narrower": "Broken narrower",
    "broken_top_concept": "Broken top concept",
    "circular_hierarchy": "Circular hierarchy",
    "alt_same_as_pref": "altLabel=prefLabel",
    "duplicate_pref_label": "Duplicate label",
    "missing_in_scheme": "Not in any scheme",
    "broken_exact_match": "Broken exactMatch",
    "broken_broad_match": "Broken broadMatch",
    "broken_narrow_match": "Broken narrowMatch",
    "broken_related_match": "Broken relatedMatch",
    "broken_close_match": "Broken closeMatch",
}


# ── Result dataclasses ────────────────────────────────────────────────────────


@dataclass
class SchemeStats:
    """Structural statistics for one ConceptScheme."""

    total_concepts: int
    top_level_concepts: int
    max_depth: int
    avg_depth: float
    languages: list[str]  # sorted language codes present in prefLabels


@dataclass
class PropertyCompletion:
    """Per-language completion rate for one SKOS property."""

    property_key: str  # "pref_label" | "alt_label" | "definition" | "scope_note"
    display_name: str  # e.g. "prefLabel"
    total: int  # total concepts in scope
    by_language: dict[str, int]  # lang → number of concepts that have this property


@dataclass
class TaxonomyIssue:
    """A single quality issue detected in a taxonomy."""

    issue_key: str  # machine-readable type, maps to ISSUE_DISPLAY_NAMES
    severity: str  # SEVERITY_ERROR | SEVERITY_WARNING | SEVERITY_INFO
    concept_uri: str | None  # None for scheme-level issues
    message: str  # human-readable description (shown in the detail panel)
    extra: dict = field(default_factory=dict)  # e.g. {"attr": "exact_match", "target_uri": "..."}


@dataclass
class SchemeAnalysis:
    """Complete analysis of one ConceptScheme."""

    scheme_uri: str
    stats: SchemeStats
    completions: list[PropertyCompletion]
    issues: list[TaxonomyIssue]


# A detector is a pure function: (taxonomy, scheme_uri, concept_uris) → issues
IssueDetector = Callable[[Taxonomy, str, list[str]], list[TaxonomyIssue]]


# ── Concept scoping ───────────────────────────────────────────────────────────


def get_scheme_concepts(taxonomy: Taxonomy, scheme_uri: str) -> list[str]:
    """Return all concept URIs reachable from the scheme's top concepts (BFS)."""
    scheme = taxonomy.schemes.get(scheme_uri)
    if not scheme:
        return []
    visited: set[str] = set()
    queue: deque[str] = deque(u for u in scheme.top_concepts if u in taxonomy.concepts)
    while queue:
        uri = queue.popleft()
        if uri in visited:
            continue
        visited.add(uri)
        concept = taxonomy.concepts.get(uri)
        if concept:
            for child in concept.narrower:
                if child in taxonomy.concepts and child not in visited:
                    queue.append(child)
    return list(visited)


def _compute_depths(taxonomy: Taxonomy, scheme_uri: str) -> dict[str, int]:
    """Map concept_uri → depth (top concepts are depth 0)."""
    scheme = taxonomy.schemes.get(scheme_uri)
    if not scheme:
        return {}
    depths: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque(
        (u, 0) for u in scheme.top_concepts if u in taxonomy.concepts
    )
    visited: set[str] = set()
    while queue:
        uri, d = queue.popleft()
        if uri in visited:
            continue
        visited.add(uri)
        depths[uri] = d
        concept = taxonomy.concepts.get(uri)
        if concept:
            for child in concept.narrower:
                if child in taxonomy.concepts and child not in visited:
                    queue.append((child, d + 1))
    return depths


# ── Stats & completion ────────────────────────────────────────────────────────


def _compute_stats(taxonomy: Taxonomy, scheme_uri: str, concept_uris: list[str]) -> SchemeStats:
    scheme = taxonomy.schemes.get(scheme_uri)
    top_level = len([u for u in (scheme.top_concepts if scheme else []) if u in taxonomy.concepts])

    depths = _compute_depths(taxonomy, scheme_uri)
    depth_vals = [depths[u] for u in concept_uris if u in depths]
    max_depth = max(depth_vals) if depth_vals else 0
    avg_depth = round(sum(depth_vals) / len(depth_vals), 1) if depth_vals else 0.0

    langs: set[str] = set()
    for uri in concept_uris:
        c = taxonomy.concepts.get(uri)
        if c:
            for lbl in c.labels:
                if lbl.type == LabelType.PREF:
                    langs.add(lbl.lang)

    return SchemeStats(
        total_concepts=len(concept_uris),
        top_level_concepts=top_level,
        max_depth=max_depth,
        avg_depth=avg_depth,
        languages=sorted(langs),
    )


def _compute_completions(taxonomy: Taxonomy, concept_uris: list[str]) -> list[PropertyCompletion]:
    """Compute per-language completion for core SKOS properties."""
    total = len(concept_uris)
    pref_by_lang: dict[str, int] = {}
    alt_by_lang: dict[str, int] = {}
    def_by_lang: dict[str, int] = {}
    scope_by_lang: dict[str, int] = {}

    for uri in concept_uris:
        c = taxonomy.concepts.get(uri)
        if not c:
            continue
        pref_langs: set[str] = set()
        alt_langs: set[str] = set()
        for lbl in c.labels:
            if lbl.type == LabelType.PREF:
                pref_langs.add(lbl.lang)
            elif lbl.type == LabelType.ALT:
                alt_langs.add(lbl.lang)
        for lg in pref_langs:
            pref_by_lang[lg] = pref_by_lang.get(lg, 0) + 1
        for lg in alt_langs:
            alt_by_lang[lg] = alt_by_lang.get(lg, 0) + 1
        for d in c.definitions:
            def_by_lang[d.lang] = def_by_lang.get(d.lang, 0) + 1
        for s in c.scope_notes:
            scope_by_lang[s.lang] = scope_by_lang.get(s.lang, 0) + 1

    result: list[PropertyCompletion] = []
    if pref_by_lang:
        result.append(PropertyCompletion("pref_label", "prefLabel", total, pref_by_lang))
    if alt_by_lang:
        result.append(PropertyCompletion("alt_label", "altLabel", total, alt_by_lang))
    if def_by_lang:
        result.append(PropertyCompletion("definition", "definition", total, def_by_lang))
    if scope_by_lang:
        result.append(PropertyCompletion("scope_note", "scopeNote", total, scope_by_lang))
    return result


def compute_completions(taxonomy: Taxonomy, concept_uris: list[str]) -> list[PropertyCompletion]:
    """Public alias for _compute_completions."""
    return _compute_completions(taxonomy, concept_uris)


# ── Issue detectors ───────────────────────────────────────────────────────────


def _detect_missing_pref_label(
    taxonomy: Taxonomy, scheme_uri: str, concept_uris: list[str]
) -> list[TaxonomyIssue]:
    issues = []
    for uri in concept_uris:
        c = taxonomy.concepts.get(uri)
        if c and not any(lbl.type == LabelType.PREF for lbl in c.labels):
            h = taxonomy.uri_to_handle(uri) or c.local_name
            issues.append(
                TaxonomyIssue("missing_pref_label", SEVERITY_ERROR, uri, f"No prefLabel  [{h}]")
            )
    return issues


def _detect_missing_pref_label_lang(
    taxonomy: Taxonomy, scheme_uri: str, concept_uris: list[str]
) -> list[TaxonomyIssue]:
    scheme = taxonomy.schemes.get(scheme_uri)
    if not scheme or not scheme.languages:
        return []
    issues = []
    for uri in concept_uris:
        c = taxonomy.concepts.get(uri)
        if not c:
            continue
        pref_langs = {lbl.lang for lbl in c.labels if lbl.type == LabelType.PREF}
        for declared in scheme.languages:
            if declared not in pref_langs:
                h = taxonomy.uri_to_handle(uri) or c.local_name
                issues.append(
                    TaxonomyIssue(
                        "missing_pref_label_lang",
                        SEVERITY_WARNING,
                        uri,
                        f"No prefLabel [{declared}]  [{h}]",
                    )
                )
    return issues


def _detect_missing_definition(
    taxonomy: Taxonomy, scheme_uri: str, concept_uris: list[str]
) -> list[TaxonomyIssue]:
    issues = []
    for uri in concept_uris:
        c = taxonomy.concepts.get(uri)
        if c and not c.definitions:
            h = taxonomy.uri_to_handle(uri) or c.local_name
            issues.append(
                TaxonomyIssue("missing_definition", SEVERITY_INFO, uri, f"No definition  [{h}]")
            )
    return issues


def _detect_missing_scope_note(
    taxonomy: Taxonomy, scheme_uri: str, concept_uris: list[str]
) -> list[TaxonomyIssue]:
    # Only flag if at least one concept already has scope notes (consistent choice otherwise)
    any_scope = any(
        bool(taxonomy.concepts[u].scope_notes) for u in concept_uris if u in taxonomy.concepts
    )
    if not any_scope:
        return []
    issues = []
    for uri in concept_uris:
        c = taxonomy.concepts.get(uri)
        if c and not c.scope_notes:
            h = taxonomy.uri_to_handle(uri) or c.local_name
            issues.append(
                TaxonomyIssue("missing_scope_note", SEVERITY_INFO, uri, f"No scopeNote  [{h}]")
            )
    return issues


def _detect_broken_broader(
    taxonomy: Taxonomy, scheme_uri: str, concept_uris: list[str]
) -> list[TaxonomyIssue]:
    issues = []
    for uri in concept_uris:
        c = taxonomy.concepts.get(uri)
        if not c:
            continue
        if any(b not in taxonomy.concepts for b in c.broader):
            h = taxonomy.uri_to_handle(uri) or c.local_name
            issues.append(
                TaxonomyIssue("broken_broader", SEVERITY_ERROR, uri, f"Broader not found  [{h}]")
            )
    return issues


def _detect_broken_narrower(
    taxonomy: Taxonomy, scheme_uri: str, concept_uris: list[str]
) -> list[TaxonomyIssue]:
    issues = []
    for uri in concept_uris:
        c = taxonomy.concepts.get(uri)
        if not c:
            continue
        if any(n not in taxonomy.concepts for n in c.narrower):
            h = taxonomy.uri_to_handle(uri) or c.local_name
            issues.append(
                TaxonomyIssue("broken_narrower", SEVERITY_WARNING, uri, f"Broken narrower  [{h}]")
            )
    return issues


def _detect_broken_top_concepts(
    taxonomy: Taxonomy, scheme_uri: str, concept_uris: list[str]
) -> list[TaxonomyIssue]:
    scheme = taxonomy.schemes.get(scheme_uri)
    if not scheme:
        return []
    return [
        TaxonomyIssue(
            "broken_top_concept",
            SEVERITY_ERROR,
            None,
            f"hasTopConcept → not found: {uri}",
        )
        for uri in scheme.top_concepts
        if uri not in taxonomy.concepts
    ]


def _detect_circular_hierarchy(
    taxonomy: Taxonomy, scheme_uri: str, concept_uris: list[str]
) -> list[TaxonomyIssue]:
    """DFS with white/gray/black colouring to detect hierarchy cycles."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(concept_uris, WHITE)
    issues: list[TaxonomyIssue] = []
    reported: set[str] = set()

    def dfs(uri: str) -> None:
        color[uri] = GRAY
        c = taxonomy.concepts.get(uri)
        if c:
            for child in c.narrower:
                if child not in color:
                    continue
                if color[child] == GRAY and child not in reported:
                    reported.add(child)
                    h = taxonomy.uri_to_handle(child) or child
                    issues.append(
                        TaxonomyIssue(
                            "circular_hierarchy",
                            SEVERITY_ERROR,
                            child,
                            f"Circular hierarchy  [{h}]",
                        )
                    )
                elif color[child] == WHITE:
                    dfs(child)
        color[uri] = BLACK

    for uri in concept_uris:
        if color[uri] == WHITE:
            dfs(uri)
    return issues


def _detect_alt_same_as_pref(
    taxonomy: Taxonomy, scheme_uri: str, concept_uris: list[str]
) -> list[TaxonomyIssue]:
    """SKOS integrity: skos:altLabel must not equal skos:prefLabel for the same language."""
    issues = []
    for uri in concept_uris:
        c = taxonomy.concepts.get(uri)
        if not c:
            continue
        pref = {lbl.lang: lbl.value for lbl in c.labels if lbl.type == LabelType.PREF}
        for lbl in c.labels:
            if lbl.type == LabelType.ALT and pref.get(lbl.lang) == lbl.value:
                h = taxonomy.uri_to_handle(uri) or c.local_name
                issues.append(
                    TaxonomyIssue(
                        "alt_same_as_pref",
                        SEVERITY_ERROR,
                        uri,
                        f"altLabel=prefLabel [{lbl.lang}]  [{h}]",
                    )
                )
                break
    return issues


def _detect_duplicate_pref_label(
    taxonomy: Taxonomy, scheme_uri: str, concept_uris: list[str]
) -> list[TaxonomyIssue]:
    """Warn when two concepts share the same prefLabel in the same language."""
    seen: dict[tuple[str, str], list[str]] = {}
    for uri in concept_uris:
        c = taxonomy.concepts.get(uri)
        if not c:
            continue
        for lbl in c.labels:
            if lbl.type == LabelType.PREF:
                key = (lbl.lang, lbl.value.lower())
                seen.setdefault(key, []).append(uri)

    issues: list[TaxonomyIssue] = []
    reported: set[str] = set()
    for (lang, _val), uris in seen.items():
        if len(uris) > 1:
            for uri in uris:
                if uri not in reported:
                    reported.add(uri)
                    h = taxonomy.uri_to_handle(uri) or uri
                    issues.append(
                        TaxonomyIssue(
                            "duplicate_pref_label",
                            SEVERITY_WARNING,
                            uri,
                            f"Duplicate prefLabel [{lang}]  [{h}]",
                        )
                    )
    return issues


def _detect_missing_in_scheme(
    taxonomy: Taxonomy, scheme_uri: str, concept_uris: list[str]
) -> list[TaxonomyIssue]:
    """Flag concepts that are not reachable from any scheme (truly orphaned).

    Runs only for the first scheme to avoid duplicate reporting across schemes.
    """
    all_scheme_uris = list(taxonomy.schemes.keys())
    if not all_scheme_uris or all_scheme_uris[0] != scheme_uri:
        return []
    reachable: set[str] = set()
    for s_uri in taxonomy.schemes:
        reachable.update(get_scheme_concepts(taxonomy, s_uri))
    issues = []
    for uri, concept in taxonomy.concepts.items():
        if uri not in reachable:
            h = taxonomy.uri_to_handle(uri) or concept.local_name
            issues.append(
                TaxonomyIssue("missing_in_scheme", SEVERITY_ERROR, uri, f"Not in any scheme  [{h}]")
            )
    return issues


_MAPPING_ATTRS: list[tuple[str, str, str]] = [
    ("exact_match", "exactMatch", "broken_exact_match"),
    ("broad_match", "broadMatch", "broken_broad_match"),
    ("narrow_match", "narrowMatch", "broken_narrow_match"),
    ("related_match", "relatedMatch", "broken_related_match"),
    ("close_match", "closeMatch", "broken_close_match"),
]


def _detect_broken_mappings(
    taxonomy: Taxonomy, scheme_uri: str, concept_uris: list[str]
) -> list[TaxonomyIssue]:
    """Warn when a mapping property points to a URI not present in the merged taxonomy."""
    issues = []
    for uri in concept_uris:
        c = taxonomy.concepts.get(uri)
        if not c:
            continue
        h = taxonomy.uri_to_handle(uri) or c.local_name
        for attr, display, issue_key in _MAPPING_ATTRS:
            for target_uri in getattr(c, attr, []):
                if target_uri not in taxonomy.concepts:
                    issues.append(
                        TaxonomyIssue(
                            issue_key=issue_key,
                            severity=SEVERITY_WARNING,
                            concept_uri=uri,
                            message=f"Broken {display}  [{h}]",
                            extra={"attr": attr, "target_uri": target_uri},
                        )
                    )
    return issues


# ── Registry — add new detectors here only ────────────────────────────────────

ISSUE_DETECTORS: list[IssueDetector] = [
    _detect_broken_top_concepts,  # ERROR — missing/broken hasTopConcept
    _detect_missing_in_scheme,  # ERROR — concept not reachable from any scheme
    _detect_broken_broader,  # ERROR — broken skos:broader link
    _detect_circular_hierarchy,  # ERROR — skos:narrower cycle
    _detect_missing_pref_label,  # ERROR — mandatory SKOS property
    _detect_broken_narrower,  # WARNING — broken skos:narrower link
    _detect_broken_mappings,  # WARNING — broken cross-scheme mapping links
    _detect_duplicate_pref_label,  # WARNING — duplicate prefLabel same language
]


# ── Entry points ──────────────────────────────────────────────────────────────


def analyze_scheme(taxonomy: Taxonomy, scheme_uri: str) -> SchemeAnalysis:
    """Compute full analysis for one scheme. Pure, safe (detectors are wrapped)."""
    concept_uris = get_scheme_concepts(taxonomy, scheme_uri)
    stats = _compute_stats(taxonomy, scheme_uri, concept_uris)
    completions = _compute_completions(taxonomy, concept_uris)
    issues: list[TaxonomyIssue] = []
    for detector in ISSUE_DETECTORS:
        try:
            issues.extend(detector(taxonomy, scheme_uri, concept_uris))
        except Exception:
            pass  # never let a broken detector crash the UI
    issues.sort(key=lambda i: (_SEVERITY_RANK.get(i.severity, 99), i.message))
    return SchemeAnalysis(
        scheme_uri=scheme_uri,
        stats=stats,
        completions=completions,
        issues=issues,
    )


def analyze_taxonomy(taxonomy: Taxonomy) -> dict[str, SchemeAnalysis]:
    """Compute analysis for all schemes."""
    return {uri: analyze_scheme(taxonomy, uri) for uri in taxonomy.schemes}


# ── Serialization (used by analysis_cache) ────────────────────────────────────


def scheme_analysis_to_dict(a: SchemeAnalysis) -> dict:
    return {
        "scheme_uri": a.scheme_uri,
        "stats": {
            "total_concepts": a.stats.total_concepts,
            "top_level_concepts": a.stats.top_level_concepts,
            "max_depth": a.stats.max_depth,
            "avg_depth": a.stats.avg_depth,
            "languages": a.stats.languages,
        },
        "completions": [
            {
                "property_key": c.property_key,
                "display_name": c.display_name,
                "total": c.total,
                "by_language": c.by_language,
            }
            for c in a.completions
        ],
        "issues": [
            {
                "issue_key": i.issue_key,
                "severity": i.severity,
                "concept_uri": i.concept_uri,
                "message": i.message,
                "extra": i.extra,
            }
            for i in a.issues
        ],
    }


def scheme_analysis_from_dict(d: dict) -> SchemeAnalysis:
    s = d["stats"]
    return SchemeAnalysis(
        scheme_uri=d["scheme_uri"],
        stats=SchemeStats(
            total_concepts=s["total_concepts"],
            top_level_concepts=s["top_level_concepts"],
            max_depth=s["max_depth"],
            avg_depth=s["avg_depth"],
            languages=s["languages"],
        ),
        completions=[
            PropertyCompletion(
                property_key=c["property_key"],
                display_name=c["display_name"],
                total=c["total"],
                by_language=c["by_language"],
            )
            for c in d.get("completions", [])
        ],
        issues=[
            TaxonomyIssue(
                issue_key=i["issue_key"],
                severity=i["severity"],
                concept_uri=i.get("concept_uri"),
                message=i["message"],
                extra=i.get("extra", {}),
            )
            for i in d.get("issues", [])
        ],
    )
