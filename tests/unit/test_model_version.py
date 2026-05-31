"""Unit tests for OWL version fields in Taxonomy (model.py + store.py)."""

from __future__ import annotations

from ster.model import Taxonomy
from ster.store import graph_to_taxonomy, taxonomy_to_graph


def _base_taxonomy(uri: str = "https://ex.org/onto") -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = uri
    return t


def _roundtrip(t: Taxonomy) -> Taxonomy:
    g = taxonomy_to_graph(t)
    ttl = g.serialize(format="turtle")
    from rdflib import Graph

    g2 = Graph()
    g2.parse(data=ttl, format="turtle")
    return graph_to_taxonomy(g2)


def test_taxonomy_has_version_info_field() -> None:
    t = Taxonomy()
    assert hasattr(t, "version_info")
    assert t.version_info is None


def test_taxonomy_has_version_iri_field() -> None:
    t = Taxonomy()
    assert hasattr(t, "version_iri")
    assert t.version_iri is None


def test_taxonomy_has_prior_version_field() -> None:
    t = Taxonomy()
    assert hasattr(t, "prior_version")
    assert t.prior_version is None


def test_version_info_roundtrip_save_load() -> None:
    t = _base_taxonomy()
    t.version_info = "1.1.0"
    t2 = _roundtrip(t)
    assert t2.version_info == "1.1.0"


def test_version_iri_roundtrip_save_load() -> None:
    t = _base_taxonomy()
    t.version_iri = "https://ex.org/onto/1.1.0"
    t2 = _roundtrip(t)
    assert t2.version_iri == "https://ex.org/onto/1.1.0"


def test_prior_version_roundtrip_save_load() -> None:
    t = _base_taxonomy()
    t.prior_version = "https://ex.org/onto/1.0.0"
    t2 = _roundtrip(t)
    assert t2.prior_version == "https://ex.org/onto/1.0.0"


def test_missing_version_fields_are_none() -> None:
    t = _base_taxonomy()
    t2 = _roundtrip(t)
    assert t2.version_info is None
    assert t2.version_iri is None
    assert t2.prior_version is None


def test_all_three_version_fields_roundtrip() -> None:
    t = _base_taxonomy()
    t.version_info = "1.2.0+20260528.abc1234"
    t.version_iri = "https://ex.org/onto/1.2.0"
    t.prior_version = "https://ex.org/onto/1.1.0"
    t2 = _roundtrip(t)
    assert t2.version_info == "1.2.0+20260528.abc1234"
    assert t2.version_iri == "https://ex.org/onto/1.2.0"
    assert t2.prior_version == "https://ex.org/onto/1.1.0"
