"""Unit tests for splitting node detail out of the graph payload.

Detail is 91% of the payload on a real thesaurus yet is only ever read for one
node at a time, so the page ships without it and fetches per node on click.
"""

from __future__ import annotations

import json

import pytest

from ster.model import (
    Concept,
    ConceptScheme,
    Label,
    LabelType,
    OWLIndividual,
    RDFClass,
    Taxonomy,
)
from ster.viz_vowl import (
    build_detail_map,
    build_vowl_graph,
    node_detail,
    render_vowl_html,
    strip_detail,
)

NS = "https://example.org/zoo#"


def _lbl(value: str, lang: str = "en") -> Label:
    return Label(lang=lang, value=value, type=LabelType.PREF)


@pytest.fixture
def zoo() -> Taxonomy:
    tax = Taxonomy()
    tax.ontology_uri = "https://example.org/zoo"
    tax.schemes[NS + "Scheme"] = ConceptScheme(uri=NS + "Scheme", labels=[_lbl("Zoo Scheme")])
    tax.concepts[NS + "Animal"] = Concept(uri=NS + "Animal", labels=[_lbl("Animal")])
    tax.owl_classes[NS + "Enclosure"] = RDFClass(uri=NS + "Enclosure", labels=[_lbl("Enclosure")])
    tax.owl_individuals[NS + "Aviary1"] = OWLIndividual(
        uri=NS + "Aviary1", labels=[_lbl("Aviary 1")], types=[NS + "Enclosure"]
    )
    return tax


def test_strip_detail_removes_every_detail_block(zoo):
    graph = strip_detail(build_vowl_graph(zoo))

    assert graph["nodes"], "sanity: the graph still has nodes"
    assert all("detail" not in node for node in graph["nodes"])


def test_strip_detail_keeps_nodes_and_edges_intact(zoo):
    full = build_vowl_graph(zoo)
    expected_ids = [n["id"] for n in full["nodes"]]
    expected_edges = len(full["edges"])

    graph = strip_detail(build_vowl_graph(zoo))

    assert [n["id"] for n in graph["nodes"]] == expected_ids
    assert len(graph["edges"]) == expected_edges


def test_strip_detail_shrinks_the_payload(zoo):
    full = len(json.dumps(build_vowl_graph(zoo)))
    slim = len(json.dumps(strip_detail(build_vowl_graph(zoo))))

    assert slim < full


@pytest.mark.parametrize("name", ["Scheme", "Animal", "Enclosure", "Aviary1"])
def test_node_detail_matches_what_the_graph_carried(zoo, name):
    """Every node kind must resolve, including schemes and individuals.

    The lookup order has to mirror add_node's first-kind-wins, or a URI that is
    both a class and a concept would describe itself differently on click.
    """
    uri = NS + name
    expected = {n["id"]: n["detail"] for n in build_vowl_graph(zoo)["nodes"]}[uri]

    assert node_detail(zoo, uri) == expected


def test_node_detail_for_an_unknown_uri_is_empty(zoo):
    assert node_detail(zoo, NS + "Nope") == {}


def test_build_detail_map_covers_every_node_with_detail(zoo):
    graph = build_vowl_graph(zoo)
    with_detail = {n["id"] for n in graph["nodes"] if n.get("detail")}

    assert set(build_detail_map(zoo)) == with_detail


def test_rendered_html_does_not_inline_detail(zoo):
    """The regression that matters: detail must not reach the first byte."""
    html = render_vowl_html(zoo, None)

    assert '"detail"' not in html


# ── delivery: API route and static sidecar ───────────────────────────────────
#
# Detail left the graph payload, so both transports that replace it need cover:
# the live server answers per node, a static export writes a companion file.

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def client(zoo):
    from fastapi.testclient import TestClient

    from ster.api import SSEBroadcaster, create_app

    return TestClient(create_app(zoo, TOKEN, SSEBroadcaster(), lambda t: None))


def test_node_detail_endpoint_requires_auth(client):
    assert client.get("/api/node-detail", params={"uri": NS + "Animal"}).status_code == 401


def test_node_detail_endpoint_returns_the_same_detail(client, zoo):
    resp = client.get("/api/node-detail", params={"uri": NS + "Animal"}, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == node_detail(zoo, NS + "Animal")


def test_node_detail_endpoint_is_empty_for_an_unknown_uri(client):
    resp = client.get("/api/node-detail", params={"uri": NS + "Nope"}, headers=AUTH)

    assert resp.status_code == 200
    assert resp.json() == {}


def test_api_graph_no_longer_ships_detail(client):
    """The live-refresh payload is fetched on every SSE tick; keep it slim."""
    graph = client.get("/api/graph", headers=AUTH).json()

    assert graph["nodes"]
    assert all("detail" not in node for node in graph["nodes"])


def test_static_export_writes_a_detail_sidecar(tmp_path, zoo):
    from ster.viz_vowl import _data_path, _detail_path, _write_data_json

    out = tmp_path / "zoo_vowl.html"
    _write_data_json(zoo, out)

    polled = json.loads(_data_path(out).read_text(encoding="utf-8"))
    sidecar = json.loads(_detail_path(out).read_text(encoding="utf-8"))

    assert all("detail" not in node for node in polled["nodes"])
    assert sidecar == build_detail_map(zoo)
