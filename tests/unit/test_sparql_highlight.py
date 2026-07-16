"""Unit tests for the pure SPARQL regex highlighter (ster/tui/sparql_highlight.py)."""

from __future__ import annotations

from ster.tui.sparql_highlight import spans


def _named(line: str) -> dict[str, str]:
    """Map each highlight name to the substring it covers (first occurrence)."""
    out: dict[str, str] = {}
    for start, end, name in spans(line):
        out.setdefault(name, line[start:end])
    return out


def test_keywords_are_highlighted_case_insensitively() -> None:
    tags = _named("SELECT ?s where { ?s a :C }")
    assert tags["keyword"] in ("SELECT", "where", "a")
    names = [n for _, _, n in spans("SELECT ?s where")]
    assert names.count("keyword") == 2  # SELECT and where


def test_variables_iris_qnames_and_punctuation() -> None:
    tags = _named('SELECT ?s WHERE { ?s vocab:p <http://x> ; :q "v" . FILTER(?s > 1) }')
    assert tags["variable.builtin"] == "?s"
    assert tags["qname" if False else "type"] == "vocab:p"  # qname → 'type'
    assert tags["link.uri"] == "<http://x>"
    assert tags["string"] == '"v"'
    assert tags["punctuation.bracket"] == "{"
    assert tags["punctuation.delimiter"] in (";", ".")
    assert tags["operator"] == ">"


def test_comment_and_number() -> None:
    tags = _named("LIMIT 25")  # spans works per line
    assert tags["keyword"] == "LIMIT" and tags["number"] == "25"
    assert _named("# hello")["comment"] == "# hello"


def test_the_rdf_type_shorthand_a_is_a_keyword() -> None:
    names = {n for _, _, n in spans("?s a :Thing")}
    assert "keyword" in names  # 'a'
    # a plain local name that isn't a keyword is not coloured as a keyword
    assert "keyword" not in {n for _, _, n in spans("?s foo ?o")}
