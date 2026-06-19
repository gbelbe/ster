"""BDD step definitions for dcterms:title and dcterms:description on owl:Ontology."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios("../features/owl/ontology_metadata.feature")


@pytest.fixture
def ctx():
    return {}


# ── Given ─────────────────────────────────────────────────────────────────────


@given('a taxonomy with ontology URI "https://ex.org/onto" and dcterms:title "My Ontology"')
def given_taxonomy_with_title(ctx):
    from ster.model import Taxonomy

    t = Taxonomy()
    t.ontology_uri = "https://ex.org/onto"
    t.ontology_title = "My Ontology"
    ctx["taxonomy"] = t


@given('a taxonomy with ontology URI "https://ex.org/onto" and dcterms:description "A description"')
def given_taxonomy_with_description(ctx):
    from ster.model import Taxonomy

    t = Taxonomy()
    t.ontology_uri = "https://ex.org/onto"
    t.ontology_description = "A description"
    ctx["taxonomy"] = t


@given(
    'a taxonomy with ontology URI "https://ex.org/onto" and rdfs:label "Kai" but no dcterms:title'
)
def given_taxonomy_label_no_title(ctx):
    ttl = (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        '<https://ex.org/onto> a owl:Ontology ; rdfs:label "Kai" .\n'
    )
    ctx["ttl"] = ttl


@given(
    'a taxonomy with ontology URI "https://ex.org/onto" and rdfs:label "Kai" but no dcterms:description'
)
def given_taxonomy_label_no_description(ctx):
    ttl = (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        '<https://ex.org/onto> a owl:Ontology ; rdfs:label "Kai" .\n'
    )
    ctx["ttl"] = ttl


@given(
    'a taxonomy with ontology URI "https://ex.org/onto", rdfs:label "Kai", and dcterms:title "My Ontology"'
)
def given_taxonomy_label_and_title(ctx):
    from ster.model import Taxonomy

    t = Taxonomy()
    t.ontology_uri = "https://ex.org/onto"
    t.ontology_label = "Kai"
    t.ontology_title = "My Ontology"
    ctx["taxonomy"] = t


@given(
    'a taxonomy with ontology URI "https://ex.org/onto", dcterms:title "My Ontology", and dcterms:description "A description"'
)
def given_taxonomy_title_and_description(ctx):
    from ster.model import Taxonomy

    t = Taxonomy()
    t.ontology_uri = "https://ex.org/onto"
    t.ontology_title = "My Ontology"
    t.ontology_description = "A description"
    ctx["taxonomy"] = t


# ── When ──────────────────────────────────────────────────────────────────────


@when("I save and reload the taxonomy")
def when_save_reload(ctx):
    from ster import store

    with tempfile.NamedTemporaryFile(suffix=".ttl", delete=False) as f:
        tmp = Path(f.name)
    store.save(ctx["taxonomy"], tmp)
    ctx["reloaded"] = store.load(tmp)
    tmp.unlink(missing_ok=True)


@when("I load the taxonomy")
def when_load_taxonomy(ctx):
    from ster import store

    with tempfile.NamedTemporaryFile(suffix=".ttl", delete=False, mode="w") as f:
        f.write(ctx["ttl"])
        tmp = Path(f.name)
    ctx["reloaded"] = store.load(tmp)
    tmp.unlink(missing_ok=True)


@when("I build the ontology overview fields")
def when_build_overview(ctx):
    from ster.nav.logic import build_ontology_overview_fields

    ctx["fields"] = build_ontology_overview_fields(ctx["taxonomy"], lang="en")


# ── Then ──────────────────────────────────────────────────────────────────────


@then('taxonomy.ontology_title is "My Ontology"')
def then_title_is_my_ontology(ctx):
    assert ctx["reloaded"].ontology_title == "My Ontology"


@then('taxonomy.ontology_description is "A description"')
def then_description_is(ctx):
    assert ctx["reloaded"].ontology_description == "A description"


@then('taxonomy.ontology_title is "Kai"')
def then_title_is_kai(ctx):
    assert ctx["reloaded"].ontology_title == "Kai"


@then('taxonomy.ontology_description is "Kai"')
def then_description_is_kai(ctx):
    assert ctx["reloaded"].ontology_description == "Kai"


@then('a field with type "ont_title" is present and editable')
def then_ont_title_editable(ctx):
    f = next((f for f in ctx["fields"] if f.meta.get("type") == "ont_title"), None)
    assert f is not None
    assert f.editable is True


@then('a field with type "ont_description" is present and editable')
def then_ont_description_editable(ctx):
    f = next((f for f in ctx["fields"] if f.meta.get("type") == "ont_description"), None)
    assert f is not None
    assert f.editable is True


@then('the "ont_title" field comes after the "ont_label" field')
def then_title_after_label(ctx):
    types = [f.meta.get("type") for f in ctx["fields"]]
    assert "ont_label" in types
    assert "ont_title" in types
    assert types.index("ont_title") > types.index("ont_label")


@then('the "ont_description" field comes after the "ont_title" field')
def then_description_after_title(ctx):
    types = [f.meta.get("type") for f in ctx["fields"]]
    assert "ont_title" in types
    assert "ont_description" in types
    assert types.index("ont_description") > types.index("ont_title")


# ── generic descriptive metadata round-trip (Slice 1) ───────────────────────────

_DCT = "http://purl.org/dc/terms/"
_OWL = "http://www.w3.org/2002/07/owl#"


def _values(tax, predicate):
    return [a.value for a in tax.ontology_annotations if a.predicate == predicate]


@given("a taxonomy with full descriptive ontology metadata")
def given_full_descriptive_metadata(ctx):
    from ster.model import OntologyAnnotation, Taxonomy

    t = Taxonomy()
    t.ontology_uri = "https://ex.org/onto"
    t.ontology_title = "Example Ontology"  # typed accessor → dcterms:title
    t.ontology_description = "An **example** ontology."
    t.ontology_annotations.append(OntologyAnnotation(_DCT + "creator", "Alice"))
    t.ontology_annotations.append(OntologyAnnotation(_DCT + "publisher", "ACME"))
    t.ontology_annotations.append(
        OntologyAnnotation(_DCT + "license", "https://cc.org/by/4.0/", is_iri=True)
    )
    t.ontology_annotations.append(OntologyAnnotation(_DCT + "language", "en"))
    ctx["taxonomy"] = t


@given("a taxonomy with only an ontology URI and no descriptive metadata")
def given_only_uri(ctx):
    from ster.model import Taxonomy

    t = Taxonomy()
    t.ontology_uri = "https://ex.org/onto"
    ctx["taxonomy"] = t


@given("a taxonomy with multiple creators languages and imports")
def given_multivalued(ctx):
    from ster.model import OntologyAnnotation, Taxonomy

    t = Taxonomy()
    t.ontology_uri = "https://ex.org/onto"
    for name in ("Alice", "Bob", "Carol"):
        t.ontology_annotations.append(OntologyAnnotation(_DCT + "creator", name))
    for code in ("en", "fr", "de"):
        t.ontology_annotations.append(OntologyAnnotation(_DCT + "language", code))
    for imp in ("http://xmlns.com/foaf/0.1/", "http://purl.org/dc/terms/"):
        t.ontology_annotations.append(OntologyAnnotation(_OWL + "imports", imp, is_iri=True))
    ctx["taxonomy"] = t


@then("every descriptive metadata field is preserved")
def then_every_field_preserved(ctx):
    src, out = ctx["taxonomy"], ctx["reloaded"]
    assert out.ontology_title == src.ontology_title
    assert out.ontology_description == src.ontology_description
    assert _values(out, _DCT + "creator") == _values(src, _DCT + "creator")
    assert _values(out, _DCT + "publisher") == _values(src, _DCT + "publisher")
    assert _values(out, _DCT + "license") == _values(src, _DCT + "license")
    assert _values(out, _DCT + "language") == _values(src, _DCT + "language")


@then("the optional descriptive metadata fields are empty")
def then_optional_empty(ctx):
    assert ctx["reloaded"].ontology_annotations == []


@then("all creators languages and imports are preserved")
def then_multivalued_preserved(ctx):
    src, out = ctx["taxonomy"], ctx["reloaded"]
    assert set(_values(out, _DCT + "creator")) == set(_values(src, _DCT + "creator"))
    assert set(_values(out, _DCT + "language")) == set(_values(src, _DCT + "language"))
    assert set(_values(out, _OWL + "imports")) == set(_values(src, _OWL + "imports"))
