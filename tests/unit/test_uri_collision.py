"""A new entity may not reuse a URI already taken by another entity.

Every entity in a taxonomy is identified by its URI, so creating a second entity under an
existing URI is a mistake — except the one deliberate case: a *pun* (a shared owl:Class +
skos:Concept), which is made only via ``promote_concept_to_class`` and serialises with both
rdf:types on the one subject. The create ops guard every other path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ster import store
from ster.domain.owl import add_owl_individual, add_owl_property
from ster.domain.skos import add_concept, create_scheme
from ster.exceptions import URIAlreadyExistsError

E = "https://ex.org/"

TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://ex.org/> .

ex:scheme a skos:ConceptScheme ; skos:hasTopConcept ex:Hiking .
ex:Hiking a skos:Concept ; skos:inScheme ex:scheme ; skos:prefLabel "Hiking"@en .
ex:Gear a owl:Class ; rdfs:label "Gear"@en .
ex:rex a owl:NamedIndividual, ex:Gear .
ex:hasPart a owl:ObjectProperty .
"""


def _tax(tmp_path: Path):
    src = tmp_path / "o.ttl"
    src.write_text(TTL, encoding="utf-8")
    return store.load(src)


def test_uri_taken_reports_every_layer(tmp_path) -> None:
    tax = _tax(tmp_path)
    for uri in (E + "Hiking", E + "scheme", E + "Gear", E + "rex", E + "hasPart"):
        assert tax.uri_taken(uri), uri
    assert not tax.uri_taken(E + "Fresh")


def test_add_property_with_a_concept_uri_is_blocked(tmp_path) -> None:
    """The reported bug: a new property under a concept's URI must be rejected."""
    tax = _tax(tmp_path)
    with pytest.raises(URIAlreadyExistsError):
        add_owl_property(tax, E + "Hiking", "ObjectProperty", "", "en")


def test_add_individual_with_a_class_uri_is_blocked(tmp_path) -> None:
    tax = _tax(tmp_path)
    with pytest.raises(URIAlreadyExistsError):
        add_owl_individual(tax, E + "Gear")


def test_add_concept_with_a_property_uri_is_blocked(tmp_path) -> None:
    tax = _tax(tmp_path)
    with pytest.raises(URIAlreadyExistsError):
        add_concept(tax, E + "hasPart", {"en": "Part"})


def test_create_scheme_with_an_individual_uri_is_blocked(tmp_path) -> None:
    tax = _tax(tmp_path)
    with pytest.raises(URIAlreadyExistsError):
        create_scheme(tax, E + "rex", labels={"en": "Rex"})


def test_create_class_command_with_a_concept_uri_is_blocked(tmp_path) -> None:
    """The 'New class' / 'New subclass' flow (a command) is blocked too — only the promote
    menu may mint a class under a concept's URI."""
    from ster.core.commands import OwlCreateClass, OwlCreateSubclass

    for cmd in (
        OwlCreateClass(tmp_path / "o.ttl", E + "Hiking"),
        OwlCreateSubclass(tmp_path / "o.ttl", E + "Hiking", E + "Gear"),
    ):
        with pytest.raises(URIAlreadyExistsError):
            cmd.apply(_tax(tmp_path))


def test_a_fresh_uri_still_creates(tmp_path) -> None:
    """The guard only blocks collisions — a genuinely new URI creates fine."""
    tax = _tax(tmp_path)
    prop = add_owl_property(tax, E + "hasColour", "DatatypeProperty", "colour", "en")
    assert prop.uri == E + "hasColour" and E + "hasColour" in tax.owl_properties


# ── the one allowed same-URI case: a pun via promote ──────────────────────────


def test_promote_allows_a_shared_concept_class_uri_and_serialises_as_a_pun(tmp_path) -> None:
    """Promoting a concept mints a class under the *same* URI (a pun) — allowed — and it
    round-trips through the store as a subject typed both skos:Concept and owl:Class."""
    from ster.domain.cross import promote_concept_to_class

    src = tmp_path / "o.ttl"
    src.write_text(TTL, encoding="utf-8")
    tax = store.load(src)
    promote_concept_to_class(tax, E + "Hiking")
    assert tax.uri_taken(E + "Hiking")
    assert tax.node_type(E + "Hiking") == "promoted"  # concept + class

    store.save(tax, src)
    reloaded = store.load(src)
    assert E + "Hiking" in reloaded.concepts and E + "Hiking" in reloaded.owl_classes
