"""Tests for the RDF persistence layer."""
from __future__ import annotations
import pytest
from pathlib import Path
from ster import store
from ster.model import LabelType

BASE = "https://example.org/test/"


def test_load_finds_scheme(taxonomy):
    assert BASE + "Scheme" in taxonomy.schemes


def test_load_finds_all_concepts(taxonomy):
    expected = {BASE + c for c in ("Top", "Child1", "Child2", "Grandchild")}
    assert expected == set(taxonomy.concepts)


def test_load_pref_labels(taxonomy):
    top = taxonomy.concepts[BASE + "Top"]
    assert top.pref_label("en") == "Top Concept"
    assert top.pref_label("fr") == "Concept Principal"


def test_load_alt_label(taxonomy):
    child2 = taxonomy.concepts[BASE + "Child2"]
    alts = child2.alt_labels()
    assert "Second child" in alts.get("en", [])


def test_load_definition(taxonomy):
    top = taxonomy.concepts[BASE + "Top"]
    assert top.definition("en") == "The root concept."


def test_load_narrower(taxonomy):
    top = taxonomy.concepts[BASE + "Top"]
    assert BASE + "Child1" in top.narrower
    assert BASE + "Child2" in top.narrower


def test_load_normalizes_broader(taxonomy):
    """Broader links should be populated even if only narrower is in the file."""
    child1 = taxonomy.concepts[BASE + "Child1"]
    assert BASE + "Top" in child1.broader


def test_load_top_concepts(taxonomy):
    scheme = taxonomy.schemes[BASE + "Scheme"]
    assert BASE + "Top" in scheme.top_concepts


def test_load_assigns_handles(taxonomy):
    assert len(taxonomy.handle_index) > 0
    # Every concept and scheme should have a handle
    for uri in list(taxonomy.concepts) + list(taxonomy.schemes):
        assert taxonomy.uri_to_handle(uri) is not None


def test_base_uri_round_trip(tmp_path):
    """base_uri stored as void:uriSpace survives a save/reload cycle."""
    from ster import operations
    from ster.model import Taxonomy
    t = Taxonomy()
    operations.create_scheme(
        t, BASE + "Scheme", {"en": "Test"}, base_uri=BASE
    )
    out = tmp_path / "out.ttl"
    store.save(t, out)
    reloaded = store.load(out)
    scheme = reloaded.primary_scheme()
    assert scheme is not None
    assert scheme.base_uri == BASE


def test_taxonomy_base_uri_derived_from_concepts(simple_taxonomy):
    """Taxonomy.base_uri() returns scheme.base_uri when set."""
    assert simple_taxonomy.base_uri() == BASE


def test_unsupported_extension_raises(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("nope")
    with pytest.raises(ValueError, match="Unsupported file extension"):
        store.load(p)


def test_round_trip_turtle(tmp_ttl, tmp_path, taxonomy):
    """Load → save → reload should produce the same concepts."""
    out = tmp_path / "out.ttl"
    store.save(taxonomy, out)
    reloaded = store.load(out)
    assert set(reloaded.concepts) == set(taxonomy.concepts)
    assert set(reloaded.schemes) == set(taxonomy.schemes)


def test_round_trip_preserves_labels(tmp_ttl, tmp_path, taxonomy):
    out = tmp_path / "out.ttl"
    store.save(taxonomy, out)
    reloaded = store.load(out)
    for uri, original in taxonomy.concepts.items():
        reloaded_concept = reloaded.concepts[uri]
        assert original.pref_label("en") == reloaded_concept.pref_label("en")


def test_round_trip_jsonld(tmp_path, minimal_turtle):
    ttl = tmp_path / "source.ttl"
    ttl.write_text(minimal_turtle)
    t1 = store.load(ttl)

    jsonld = tmp_path / "out.jsonld"
    store.save(t1, jsonld)
    t2 = store.load(jsonld)

    assert set(t1.concepts) == set(t2.concepts)
