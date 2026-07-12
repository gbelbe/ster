"""Unit tests for OWL individual property capture and display."""

from __future__ import annotations

import textwrap

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.nav.logic import build_individual_detail
from ster.store import graph_to_taxonomy, taxonomy_to_graph

BASE = "https://example.org/onto/"
XSD_DATE = "http://www.w3.org/2001/XMLSchema#date"


# ── helpers ───────────────────────────────────────────────────────────────────


def _has_prop_row(fields, prop_label: str, value: str) -> bool:
    """Return True if any display field shows prop_label → value."""
    return any(prop_label in f.display and value in f.value for f in fields)


def _has_action(fields, action_name: str) -> bool:
    return any(f.meta.get("action") == action_name for f in fields)


def _roundtrip(taxonomy: Taxonomy) -> Taxonomy:
    g = taxonomy_to_graph(taxonomy)
    return graph_to_taxonomy(g)


def _load_ttl(ttl: str) -> Taxonomy:
    from io import BytesIO

    from rdflib import Graph

    g = Graph()
    g.parse(BytesIO(ttl.encode()), format="turtle")
    return graph_to_taxonomy(g)


# ── Store: URI property capture ───────────────────────────────────────────────


def test_uri_property_values_include_external_uri():
    """ObjectProperty pointing to an external (non-local) URI must be captured."""
    ttl = textwrap.dedent(f"""\
        @prefix ex: <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        ex:knows a owl:ObjectProperty .
        ex:Alice a owl:NamedIndividual ;
            ex:knows <https://external.org/Bob> .
    """)
    t = _load_ttl(ttl)
    alice = t.owl_individuals.get(BASE + "Alice")
    assert alice is not None
    assert (BASE + "knows", "https://external.org/Bob") in alice.property_values


def test_uri_property_values_include_undeclared_predicate():
    """A predicate not declared as owl:ObjectProperty but used with a URI value is captured."""
    ttl = textwrap.dedent(f"""\
        @prefix ex: <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        ex:Doc a owl:NamedIndividual ;
            ex:seeAlso <https://example.org/ref> .
    """)
    t = _load_ttl(ttl)
    doc = t.owl_individuals.get(BASE + "Doc")
    assert doc is not None
    assert (BASE + "seeAlso", "https://example.org/ref") in doc.property_values


def test_structural_predicates_not_in_property_values():
    """rdfs:label, rdf:type, schema:url must not appear in property_values or literal_values."""
    ttl = textwrap.dedent(f"""\
        @prefix ex: <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix schema: <https://schema.org/> .

        ex:Thing a owl:Class .
        ex:Item a owl:NamedIndividual, ex:Thing ;
            rdfs:label "My Label"@en ;
            schema:url <https://example.org> .
    """)
    t = _load_ttl(ttl)
    item = t.owl_individuals.get(BASE + "Item")
    assert item is not None
    pred_uris_uri = {pv[0] for pv in item.property_values}
    pred_uris_lit = {lv[0] for lv in item.literal_values}
    assert "http://www.w3.org/2000/01/rdf-schema#label" not in pred_uris_uri
    assert "http://www.w3.org/2000/01/rdf-schema#label" not in pred_uris_lit
    assert "http://www.w3.org/1999/02/22-rdf-syntax-ns#type" not in pred_uris_uri
    assert "https://schema.org/url" not in pred_uris_uri
    assert "https://schema.org/url" not in pred_uris_lit


# ── Store: literal value capture ─────────────────────────────────────────────


def test_literal_values_captured_for_datatype_property():
    """DatatypeProperty literal assertion captured in literal_values."""
    ttl = textwrap.dedent(f"""\
        @prefix ex: <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .

        ex:title a owl:DatatypeProperty .
        ex:Report a owl:NamedIndividual ;
            ex:title "Annual Report" .
    """)
    t = _load_ttl(ttl)
    rep = t.owl_individuals.get(BASE + "Report")
    assert rep is not None
    assert (BASE + "title", "Annual Report", "") in rep.literal_values


