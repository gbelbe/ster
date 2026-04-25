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
    # AI fields
    assert qs.ai_step == ""
    assert qs.ai_question == ""
    assert not qs.ai_generating
    # @ autocomplete fields
    assert not qs.ac_active
    assert qs.ac_trigger_pos == 0
    assert qs.ac_cursor == 0
    assert qs.ac_scroll == 0
    assert qs.ac_level == 1
    assert qs.ac_scheme_uri == ""
    assert qs.ac_scheme_label == ""


# ── AI SPARQL generation (ai.py) ──────────────────────────────────────────────


def test_parse_sparql_strips_fenced_code_block() -> None:
    from ster.ai import _parse_sparql

    text = "Here is the query:\n```sparql\nSELECT ?s WHERE { ?s ?p ?o }\n```"
    result = _parse_sparql(text)
    assert "SELECT ?s WHERE { ?s ?p ?o }" in result
    assert "PREFIX skos:" in result


def test_parse_sparql_strips_plain_fence() -> None:
    from ster.ai import _parse_sparql

    text = "```\nSELECT ?s WHERE { ?s ?p ?o }\n```"
    result = _parse_sparql(text)
    assert "SELECT ?s WHERE { ?s ?p ?o }" in result
    assert "PREFIX skos:" in result


def test_parse_sparql_returns_raw_when_no_fence() -> None:
    from ster.ai import _parse_sparql

    text = "SELECT ?s WHERE { ?s ?p ?o }"
    result = _parse_sparql(text)
    assert "SELECT ?s WHERE { ?s ?p ?o }" in result
    assert result.startswith("PREFIX")


def test_parse_sparql_strips_leading_prose() -> None:
    from ster.ai import _parse_sparql

    text = "Sure, here is the query:\nSELECT ?s WHERE { ?s ?p ?o }"
    result = _parse_sparql(text)
    assert "SELECT" in result
    assert "PREFIX skos:" in result


def test_parse_sparql_keeps_existing_prefixes() -> None:
    from ster.ai import _parse_sparql

    # LLM included its own prefixes → don't double-prepend
    text = "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\nSELECT ?s WHERE { ?s ?p ?o }"
    result = _parse_sparql(text)
    assert result.count("PREFIX skos:") == 1


def test_render_generate_sparql_prompt_contains_question() -> None:
    from ster.ai import render_generate_sparql_prompt

    prompt = render_generate_sparql_prompt(
        taxonomy_name="My Taxonomy",
        taxonomy_description="A test taxonomy.",
        scheme_uris=["https://example.org/scheme"],
        question="find all concepts without a definition",
    )
    assert "find all concepts without a definition" in prompt
    assert "My Taxonomy" in prompt
    # Prefixes are injected post-processing, not in the prompt itself
    assert "PREFIX skos:" not in prompt


def test_render_generate_sparql_prompt_includes_scheme_uri() -> None:
    from ster.ai import render_generate_sparql_prompt

    prompt = render_generate_sparql_prompt(
        taxonomy_name="T",
        taxonomy_description="",
        scheme_uris=["https://example.org/s1", "https://example.org/s2"],
        question="list all top concepts",
    )
    assert "https://example.org/s1" in prompt


def test_render_generate_sparql_prompt_no_description() -> None:
    from ster.ai import render_generate_sparql_prompt

    prompt = render_generate_sparql_prompt(
        taxonomy_name="T",
        taxonomy_description="",
        scheme_uris=[],
        question="q",
    )
    assert "Description:" not in prompt


def test_generate_sparql_task_registered() -> None:
    from ster.prompts import ALL_TASKS, GENERATE_SPARQL, SPARQL_REPAIR

    assert GENERATE_SPARQL in ALL_TASKS
    assert SPARQL_REPAIR in ALL_TASKS


# ── _validate_sparql_syntax ───────────────────────────────────────────────────


def test_validate_sparql_syntax_valid() -> None:
    from ster.ai import _validate_sparql_syntax

    q = "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\nSELECT ?c WHERE { ?c a skos:Concept }"
    assert _validate_sparql_syntax(q) == ""


def test_validate_sparql_syntax_two_forms() -> None:
    from ster.ai import _validate_sparql_syntax

    # SELECT and ASK in the same statement — invalid
    q = "SELECT ?s WHERE { ?s ?p ?o } ASK { ?s ?p ?o }"
    assert _validate_sparql_syntax(q) != ""


def test_validate_sparql_syntax_filter_triple() -> None:
    from ster.ai import _validate_sparql_syntax

    # FILTER with a triple pattern instead of a boolean — invalid
    q = (
        "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\n"
        "SELECT ?c WHERE { ?c a skos:Concept . FILTER(?c skos:prefLabel != null) }"
    )
    assert _validate_sparql_syntax(q) != ""


def test_validate_sparql_syntax_ask() -> None:
    from ster.ai import _validate_sparql_syntax

    q = "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\nASK { ?c a skos:Concept }"
    assert _validate_sparql_syntax(q) == ""


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
