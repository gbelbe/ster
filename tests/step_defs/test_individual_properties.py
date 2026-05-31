"""BDD step definitions for tests/features/owl/individual_properties.feature."""

from __future__ import annotations

import textwrap
from io import BytesIO

import pytest
from pytest_bdd import given, parsers, scenarios, then, when
from rdflib import Graph

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy
from ster.nav.logic import build_individual_detail
from ster.store import graph_to_taxonomy, taxonomy_to_graph

scenarios("../features/owl/individual_properties.feature")

BASE = "https://example.org/onto/"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
SCHEMA = "https://schema.org/"


@pytest.fixture
def ctx():
    return {}


def _load_ttl(ttl: str) -> Taxonomy:
    g = Graph()
    g.parse(BytesIO(ttl.encode()), format="turtle")
    return graph_to_taxonomy(g)


def _roundtrip(taxonomy: Taxonomy) -> Taxonomy:
    g = taxonomy_to_graph(taxonomy)
    return graph_to_taxonomy(g)


# ── Given: TTL-based scenarios ────────────────────────────────────────────────


@given(
    parsers.parse(
        'a taxonomy with individual "{ind}" having ObjectProperty "{prop}" pointing to external URI "{ext_uri}"'
    )
)
def given_ind_obj_prop_external(ctx, ind, prop, ext_uri):
    ttl = textwrap.dedent(f"""\
        @prefix ex: <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        ex:{prop} a owl:ObjectProperty .
        ex:{ind} a owl:NamedIndividual ;
            ex:{prop} <{ext_uri}> .
    """)
    ctx["ttl"] = ttl
    ctx["ind_uri"] = BASE + ind
    ctx["prop_uri"] = BASE + prop
    ctx["val_uri"] = ext_uri


@given(
    parsers.parse(
        'a taxonomy TTL with individual "{ind}" having undeclared predicate "{pred}" pointing to "{val_uri}"'
    )
)
def given_ind_undeclared_pred(ctx, ind, pred, val_uri):
    ttl = textwrap.dedent(f"""\
        @prefix ex: <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        ex:{ind} a owl:NamedIndividual ;
            ex:{pred} <{val_uri}> .
    """)
    ctx["ttl"] = ttl
    ctx["ind_uri"] = BASE + ind
    ctx["prop_uri"] = BASE + pred
    ctx["val_uri"] = val_uri


@given(parsers.parse('a taxonomy TTL with individual "{ind}" having rdfs:label "{lbl}"'))
def given_ind_rdfs_label(ctx, ind, lbl):
    ttl = textwrap.dedent(f"""\
        @prefix ex: <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        ex:{ind} a owl:NamedIndividual ;
            rdfs:label "{lbl}" .
    """)
    ctx["ttl"] = ttl
    ctx["ind_uri"] = BASE + ind
    ctx["pred_uri"] = RDFS + "label"


@given(parsers.parse('a taxonomy TTL with individual "{ind}" typed as class "{cls}"'))
def given_ind_typed(ctx, ind, cls):
    ttl = textwrap.dedent(f"""\
        @prefix ex: <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        ex:{cls} a owl:Class .
        ex:{ind} a owl:NamedIndividual, ex:{cls} .
    """)
    ctx["ttl"] = ttl
    ctx["ind_uri"] = BASE + ind
    ctx["pred_uri"] = RDF_NS + "type"


@given(parsers.parse('a taxonomy TTL with individual "{ind}" having schema:url "{url}"'))
def given_ind_schema_url(ctx, ind, url):
    ttl = textwrap.dedent(f"""\
        @prefix ex: <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix schema: <https://schema.org/> .
        ex:{ind} a owl:NamedIndividual ;
            schema:url <{url}> .
    """)
    ctx["ttl"] = ttl
    ctx["ind_uri"] = BASE + ind
    ctx["pred_uri"] = SCHEMA + "url"


@given(
    parsers.parse(
        'a taxonomy with individual "{ind}" having DatatypeProperty "{prop}" with literal value "{val}"'
    )
)
def given_ind_dt_plain(ctx, ind, prop, val):
    ttl = textwrap.dedent(f"""\
        @prefix ex: <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        ex:{prop} a owl:DatatypeProperty .
        ex:{ind} a owl:NamedIndividual ;
            ex:{prop} "{val}" .
    """)
    ctx["ttl"] = ttl
    ctx["ind_uri"] = BASE + ind
    ctx["prop_uri"] = BASE + prop
    ctx["lit_val"] = val
    ctx["lit_lang_dt"] = ""


