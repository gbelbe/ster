"""Facets for the map, discovered from the graph rather than configured.

A map of places is often only half the question. The other half is what those
places *are* — which brand runs this store, which unit, which format — and that
lives on entities the map never draws. Those are facets, and which ones exist is
a property of the ontology, not of ster.

The rule is: from a place, follow object properties that are not containment,
and stop at anything that is itself a place. What is left is a facet. Nothing
here knows the word "brand".
"""

from __future__ import annotations

import pytest
import rdflib

from ster import geo_shapes

NS = "https://example.org/f#"

TTL = f"""\
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix wgs:  <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix schema: <https://schema.org/> .
@prefix ex:   <{NS}> .

ex:Place a owl:Class .
ex:Country a owl:Class ; rdfs:subClassOf ex:Place ; rdfs:label "Country"@en .
ex:Shop  a owl:Class ; rdfs:subClassOf ex:Place ; rdfs:label "Shop"@en .
ex:Chain a owl:Class ; rdfs:label "Chain"@en .
ex:Group a owl:Class ; rdfs:label "Group"@en .
ex:Format a owl:Class ; rdfs:label "Format"@en .

ex:within a owl:ObjectProperty ; rdfs:domain ex:Place ; rdfs:range ex:Place .
ex:runBy    a owl:ObjectProperty ; rdfs:domain ex:Shop  ; rdfs:range ex:Chain .
ex:ownedBy  a owl:ObjectProperty ; rdfs:domain ex:Chain ; rdfs:range ex:Group .
ex:hasFormat a owl:ObjectProperty ; rdfs:domain ex:Group ; rdfs:range ex:Format .
ex:tradesIn a owl:ObjectProperty ; rdfs:domain ex:Chain ; rdfs:range ex:Country .

ex:big a owl:NamedIndividual, ex:Format ; rdfs:label "Big"@en .
ex:acme a owl:NamedIndividual, ex:Group ; rdfs:label "Acme"@en ;
    ex:hasFormat ex:big ; schema:image <https://img.example.org/acme.svg> .
ex:chainA a owl:NamedIndividual, ex:Chain ; rdfs:label "Chain A"@en ;
    ex:ownedBy ex:acme ; ex:tradesIn ex:france .

ex:france a owl:NamedIndividual, ex:Country ; rdfs:label "France"@en ;
    wgs:lat "46.7" ; wgs:long "1.7" .
ex:shop1 a owl:NamedIndividual, ex:Shop ; rdfs:label "Shop 1"@en ;
    ex:within ex:france ; ex:runBy ex:chainA ; wgs:lat "48.8" ; wgs:long "2.3" .
"""


@pytest.fixture
def graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=TTL, format="turtle")
    return g


def _facets(graph, local):
    return geo_shapes.facets_of(graph, rdflib.URIRef(NS + local))


def test_a_direct_relation_becomes_a_facet(graph) -> None:
    assert NS + "chainA" in _facets(graph, "shop1").get(NS + "Chain", [])


def test_it_follows_further_than_one_hop(graph) -> None:
    """Shop → Chain → Group → Format. Stopping at one hop finds only the chain."""
    found = _facets(graph, "shop1")

    assert NS + "acme" in found.get(NS + "Group", [])
    assert NS + "big" in found.get(NS + "Format", [])


def test_a_place_is_never_a_facet(graph) -> None:
    """ex:france is reachable via tradesIn, but the map already draws it."""
    found = _facets(graph, "shop1")

    assert NS + "Country" not in found
    assert not any(NS + "france" in v for v in found.values())


def test_containment_is_not_a_facet(graph) -> None:
    """`within` is the drill-down; it must not also appear as a filter."""
    assert NS + "Place" not in _facets(graph, "shop1")


def test_values_are_grouped_by_their_own_class(graph) -> None:
    found = _facets(graph, "shop1")

    assert set(found) == {NS + "Chain", NS + "Group", NS + "Format"}


def test_an_entity_classified_on_two_axes_appears_in_both_menus(graph) -> None:
    """Two unrelated classes are two filters, and dropping one retires a menu.

    Where brands are modelled as classes, a chain is both a Chain and, say, a
    ChainA — neither subsumes the other. Keeping only the deeper of the two
    would make the "Chain" filter vanish the moment brands became classes.
    """
    chain_a = rdflib.URIRef(NS + "chainA")
    graph.add((rdflib.URIRef(NS + "BrandA"), rdflib.RDFS.subClassOf, rdflib.URIRef(NS + "Format")))
    graph.add((chain_a, rdflib.RDF.type, rdflib.URIRef(NS + "BrandA")))

    found = _facets(graph, "shop1")

    assert str(chain_a) in found[NS + "Chain"]
    assert str(chain_a) in found[NS + "BrandA"]


def test_a_class_another_one_already_implies_is_not_offered_twice(graph) -> None:
    """Chain is dropped when the entity is also a subclass of it — that filter
    says strictly less than the deeper one."""
    graph.add((rdflib.URIRef(NS + "Premium"), rdflib.RDFS.subClassOf, rdflib.URIRef(NS + "Chain")))
    graph.add((rdflib.URIRef(NS + "chainA"), rdflib.RDF.type, rdflib.URIRef(NS + "Premium")))

    found = _facets(graph, "shop1")

    assert NS + "Chain" not in found
    assert str(rdflib.URIRef(NS + "chainA")) in found[NS + "Premium"]


