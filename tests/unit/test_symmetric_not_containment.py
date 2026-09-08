"""A relation between peers is neither a hierarchy nor an attribute.

ster infers containment from any object property whose domain and range are the
same class — a place inside a place, an organisation inside an organisation.
That rule is right for containment and wrong for anything symmetric: two rivals,
two twinned towns, two interchangeable parts all have the same domain and range
and none of them nests.

Left alone, declaring `competesWith` made ster read competition as geography:
the drill-down followed it, and a business unit acquired a "parent" that was
simply its rival.

`owl:SymmetricProperty` is the discriminator, and it is not a heuristic —
containment is antisymmetric by definition. If A contains B then B does not
contain A, so a property that holds both ways cannot be containment whatever its
domain and range say.
"""

from __future__ import annotations

import rdflib

from ster import geo_shapes

HEAD = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wgs:  <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix ex:   <https://example.org/#> .

ex:Place a owl:Class .
ex:City  a owl:Class ; rdfs:subClassOf ex:Place .
ex:Unit  a owl:Class .
ex:withinArea a owl:ObjectProperty ; rdfs:domain ex:Place ; rdfs:range ex:Place .
"""


def _graph(body: str) -> rdflib.Graph:
    graph = rdflib.Graph()
    graph.parse(data=HEAD + body, format="turtle")
    return graph


def _containment(graph: rdflib.Graph) -> list[str]:
    return [p.rsplit("#", 1)[-1] for p in geo_shapes._declared_containment(graph)]


def test_a_symmetric_property_is_not_containment() -> None:
    graph = _graph("""
ex:competesWith a owl:ObjectProperty, owl:SymmetricProperty ;
    rdfs:domain ex:Unit ; rdfs:range ex:Unit .
""")

    assert _containment(graph) == ["withinArea"]


def test_containment_still_works_beside_it() -> None:
    """The point is to exclude one property, not to break the inference."""
    graph = _graph("""
ex:competesWith a owl:ObjectProperty, owl:SymmetricProperty ;
    rdfs:domain ex:Unit ; rdfs:range ex:Unit .
ex:partOf a owl:ObjectProperty ; rdfs:domain ex:Unit ; rdfs:range ex:Unit .
""")

    assert set(_containment(graph)) == {"withinArea", "partOf"}


def test_a_symmetric_place_property_is_still_excluded() -> None:
    """Twinned towns are places on both sides and still not a hierarchy."""
    graph = _graph("""
ex:twinnedWith a owl:ObjectProperty, owl:SymmetricProperty ;
    rdfs:domain ex:Place ; rdfs:range ex:Place .
""")

    assert _containment(graph) == ["withinArea"]


def test_a_rival_does_not_become_a_parent() -> None:
    """The symptom, end to end: the drill-down followed competition."""
    graph = _graph("""
ex:competesWith a owl:ObjectProperty, owl:SymmetricProperty ;
    rdfs:domain ex:Unit ; rdfs:range ex:Unit .
ex:a a owl:NamedIndividual, ex:Unit ; ex:competesWith ex:b .
ex:b a owl:NamedIndividual, ex:Unit ; ex:competesWith ex:a .
""")

    assert geo_shapes.place_parent(graph, rdflib.URIRef("https://example.org/#a")) is None


# ── and the facet walk must not cross one either ──────────────────────────────

RIVALS = (
    HEAD
    + """
ex:Group a owl:Class . ex:Store a owl:Class .
ex:locatedIn  a owl:ObjectProperty ; rdfs:domain ex:Store ; rdfs:range ex:City .
ex:operatedBy a owl:ObjectProperty ; rdfs:domain ex:Store ; rdfs:range ex:Unit .
ex:ownedBy    a owl:ObjectProperty ; rdfs:domain ex:Unit  ; rdfs:range ex:Group .
ex:competesWith a owl:ObjectProperty, owl:SymmetricProperty ;
    rdfs:domain ex:Unit ; rdfs:range ex:Unit .

ex:fr    a owl:NamedIndividual, ex:City ; wgs:lat "46.6" ; wgs:long "2.3" .
ex:paris a owl:NamedIndividual, ex:City ; ex:withinArea ex:fr ;
    wgs:lat "48.85" ; wgs:long "2.35" .
ex:ours   a owl:NamedIndividual, ex:Group ; rdfs:label "Ours"@en .
ex:theirs a owl:NamedIndividual, ex:Group ; rdfs:label "Theirs"@en .
ex:mine  a owl:NamedIndividual, ex:Unit ; ex:ownedBy ex:ours   ; ex:competesWith ex:yours .
ex:yours a owl:NamedIndividual, ex:Unit ; ex:ownedBy ex:theirs ; ex:competesWith ex:mine .
ex:s1 a owl:NamedIndividual, ex:Store ; wgs:lat "48.86" ; wgs:long "2.34" ;
    ex:locatedIn ex:paris ; ex:operatedBy ex:mine .
"""
)


def _groups_on(uri: str) -> list[str]:
    graph = rdflib.Graph()
    graph.parse(data=RIVALS, format="turtle")
    facets = geo_shapes.facets_of(graph, rdflib.URIRef(uri))
    return [v.rsplit("#", 1)[-1] for v in facets.get("https://example.org/#Group", [])]


def test_a_store_is_not_attributed_to_its_rivals_owner() -> None:
    """The walk reached the rival through competesWith and brought its owner
    back, so every shop listed both groups and filtering by owner selected
    everything."""
    assert _groups_on("https://example.org/#s1") == ["ours"]


def test_the_relation_itself_is_untouched() -> None:
    """Excluded from the walk, not removed from the graph — the data is still
    there to query, and to draw."""
    graph = rdflib.Graph()
    graph.parse(data=RIVALS, format="turtle")
    rivals = list(
        graph.objects(
            rdflib.URIRef("https://example.org/#mine"),
            rdflib.URIRef("https://example.org/#competesWith"),
        )
    )

    assert [str(r).rsplit("#", 1)[-1] for r in rivals] == ["yours"]
