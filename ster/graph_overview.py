"""The orientation answer for a graph, read from the same store SPARQL runs against.

``get_overview`` used to count the typed tables of the in-memory model. That model is a partial view of the graph (it
sets aside every triple it cannot describe), so a count could disagree with what ``run_sparql`` returns for the same
question. Here the counts, the ontology, the schemes and the languages are themselves SPARQL queries on the session's
store, so an agent that checks a figure with its own query finds the same one.

Nothing in this answer says which file a triple came from: a graph is what is in the store.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from .single_flight import single_flight
from .sparql_query import run_query_on_taxonomy

_PREFIXES = """\
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
"""

# What makes a subject a property, and what makes it something other than an individual.
_PROPERTY_TYPES = "owl:ObjectProperty owl:DatatypeProperty owl:AnnotationProperty rdf:Property"
_NOT_INDIVIDUAL_TYPES = (
    f"owl:Class rdfs:Class skos:Concept skos:ConceptScheme owl:Ontology {_PROPERTY_TYPES}"
)

COUNTS = (
    _PREFIXES
    + f"""
SELECT ?schemes ?concepts ?classes ?individuals ?properties WHERE {{
  {{ SELECT (COUNT(DISTINCT ?s) AS ?schemes) WHERE {{ ?s a skos:ConceptScheme . FILTER(isIRI(?s)) }} }}
  {{ SELECT (COUNT(DISTINCT ?s) AS ?concepts) WHERE {{ ?s a skos:Concept . FILTER(isIRI(?s)) }} }}
  {{ SELECT (COUNT(DISTINCT ?s) AS ?classes) WHERE {{
      {{ ?s a owl:Class }} UNION {{ ?s a rdfs:Class }} FILTER(isIRI(?s)) }} }}
  {{ SELECT (COUNT(DISTINCT ?s) AS ?individuals) WHERE {{
      {{ ?s a owl:NamedIndividual }}
      UNION {{ ?s a ?c . FILTER(!STRSTARTS(STR(?c), "http://www.w3.org/")) }}
      FILTER(isIRI(?s))
      FILTER NOT EXISTS {{ VALUES ?t {{ {_NOT_INDIVIDUAL_TYPES} }} ?s a ?t }} }} }}
  {{ SELECT (COUNT(DISTINCT ?s) AS ?properties) WHERE {{
      VALUES ?t {{ {_PROPERTY_TYPES} }} ?s a ?t . FILTER(isIRI(?s)) }} }}
}}
"""
)

ONTOLOGY = (
    _PREFIXES
    + """
SELECT ?o ?title WHERE {
  ?o a owl:Ontology . FILTER(isIRI(?o))
  OPTIONAL { ?o (dcterms:title|dc:title|rdfs:label|skos:prefLabel) ?title }
} ORDER BY ?o
"""
)

SCHEMES = (
    _PREFIXES
    + """
SELECT ?s ?label (LANG(?label) AS ?lang) WHERE {
  ?s a skos:ConceptScheme . FILTER(isIRI(?s))
  OPTIONAL { ?s (skos:prefLabel|dcterms:title|dc:title|rdfs:label) ?label }
} ORDER BY ?s
"""
)

LANGUAGES = (
    _PREFIXES
    + """
SELECT DISTINCT ?lang WHERE {
  VALUES ?t { skos:Concept owl:Class rdfs:Class }
  ?s a ?t . ?s (skos:prefLabel|skos:altLabel|rdfs:label) ?l .
  BIND(LANG(?l) AS ?lang) FILTER(?lang != "")
} ORDER BY ?lang
"""
)


_MASK = (1 << 64) - 1
# When this ster process started. A client that held a connection to an earlier process (an agent whose MCP session
# outlived a restart) can tell it is talking to a new one.
_STARTED = datetime.now(UTC).isoformat().replace("+00:00", "Z")


def graph_fingerprint(taxonomy: Any) -> dict[str, Any]:
    """A stamp of the graph's content: how many triples, and an order-independent hash of them.

    Each triple is hashed alone and the hashes are added, so neither the order the files were read in nor the order
    the store happens to hold them in changes it. A blank node counts as a blank node (its generated label differs
    from one load to the next), so only structure-free triples affect the hash. Computed once per store build.
    Two graphs with the same stamp are, for an agent's purposes, the same graph; any edit changes it.
    """
    return single_flight(
        ("fingerprint", id(taxonomy)),
        lambda: getattr(taxonomy, "_ster_fingerprint", None),
        lambda: _compute_fingerprint(taxonomy),
    )


def _compute_fingerprint(taxonomy: Any) -> dict[str, Any]:
    from .store import full_graph_rdflib  # noqa: PLC0415

    total = count = 0
    for triple in full_graph_rdflib(taxonomy):
        line = " ".join("_:b" if t.__class__.__name__ == "BNode" else t.n3() for t in triple)
        total = (
            total + int.from_bytes(hashlib.blake2b(line.encode(), digest_size=8).digest(), "big")
        ) & _MASK
        count += 1
    stamp = {"triples": count, "fingerprint": f"{total:016x}"}
    try:
        taxonomy._ster_fingerprint = stamp
    except AttributeError:  # a model that refuses attributes: recompute next time
        pass
    return stamp


def _rows(taxonomy: Any, sparql: str) -> list[list[str]]:
    result = run_query_on_taxonomy(taxonomy, sparql)
    if result.error:
        raise ValueError(f"overview query failed: {result.error}")
    return result.rows


def _local_name(uri: str) -> str:
    return uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def graph_overview(taxonomy: Any, lang: str = "en") -> dict[str, Any]:
    """Orientation: what this graph is and how much of each thing it holds, as the store sees it."""
    [counts] = _rows(taxonomy, COUNTS) or [["0"] * 5]
    schemes, concepts, classes, individuals, properties = (int(c or 0) for c in counts)
    ontology = _ontology(_rows(taxonomy, ONTOLOGY))
    return {
        "ontology_uri": ontology[0],
        "title": ontology[1],
        "file": str(taxonomy.file_path) if taxonomy.file_path else None,
        "graph": graph_fingerprint(taxonomy),
        "server": {"started": _STARTED},
        "counts": {
            "schemes": schemes,
            "concepts": concepts,
            "classes": classes,
            "individuals": individuals,
            "properties": properties,
        },
        "schemes": _schemes(taxonomy, lang),
        "languages": [r[0] for r in _rows(taxonomy, LANGUAGES)],
    }


def _ontology(rows: list[list[str]]) -> tuple[str | None, str | None]:
    """The first declared ontology and its title (the model's ontology_title reads the same predicates)."""
    if not rows:
        return None, None
    uri = rows[0][0]
    titles = [r[1] for r in rows if r[0] == uri and r[1]]
    return uri, (titles[0] if titles else None)


def _schemes(taxonomy: Any, lang: str) -> list[dict[str, str]]:
    """Each scheme with its label in *lang*, else untagged, else in any language, else its local name."""
    labels: dict[str, dict[str, str]] = {}
    for uri, label, tag in _rows(taxonomy, SCHEMES):
        labels.setdefault(uri, {})
        if label:
            labels[uri].setdefault(tag, label)
    return [
        {
            "uri": uri,
            "label": by_tag.get(lang)
            or by_tag.get("")
            or next(iter(by_tag.values()), _local_name(uri)),
        }
        for uri, by_tag in labels.items()
    ]
