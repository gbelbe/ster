"""The paths that only run when something is missing or unusual.

Each of these is a decision the code makes when the happy path is unavailable:
the native engine absent, a model that will not hold a cache, a query form that
is not SELECT, a variable that did not bind, a query that is empty. They are
easy to leave untested precisely because nothing exercises them by accident —
and they are the ones a user meets on the day something is wrong.
"""

from __future__ import annotations

import sys

import pytest

from ster import store
from ster.model import Taxonomy
from ster.sparql_query import run_query_on_taxonomy
from ster.store import full_graph_oxigraph, full_graph_rdflib

E = "https://example.org/#"

TTL = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/#> .
ex:O a owl:Ontology .
ex:Shop  a owl:Class ; rdfs:label "Shop"@en .
ex:Paint a owl:Class .
"""


@pytest.fixture
def tax(tmp_path):
    path = tmp_path / "o.ttl"
    path.write_text(TTL, encoding="utf-8")
    return store.load(path)


class Unwritable(Taxonomy):
    """A model that will not take a cache attribute — frozen, slotted, proxied."""

    def __setattr__(self, name: str, value: object) -> None:
        if name.startswith("_ster_"):
            raise AttributeError(name)
        super().__setattr__(name, value)


def _stubborn(loaded: Taxonomy) -> Unwritable:
    clone = Unwritable()
    clone.__dict__.update({k: v for k, v in loaded.__dict__.items() if not k.startswith("_ster_")})
    return clone


# ── query forms other than SELECT ────────────────────────────────────────────


def test_construct_returns_its_triples(tax):
    """A CONSTRUCT answers with a graph, not a solution table, and the shared
    QueryResult has to carry it in the one shape every caller reads."""
    result = run_query_on_taxonomy(tax, "CONSTRUCT { ?s ?p ?o } WHERE { ?s a ?o . ?s ?p ?o }")

    assert result.query_type == "CONSTRUCT"
    assert result.columns == ["triple"]
    assert result.rows


def test_an_unbound_variable_is_an_empty_cell(tax):
    """OPTIONAL that does not match leaves the variable unbound. It has to come
    back as an empty string, not None, or a caller formatting a row breaks."""
    result = run_query_on_taxonomy(
        tax,
        "SELECT ?s ?missing WHERE { ?s a <http://www.w3.org/2002/07/owl#Class> "
        "OPTIONAL { ?s <https://example.org/#nothing> ?missing } }",
    )

    assert result.rows
    assert all(row[1] == "" for row in result.rows)


def test_an_empty_query_is_refused_before_any_engine_runs(tax):
    result = run_query_on_taxonomy(tax, "   ")

    assert result.error == "Empty query."
    assert result.rows == []


# ── the native engine being absent ───────────────────────────────────────────


def test_no_native_engine_means_no_store(tax, monkeypatch):
    """full_graph_oxigraph returns None rather than raising, so the caller can
    fall back. A build without the native wheel must still answer."""
    monkeypatch.setitem(sys.modules, "pyoxigraph", None)
    monkeypatch.delattr(tax, "_ster_graph_oxigraph", raising=False)

    assert full_graph_oxigraph(tax) is None


def test_a_query_still_answers_without_the_native_engine(tax, monkeypatch):
    """The fallback has to be a real answer, not a degraded one."""
    native = run_query_on_taxonomy(tax, "SELECT ?s WHERE { ?s a ?t }")
    monkeypatch.setitem(sys.modules, "pyoxigraph", None)
    monkeypatch.delattr(tax, "_ster_graph_oxigraph", raising=False)

    without = run_query_on_taxonomy(tax, "SELECT ?s WHERE { ?s a ?t }")

    assert sorted(without.rows) == sorted(native.rows)


# ── a model that will not hold a cache ───────────────────────────────────────


def test_the_rdflib_graph_is_rebuilt_when_it_cannot_be_cached(tax):
    stubborn = _stubborn(tax)

    first, second = full_graph_rdflib(stubborn), full_graph_rdflib(stubborn)

    assert len(first) == len(second) > 0
    assert first is not second


def test_the_oxigraph_store_is_rebuilt_when_it_cannot_be_cached(tax):
    stubborn = _stubborn(tax)

    first, second = full_graph_oxigraph(stubborn), full_graph_oxigraph(stubborn)

    assert first is not None
    assert first is not second


def test_the_vocabulary_is_recomputed_when_it_cannot_be_cached(tax):
    """Memoising is an optimisation. A model that refuses the attribute must
    still get its vocabulary rather than an AttributeError from inside a read."""
    from ster import mcp_context as mc

    stubborn = _stubborn(tax)

    first, second = mc.vocabulary(stubborn), mc.vocabulary(stubborn)

    assert first == second
    assert first is not second
