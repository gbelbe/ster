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
    select_and_where = 2
    assert names.count("keyword") == select_and_where


def test_variables_iris_qnames_and_punctuation() -> None:
    tags = _named('SELECT ?s WHERE { ?s vocab:p <http://x> ; :q "v" . FILTER(?s > 1) }')
    assert tags["variable.builtin"] == "?s"
    assert tags["type"] == "vocab:p"  # qname → 'type'
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


def test_words_from_a_multi_word_autocomplete_phrase_still_colour_individually() -> None:
    """The highlighter's keyword set is derived from SPARQL_KEYWORDS by
    splitting each entry into words — a phrase like "GROUP BY" is one
    autocomplete suggestion but two separate tokens on the page, and each
    must still be recognised on its own."""
    names = {n for _, _, n in spans("SELECT ?s WHERE { ?s ?p ?o } GROUP BY ?s")}
    assert "keyword" in names


def test_keywords_that_only_autocomplete_ever_knew_about_now_colour_too() -> None:
    """Regression: before deriving _KEYWORDS from SPARQL_KEYWORDS, the two
    lists had drifted apart — GROUP, BY, ORDER, NOT, INTO, TO and DEFAULT
    were valid SPARQL keywords that the editor's autocomplete offered but the
    highlighter, with its own separately hand-copied list, did not colour."""
    for word in ("GROUP", "BY", "ORDER", "NOT", "INTO", "TO", "DEFAULT"):
        names = {n for _, _, n in spans(word)}
        assert names == {"keyword"}, word
