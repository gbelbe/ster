"""Unit tests for build_individual_candidates_grouped range filtering."""

from __future__ import annotations

from ster.model import Label, OWLIndividual, RDFClass, Taxonomy
from ster.nav.logic import build_individual_candidates_grouped

NS = "https://example.org/onto#"


def _uri(name: str) -> str:
    return NS + name


def _cls(name: str, sub_of: list[str] | None = None) -> RDFClass:
    return RDFClass(uri=_uri(name), labels=[Label("en", name)], sub_class_of=sub_of or [])


def _ind(name: str, *types: str) -> OWLIndividual:
    return OWLIndividual(uri=_uri(name), labels=[Label("en", name)], types=[_uri(t) for t in types])


def _uris(candidates: list[tuple[str, str]]) -> set[str]:
    return {u for u, _ in candidates if not u.startswith("__HDR__:")}


def _make_base_taxonomy() -> Taxonomy:
    tax = Taxonomy()
    tax.owl_classes[_uri("Dog")] = _cls("Dog")
    tax.owl_classes[_uri("Person")] = _cls("Person")
    tax.owl_individuals[_uri("Rex")] = _ind("Rex", "Dog")
    tax.owl_individuals[_uri("Alice")] = _ind("Alice", "Person")
    return tax


# ── range filtering ────────────────────────────────────────────────────────────


def test_filters_to_range_class() -> None:
    tax = _make_base_taxonomy()
    result = _uris(build_individual_candidates_grouped(tax, "en", [_uri("Person")], ""))
    assert _uri("Alice") in result
    assert _uri("Rex") not in result


def test_shows_all_when_no_range() -> None:
    tax = _make_base_taxonomy()
    result = _uris(build_individual_candidates_grouped(tax, "en", [], ""))
    assert _uri("Alice") in result
    assert _uri("Rex") in result


def test_excludes_source_individual() -> None:
    tax = _make_base_taxonomy()
    result = _uris(build_individual_candidates_grouped(tax, "en", [_uri("Person")], _uri("Alice")))
    assert _uri("Alice") not in result


def test_includes_subclass_individuals() -> None:
    tax = _make_base_taxonomy()
    tax.owl_classes[_uri("Puppy")] = _cls("Puppy", sub_of=[_uri("Dog")])
    tax.owl_individuals[_uri("Tiny")] = _ind("Tiny", "Puppy")
    result = _uris(build_individual_candidates_grouped(tax, "en", [_uri("Dog")], ""))
    assert _uri("Rex") in result
    assert _uri("Tiny") in result
    assert _uri("Alice") not in result


def test_excludes_non_range_classes() -> None:
    tax = _make_base_taxonomy()
    result = _uris(build_individual_candidates_grouped(tax, "en", [_uri("Dog")], ""))
    assert _uri("Rex") in result
    assert _uri("Alice") not in result


def test_empty_taxonomy_returns_empty() -> None:
    tax = Taxonomy()
    result = build_individual_candidates_grouped(tax, "en", [_uri("Person")], "")
    assert result == []


def test_range_class_with_no_individuals_returns_empty() -> None:
    tax = _make_base_taxonomy()
    tax.owl_classes[_uri("Cat")] = _cls("Cat")
    result = _uris(build_individual_candidates_grouped(tax, "en", [_uri("Cat")], ""))
    assert result == set()


# ── header rows ───────────────────────────────────────────────────────────────


def test_class_header_row_present_when_has_individuals() -> None:
    tax = _make_base_taxonomy()
    candidates = build_individual_candidates_grouped(tax, "en", [_uri("Person")], "")
    headers = [u for u, _ in candidates if u.startswith("__HDR__:")]
    assert f"__HDR__:{_uri('Person')}" in headers


def test_no_header_for_empty_class() -> None:
    tax = _make_base_taxonomy()
    tax.owl_classes[_uri("Cat")] = _cls("Cat")
    candidates = build_individual_candidates_grouped(tax, "en", [_uri("Cat")], "")
    headers = [u for u, _ in candidates if u.startswith("__HDR__:")]
    assert not headers
