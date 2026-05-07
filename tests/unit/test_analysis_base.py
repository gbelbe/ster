"""Tests for ster/analysis_base.py — shared analysis primitives."""

from __future__ import annotations

from ster.analysis_base import SEVERITY_ERROR, SEVERITY_WARNING, Coverage, Issue, pct, pct_bar

# ── pct ───────────────────────────────────────────────────────────────────────


def test_pct_zero_total():
    assert pct(0, 0) == 0


def test_pct_partial():
    assert pct(1, 3) == 33


def test_pct_full():
    assert pct(3, 3) == 100


def test_pct_truncates_not_rounds():
    # int() truncates: 2/3 = 66.6… → 66
    assert pct(2, 3) == 66


# ── pct_bar ───────────────────────────────────────────────────────────────────


def test_pct_bar_empty():
    assert pct_bar(0) == "░░░░░░░░"


def test_pct_bar_full():
    assert pct_bar(100) == "████████"


def test_pct_bar_half():
    assert pct_bar(50) == "████░░░░"


def test_pct_bar_custom_width():
    bar = pct_bar(50, width=4)
    assert len(bar) == 4
    assert bar == "██░░"


# ── Issue ─────────────────────────────────────────────────────────────────────


def test_issue_entity_uri_field():
    i = Issue("missing_label", SEVERITY_ERROR, "http://x/A", "No label")
    assert i.entity_uri == "http://x/A"
    assert i.issue_key == "missing_label"
    assert i.severity == SEVERITY_ERROR


def test_issue_entity_uri_none():
    i = Issue("scheme_error", SEVERITY_WARNING, None, "Scheme-level issue")
    assert i.entity_uri is None


def test_issue_extra_defaults_empty():
    i = Issue("k", "error", None, "m")
    assert i.extra == {}


# ── Coverage ──────────────────────────────────────────────────────────────────


def test_coverage_fields():
    c = Coverage("rdf_label", "rdfs:label", 10, {"en": 8, "fr": 5})
    assert c.total == 10
    assert c.by_language["en"] == 8
    assert c.property_key == "rdf_label"
