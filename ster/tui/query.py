"""Thin adapter between the New-TUI query screen and the SPARQL engine.

Isolates :mod:`ster.sparql_query` (and rdflib) behind one module so the screen
imports our API, never the engine directly. Queries run against the *in-memory*
taxonomy (``taxonomy_to_graph``) so unsaved edits are reflected.
"""

from __future__ import annotations

from ster.model import Taxonomy
from ster.sparql_query import PRESET_QUERIES, PresetQuery, QueryResult, run_query_on_graph
from ster.store import taxonomy_to_graph

# A starter query: the common prefixes plus a SELECT skeleton to edit.
DEFAULT_QUERY = """\
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX owl:  <http://www.w3.org/2002/07/owl#>

SELECT ?s ?p ?o
WHERE { ?s ?p ?o }
LIMIT 50
"""


def presets() -> list[PresetQuery]:
    """The built-in preset queries (label · description · sparql)."""
    return list(PRESET_QUERIES)


def run(tax: Taxonomy, sparql: str) -> QueryResult:
    """Run *sparql* against *tax* in memory, returning a normalised ``QueryResult``."""
    return run_query_on_graph(taxonomy_to_graph(tax), sparql)