@given(
    parsers.parse(
        'a taxonomy with individual "{ind}" having DatatypeProperty "{prop}" with literal "{val}"@en'
    )
)
def given_ind_dt_lang(ctx, ind, prop, val):
    ttl = textwrap.dedent(f"""\
        @prefix ex: <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        ex:{prop} a owl:DatatypeProperty .
        ex:{ind} a owl:NamedIndividual ;
            ex:{prop} "{val}"@en .
    """)
    ctx["ttl"] = ttl
    ctx["ind_uri"] = BASE + ind
    ctx["prop_uri"] = BASE + prop
    ctx["lit_val"] = val
    ctx["lit_lang_dt"] = "@en"


@given(
    parsers.parse(
        'a taxonomy with individual "{ind}" having DatatypeProperty "{prop}" with literal "{val}"^^xsd:date'
    )
)
def given_ind_dt_date(ctx, ind, prop, val):
    ttl = textwrap.dedent(f"""\
        @prefix ex: <{BASE}> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        ex:{prop} a owl:DatatypeProperty .
        ex:{ind} a owl:NamedIndividual ;
            ex:{prop} "{val}"^^xsd:date .
    """)
    ctx["ttl"] = ttl
    ctx["ind_uri"] = BASE + ind
    ctx["prop_uri"] = BASE + prop
    ctx["lit_val"] = val
    ctx["lit_lang_dt"] = XSD + "date"


@given(
    parsers.parse(
        'an in-memory taxonomy with individual "{ind}" having property_value ("{prop}", "{val}")'
    )
)
def given_inmem_prop_val(ctx, ind, prop, val):
    t = Taxonomy()
    t.ontology_uri = BASE.rstrip("/")
    ind_obj = OWLIndividual(uri=BASE + ind, labels=[Label("en", ind)])
    ind_obj.property_values.append((BASE + prop, val))
    t.owl_individuals[BASE + ind] = ind_obj
    ctx["taxonomy"] = t
    ctx["ind_uri"] = BASE + ind
    ctx["prop_uri"] = BASE + prop
    ctx["val_uri"] = val


@given(
    parsers.parse(
        'an in-memory taxonomy with individual "{ind}" having literal_value ("{prop}", "{val}", "{lang_dt}")'
    )
)
def given_inmem_literal_val(ctx, ind, prop, val, lang_dt):
    t = Taxonomy()
    t.ontology_uri = BASE.rstrip("/")
    ind_obj = OWLIndividual(uri=BASE + ind, labels=[Label("en", ind)])
    ind_obj.literal_values.append((BASE + prop, val, lang_dt))
    t.owl_individuals[BASE + ind] = ind_obj
    ctx["taxonomy"] = t
    ctx["ind_uri"] = BASE + ind
    ctx["prop_uri"] = BASE + prop
    ctx["lit_val"] = val
    ctx["lit_lang_dt"] = lang_dt


# ── Given: display scenarios ──────────────────────────────────────────────────


@given(
    parsers.parse(
        'a taxonomy with individual "{ind}" of class "{cls}" having property "{prop}" with domain "{dom}" pointing to individual "{target}"'
    )
)
def given_ind_with_mismatch_domain(ctx, ind, cls, prop, dom, target):
    t = Taxonomy()
    t.owl_classes[BASE + cls] = RDFClass(uri=BASE + cls, labels=[Label("en", cls)])
    t.owl_classes[BASE + dom] = RDFClass(uri=BASE + dom, labels=[Label("en", dom)])
    ind_obj = OWLIndividual(uri=BASE + ind, labels=[Label("en", ind)], types=[BASE + cls])
    ind_obj.property_values.append((BASE + prop, BASE + target))
    t.owl_individuals[BASE + ind] = ind_obj
    t.owl_individuals[BASE + target] = OWLIndividual(
        uri=BASE + target, labels=[Label("en", target)]
    )
    t.owl_properties[BASE + prop] = OWLProperty(
        uri=BASE + prop, labels=[Label("en", prop)], domains=[BASE + dom]
    )
    ctx["taxonomy"] = t
    ctx["ind_uri"] = BASE + ind
    ctx["prop_lbl"] = prop
    ctx["val_lbl"] = target


@given(
    parsers.parse(
        'a taxonomy with individual "{ind}" having property "{prop}" pointing to external URI "{ext_uri}"'
    )
)
def given_ind_ext_uri_display(ctx, ind, prop, ext_uri):
    t = Taxonomy()
    ind_obj = OWLIndividual(uri=BASE + ind, labels=[Label("en", ind)])
    ind_obj.property_values.append((BASE + prop, ext_uri))
    t.owl_individuals[BASE + ind] = ind_obj
    t.owl_properties[BASE + prop] = OWLProperty(uri=BASE + prop, labels=[Label("en", prop)])
    ctx["taxonomy"] = t
    ctx["ind_uri"] = BASE + ind
    ctx["prop_lbl"] = prop
    ctx["val_lbl"] = ext_uri


