"""The whole session as one graph — what the map reads.

``full_graph_rdflib`` differs from ``taxonomy_to_graph`` in exactly two ways, and both
matter to a caller that is reading rather than writing: it includes entities
merged from context files, and it re-emits those files' residue. The write path
must do neither, which is why the flag defaults to off.

It is also memoised, because the map asks on every pan and rebuilding costs a
few hundred milliseconds on a real ontology. The cache lives on the taxonomy
object so it cannot outlive the model it was built from.
"""

from __future__ import annotations

import pytest
import rdflib

from ster import store
from ster.model import Taxonomy
from ster.store import full_graph_rdflib, taxonomy_to_graph

E = "https://example.org/#"

MAIN = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/#> .
ex:O a owl:Ontology .
ex:Shop a owl:Class ; rdfs:label "Shop"@en .
"""

# ex:ghost is referenced but never declared, so it cannot be modelled and lands
# in residue — which is precisely what the read path has to put back.
CTX = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/#> .
ex:V a owl:Ontology .
ex:Paint a owl:Class ; rdfs:label "Paint"@en .
ex:ghost ex:mentions ex:nothing .
"""

GHOST = (
    rdflib.URIRef(E + "ghost"),
    rdflib.URIRef(E + "mentions"),
    rdflib.URIRef(E + "nothing"),
)


@pytest.fixture
def loaded(tmp_path):
    main, ctx = tmp_path / "main.ttl", tmp_path / "ctx.ttl"
    main.write_text(MAIN, encoding="utf-8")
    ctx.write_text(CTX, encoding="utf-8")
    return store.load(main, context=[ctx])


def test_a_context_entity_is_in_the_read_graph(loaded):
    assert (rdflib.URIRef(E + "Paint"), None, None) in full_graph_rdflib(loaded)


def test_a_context_entity_is_not_in_the_write_graph(loaded):
    """The same model, serialised for writing, must not absorb the other file."""
    assert (rdflib.URIRef(E + "Paint"), None, None) not in taxonomy_to_graph(loaded)


def test_context_residue_is_re_emitted_for_reading(loaded):
    """A triple the model could not describe is still part of the graph a query
    runs against; dropping it would make the map answer from half the data."""
    assert GHOST in full_graph_rdflib(loaded)


def test_context_residue_is_not_written_back_into_the_editable_file(loaded):
    assert GHOST not in taxonomy_to_graph(loaded)


def test_the_graph_is_built_once_per_model(loaded):
    """The map asks on every pan; rebuilding each time is the difference between
    usable and not."""
    assert full_graph_rdflib(loaded) is full_graph_rdflib(loaded)


def test_a_model_that_refuses_attributes_still_answers(tmp_path):
    """The cache is an optimisation, never a requirement.

    Memoising writes an attribute onto the taxonomy. A model that will not take
    one — frozen, slotted, or proxied — must still get its graph, just rebuilt
    each time, rather than raising from inside a read.
    """

    class Unwritable(Taxonomy):
        def __setattr__(self, name: str, value: object) -> None:
            if name.startswith("_ster_"):
                raise AttributeError(name)
            super().__setattr__(name, value)

    path = tmp_path / "m.ttl"
    path.write_text(MAIN, encoding="utf-8")
    loaded = store.load(path)
    stubborn = Unwritable()
    stubborn.__dict__.update(
        {k: v for k, v in loaded.__dict__.items() if not k.startswith("_ster_")}
    )

    first, second = full_graph_rdflib(stubborn), full_graph_rdflib(stubborn)

    assert len(first) == len(second) > 0
    assert first is not second, "no attribute was set, so nothing can have been cached"
