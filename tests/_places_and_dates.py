"""A tiny ontology with something to map and something to date.

Shared by the `open_view` unit, API and BDD tests, which all need a real file
loaded the way `ster serve` loads one: the views are only as good as what the
API finds in it.
"""

from __future__ import annotations

from pathlib import Path

from ster.model import Taxonomy

NS = "https://example.org/v#"

TTL = f"""\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix wgs:  <http://www.w3.org/2003/01/geo/wgs84_pos#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix ex:   <{NS}> .

ex:Scheme a skos:ConceptScheme ; skos:prefLabel "Places"@en .

ex:Nantes a skos:Concept ; skos:inScheme ex:Scheme ; skos:prefLabel "Nantes"@en ;
    wgs:lat "47.21" ; wgs:long "-1.55" ;
    dcterms:created "1990-05-01"^^xsd:date .

ex:Brest a skos:Concept ; skos:inScheme ex:Scheme ; skos:prefLabel "Brest"@en ;
    wgs:lat "48.39" ; wgs:long "-4.49" .

ex:Idea a skos:Concept ; skos:inScheme ex:Scheme ; skos:prefLabel "Idea"@en .
"""

PREFIXES = f"PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\nPREFIX ex: <{NS}>\n"
PLACES = PREFIXES + "SELECT ?c WHERE { VALUES ?c { ex:Nantes ex:Brest } }"
DATED = PREFIXES + "SELECT ?c WHERE { VALUES ?c { ex:Nantes } }"
NOTHING_PLACED = PREFIXES + "SELECT ?c WHERE { VALUES ?c { ex:Idea } }"
CONSTRUCT = PREFIXES + "CONSTRUCT { ?c skos:inScheme ?s } WHERE { ?c skos:inScheme ?s }"


def load_places_and_dates(tmp_path: Path) -> Taxonomy:
    from ster.store import load

    path = tmp_path / "places.ttl"
    path.write_text(TTL, encoding="utf-8")
    return load(path)