@given(
    parsers.parse('a taxonomy with individual "{ind}" having literal_value ("{prop}", "{val}", "")')
)
def given_ind_literal_display(ctx, ind, prop, val):
    t = Taxonomy()
    ind_obj = OWLIndividual(uri=BASE + ind, labels=[Label("en", ind)])
    ind_obj.literal_values.append((BASE + prop, val, ""))
    t.owl_individuals[BASE + ind] = ind_obj
    t.owl_properties[BASE + prop] = OWLProperty(
        uri=BASE + prop, prop_type="DatatypeProperty", labels=[Label("en", prop)]
    )
    ctx["taxonomy"] = t
    ctx["ind_uri"] = BASE + ind
    ctx["prop_lbl"] = prop
    ctx["val_lbl"] = val


@given(
    parsers.parse(
        'a taxonomy with individual "{ind}" of class "{cls}" with applicable property "{prop}" and no asserted value'
    )
)
def given_ind_applicable_no_value(ctx, ind, cls, prop):
    t = Taxonomy()
    t.owl_classes[BASE + cls] = RDFClass(uri=BASE + cls, labels=[Label("en", cls)])
    ind_obj = OWLIndividual(uri=BASE + ind, labels=[Label("en", ind)], types=[BASE + cls])
    t.owl_individuals[BASE + ind] = ind_obj
    t.owl_properties[BASE + prop] = OWLProperty(
        uri=BASE + prop, labels=[Label("en", prop)], domains=[BASE + cls]
    )
    ctx["taxonomy"] = t
    ctx["ind_uri"] = BASE + ind
    ctx["prop_lbl"] = prop


@given(
    parsers.parse(
        'a taxonomy with individual "{ind}" of class "{cls}" having property "{prop}" pointing to individual "{target}"'
    )
)
def given_ind_applicable_with_value(ctx, ind, cls, prop, target):
    t = Taxonomy()
    t.owl_classes[BASE + cls] = RDFClass(uri=BASE + cls, labels=[Label("en", cls)])
    ind_obj = OWLIndividual(uri=BASE + ind, labels=[Label("en", ind)], types=[BASE + cls])
    ind_obj.property_values.append((BASE + prop, BASE + target))
    t.owl_individuals[BASE + ind] = ind_obj
    t.owl_individuals[BASE + target] = OWLIndividual(
        uri=BASE + target, labels=[Label("en", target)]
    )
    t.owl_properties[BASE + prop] = OWLProperty(
        uri=BASE + prop, labels=[Label("en", prop)], domains=[BASE + cls]
    )
    ctx["taxonomy"] = t
    ctx["ind_uri"] = BASE + ind
    ctx["prop_lbl"] = prop
    ctx["val_lbl"] = target


@given(parsers.parse('a taxonomy with individual "{ind}" having schema:url "{url}"'))
def given_ind_schema_url_display(ctx, ind, url):
    t = Taxonomy()
    ind_obj = OWLIndividual(uri=BASE + ind, labels=[Label("en", ind)])
    ind_obj.schema_urls.append(url)
    t.owl_individuals[BASE + ind] = ind_obj
    ctx["taxonomy"] = t
    ctx["ind_uri"] = BASE + ind


@given(parsers.parse('a taxonomy with individual "{ind}" having no schema:image'))
def given_ind_no_schema_image(ctx, ind):
    t = Taxonomy()
    ind_obj = OWLIndividual(uri=BASE + ind, labels=[Label("en", ind)])
    t.owl_individuals[BASE + ind] = ind_obj
    ctx["taxonomy"] = t
    ctx["ind_uri"] = BASE + ind


# ── When steps ────────────────────────────────────────────────────────────────


@when("I load the taxonomy from TTL")
def when_load_ttl(ctx):
    ctx["taxonomy"] = _load_ttl(ctx["ttl"])


@when("I save and reload the taxonomy")
def when_roundtrip(ctx):
    ctx["taxonomy"] = _roundtrip(ctx["taxonomy"])


@when(parsers.parse('I build the individual detail for "{ind}"'))
def when_build_detail(ctx, ind):
    ctx["fields"] = build_individual_detail(ctx["taxonomy"], BASE + ind, "en")


