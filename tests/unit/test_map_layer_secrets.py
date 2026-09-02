"""A layer may need an API key; the key must not live in the ontology.

An ontology gets committed, shared and published. A tile URL with a key baked in
leaks it to everyone who receives the file. So a layer names an *environment
variable* and ster substitutes it when serving — the file says which secret it
needs, never what the secret is.
"""

from __future__ import annotations

import pytest
import rdflib

from ster import geo_shapes

STER = "https://ster.dev/ns/map#"
NS = "https://example.org/l#"

TTL = f"""\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ster: <{STER}> .
@prefix ex:   <{NS}> .

ex:rain a ster:MapLayer ;
    rdfs:label "Rain"@en ;
    ster:tileUrl "https://tile.example.org/{{z}}/{{x}}/{{y}}.png?appid={{env:DEMO_MAP_KEY}}" .

ex:plain a ster:MapLayer ;
    rdfs:label "Plain"@en ;
    ster:tileUrl "https://tile.example.org/plain/{{z}}/{{x}}/{{y}}.png" .
"""


@pytest.fixture
def graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(data=TTL, format="turtle")
    return g


def test_the_key_is_substituted_from_the_environment(graph, monkeypatch):
    monkeypatch.setenv("DEMO_MAP_KEY", "s3cret")

    rain = next(x for x in geo_shapes.map_layers(graph) if x["label"] == "Rain")

    assert rain["url"].endswith("appid=s3cret")


def test_a_layer_whose_key_is_unset_is_not_offered(graph, monkeypatch):
    """Better absent than in the menu returning 401 on every tile."""
    monkeypatch.delenv("DEMO_MAP_KEY", raising=False)

    labels = {x["label"] for x in geo_shapes.map_layers(graph)}

    assert "Rain" not in labels
    assert "Plain" in labels, "a layer needing no key is unaffected"


def test_the_ontology_never_holds_the_secret(graph, monkeypatch):
    """The file names the variable; the value is nowhere in it."""
    monkeypatch.setenv("DEMO_MAP_KEY", "s3cret")

    assert "s3cret" not in TTL
    assert "env:DEMO_MAP_KEY" in TTL


def test_only_the_named_variable_is_read(graph, monkeypatch):
    """A placeholder must not be able to reach any other part of the environment."""
    monkeypatch.setenv("DEMO_MAP_KEY", "s3cret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-appear")

    urls = " ".join(str(x["url"]) for x in geo_shapes.map_layers(graph))

    assert "must-not-appear" not in urls


def test_a_malformed_placeholder_is_left_alone(monkeypatch):
    """Not silently turned into an empty string, which would look like it worked."""
    g = rdflib.Graph()
    g.parse(
        data=f"""\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ster: <{STER}> .
@prefix ex:   <{NS}> .
ex:odd a ster:MapLayer ; rdfs:label "Odd"@en ;
    ster:tileUrl "https://t.example.org/{{z}}/{{x}}/{{y}}.png?k={{env:}}" .
""",
        format="turtle",
    )

    assert geo_shapes.map_layers(g) == []
