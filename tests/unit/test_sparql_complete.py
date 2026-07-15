"""Unit tests for the pure SPARQL completion logic (ster/tui/sparql_complete.py)."""

from __future__ import annotations

from ster.tui.sparql_complete import (
    Completion,
    EntityIndex,
    context_at,
    current_word,
    keyword_candidates,
    keyword_insertion,
    qname_at_cursor,
    suggest,
    triple_slot,
)

KEYWORDS = ["SELECT", "WHERE", "FILTER", "OPTIONAL", "PREFIX", "DISTINCT", "SERVICE"]


def _index() -> EntityIndex:
    return EntityIndex(
        prefixes={"kai": "https://ex/kai/", "skos": "http://www.w3.org/2004/02/skos/core#"},
        classes={"kai": ["Person", "Product"]},
        individuals={"kai": ["alice"]},
        properties={"kai": ["hasOwner"]},
        concepts={"skos": []},
    )


# ── word / qname scanning ─────────────────────────────────────────────────────


def test_current_word_stops_at_separators() -> None:
    assert current_word("SELECT ?s WHERE { ?s ex", 23) == ("ex", 21)
    assert current_word("", 0) == ("", 0)


def test_qname_at_cursor_after_colon() -> None:
    text = "WHERE { ?s kai:"
    assert qname_at_cursor(text, len(text), {"kai"}) == ("kai", "")


def test_qname_at_cursor_mid_local_name() -> None:
    text = "WHERE { ?s kai:Pers"
    assert qname_at_cursor(text, len(text), {"kai"}) == ("kai", "Pers")


def test_qname_at_cursor_unknown_prefix_is_none() -> None:
    text = "WHERE { ?s foo:Bar"
    assert qname_at_cursor(text, len(text), {"kai"}) is None


def test_qname_at_cursor_plain_word_is_none() -> None:
    assert qname_at_cursor("SELECT ?s", 9, {"kai"}) is None


# ── keyword insertion ─────────────────────────────────────────────────────────


def test_keyword_insertion_block_keyword_expands_with_caret_inside() -> None:
    text, caret = keyword_insertion("WHERE", indent=0)
    assert text == "WHERE {\n  \n}"
    assert text[caret:] == "\n}"  # caret sits on the inner indented line


def test_keyword_insertion_block_keyword_respects_indent() -> None:
    text, caret = keyword_insertion("OPTIONAL", indent=2)
    assert text == "OPTIONAL {\n    \n  }"
    assert text[caret:] == "\n  }"


def test_keyword_insertion_paren_keyword() -> None:
    assert keyword_insertion("FILTER") == ("FILTER()", len("FILTER") + 1)


def test_keyword_insertion_plain_keyword() -> None:
    assert keyword_insertion("SELECT") == ("SELECT", len("SELECT"))


def test_keyword_candidates_are_case_insensitive_prefix() -> None:
    assert keyword_candidates("se", KEYWORDS) == ["SELECT", "SERVICE"]
    assert keyword_candidates("", KEYWORDS) == []


# ── context ───────────────────────────────────────────────────────────────────


def test_context_prologue_then_projection_then_where() -> None:
    assert context_at("PREFIX kai: <x> ", 16) == "prologue"
    assert context_at("SELECT ?s ", 10) == "projection"
    assert context_at("SELECT ?s WHERE { ", 18) == "where"


def test_context_predicate_slot_after_a_subject() -> None:
    assert context_at("SELECT ?s WHERE { ?s ", 21) == "predicate"


# ── suggest ───────────────────────────────────────────────────────────────────


def test_suggest_entities_after_known_prefix() -> None:
    text = "SELECT ?s WHERE { ?s a kai:"
    out = suggest(text, len(text), _index(), KEYWORDS)
    labels = [c.label for c in out]
    kinds = {c.kind for c in out}
    assert "kai:Person" in labels and "kai:hasOwner" in labels and "kai:alice" in labels
    assert kinds <= {"class", "individual", "property", "concept"}


def test_suggest_entities_filtered_by_partial() -> None:
    text = "SELECT ?s WHERE { ?s a kai:P"  # partial "P" → Person + Product, not alice/hasOwner
    out = suggest(text, len(text), _index(), KEYWORDS)
    assert [c.insert for c in out] == ["Person", "Product"]


def test_triple_slot_classifies_subject_predicate_type_object() -> None:
    assert triple_slot("SELECT ?s WHERE { ", 18) == "subject"
    assert triple_slot("SELECT ?s WHERE { ?s ", 21) == "predicate"
    assert triple_slot("SELECT ?s WHERE { ?s a ", 23) == "type-object"


def test_suggest_predicate_slot_ranks_properties_first() -> None:
    text = "SELECT ?s WHERE { ?s kai:"  # subject present → predicate slot
    out = suggest(text, len(text), _index(), KEYWORDS)
    assert out[0].kind == "property"


def test_suggest_type_object_after_a_ranks_classes_first() -> None:
    text = "SELECT ?s WHERE { ?s a kai:"  # object of 'a' → a class
    out = suggest(text, len(text), _index(), KEYWORDS)
    assert out[0].kind == "class"


def test_suggest_keywords_while_typing_a_word() -> None:
    text = "SEL"
    out = suggest(text, len(text), _index(), KEYWORDS)
    assert out and out[0] == Completion("SELECT", "SELECT", "keyword", len("SELECT"))


def test_suggest_keywords_are_position_aware_no_select_inside_where() -> None:
    text = "SELECT ?s WHERE { SEL"  # inside the graph pattern → SELECT is not offered
    out = suggest(text, len(text), _index(), KEYWORDS)
    assert "SELECT" not in [c.label for c in out]


def test_suggest_empty_when_nothing_to_complete() -> None:
    assert suggest("SELECT ?s ", 10, _index(), KEYWORDS) == []
