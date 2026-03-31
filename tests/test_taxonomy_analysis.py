"""Tests for ster/taxonomy_analysis.py — pure analysis functions."""

from __future__ import annotations

import pytest

from ster.model import Concept, ConceptScheme, Definition, Label, LabelType, Taxonomy
from ster.taxonomy_analysis import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    PropertyCompletion,
    SchemeAnalysis,
    SchemeStats,
    TaxonomyIssue,
    _compute_completions,
    _compute_stats,
    _detect_alt_same_as_pref,
    _detect_broken_broader,
    _detect_broken_narrower,
    _detect_broken_top_concepts,
    _detect_circular_hierarchy,
    _detect_duplicate_pref_label,
    _detect_missing_definition,
    _detect_missing_pref_label,
    _detect_missing_pref_label_lang,
    analyze_scheme,
    analyze_taxonomy,
    get_scheme_concepts,
    scheme_analysis_from_dict,
    scheme_analysis_to_dict,
)

BASE = "https://example.org/test/"


# ── helpers ───────────────────────────────────────────────────────────────────


def _tax_with_concepts(*labels_per_concept: list[tuple[str, str]]) -> tuple[Taxonomy, str]:
    """Build a linear chain: scheme → C0 → C1 → … with given pref labels (lang, value)."""
    t = Taxonomy()
    scheme_uri = BASE + "Scheme"
    concepts = []
    for i, lbls in enumerate(labels_per_concept):
        uri = BASE + f"C{i}"
        c = Concept(uri=uri, labels=[Label(lg, val, LabelType.PREF) for lg, val in lbls])
        t.concepts[uri] = c
        concepts.append(uri)

    scheme = ConceptScheme(uri=scheme_uri, top_concepts=[concepts[0]] if concepts else [])
    # build narrower chain
    for i in range(len(concepts) - 1):
        t.concepts[concepts[i]].narrower.append(concepts[i + 1])
        t.concepts[concepts[i + 1]].broader.append(concepts[i])
    t.schemes[scheme_uri] = scheme
    return t, scheme_uri


# ── get_scheme_concepts ───────────────────────────────────────────────────────


def test_get_scheme_concepts_chain():
    t, s = _tax_with_concepts([("en", "A")], [("en", "B")], [("en", "C")])
    uris = get_scheme_concepts(t, s)
    assert len(uris) == 3


def test_get_scheme_concepts_empty_scheme():
    t = Taxonomy()
    t.schemes["https://x.org/S"] = ConceptScheme(uri="https://x.org/S")
    assert get_scheme_concepts(t, "https://x.org/S") == []


def test_get_scheme_concepts_missing_concept_skipped():
    t = Taxonomy()
    scheme = ConceptScheme(uri=BASE + "S", top_concepts=[BASE + "Ghost"])
    t.schemes[scheme.uri] = scheme
    # Ghost concept is NOT in t.concepts
    assert get_scheme_concepts(t, scheme.uri) == []


def test_get_scheme_concepts_handles_cycles():
    """BFS should not loop forever on a cyclic hierarchy."""
    t = Taxonomy()
    s_uri = BASE + "S"
    a_uri = BASE + "A"
    b_uri = BASE + "B"
    ca = Concept(uri=a_uri, labels=[], narrower=[b_uri], broader=[b_uri])
    cb = Concept(uri=b_uri, labels=[], narrower=[a_uri], broader=[a_uri])
    t.concepts[a_uri] = ca
    t.concepts[b_uri] = cb
    t.schemes[s_uri] = ConceptScheme(uri=s_uri, top_concepts=[a_uri])
    result = get_scheme_concepts(t, s_uri)
    assert set(result) == {a_uri, b_uri}


# ── _compute_stats ────────────────────────────────────────────────────────────


def test_compute_stats_basic():
    t, s = _tax_with_concepts([("en", "A")], [("en", "B")], [("en", "C")])
    uris = get_scheme_concepts(t, s)
    stats = _compute_stats(t, s, uris)
    assert stats.total_concepts == 3
    assert stats.top_level_concepts == 1
    assert stats.max_depth == 2
    assert stats.languages == ["en"]


def test_compute_stats_empty():
    t = Taxonomy()
    t.schemes["x"] = ConceptScheme(uri="x")
    stats = _compute_stats(t, "x", [])
    assert stats.total_concepts == 0
    assert stats.max_depth == 0
    assert stats.avg_depth == 0.0


def test_compute_stats_multilang():
    t, s = _tax_with_concepts([("en", "A"), ("fr", "B")])
    uris = get_scheme_concepts(t, s)
    stats = _compute_stats(t, s, uris)
    assert sorted(stats.languages) == ["en", "fr"]


# ── _compute_completions ──────────────────────────────────────────────────────


