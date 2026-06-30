"""Tests for the SPARQL query engine (sparql_query.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ster import sparql_query as sq

# ── helpers ───────────────────────────────────────────────────────────────────

MINIMAL_TTL = """\
@prefix skos:    <http://www.w3.org/2004/02/skos/core#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix t:       <https://example.org/test/> .

t:Scheme a skos:ConceptScheme ;
    skos:prefLabel "Test Taxonomy"@en ;
    skos:hasTopConcept t:Top .

t:Top a skos:Concept ;
    skos:inScheme t:Scheme ;
    skos:topConceptOf t:Scheme ;
    skos:prefLabel "Top Concept"@en ;
    skos:definition "The root concept."@en ;
    skos:narrower t:Child1 , t:Child2 .

t:Child1 a skos:Concept ;
    skos:inScheme t:Scheme ;
    skos:prefLabel "Child One"@en ;
    skos:altLabel "First child"@en ;
    skos:broader t:Top .

t:Child2 a skos:Concept ;
    skos:inScheme t:Scheme ;
    skos:prefLabel "Child Two"@en ;
    skos:broader t:Top .
"""


@pytest.fixture
def ttl_file(tmp_path: Path) -> Path:
    p = tmp_path / "test.ttl"
    p.write_text(MINIMAL_TTL, encoding="utf-8")
    return p


# ── QueryResult / run_query ───────────────────────────────────────────────────


def test_run_query_empty_returns_error():
    result = sq.run_query([], "")
    assert result.error


def test_run_query_select(ttl_file: Path) -> None:
    result = sq.run_query(
        [ttl_file],
        "PREFIX skos: <http://www.w3.org/2004/02/skos/core#> SELECT ?c WHERE { ?c a skos:Concept }",
    )
    assert not result.error
    assert result.query_type == "SELECT"
    assert "c" in result.columns
    assert len(result.rows) == 3  # Top, Child1, Child2


def test_run_query_ask_true(ttl_file: Path) -> None:
    result = sq.run_query(
        [ttl_file],
        "PREFIX skos: <http://www.w3.org/2004/02/skos/core#> ASK { ?c a skos:Concept }",
    )
    assert not result.error
    assert result.query_type == "ASK"
    assert result.rows == [["true"]]


def test_run_query_invalid_sparql(ttl_file: Path) -> None:
    result = sq.run_query([ttl_file], "NOT VALID SPARQL !!!")
    assert result.error


def test_run_query_missing_file() -> None:
    result = sq.run_query([Path("/nonexistent/file.ttl")], "SELECT ?s WHERE { ?s ?p ?o }")
    assert result.error


def test_run_query_order_by(ttl_file: Path) -> None:
    result = sq.run_query(
        [ttl_file],
        sq.PRESET_QUERIES[0].sparql,  # "All concepts" ordered by label
    )
    assert not result.error
    assert len(result.rows) >= 3
    labels = [row[1] for row in result.rows]
    assert labels == sorted(labels)


# ── preset queries ────────────────────────────────────────────────────────────


def test_all_presets_have_required_fields() -> None:
    for p in sq.PRESET_QUERIES:
        assert p.label
        assert p.description
        assert "SELECT" in p.sparql.upper() or "ASK" in p.sparql.upper()


def test_preset_missing_definitions(ttl_file: Path) -> None:
    preset = next(p for p in sq.PRESET_QUERIES if p.label == "Missing definitions")
    result = sq.run_query([ttl_file], preset.sparql)
    assert not result.error
    # Child1 and Child2 have no definition
    assert len(result.rows) == 2


def test_preset_missing_alt_labels(ttl_file: Path) -> None:
    preset = next(p for p in sq.PRESET_QUERIES if p.label == "Missing alt labels")
    result = sq.run_query([ttl_file], preset.sparql)
    assert not result.error
    # Top and Child2 have no altLabel
    assert len(result.rows) == 2


def test_preset_hierarchy(ttl_file: Path) -> None:
    preset = next(p for p in sq.PRESET_QUERIES if p.label == "Hierarchy")
    result = sq.run_query([ttl_file], preset.sparql)
    assert not result.error
    # Top → Child1, Top → Child2
    assert len(result.rows) == 2


def test_preset_top_concepts(ttl_file: Path) -> None:
    preset = next(p for p in sq.PRESET_QUERIES if p.label == "Top concepts")
    result = sq.run_query([ttl_file], preset.sparql)
    assert not result.error
    assert len(result.rows) == 1
    assert any("Top" in cell for row in result.rows for cell in row)


# ── find_uri_column ───────────────────────────────────────────────────────────


def test_find_uri_column_detects_first_uri_column() -> None:
    result = sq.QueryResult(
        columns=["concept", "label"],
        rows=[
            ["https://example.org/A", "Label A"],
            ["https://example.org/B", "Label B"],
        ],
    )
    assert sq.find_uri_column(result) == 0


def test_find_uri_column_skips_non_uri_column() -> None:
    result = sq.QueryResult(
        columns=["label", "concept"],
        rows=[
            ["Label A", "https://example.org/A"],
            ["Label B", "https://example.org/B"],
        ],
    )
    assert sq.find_uri_column(result) == 1


def test_find_uri_column_returns_none_when_no_uris() -> None:
    result = sq.QueryResult(
        columns=["a", "b"],
        rows=[["foo", "bar"], ["baz", "qux"]],
    )
    assert sq.find_uri_column(result) is None


def test_find_uri_column_empty_result() -> None:
    assert sq.find_uri_column(sq.QueryResult(columns=[], rows=[])) is None


# ── compute_col_widths ────────────────────────────────────────────────────────


def test_compute_col_widths_fits_available() -> None:
    widths = sq.compute_col_widths(["a", "b"], [["short", "x"]], 80)
    assert len(widths) == 2
    assert all(w >= 4 for w in widths)


def test_compute_col_widths_scales_down() -> None:
    # Very narrow terminal — widths must be ≥ 4 each
    cols = ["col1", "col2", "col3"]
    rows = [["a" * 30, "b" * 30, "c" * 30]]
    widths = sq.compute_col_widths(cols, rows, 20)
    assert len(widths) == 3
    assert all(w >= 4 for w in widths)


def test_compute_col_widths_empty() -> None:
    assert sq.compute_col_widths([], [], 80) == []


# ── _detect_query_type ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sparql, expected",
    [
        ("SELECT ?s WHERE { ?s ?p ?o }", "SELECT"),
        ("ASK { ?s ?p ?o }", "ASK"),
        ("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }", "CONSTRUCT"),
        ("DESCRIBE ?s WHERE { ?s ?p ?o }", "DESCRIBE"),
        ("select ?s where { ?s ?p ?o }", "SELECT"),  # case-insensitive
        ("garbage text", "SELECT"),  # default
    ],
)
def test_detect_query_type(sparql: str, expected: str) -> None:
    assert sq._detect_query_type(sparql) == expected


# ── nav_state QueryState ──────────────────────────────────────────────────────


def test_query_state_defaults() -> None:
    from ster.nav.state import QueryState

    qs = QueryState()
    assert qs.panel == "editor"
    assert qs.query_buffer == ""
    assert not qs.running
    assert not qs.show_presets
    assert qs.columns == []
    assert qs.rows == []
    # @ autocomplete fields
    assert not qs.ac_active
    assert qs.ac_trigger_pos == 0
    assert qs.ac_cursor == 0
    assert qs.ac_scroll == 0
    assert qs.ac_level == 1
    assert qs.ac_scheme_uri == ""
    assert qs.ac_scheme_label == ""


# ── _ac_matches ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "label, q, expected",
    [
        ("Machine Learning", "", True),  # empty query matches all
        ("Machine Learning", "mach", True),  # prefix of full label
        ("Machine Learning", "learn", True),  # prefix of second word
        ("Machine Learning", "MACH", True),  # case-insensitive
        ("Machine Learning", "achine", False),  # substring inside word — no match
        ("Machine Learning", "earn", False),  # substring inside word — no match
        ("Machine Learning", "xyz", False),  # no match at all
        ("Top Concept", "top", True),  # prefix of first word
        ("Top Concept", "con", True),  # prefix of second word
        ("Top Concept", "op", False),  # substring inside word — no match
    ],
)
def test_ac_matches(label: str, q: str, expected: bool) -> None:
    from ster.nav import _ac_matches

    assert _ac_matches(label, q) == expected


# ── query autocomplete buffer helpers (TaxonomyViewer._query_ac_*) ─────────────
# These mutate a QueryState's buffer/cursor and use no `self`, so we call them on
# the class with a stub self — pure, terminal-free coverage of the kept manual-
# query autocomplete code that the AI-removal touched.


def _qs(buffer: str, pos: int, trigger: int):  # noqa: ANN202
    from ster.nav.state import QueryState

    qs = QueryState()
    qs.query_buffer = buffer
    qs.query_pos = pos
    qs.ac_trigger_pos = trigger
    qs.ac_active = True
    qs.ac_level = 2
    return qs


def test_query_ac_insert_replaces_at_filter_with_uri() -> None:
    from ster.nav.viewer import TaxonomyViewer

    qs = _qs("ASK { @Ch", pos=9, trigger=7)  # '@' at idx 6, filter "Ch"
    TaxonomyViewer._query_ac_insert(None, qs, ("Child", "https://ex/Child", "CON", ""))
    assert qs.query_buffer == "ASK { <https://ex/Child>"
    assert qs.query_pos == len("ASK { <https://ex/Child>")
    assert qs.ac_active is False
    assert qs.ac_level == 1


def test_query_ac_clear_filter_drops_text_after_at() -> None:
    from ster.nav.viewer import TaxonomyViewer

    qs = _qs("ASK { @Child", pos=12, trigger=7)
    TaxonomyViewer._query_ac_clear_filter(None, qs)
    assert qs.query_buffer == "ASK { @"
    assert qs.query_pos == 7


def test_query_ac_cancel_removes_at_and_filter() -> None:
    from ster.nav.viewer import TaxonomyViewer

    qs = _qs("ASK { @Child", pos=12, trigger=7)
    TaxonomyViewer._query_ac_cancel(None, qs)
    assert qs.query_buffer == "ASK { "
    assert qs.query_pos == 6
    assert qs.ac_active is False