def test_literal_values_lang_tag_preserved():
    """Language tag on literal is stored as '@en' in literal_values."""
    ttl = textwrap.dedent(f"""\
        @prefix ex: <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .

        ex:description a owl:DatatypeProperty .
        ex:Page a owl:NamedIndividual ;
            ex:description "Hello"@en .
    """)
    t = _load_ttl(ttl)
    page = t.owl_individuals.get(BASE + "Page")
    assert page is not None
    assert (BASE + "description", "Hello", "@en") in page.literal_values


def test_literal_values_datatype_preserved():
    """xsd:date datatype is stored as the full datatype URI in literal_values."""
    ttl = textwrap.dedent(f"""\
        @prefix ex: <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

        ex:date a owl:DatatypeProperty .
        ex:Event a owl:NamedIndividual ;
            ex:date "2026-01-01"^^xsd:date .
    """)
    t = _load_ttl(ttl)
    ev = t.owl_individuals.get(BASE + "Event")
    assert ev is not None
    assert (BASE + "date", "2026-01-01", XSD_DATE) in ev.literal_values


def test_schema_predicates_not_in_literal_values():
    """schema:url stored in schema_urls, not in literal_values."""
    ttl = textwrap.dedent(f"""\
        @prefix ex: <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix schema: <https://schema.org/> .

        ex:Item a owl:NamedIndividual ;
            schema:url <https://example.org/page> .
    """)
    t = _load_ttl(ttl)
    item = t.owl_individuals.get(BASE + "Item")
    assert item is not None
    assert "https://schema.org/url" not in {lv[0] for lv in item.literal_values}
    assert "https://schema.org/url" not in {pv[0] for pv in item.property_values}
    assert "https://example.org/page" in item.schema_urls


# ── Store: round-trip ─────────────────────────────────────────────────────────


def test_property_values_roundtrip():
    """URI property value survives save → reload."""
    t = Taxonomy()
    t.ontology_uri = BASE.rstrip("/")
    ind = OWLIndividual(uri=BASE + "A")
    ind.property_values.append((BASE + "rel", "https://example.org/B"))
    t.owl_individuals[BASE + "A"] = ind
    t2 = _roundtrip(t)
    a2 = t2.owl_individuals.get(BASE + "A")
    assert a2 is not None
    assert (BASE + "rel", "https://example.org/B") in a2.property_values


def test_literal_values_roundtrip():
    """Literal value with lang tag survives save → reload."""
    t = Taxonomy()
    t.ontology_uri = BASE.rstrip("/")
    ind = OWLIndividual(uri=BASE + "A")
    ind.literal_values.append((BASE + "note", "hello", "@en"))
    t.owl_individuals[BASE + "A"] = ind
    t2 = _roundtrip(t)
    a2 = t2.owl_individuals.get(BASE + "A")
    assert a2 is not None
    assert (BASE + "note", "hello", "@en") in a2.literal_values


def test_literal_values_datatype_roundtrip():
    """Literal with xsd:date datatype survives save → reload."""
    t = Taxonomy()
    t.ontology_uri = BASE.rstrip("/")
    ind = OWLIndividual(uri=BASE + "A")
    ind.literal_values.append((BASE + "date", "2026-01-01", XSD_DATE))
    t.owl_individuals[BASE + "A"] = ind
    t2 = _roundtrip(t)
    a2 = t2.owl_individuals.get(BASE + "A")
    assert a2 is not None
    assert (BASE + "date", "2026-01-01", XSD_DATE) in a2.literal_values


# ── Display: all asserted values shown ───────────────────────────────────────


def _make_ind_taxonomy(ind_uri, types=None, prop_uri=None, val_uri=None, literal_vals=None):
    """Build a minimal taxonomy for display tests."""
    t = Taxonomy()
    ind = OWLIndividual(uri=ind_uri, labels=[Label("en", ind_uri.rsplit("/", 1)[-1])])
    if types:
        ind.types = list(types)
    if prop_uri and val_uri:
        ind.property_values.append((prop_uri, val_uri))
    if literal_vals:
        ind.literal_values.extend(literal_vals)
    t.owl_individuals[ind_uri] = ind
    return t


