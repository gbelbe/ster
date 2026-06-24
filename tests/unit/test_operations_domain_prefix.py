"""Unit tests for editing the ontology domain and prefix with propagation/counts."""

from __future__ import annotations

from ster.model import Label, OWLIndividual, OWLProperty, RDFClass, Taxonomy

BASE = "https://www.adeo.com/ontology/kai"


def _tax(sep: str = "#", ont: str = BASE) -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = ont
    t.namespace_bindings["kai"] = ont + sep
    for name in ("Animal", "Dog"):
        u = f"{ont}{sep}{name}"
        t.owl_classes[u] = RDFClass(uri=u, labels=[Label("en", name)])
    rex = f"{ont}{sep}Rex"
    t.owl_individuals[rex] = OWLIndividual(
        uri=rex, labels=[Label("en", "Rex")], types=[f"{ont}{sep}Dog"]
    )
    p = f"{ont}{sep}hasMaster"
    t.owl_properties[p] = OWLProperty(
        uri=p, labels=[Label("en", "hasMaster")], domains=[f"{ont}{sep}Dog"]
    )
    return t


# ── domain ────────────────────────────────────────────────────────────────────


def test_ontology_domain_extracts_host():
    from ster.operations import ontology_domain

    assert ontology_domain(_tax()) == "www.adeo.com"


def test_ontology_domain_empty_when_no_ontology_uri():
    from ster.operations import ontology_domain

    t = Taxonomy()
    assert ontology_domain(t) == ""


def test_ontology_domain_empty_for_file_uri():
    from ster.operations import ontology_domain

    t = Taxonomy()
    t.ontology_uri = "file:///tmp/onto.ttl"
    assert ontology_domain(t) == ""


def test_rename_domain_swaps_host_keeps_path_and_sep():
    from ster.operations import ontology_domain, rename_ontology_domain

    t = _tax()
    rename_ontology_domain(t, "kai.adeo.com")
    assert t.ontology_uri == "https://kai.adeo.com/ontology/kai"
    assert ontology_domain(t) == "kai.adeo.com"


def test_rename_domain_propagates_to_all_entities():
    from ster.operations import rename_ontology_domain

    t = _tax()
    rename_ontology_domain(t, "kai.adeo.com")
    nb = "https://kai.adeo.com/ontology/kai#"
    assert f"{nb}Dog" in t.owl_classes
    assert f"{nb}Rex" in t.owl_individuals
    assert f"{nb}hasMaster" in t.owl_properties
    # cross-reference updated
    assert t.owl_individuals[f"{nb}Rex"].types == [f"{nb}Dog"]


def test_rename_domain_keeps_slash_separator():
    from ster.operations import rename_ontology_domain

    t = _tax(sep="/")
    rename_ontology_domain(t, "kai.adeo.com")
    assert "https://kai.adeo.com/ontology/kai/Dog" in t.owl_classes


def test_count_domain_rename_counts_all_local():
    from ster.operations import count_domain_rename_changes

    old_base, new_base, n = count_domain_rename_changes(_tax(), "kai.adeo.com")
    assert old_base == "https://www.adeo.com/ontology/kai#"
    assert new_base == "https://kai.adeo.com/ontology/kai#"
    assert n == 4  # Animal, Dog, Rex, hasMaster


def test_count_domain_rename_unchanged_is_zero():
    from ster.operations import count_domain_rename_changes

    _, _, n = count_domain_rename_changes(_tax(), "www.adeo.com")
    assert n == 0


# ── prefix ──────────────────────────────────────────────────────────────────


def test_ontology_prefix_returns_bound_prefix():
    from ster.operations import ontology_prefix

    assert ontology_prefix(_tax()) == "kai"


def test_ontology_prefix_none_when_unbound():
    from ster.operations import ontology_prefix

    t = _tax()
    t.namespace_bindings.clear()
    assert ontology_prefix(t) is None


