"""Unit tests for the unreadable-file diagnosis: why a load produced no entities."""

from __future__ import annotations

from rdflib import BNode, Literal, URIRef

from ster.model import Concept, Taxonomy
from ster.store import (
    NO_RECOGNISED_TYPES,
    NO_TRIPLES,
    declaration_turtle,
    describe_unreadable,
    diagnose,
    type_lines,
)

_TYPE = URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
_CAPABILITY = URIRef("https://example.com/business-capability/BusinessCapability")
_DOMAIN = URIRef("https://example.com/business-capability/Domain")


def _typed(local: str, type_uri: URIRef) -> tuple:
    return (URIRef(f"https://example.com/business-capability/{local}"), _TYPE, type_uri)


def _residue_taxonomy(*triples: tuple) -> Taxonomy:
    taxonomy = Taxonomy()
    taxonomy.residue = list(triples)
    return taxonomy


def test_diagnose_returns_none_when_entities_exist() -> None:
    taxonomy = _residue_taxonomy(_typed("a", _CAPABILITY))
    taxonomy.concepts["https://example.com/c"] = Concept(uri="https://example.com/c")
    assert diagnose(taxonomy) is None


def test_diagnose_flags_undeclared_type_with_instance_count() -> None:
    result = diagnose(_residue_taxonomy(_typed("a", _CAPABILITY), _typed("b", _CAPABILITY)))
    assert result is not None
    assert result.reason == NO_RECOGNISED_TYPES
    assert result.undeclared_types == ((str(_CAPABILITY), 2),)
    assert result.fixable


def test_diagnose_ranks_undeclared_types_by_frequency() -> None:
    result = diagnose(
        _residue_taxonomy(
            _typed("a", _DOMAIN),
            _typed("b", _CAPABILITY),
            _typed("c", _CAPABILITY),
        )
    )
    assert result is not None
    assert result.undeclared_types == ((str(_CAPABILITY), 2), (str(_DOMAIN), 1))


def test_diagnose_reports_no_triples_for_empty_file() -> None:
    result = diagnose(Taxonomy())
    assert result is not None
    assert result.reason == NO_TRIPLES
    assert result.total_triples == 0
    assert not result.fixable


def test_diagnose_ignores_builtin_types() -> None:
    builtin = URIRef("http://www.w3.org/2002/07/owl#Thing")
    result = diagnose(_residue_taxonomy(_typed("a", builtin)))
    assert result is not None
    assert result.reason == NO_RECOGNISED_TYPES
    assert result.undeclared_types == ()
    assert not result.fixable


def test_diagnose_ignores_blank_node_types() -> None:
    """A class expression is a blank node — it names nothing the user could declare."""
    result = diagnose(_residue_taxonomy((URIRef("https://example.com/a"), _TYPE, BNode())))
    assert result is not None
    assert result.undeclared_types == ()


def test_diagnose_handles_residue_with_no_rdf_type_at_all() -> None:
    label = URIRef("http://www.w3.org/2004/02/skos/core#prefLabel")
    result = diagnose(_residue_taxonomy((URIRef("https://example.com/a"), label, Literal("A"))))
    assert result is not None
    assert result.reason == NO_RECOGNISED_TYPES
    assert result.total_triples == 1
    assert not result.fixable


def test_declaration_turtle_is_pasteable() -> None:
    result = diagnose(_residue_taxonomy(_typed("a", _CAPABILITY)))
    assert result is not None
    turtle = declaration_turtle(result)
    assert "@prefix owl: <http://www.w3.org/2002/07/owl#> ." in turtle
    assert f"<{_CAPABILITY}> a owl:Class ." in turtle


def test_declaration_turtle_is_empty_when_nothing_is_declarable() -> None:
    assert declaration_turtle(diagnose(Taxonomy())) == ""


def test_describe_names_the_file_and_the_counts() -> None:
    result = diagnose(_residue_taxonomy(_typed("a", _CAPABILITY), _typed("b", _CAPABILITY)))
    assert result is not None
    text = describe_unreadable(result, "business_capabilities.ttl")
    assert "business_capabilities.ttl" in text
    assert "2 triples" in text
    assert "no entity" in text.lower()


def test_describe_says_the_file_is_empty_when_there_are_no_triples() -> None:
    text = describe_unreadable(diagnose(Taxonomy()), "empty.ttl")
    assert "empty.ttl" in text
    assert "no triples" in text.lower()


def test_type_lines_right_align_counts_and_end_with_the_uri() -> None:
    """The URI ends the line so folding never breaks a sentence around it."""
    result = diagnose(
        _residue_taxonomy(
            _typed("a", _DOMAIN),
            _typed("b", _CAPABILITY),
            _typed("c", _CAPABILITY),
        )
    )
    assert type_lines(result) == [f"2 ×  {_CAPABILITY}", f"1 ×  {_DOMAIN}"]


def test_type_lines_pad_counts_to_the_widest() -> None:
    residue = [_typed(f"c{n}", _CAPABILITY) for n in range(10)] + [_typed("d", _DOMAIN)]
    lines = type_lines(diagnose(_residue_taxonomy(*residue)))
    assert lines == [f"10 ×  {_CAPABILITY}", f" 1 ×  {_DOMAIN}"]


def test_type_lines_are_empty_when_nothing_is_declarable() -> None:
    assert type_lines(diagnose(Taxonomy())) == []
