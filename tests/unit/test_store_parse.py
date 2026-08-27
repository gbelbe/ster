"""Unit tests for the parse path in :mod:`ster.store`.

These deliberately use real graphs rather than mocks. The Oxigraph store swap
they replace was covered only by mocked tests that asserted
``Graph(store="Oxigraph")`` was *called* — never that it worked — so they stayed
green for months while every parse silently fell back to the default store.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from ster import store

_TTL = (
    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
    "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
    "@prefix ex: <https://example.org/> .\n"
    "ex:Scheme a skos:ConceptScheme .\n"
    "ex:Concept a skos:Concept ; skos:inScheme ex:Scheme .\n"
)

_XML = (
    '<?xml version="1.0"?>\n'
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"\n'
    '         xmlns:skos="http://www.w3.org/2004/02/skos/core#">\n'
    '  <skos:Concept rdf:about="https://example.org/Concept"/>\n'
    "</rdf:RDF>\n"
)


@pytest.mark.parametrize(
    ("fmt", "suffix", "text", "expected"),
    [("turtle", ".ttl", _TTL, 3), ("xml", ".rdf", _XML, 1)],
)
def test_parse_into_returns_a_populated_graph(tmp_path: Path, fmt, suffix, text, expected):
    """Real parse, no mocks: the triples actually land in the graph."""
    path = tmp_path / f"sample{suffix}"
    path.write_text(text, encoding="utf-8")

    graph = store._parse_into(fmt, path)

    assert len(graph) == expected


def test_parse_into_uses_the_default_store(tmp_path: Path):
    """No store swap on the parse path.

    ``graph_to_taxonomy`` drains the graph with ``for s, p, o in g``. Measured on
    GEMET (323k triples), an Oxigraph-backed store made that drain 2.2x slower
    (1.3s -> 2.9s) for no parse gain (8.3s vs 8.4s), so ster's total load went
    9.6s -> 11.2s. Python-level iteration is what this graph is *for*; keep the
    store that is fast at it.
    """
    path = tmp_path / "sample.ttl"
    path.write_text(_TTL, encoding="utf-8")

    graph = store._parse_into("turtle", path)

    assert type(graph.store).__name__ == "Memory"


def test_oxigraph_is_not_wired_in_as_an_rdflib_store():
    """pyoxigraph earns its place as a parser, never as an rdflib store backend.

    Both integrations exist and only one is worth having:

    * ``Graph(store="Oxigraph")`` needs ``oxrdflib`` and marshals every triple
      across the FFI boundary, which made ster's load *slower* (9.6s -> 11.2s).
    * ``pyoxigraph.parse()`` keeps parsing inside Rust and streams quads once,
      which made it faster (10.4s -> 2.8s) — see :mod:`ster.store._native_index`.

    So the dependency is expected, and the store plugin is expected to be absent.
    """
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    deps = " ".join(data["project"]["dependencies"])

    assert "pyoxigraph" in deps
    assert "oxrdflib" not in deps
