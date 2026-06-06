"""Unit tests for adding a datatype/object property to a class (with datatype choice)."""

from __future__ import annotations

from ster.model import Label, OWLIndividual, RDFClass, Taxonomy

XSD = "http://www.w3.org/2001/XMLSchema#"
BASE = "https://ex.org/onto"


def _tax() -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = BASE
    t.owl_classes[f"{BASE}#Paper"] = RDFClass(uri=f"{BASE}#Paper", labels=[Label("en", "Paper")])
    return t


# ── SUPPORTED_DATATYPES ───────────────────────────────────────────────────────


def test_supported_datatypes_has_common_xsd_types():
    from ster.operations import SUPPORTED_DATATYPES

    uris = {uri for _label, uri in SUPPORTED_DATATYPES}
    for t in ("string", "anyURI", "integer", "decimal", "boolean", "date", "dateTime"):
        assert XSD + t in uris


def test_supported_datatypes_all_full_xsd_uris():
    from ster.operations import SUPPORTED_DATATYPES

    assert SUPPORTED_DATATYPES  # non-empty
    assert all(uri.startswith(XSD) for _label, uri in SUPPORTED_DATATYPES)


# ── advance_property_create (pure state-machine transition) ───────────────────


def test_advance_kind_attribute_goes_to_datatype_picker():
    from ster.operations import advance_property_create

    assert advance_property_create("kind", 0) == ("datatype", None, None)


def test_advance_kind_relationship_creates_object_property():
    from ster.operations import advance_property_create

    assert advance_property_create("kind", 1) == ("create", "ObjectProperty", None)


def test_advance_datatype_creates_datatype_property_with_range():
    from ster.operations import SUPPORTED_DATATYPES, advance_property_create

    nxt, ptype, rng = advance_property_create("datatype", 0)
    assert nxt == "create"
    assert ptype == "DatatypeProperty"
    assert rng == SUPPORTED_DATATYPES[0][1]


# ── creating an attribute (datatype property) at the class ────────────────────


def test_add_datatype_property_sets_type_domain_range():
    from ster.operations import add_owl_property

    t = _tax()
    prop = add_owl_property(
        t, f"{BASE}#year", "DatatypeProperty", "year", "en", f"{BASE}#Paper", XSD + "integer"
    )
    assert prop.prop_type == "DatatypeProperty"
    assert prop.domains == [f"{BASE}#Paper"]
    assert prop.ranges == [XSD + "integer"]


def test_new_datatype_prop_is_direct_property_of_class():
    from ster.nav.logic import _direct_properties
    from ster.operations import add_owl_property

    t = _tax()
    add_owl_property(
        t, f"{BASE}#year", "DatatypeProperty", "year", "en", f"{BASE}#Paper", XSD + "integer"
    )
    direct = {p.uri for p in _direct_properties(t, f"{BASE}#Paper")}
    assert f"{BASE}#year" in direct


def test_new_datatype_prop_applicable_on_individual_of_class():
    from ster.nav.logic import build_individual_detail
    from ster.operations import add_owl_property

    t = _tax()
    ind = f"{BASE}#MyPaper"
    t.owl_individuals[ind] = OWLIndividual(uri=ind, types=[f"{BASE}#Paper"])
    add_owl_property(
        t, f"{BASE}#year", "DatatypeProperty", "year", "en", f"{BASE}#Paper", XSD + "integer"
    )
    fields = build_individual_detail(t, ind, "en")
    # the new datatype property is offered as an applicable (unapplied) row
    assert any(f"{BASE}#year" in (fld.key or "") for fld in fields)


def test_add_object_property_relationship_regression():
    from ster.operations import add_owl_property

    t = _tax()
    prop = add_owl_property(t, f"{BASE}#cites", "ObjectProperty", "cites", "en", f"{BASE}#Paper")
    assert prop.prop_type == "ObjectProperty"
    assert prop.domains == [f"{BASE}#Paper"]
    assert prop.ranges == []


# ── class panel surfaces the kind/datatype action rows ────────────────────────


def test_class_panel_offers_relationship_and_each_datatype():
    from ster.nav.logic import build_rdf_class_detail
    from ster.operations import SUPPORTED_DATATYPES

    fields = build_rdf_class_detail(_tax(), f"{BASE}#Paper", "en")
    adds = [f.meta for f in fields if f.meta.get("action") == "add_class_property"]
    # one relationship row + one row per supported datatype
    assert any(m.get("prop_type") == "ObjectProperty" for m in adds)
    dt_ranges = {m.get("range_uri") for m in adds if m.get("prop_type") == "DatatypeProperty"}
    assert dt_ranges == {uri for _label, uri in SUPPORTED_DATATYPES}


# ── viewer wiring: action dispatch → URI prompt → commit creates the property ──


def _viewer(tmp_path):
    from ster import store
    from ster.nav.viewer import TaxonomyViewer

    t = _tax()
    f = tmp_path / "o.ttl"
    store.save(t, f)
    return TaxonomyViewer(t, f, lang="en")


def test_add_class_property_action_carries_type_and_range(tmp_path):
    from ster.nav.state import EditState

    v = _viewer(tmp_path)
    v._trigger_action(
        "add_class_property",
        {"class_uri": f"{BASE}#Paper", "prop_type": "DatatypeProperty", "range_uri": XSD + "date"},
    )
    assert isinstance(v._state, EditState)
    assert v._state.field is not None
    assert v._state.field.meta["prop_type"] == "DatatypeProperty"
    assert v._state.field.meta["range_uri"] == XSD + "date"
    assert v._state.field.meta["class_uri"] == f"{BASE}#Paper"


def test_commit_new_class_property_creates_datatype_with_range(tmp_path):
    from ster.nav.logic import DetailField
    from ster.nav.state import EditState

    v = _viewer(tmp_path)
    new_uri = f"{BASE}#year"
    fld = DetailField(
        "new:owl_class_property",
        "New property URI",
        new_uri,
        editable=True,
        meta={
            "type": "new_owl_class_property_uri",
            "class_uri": f"{BASE}#Paper",
            "prop_type": "DatatypeProperty",
            "range_uri": XSD + "integer",
        },
    )
    v._state = EditState(buffer=new_uri, pos=len(new_uri), field=fld, return_to=None)
    v._commit_edit()
    prop = v.taxonomy.owl_properties[new_uri]
    assert prop.prop_type == "DatatypeProperty"
    assert prop.domains == [f"{BASE}#Paper"]
    assert prop.ranges == [XSD + "integer"]
