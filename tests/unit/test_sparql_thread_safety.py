"""Regression: rdflib's SPARQL parser is not thread-safe.

The viewer warms the graph cache in a background daemon thread
(``ster-cache-warm``) that runs ``g.query()``. rdflib's SPARQL parser
(pyparsing packrat cache + parse-action binding) is global and not
thread-safe, so that background parse racing a foreground ``prepareQuery`` /
``g.query`` permanently corrupts the parser — every later parse then fails with
``<lambda>() missing 1 required positional argument: 'x'`` and similar. Under
xdist this poisons every SPARQL-parsing test sharing the worker.

ster serialises all SPARQL parsing behind ``sparql_query._SPARQL_LOCK``. This
test drives the adapter concurrently and asserts the parser stays intact.
"""

from __future__ import annotations

import threading

import rdflib

from ster import sparql_query

_TTL = (
    "@prefix skos: <http://www.w3.org/2004/02/skos/core#> . <http://example.org/c> a skos:Concept ."
)
GOOD = "PREFIX skos: <http://www.w3.org/2004/02/skos/core#>\nSELECT ?c WHERE { ?c a skos:Concept }"


def _graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=_TTL, format="turtle")
    return g


def test_concurrent_sparql_access_does_not_corrupt_parser():
    g = _graph()
    errors: list[str] = []

    def hammer() -> None:
        for _ in range(40):
            res = sparql_query.run_query_on_graph(g, GOOD)
            if res.error:
                errors.append(res.error)

    threads = [threading.Thread(target=hammer) for _ in range(6)]
    for t in threads:
        t.start()
    # Foreground parsing racing the background query threads — both go through the
    # lock-guarded adapter, so the shared rdflib parser must stay intact.
    for _ in range(120):
        res = sparql_query.run_query_on_graph(g, GOOD)
        if res.error:
            errors.append(res.error)
    for t in threads:
        t.join()

    assert errors == [], f"parser corrupted under concurrency: {errors[:3]}"
    # The parser must still be usable after the concurrent burst.
    assert not sparql_query.run_query_on_graph(g, GOOD).error