def test_compute_completions_pref_label():
    t, s = _tax_with_concepts([("en", "A"), ("fr", "AZ")], [("en", "B")])
    uris = get_scheme_concepts(t, s)
    comps = _compute_completions(t, uris)
    pref = next(c for c in comps if c.property_key == "pref_label")
    assert pref.total == 2
    assert pref.by_language["en"] == 2
    assert pref.by_language["fr"] == 1


def test_compute_completions_with_definitions():
    t, s = _tax_with_concepts([("en", "A")], [("en", "B")])
    t.concepts[BASE + "C0"].definitions.append(Definition("en", "Def of A"))
    uris = get_scheme_concepts(t, s)
    comps = _compute_completions(t, uris)
    defn = next((c for c in comps if c.property_key == "definition"), None)
    assert defn is not None
    assert defn.by_language["en"] == 1
    assert defn.total == 2


# ── Issue detectors ───────────────────────────────────────────────────────────


def test_detect_missing_pref_label():
    t = Taxonomy()
    s_uri = BASE + "S"
    a_uri = BASE + "A"
    c = Concept(uri=a_uri, labels=[])  # no labels at all
    t.concepts[a_uri] = c
    t.schemes[s_uri] = ConceptScheme(uri=s_uri, top_concepts=[a_uri])
    issues = _detect_missing_pref_label(t, s_uri, [a_uri])
    assert len(issues) == 1
    assert issues[0].severity == SEVERITY_ERROR
    assert issues[0].concept_uri == a_uri


def test_detect_missing_pref_label_lang():
    t = Taxonomy()
    s_uri = BASE + "S"
    a_uri = BASE + "A"
    c = Concept(uri=a_uri, labels=[Label("en", "Alpha", LabelType.PREF)])
    t.concepts[a_uri] = c
    # Scheme declares both en and fr
    t.schemes[s_uri] = ConceptScheme(uri=s_uri, top_concepts=[a_uri], languages=["en", "fr"])
    issues = _detect_missing_pref_label_lang(t, s_uri, [a_uri])
    assert len(issues) == 1
    assert issues[0].severity == SEVERITY_WARNING
    assert "fr" in issues[0].message


def test_detect_missing_pref_label_lang_no_declared_langs():
    t = Taxonomy()
    s_uri = BASE + "S"
    a_uri = BASE + "A"
    c = Concept(uri=a_uri, labels=[Label("en", "Alpha", LabelType.PREF)])
    t.concepts[a_uri] = c
    t.schemes[s_uri] = ConceptScheme(uri=s_uri, top_concepts=[a_uri], languages=[])
    issues = _detect_missing_pref_label_lang(t, s_uri, [a_uri])
    assert issues == []


def test_detect_missing_definition():
    t, s = _tax_with_concepts([("en", "A")])
    uris = get_scheme_concepts(t, s)
    issues = _detect_missing_definition(t, s, uris)
    assert len(issues) == 1
    assert issues[0].severity == SEVERITY_INFO


def test_detect_broken_broader():
    t = Taxonomy()
    s_uri = BASE + "S"
    a_uri = BASE + "A"
    ghost = BASE + "Ghost"
    c = Concept(uri=a_uri, labels=[Label("en", "A", LabelType.PREF)], broader=[ghost])
    t.concepts[a_uri] = c
    t.schemes[s_uri] = ConceptScheme(uri=s_uri, top_concepts=[a_uri])
    issues = _detect_broken_broader(t, s_uri, [a_uri])
    assert len(issues) == 1
    assert issues[0].severity == SEVERITY_ERROR


def test_detect_broken_narrower():
    t = Taxonomy()
    s_uri = BASE + "S"
    a_uri = BASE + "A"
    ghost = BASE + "Ghost"
    c = Concept(uri=a_uri, labels=[Label("en", "A", LabelType.PREF)], narrower=[ghost])
    t.concepts[a_uri] = c
    t.schemes[s_uri] = ConceptScheme(uri=s_uri, top_concepts=[a_uri])
    issues = _detect_broken_narrower(t, s_uri, [a_uri])
    assert len(issues) == 1
    assert issues[0].severity == SEVERITY_WARNING


def test_detect_broken_top_concepts():
    t = Taxonomy()
    s_uri = BASE + "S"
    ghost = BASE + "Ghost"
    t.schemes[s_uri] = ConceptScheme(uri=s_uri, top_concepts=[ghost])
    issues = _detect_broken_top_concepts(t, s_uri, [])
    assert len(issues) == 1
    assert issues[0].concept_uri is None  # scheme-level issue


