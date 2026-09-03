"""``extract_query_variables`` — the ``?var`` name scraper used to pre-fill the
SPARQL editor's variable list. Pure regex extraction, no fixture needed.
"""

from __future__ import annotations

from ster.sparql_query import extract_query_variables


def test_extracts_each_distinct_variable_name_once_sorted():
    buffer = "SELECT ?label ?scheme WHERE { ?s skos:prefLabel ?label ; skos:inScheme ?scheme }"
    assert extract_query_variables(buffer) == ["label", "s", "scheme"]


def test_ignores_bare_question_marks_and_non_variable_text():
    assert extract_query_variables("SELECT * WHERE { ?s ?p ?o } # what?") == ["o", "p", "s"]


def test_empty_buffer_yields_no_variables():
    assert extract_query_variables("") == []