def test_ontology_prefix_prefers_named_over_empty_default():
    """Regression: after setting a prefix, the empty ':' default stays bound to the
    same base; reading must return the named prefix, not '' (else it looks lost)."""
    from ster.operations import ontology_prefix

    t = _tax()  # "kai" already bound to BASE + "#"
    t.namespace_bindings[""] = BASE + "#"  # the default ':' rdflib keeps on save
    assert ontology_prefix(t) == "kai"


def test_set_prefix_survives_save_and_reload(tmp_path):
    """Regression (close + reopen): a prefix set then persisted reads back after load."""
    from ster import store
    from ster.operations import ontology_prefix, set_ontology_prefix

    t = _tax()
    set_ontology_prefix(t, "zoo")
    path = tmp_path / "o.ttl"
    store.save(t, path)
    assert ontology_prefix(store.load(path)) == "zoo"


def test_ontology_prefix_uses_ontology_namespace_not_scheme_base():
    """Regression: with both an owl:Ontology and a SKOS scheme whose void:uriSpace
    overrides base_uri(), the ontology prefix tracks the ontology URI's namespace
    (e.g. the auto 'ns1'), not the scheme's base."""
    from ster.model import ConceptScheme
    from ster.operations import ontology_prefix, set_ontology_prefix

    t = _tax()  # ontology_uri = BASE, "kai" bound to BASE + "#"
    # A SKOS scheme whose base_uri overrides Taxonomy.base_uri() to an unrelated value.
    t.schemes["s"] = ConceptScheme(uri="s", base_uri="test")
    assert t.base_uri() == "test"  # scheme wins for base_uri()
    assert ontology_prefix(t) == "kai"  # …but the ontology prefix follows the ontology URI
    set_ontology_prefix(t, "renamed")
    assert ontology_prefix(t) == "renamed"
    assert t.namespace_bindings.get("renamed") == BASE + "#"  # rebound on the ontology ns


def test_rename_prefix_rebinds_namespace():
    from ster.operations import rename_prefix

    t = _tax()
    rename_prefix(t, "kai", "adeo")
    assert "kai" not in t.namespace_bindings
    assert t.namespace_bindings["adeo"] == "https://www.adeo.com/ontology/kai#"


def test_rename_prefix_keeps_entity_uris():
    from ster.operations import rename_prefix

    t = _tax()
    before = set(t.owl_classes)
    rename_prefix(t, "kai", "adeo")
    assert set(t.owl_classes) == before  # URIs are identity — unchanged


def test_rename_prefix_returns_use_count():
    from ster.operations import rename_prefix

    # 4 local entities serialize under the renamed prefix
    assert rename_prefix(_tax(), "kai", "adeo") == 4


def test_rename_prefix_unknown_old_is_noop():
    from ster.operations import rename_prefix

    t = _tax()
    assert rename_prefix(t, "nope", "adeo") == 0
    assert "kai" in t.namespace_bindings
    assert "adeo" not in t.namespace_bindings


def test_count_prefix_uses_counts_entities_under_ns():
    from ster.operations import count_prefix_uses

    assert count_prefix_uses(_tax(), "kai") == 4


# ── validators ────────────────────────────────────────────────────────────────


def test_validate_domain_accepts_bare_host():
    from ster.operations import validate_domain

    assert validate_domain("kai.adeo.com") is None


def test_validate_domain_rejects_empty_space_and_scheme():
    from ster.operations import validate_domain

    assert validate_domain("") is not None
    assert validate_domain("a b") is not None
    assert validate_domain("https://kai.adeo.com") is not None
    assert validate_domain("kai.adeo.com/x") is not None


def test_validate_prefix_accepts_valid_and_rejects_bad():
    from ster.operations import validate_prefix

    assert validate_prefix("kai") is None
    assert validate_prefix("adeo-kg") is None
    assert validate_prefix("") is not None
    assert validate_prefix("1bad") is not None
    assert validate_prefix("has space") is not None