def test_display_shows_asserted_value_regardless_of_domain():
    """Property value shown even when domain doesn't match individual's type."""
    prop_uri = BASE + "rel"
    ind_uri = BASE + "Inst"
    val_uri = BASE + "Target"
    t = _make_ind_taxonomy(ind_uri, prop_uri=prop_uri, val_uri=val_uri)
    # prop has domain ClassB, individual has no type → mismatch
    t.owl_properties[prop_uri] = OWLProperty(
        uri=prop_uri, labels=[Label("en", "rel")], domains=[BASE + "ClassB"]
    )
    target = OWLIndividual(uri=val_uri, labels=[Label("en", "Target")])
    t.owl_individuals[val_uri] = target
    fields = build_individual_detail(t, ind_uri, "en")
    assert _has_prop_row(fields, "rel", "Target")


def test_display_shows_external_uri_as_raw_string():
    """External URI value (not a local individual) is shown as raw URI string."""
    prop_uri = BASE + "rel"
    ind_uri = BASE + "Inst"
    ext_uri = "https://external.org/X"
    t = _make_ind_taxonomy(ind_uri, prop_uri=prop_uri, val_uri=ext_uri)
    t.owl_properties[prop_uri] = OWLProperty(uri=prop_uri, labels=[Label("en", "rel")])
    fields = build_individual_detail(t, ind_uri, "en")
    assert _has_prop_row(fields, "rel", ext_uri)


def test_display_shows_literal_values():
    """Literal value appears in the detail panel."""
    ind_uri = BASE + "Inst"
    prop_uri = BASE + "score"
    t = _make_ind_taxonomy(ind_uri, literal_vals=[(prop_uri, "42", "")])
    t.owl_properties[prop_uri] = OWLProperty(
        uri=prop_uri, prop_type="DatatypeProperty", labels=[Label("en", "score")]
    )
    fields = build_individual_detail(t, ind_uri, "en")
    assert _has_prop_row(fields, "score", "42")


# ── Display: applicable-but-unapplied ────────────────────────────────────────


def test_display_applicable_unapplied_property_not_shown():
    """The individual page prints only what's asserted in the .ttl — an applicable but
    unasserted property is NOT shown (no more '—' placeholder rows)."""
    ind_uri = BASE + "Doc"
    prop_uri = BASE + "hasAuthor"
    t = Taxonomy()
    cls = RDFClass(uri=BASE + "Document", labels=[Label("en", "Document")])
    t.owl_classes[BASE + "Document"] = cls
    ind = OWLIndividual(uri=ind_uri, labels=[Label("en", "Doc")], types=[BASE + "Document"])
    t.owl_individuals[ind_uri] = ind
    t.owl_properties[prop_uri] = OWLProperty(
        uri=prop_uri, labels=[Label("en", "hasAuthor")], domains=[BASE + "Document"]
    )
    fields = build_individual_detail(t, ind_uri, "en")
    assert not any("hasAuthor" in f.display for f in fields)  # unasserted → absent
    assert not any(f.value == "—" for f in fields)  # no placeholder rows at all


def test_display_no_empty_placeholder_when_value_asserted():
    """Applicable property that has a value does not show an empty placeholder."""
    ind_uri = BASE + "Doc"
    val_uri = BASE + "Alice"
    prop_uri = BASE + "hasAuthor"
    t = Taxonomy()
    cls = RDFClass(uri=BASE + "Document", labels=[Label("en", "Document")])
    t.owl_classes[BASE + "Document"] = cls
    ind = OWLIndividual(
        uri=ind_uri,
        labels=[Label("en", "Doc")],
        types=[BASE + "Document"],
    )
    ind.property_values.append((prop_uri, val_uri))
    t.owl_individuals[ind_uri] = ind
    t.owl_individuals[val_uri] = OWLIndividual(uri=val_uri, labels=[Label("en", "Alice")])
    t.owl_properties[prop_uri] = OWLProperty(
        uri=prop_uri, labels=[Label("en", "hasAuthor")], domains=[BASE + "Document"]
    )
    fields = build_individual_detail(t, ind_uri, "en")
    assert _has_prop_row(fields, "hasAuthor", "Alice")
    # No empty "—" row for hasAuthor
    assert not any("hasAuthor" in f.display and f.value == "—" for f in fields)


