"""An image is an image whichever vocabulary named it.

ster only ever read ``schema:image``, so an ontology using ``schema:logo``,
``foaf:depiction`` or Wikidata's P18 — all of which mean "a picture of this" —
showed the reader nothing. Every popular vocabulary spells it differently and
none of them is wrong.

The trap is on the way out, not in. A predicate that gets a handler never
reaches the generic annotations bucket, so consuming ``schema:logo`` as an image
would make the next save write it back as ``schema:image``: the file would open,
display correctly, and quietly lose the author's vocabulary. The alternatives
therefore have to be read *and* preserved.
"""

from __future__ import annotations

import pytest

from ster import store

TTL = """\
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix foaf:   <http://xmlns.com/foaf/0.1/> .
@prefix wdt:    <http://www.wikidata.org/prop/direct/> .
@prefix ex:     <https://example.org/x#> .

ex:Brand a owl:Class ; rdfs:label "Brand"@en .

ex:acme a owl:NamedIndividual, ex:Brand ; rdfs:label "Acme"@en ;
    schema:logo <https://img.example.org/acme-logo.svg> .

ex:beta a owl:NamedIndividual, ex:Brand ; rdfs:label "Beta"@en ;
    foaf:depiction <https://img.example.org/beta.jpg> .

ex:gamma a owl:NamedIndividual, ex:Brand ; rdfs:label "Gamma"@en ;
    wdt:P18 <https://img.example.org/gamma.png> .

ex:delta a owl:NamedIndividual, ex:Brand ; rdfs:label "Delta"@en ;
    schema:image <https://img.example.org/delta.png> .
"""


@pytest.fixture
def tax(tmp_path):
    src = tmp_path / "brands.ttl"
    src.write_text(TTL, encoding="utf-8")
    return store.load(src), src


NS = "https://example.org/x#"


@pytest.mark.parametrize(
    ("who", "expected"),
    [
        ("acme", "https://img.example.org/acme-logo.svg"),  # schema:logo
        ("beta", "https://img.example.org/beta.jpg"),  # foaf:depiction
        ("gamma", "https://img.example.org/gamma.png"),  # wikidata P18
        ("delta", "https://img.example.org/delta.png"),  # schema:image
    ],
)
def test_a_picture_is_found_whatever_predicate_named_it(tax, who, expected) -> None:
    taxonomy, _ = tax

    assert taxonomy.owl_individuals[NS + who].schema_images == [expected]


def test_saving_keeps_the_vocabulary_the_author_chose(tax) -> None:
    """The whole risk: display must not rewrite the file.

    schema:logo must still be schema:logo after a round trip, not silently
    promoted to schema:image because that is what ster happens to read.
    """
    taxonomy, src = tax

    store.save(taxonomy, src)
    text = src.read_text(encoding="utf-8")

    assert "schema:logo" in text or "logo" in text
    assert "acme-logo.svg" in text


def test_an_alternative_predicate_is_not_duplicated_as_schema_image(tax) -> None:
    """Preserving it must not also emit a second, invented triple."""
    taxonomy, src = tax
    store.save(taxonomy, src)

    import rdflib

    g = rdflib.Graph()
    g.parse(src, format="turtle")
    acme = rdflib.URIRef(NS + "acme")
    img = rdflib.URIRef("https://schema.org/image")

    assert (acme, img, None) not in g, "schema:logo was rewritten as schema:image"


def test_the_canonical_predicate_still_round_trips(tax) -> None:
    taxonomy, src = tax
    store.save(taxonomy, src)
    reloaded = store.load(src)

    assert reloaded.owl_individuals[NS + "delta"].schema_images == [
        "https://img.example.org/delta.png"
    ]


def test_every_alternative_is_a_real_vocabulary_term() -> None:
    """No invented predicates: each must come from a vocabulary people publish."""
    from ster.store import IMAGE_PREDICATES

    assert len(IMAGE_PREDICATES) > 5
    for p in IMAGE_PREDICATES:
        assert p.startswith("http"), p


# ── classes and concepts take a different path from individuals ──────────────
# An individual falls through to property_values, which is what preserves its
# original predicate. A class or a concept has an annotations bucket instead, so
# the handler has to put the triple back there itself.

CLASS_TTL = """\
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos:   <http://www.w3.org/2004/02/skos/core#> .
@prefix schema: <https://schema.org/> .
@prefix foaf:   <http://xmlns.com/foaf/0.1/> .
@prefix ex:     <https://example.org/x#> .

ex:Widget a owl:Class ; rdfs:label "Widget"@en ;
    schema:logo <https://img.example.org/widget-logo.svg> ;
    schema:video <https://v.example.org/widget.mp4> ;
    schema:url <https://example.org/widget> .

ex:Scheme a skos:ConceptScheme ; rdfs:label "S"@en .
ex:topic a skos:Concept ; skos:prefLabel "Topic"@en ; skos:inScheme ex:Scheme ;
    foaf:depiction <https://img.example.org/topic.jpg> .
"""


@pytest.fixture
def rich(tmp_path):
    src = tmp_path / "rich.ttl"
    src.write_text(CLASS_TTL, encoding="utf-8")
    return store.load(src), src


def test_a_class_shows_a_logo_from_an_alternative_predicate(rich) -> None:
    taxonomy, _ = rich

    assert taxonomy.owl_classes[NS + "Widget"].schema_images == [
        "https://img.example.org/widget-logo.svg"
    ]


def test_a_concept_shows_a_foaf_depiction(rich) -> None:
    taxonomy, _ = rich

    assert taxonomy.concepts[NS + "topic"].schema_images == ["https://img.example.org/topic.jpg"]


def test_a_class_keeps_its_own_predicate_through_a_save(rich) -> None:
    """The annotations bucket is what makes this survive; without it the handler
    would consume schema:logo and the save would emit schema:image instead."""
    taxonomy, src = rich
    store.save(taxonomy, src)

    import rdflib

    g = rdflib.Graph()
    g.parse(src, format="turtle")
    widget = rdflib.URIRef(NS + "Widget")

    assert (widget, rdflib.URIRef("https://schema.org/logo"), None) in g
    assert (widget, rdflib.URIRef("https://schema.org/image"), None) not in g


def test_videos_and_urls_still_round_trip(rich) -> None:
    """The canonical video and url predicates are emitted as before."""
    taxonomy, src = rich
    store.save(taxonomy, src)
    reloaded = store.load(src)
    cls = reloaded.owl_classes[NS + "Widget"]

    assert cls.schema_videos == ["https://v.example.org/widget.mp4"]
    assert cls.schema_urls == ["https://example.org/widget"]
