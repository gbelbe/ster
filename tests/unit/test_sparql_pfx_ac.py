"""Unit tests for SPARQL prefix name autocomplete."""

from __future__ import annotations

import pytest

from ster.sparql_query import _sparql_pfx_candidates


def test_pfx_candidates_empty_filter_returns_all_sorted() -> None:
    known = {"kai", "skos", "owl", "rdf"}
    result = _sparql_pfx_candidates(known, "")
    assert result == sorted(known)


def test_pfx_candidates_filter_prefix_match() -> None:
    known = {"kai", "skos", "owl", "rdf"}
    assert _sparql_pfx_candidates(known, "s") == ["skos"]


def test_pfx_candidates_case_insensitive() -> None:
    known = {"kai", "skos", "owl"}
    assert _sparql_pfx_candidates(known, "SK") == ["skos"]


def test_pfx_candidates_no_match() -> None:
    known = {"kai", "skos", "owl"}
    assert _sparql_pfx_candidates(known, "xyz") == []


def test_pfx_candidates_multiple_matches_sorted() -> None:
    known = {"rdf", "rdfs", "rdfa"}
    result = _sparql_pfx_candidates(known, "rdf")
    assert result == ["rdf", "rdfa", "rdfs"]


def test_pfx_candidates_exact_match_included() -> None:
    known = {"owl", "owltime"}
    result = _sparql_pfx_candidates(known, "owl")
    assert result == ["owl", "owltime"]


def test_pfx_candidates_excludes_non_matching() -> None:
    known = {"kai", "skos", "owl"}
    result = _sparql_pfx_candidates(known, "k")
    assert "skos" not in result
    assert "owl" not in result
    assert "kai" in result


@pytest.mark.parametrize(
    "filter_text,expected",
    [
        ("", ["kai", "owl", "rdf", "skos"]),
        ("k", ["kai"]),
        ("o", ["owl"]),
        ("s", ["skos"]),
        ("r", ["rdf"]),
        ("z", []),
    ],
)
def test_pfx_candidates_parametrized(filter_text: str, expected: list[str]) -> None:
    known = {"kai", "skos", "owl", "rdf"}
    assert _sparql_pfx_candidates(known, filter_text) == expected