# ── Display: schema.org conditional add actions ───────────────────────────────


def test_add_schema_url_hidden_when_url_present():
    """The '+ Add schema:url' action is hidden when schema:url is already set."""
    ind_uri = BASE + "Item"
    t = Taxonomy()
    ind = OWLIndividual(uri=ind_uri, labels=[Label("en", "Item")])
    ind.schema_urls.append("https://example.org")
    t.owl_individuals[ind_uri] = ind
    fields = build_individual_detail(t, ind_uri, "en")
    assert not _has_action(fields, "add_schema_url")


def test_add_schema_image_shown_when_no_image():
    """The '+ Add schema:image' action is shown when no schema:image is set."""
    ind_uri = BASE + "Item"
    t = Taxonomy()
    ind = OWLIndividual(uri=ind_uri, labels=[Label("en", "Item")])
    t.owl_individuals[ind_uri] = ind
    fields = build_individual_detail(t, ind_uri, "en")
    assert _has_action(fields, "add_schema_image")


# ── reworked display: editable value rows with a folded Delete ──────────────────


def _individual_with_values() -> tuple[Taxonomy, str]:
    t = Taxonomy()
    t.owl_classes[BASE + "Person"] = RDFClass(uri=BASE + "Person", labels=[Label("en", "Person")])
    alice = OWLIndividual(uri=BASE + "Alice", labels=[Label("en", "Alice")])
    t.owl_individuals[BASE + "Alice"] = alice
    rex = OWLIndividual(
        uri=BASE + "Rex",
        labels=[Label("en", "Rex")],
        types=[BASE + "Person"],
        property_values=[(BASE + "knows", BASE + "Alice")],
        literal_values=[(BASE + "age", "3", "")],
    )
    t.owl_individuals[BASE + "Rex"] = rex
    t.owl_properties[BASE + "knows"] = OWLProperty(
        uri=BASE + "knows", labels=[Label("en", "knows")]
    )
    t.owl_properties[BASE + "age"] = OWLProperty(
        uri=BASE + "age", prop_type="DatatypeProperty", labels=[Label("en", "age")]
    )
    return t, BASE + "Rex"


def test_object_value_is_an_editable_row_with_a_folded_remove() -> None:
    """An asserted object value is a single editable (✎) row carrying edit_prop_value,
    immediately followed by its remove (which folds into the row's Delete) — no separate
    '✎ Change' row."""
    t, rex = _individual_with_values()
    fields = build_individual_detail(t, rex, "en")
    i = next(i for i, f in enumerate(fields) if f.meta.get("type") == "ind_prop_val")
    row, nxt = fields[i], fields[i + 1]
    assert row.editable and row.meta["action"] == "edit_prop_value"
    assert nxt.meta["type"] == "action_del" and nxt.meta["action"] == "remove_prop_value"
    # no leftover separate change/edit action rows
    assert not any(f.meta.get("action") == "edit_prop_value" and not f.editable for f in fields)


def test_literal_value_is_an_editable_row_with_a_folded_remove() -> None:
    t, rex = _individual_with_values()
    fields = build_individual_detail(t, rex, "en")
    i = next(i for i, f in enumerate(fields) if f.meta.get("type") == "ind_lit_val")
    row, nxt = fields[i], fields[i + 1]
    assert row.editable and row.meta["action"] == "edit_literal_value"
    assert row.value == "3"  # raw value, editable as-is
    assert nxt.meta["type"] == "action_del" and nxt.meta["action"] == "remove_literal_value"


def test_no_inline_add_rows_on_the_individual_page() -> None:
    """Adding a value / class membership moved to the right-click menu — no inline '+ Add'."""
    t, rex = _individual_with_values()
    actions = {f.meta.get("action") for f in build_individual_detail(t, rex, "en")}
    assert "add_prop_value" not in actions and "add_ind_type" not in actions