def test_a_cycle_does_not_hang_it(graph) -> None:
    graph.add(
        (rdflib.URIRef(NS + "big"), rdflib.URIRef(NS + "ownedBy"), rdflib.URIRef(NS + "acme"))
    )

    assert _facets(graph, "shop1")


def test_a_place_with_no_relations_has_no_facets(graph) -> None:
    assert _facets(graph, "france") == {}


# ── the catalogue the menu draws from ────────────────────────────────────────


def test_the_catalogue_gives_each_value_a_label(graph) -> None:
    cat = geo_shapes.facet_catalogue(graph, [NS + "shop1"])

    assert cat[NS + "Chain"]["label"] == "Chain"
    assert cat[NS + "Chain"]["values"][NS + "chainA"]["label"] == "Chain A"


def test_the_catalogue_carries_a_logo_when_the_ontology_has_one(graph) -> None:
    """Menu buttons show the mark beside the name — where there is one."""
    cat = geo_shapes.facet_catalogue(graph, [NS + "shop1"])

    assert cat[NS + "Group"]["values"][NS + "acme"]["image"] == "https://img.example.org/acme.svg"
    assert cat[NS + "Chain"]["values"][NS + "chainA"]["image"] == ""


def test_provenance_is_not_offered_as_a_filter(graph) -> None:
    """How we know a thing is not what it is.

    An ontology that records its sources properly would otherwise offer "filter
    by which sitemap this came from" beside "filter by brand" — on a real file
    that meant eighteen source entities and a build activity in the menu.
    Excluding the vocabulary is general: PROV-O is a W3C standard, not one
    ontology's private choice.
    """
    PROV = "http://www.w3.org/ns/prov#"
    graph.add(
        (
            rdflib.URIRef(NS + "shop1"),
            rdflib.URIRef(PROV + "wasDerivedFrom"),
            rdflib.URIRef(NS + "src1"),
        )
    )
    graph.add((rdflib.URIRef(NS + "src1"), rdflib.RDF.type, rdflib.URIRef(PROV + "Entity")))
    graph.add((rdflib.URIRef(NS + "src1"), rdflib.RDFS.label, rdflib.Literal("A sitemap")))

    found = _facets(graph, "shop1")

    assert PROV + "Entity" not in found
    assert not any(NS + "src1" in v for v in found.values())


def test_a_facet_needs_more_than_one_value_to_be_worth_showing() -> None:
    """The rule the page applies: a facet that cannot discriminate is not a facet.

    Asserted on the page source because the decision is made client-side, from
    whichever places are in view at the time.
    """
    from ster import geo_map_html

    assert "seen.size > 1" in geo_map_html._PAGE


def test_the_menu_is_rebuilt_as_you_navigate() -> None:
    """Values adapt to where you are, so the strip is redrawn on every draw."""
    from ster import geo_map_html

    assert "drawFacets()" in geo_map_html._PAGE
    assert "function facetsInView()" in geo_map_html._PAGE


def test_the_page_carries_facets_onto_its_points() -> None:
    """The menu reads p.facets, and locate() builds points field by field.

    Every field the server adds has to be copied there explicitly. `facets` was
    missed on the first pass, so the server sent them, the catalogue arrived, and
    the menu still never appeared — the same silent drop that once left every
    map level drawn at once. Both builders are checked: one for the rows a query
    returned, one for the places pulled in to contain them.
    """
    from ster import geo_map_html

    page = geo_map_html._PAGE

    assert "facets:found.facets" in page, "result rows lose their facets"
    assert "facets:p.facets" in page, "context places lose their facets"


def test_filtering_judges_a_place_by_what_lies_beneath_it() -> None:
    """A continent holds no brand; its stores do.

    Judging each place only on its own facets emptied the map the moment a
    filter was chosen at continent level — the one place in view carried none of
    them. Each place is now judged on everything beneath it as well, using the
    ancestor chain the server already sends.
    """
    from ster import geo_map_html

    page = geo_map_html._PAGE

    assert "const facetsBeneath = new Map();" in page
    # The same walk also records which URIs are containers, for the Levels /
    # Everything switch; what matters here is that every ancestor still takes
    # its descendant's facets.
    assert "for (const ancestor of (p.ancestors || [])) { add(ancestor, p.facets);" in page
    assert "facetsBeneath.get(p.uri)" in page


def test_the_query_panel_starts_closed() -> None:
    """The map is the point; the SPARQL behind it is a detail you can open."""
    from ster import geo_map_html

    assert 'id="query-panel" class="closed"' in geo_map_html._PAGE
    assert ">Show query<" in geo_map_html._PAGE


def test_facet_buttons_are_text_only() -> None:
    """Logos were unreadable at button size, so the menu shows names."""
    from ster import geo_map_html

    assert ".fval img" not in geo_map_html._PAGE