@when('I build the individual detail for "Inst"')
def when_build_detail_inst(ctx):
    ctx["fields"] = build_individual_detail(ctx["taxonomy"], ctx["ind_uri"], "en")


@when('I build the individual detail for "Item"')
def when_build_detail_item(ctx):
    ctx["fields"] = build_individual_detail(ctx["taxonomy"], ctx["ind_uri"], "en")


@when('I build the individual detail for "Doc"')
def when_build_detail_doc(ctx):
    ctx["fields"] = build_individual_detail(ctx["taxonomy"], ctx["ind_uri"], "en")


# ── Then steps ────────────────────────────────────────────────────────────────


@then(parsers.parse('individual "{ind}" has property_value ("{prop}", "{val}")'))
def then_has_property_value(ctx, ind, prop, val):
    t = ctx["taxonomy"]
    # resolve prop: may be a local name or full URI
    prop_uri = BASE + prop if "://" not in prop else prop
    val_uri = val
    ind_uri = BASE + ind
    individual = t.owl_individuals.get(ind_uri)
    assert individual is not None, f"Individual {ind_uri} not found"
    assert (prop_uri, val_uri) in individual.property_values, (
        f"Expected ({prop_uri}, {val_uri}) in property_values, got {individual.property_values}"
    )


@then(parsers.parse('individual "{ind}" has no property_value with predicate "{pred}"'))
def then_no_property_value_with_pred(ctx, ind, pred):
    t = ctx["taxonomy"]
    ind_uri = BASE + ind
    individual = t.owl_individuals.get(ind_uri)
    assert individual is not None
    pred_uris = {pv[0] for pv in individual.property_values} | {
        lv[0] for lv in individual.literal_values
    }
    # resolve common prefixes
    full_pred = ctx.get("pred_uri", pred)
    assert full_pred not in pred_uris, f"Predicate {full_pred} found unexpectedly in assertions"


@then(
    parsers.re(
        r'individual "(?P<ind>[^"]+)" has literal_value \("(?P<prop>[^"]+)", "(?P<val>[^"]*)", "(?P<lang_dt>[^"]*)"\)'
    )
)
def then_has_literal_value(ctx, ind, prop, val, lang_dt):
    t = ctx["taxonomy"]
    prop_uri = BASE + prop if "://" not in prop else prop
    ind_uri = BASE + ind
    individual = t.owl_individuals.get(ind_uri)
    assert individual is not None, f"Individual {ind_uri} not found"
    assert (prop_uri, val, lang_dt) in individual.literal_values, (
        f"Expected ({prop_uri}, {val!r}, {lang_dt!r}) in literal_values, got {individual.literal_values}"
    )


@then(
    parsers.parse(
        'the detail panel contains a property row for "{prop_lbl}" with value "{val_lbl}"'
    )
)
def then_has_prop_row(ctx, prop_lbl, val_lbl):
    fields = ctx["fields"]
    found = any(prop_lbl in f.display and val_lbl in f.value for f in fields)
    assert found, (
        f"No field with display containing '{prop_lbl}' and value containing '{val_lbl}'.\n"
        f"Fields: {[(f.display, f.value) for f in fields]}"
    )


@then(parsers.parse('the detail panel contains an empty placeholder row for "{prop_lbl}"'))
def then_has_placeholder_row(ctx, prop_lbl):
    fields = ctx["fields"]
    found = any(prop_lbl in f.display and f.value == "—" for f in fields)
    assert found, (
        f"No empty placeholder row for '{prop_lbl}'.\n"
        f"Fields: {[(f.display, f.value) for f in fields]}"
    )


@then(parsers.parse('the detail panel does not contain an empty placeholder row for "{prop_lbl}"'))
def then_no_placeholder_row(ctx, prop_lbl):
    fields = ctx["fields"]
    found = any(prop_lbl in f.display and f.value == "—" for f in fields)
    assert not found, f"Unexpected empty placeholder row for '{prop_lbl}'"


@then(parsers.parse('the detail panel does not contain an "{action_name}" action'))
def then_no_action(ctx, action_name):
    fields = ctx["fields"]
    found = any(f.meta.get("action") == action_name for f in fields)
    assert not found, f"Unexpected action '{action_name}' found in panel"


@then(parsers.parse('the detail panel contains an "{action_name}" action'))
def then_has_action(ctx, action_name):
    fields = ctx["fields"]
    found = any(f.meta.get("action") == action_name for f in fields)
    assert found, (
        f"Action '{action_name}' not found in panel.\n"
        f"Actions present: {[f.meta.get('action') for f in fields if f.meta.get('action')]}"
    )