def test_detect_circular_hierarchy():
    t = Taxonomy()
    s_uri = BASE + "S"
    a_uri = BASE + "A"
    b_uri = BASE + "B"
    ca = Concept(uri=a_uri, labels=[Label("en", "A", LabelType.PREF)], narrower=[b_uri])
    cb = Concept(uri=b_uri, labels=[Label("en", "B", LabelType.PREF)], narrower=[a_uri])
    t.concepts[a_uri] = ca
    t.concepts[b_uri] = cb
    t.schemes[s_uri] = ConceptScheme(uri=s_uri, top_concepts=[a_uri])
    issues = _detect_circular_hierarchy(t, s_uri, [a_uri, b_uri])
    assert len(issues) >= 1
    assert any(i.severity == SEVERITY_ERROR for i in issues)


def test_detect_alt_same_as_pref():
    t = Taxonomy()
    s_uri = BASE + "S"
    a_uri = BASE + "A"
    c = Concept(
        uri=a_uri,
        labels=[
            Label("en", "Alpha", LabelType.PREF),
            Label("en", "Alpha", LabelType.ALT),  # same value → SKOS violation
        ],
    )
    t.concepts[a_uri] = c
    t.schemes[s_uri] = ConceptScheme(uri=s_uri, top_concepts=[a_uri])
    issues = _detect_alt_same_as_pref(t, s_uri, [a_uri])
    assert len(issues) == 1
    assert issues[0].severity == SEVERITY_ERROR


def test_detect_no_alt_same_as_pref_ok():
    t = Taxonomy()
    s_uri = BASE + "S"
    a_uri = BASE + "A"
    c = Concept(
        uri=a_uri,
        labels=[
            Label("en", "Alpha", LabelType.PREF),
            Label("en", "β", LabelType.ALT),  # different value → OK
        ],
    )
    t.concepts[a_uri] = c
    t.schemes[s_uri] = ConceptScheme(uri=s_uri, top_concepts=[a_uri])
    assert _detect_alt_same_as_pref(t, s_uri, [a_uri]) == []


def test_detect_duplicate_pref_label():
    t = Taxonomy()
    s_uri = BASE + "S"
    a_uri = BASE + "A"
    b_uri = BASE + "B"
    ca = Concept(uri=a_uri, labels=[Label("en", "Same", LabelType.PREF)])
    cb = Concept(uri=b_uri, labels=[Label("en", "Same", LabelType.PREF)])
    t.concepts[a_uri] = ca
    t.concepts[b_uri] = cb
    t.schemes[s_uri] = ConceptScheme(uri=s_uri, top_concepts=[a_uri, b_uri])
    issues = _detect_duplicate_pref_label(t, s_uri, [a_uri, b_uri])
    assert len(issues) == 2  # one per offending concept
    assert all(i.severity == SEVERITY_WARNING for i in issues)


# ── analyze_scheme ────────────────────────────────────────────────────────────


def test_analyze_scheme_returns_analysis():
    t, s = _tax_with_concepts([("en", "A")], [("en", "B")])
    result = analyze_scheme(t, s)
    assert isinstance(result, SchemeAnalysis)
    assert result.scheme_uri == s
    assert isinstance(result.stats, SchemeStats)
    assert isinstance(result.completions, list)
    assert isinstance(result.issues, list)


def test_analyze_scheme_issues_sorted_by_severity():
    t, s = _tax_with_concepts([("en", "A")])
    # Force a missing definition (INFO) — B has no prefLabel (ERROR)
    b_uri = BASE + "B"
    t.concepts[b_uri] = Concept(uri=b_uri, labels=[])
    t.schemes[s].top_concepts.append(b_uri)
    result = analyze_scheme(t, s)
    # errors should come before info
    sevs = [i.severity for i in result.issues]
    error_idx = next((i for i, v in enumerate(sevs) if v == SEVERITY_ERROR), None)
    info_idx = next((i for i, v in enumerate(sevs) if v == SEVERITY_INFO), None)
    if error_idx is not None and info_idx is not None:
        assert error_idx < info_idx


def test_analyze_taxonomy_all_schemes():
    t = Taxonomy()
    for i in range(3):
        s = ConceptScheme(uri=BASE + f"S{i}")
        t.schemes[s.uri] = s
    result = analyze_taxonomy(t)
    assert len(result) == 3
    for uri in t.schemes:
        assert uri in result


# ── Serialisation ─────────────────────────────────────────────────────────────


def test_round_trip_serialisation():
    t, s = _tax_with_concepts([("en", "A")], [("en", "B")])
    t.concepts[BASE + "C0"].definitions.append(Definition("en", "Def"))
    analysis = analyze_scheme(t, s)
    d = scheme_analysis_to_dict(analysis)
    restored = scheme_analysis_from_dict(d)

    assert restored.scheme_uri == analysis.scheme_uri
    assert restored.stats.total_concepts == analysis.stats.total_concepts
    assert len(restored.completions) == len(analysis.completions)
    assert len(restored.issues) == len(analysis.issues)
    for orig, rest in zip(analysis.issues, restored.issues):
        assert rest.issue_key == orig.issue_key
        assert rest.severity == orig.severity
        assert rest.concept_uri == orig.concept_uri
