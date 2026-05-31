"""Unit tests for dcterms:title and dcterms:description on owl:Ontology."""

from __future__ import annotations

import tempfile
from pathlib import Path

NS = "https://ex.org/onto"


def _make_taxonomy_with_ontology(label=None, title=None, description=None):
    from ster.model import Taxonomy

    t = Taxonomy()
    t.ontology_uri = NS
    t.ontology_label = label
    t.ontology_title = title
    t.ontology_description = description
    return t


def _roundtrip(taxonomy):
    from ster import store

    with tempfile.NamedTemporaryFile(suffix=".ttl", delete=False) as f:
        tmp = Path(f.name)
    store.save(taxonomy, tmp)
    result = store.load(tmp)
    tmp.unlink(missing_ok=True)
    return result


# ── Model defaults ────────────────────────────────────────────────────────────


def test_taxonomy_has_ontology_title_field():
    from ster.model import Taxonomy

    assert Taxonomy().ontology_title is None


def test_taxonomy_has_ontology_description_field():
    from ster.model import Taxonomy

    assert Taxonomy().ontology_description is None


# ── Store round-trips ─────────────────────────────────────────────────────────


def test_save_load_ontology_title():
    t = _make_taxonomy_with_ontology(title="My Ontology")
    assert _roundtrip(t).ontology_title == "My Ontology"


def test_save_load_ontology_description():
    t = _make_taxonomy_with_ontology(description="A description")
    assert _roundtrip(t).ontology_description == "A description"


def test_title_auto_populated_from_label_on_load():
    ttl = (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        f'<{NS}> a owl:Ontology ; rdfs:label "Kai" .\n'
    )
    from ster import store

    with tempfile.NamedTemporaryFile(suffix=".ttl", delete=False, mode="w") as f:
        f.write(ttl)
        tmp = Path(f.name)
    t = store.load(tmp)
    tmp.unlink(missing_ok=True)
    assert t.ontology_title == "Kai"


def test_description_auto_populated_from_label_on_load():
    ttl = (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        f'<{NS}> a owl:Ontology ; rdfs:label "Kai" .\n'
    )
    from ster import store

    with tempfile.NamedTemporaryFile(suffix=".ttl", delete=False, mode="w") as f:
        f.write(ttl)
        tmp = Path(f.name)
    t = store.load(tmp)
    tmp.unlink(missing_ok=True)
    assert t.ontology_description == "Kai"


def test_title_written_to_graph():
    from rdflib import URIRef
    from rdflib.namespace import DCTERMS

    from ster import store

    t = _make_taxonomy_with_ontology(title="My Ontology")
    g = store.taxonomy_to_graph(t)
    assert (URIRef(NS), DCTERMS.title, None) in [(s, p, None) for s, p, _ in g]
    assert str(next(g.objects(URIRef(NS), DCTERMS.title))) == "My Ontology"


def test_description_written_to_graph():
    from rdflib import URIRef
    from rdflib.namespace import DCTERMS

    from ster import store

    t = _make_taxonomy_with_ontology(description="A description")
    g = store.taxonomy_to_graph(t)
    assert str(next(g.objects(URIRef(NS), DCTERMS.description))) == "A description"


def test_no_title_triple_when_both_none():
    from rdflib import URIRef
    from rdflib.namespace import DCTERMS

    from ster import store

    t = _make_taxonomy_with_ontology()
    g = store.taxonomy_to_graph(t)
    assert not list(g.objects(URIRef(NS), DCTERMS.title))


# ── Detail panel ─────────────────────────────────────────────────────────────


def _overview_fields(title=None, description=None, label=None):
    from ster.nav.logic import build_ontology_overview_fields

    t = _make_taxonomy_with_ontology(label=label, title=title, description=description)
    return build_ontology_overview_fields(t, file_path=None, lang="en")


def _field_index(fields, meta_type):
    for i, f in enumerate(fields):
        if f.meta.get("type") == meta_type:
            return i
    return -1


def test_ontology_overview_has_title_field():
    fields = _overview_fields(title="My Ontology")
    assert _field_index(fields, "ont_title") >= 0


def test_ontology_overview_has_description_field():
    fields = _overview_fields(description="A description")
    assert _field_index(fields, "ont_description") >= 0


def test_title_field_is_editable():
    fields = _overview_fields(title="My Ontology")
    f = next(f for f in fields if f.meta.get("type") == "ont_title")
    assert f.editable is True


def test_description_field_is_editable():
    fields = _overview_fields(description="A description")
    f = next(f for f in fields if f.meta.get("type") == "ont_description")
    assert f.editable is True


def test_title_field_comes_after_label():
    fields = _overview_fields(label="Kai", title="My Ontology")
    label_idx = _field_index(fields, "ont_label")
    title_idx = _field_index(fields, "ont_title")
    assert label_idx >= 0
    assert title_idx > label_idx


def test_description_field_comes_after_title():
    fields = _overview_fields(title="My Ontology", description="A description")
    title_idx = _field_index(fields, "ont_title")
    desc_idx = _field_index(fields, "ont_description")
    assert title_idx >= 0
    assert desc_idx > title_idx
