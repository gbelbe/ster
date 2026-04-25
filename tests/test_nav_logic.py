"""Tests for ster/nav_logic.py — pure tree/detail logic, no curses."""

from __future__ import annotations

from ster.handles import assign_handles
from ster.model import (
    Concept,
    ConceptScheme,
    Label,
    LabelType,
    Taxonomy,
)
from ster.nav.logic import (
    _available_langs,
    _breadcrumb,
    _children,
    _count_descendants,
    _flatten_taxonomy,
    _parent_uri,
    build_detail_fields,
    build_scheme_fields,
    flatten_tree,
)
from ster.workspace import TaxonomyWorkspace

BASE = "https://example.org/test/"


# ── _count_descendants ────────────────────────────────────────────────────────


def test_count_descendants_leaf(simple_taxonomy):
    assert _count_descendants(simple_taxonomy, BASE + "Child2") == 0


def test_count_descendants_one_level(simple_taxonomy):
    # Child1 has one child: Grandchild
    assert _count_descendants(simple_taxonomy, BASE + "Child1") == 1


def test_count_descendants_top(simple_taxonomy):
    # Top -> Child1 -> Grandchild, Top -> Child2 = 3
    assert _count_descendants(simple_taxonomy, BASE + "Top") == 3


def test_count_descendants_missing(simple_taxonomy):
    assert _count_descendants(simple_taxonomy, BASE + "Nonexistent") == 0


# ── flatten_tree (single taxonomy) ───────────────────────────────────────────


def test_flatten_tree_returns_scheme_and_concepts(simple_taxonomy):
    lines = flatten_tree(simple_taxonomy)
    uris = [l.uri for l in lines]
    assert BASE + "Scheme" in uris
    assert BASE + "Top" in uris
    assert BASE + "Child1" in uris
    assert BASE + "Child2" in uris
    assert BASE + "Grandchild" in uris


def test_flatten_tree_scheme_first(simple_taxonomy):
    lines = flatten_tree(simple_taxonomy)
    assert lines[0].is_scheme
    assert lines[0].uri == BASE + "Scheme"


def test_flatten_tree_folded_scheme(simple_taxonomy):
    folded = {BASE + "Scheme"}
    lines = flatten_tree(simple_taxonomy, folded=folded)
    uris = [l.uri for l in lines]
    # Only scheme row should be present when scheme is folded
    assert BASE + "Scheme" in uris
    assert BASE + "Top" not in uris
    scheme_line = next(l for l in lines if l.is_scheme)
    assert scheme_line.is_folded is True
    assert scheme_line.hidden_count > 0


def test_flatten_tree_folded_concept(simple_taxonomy):
    folded = {BASE + "Top"}
    lines = flatten_tree(simple_taxonomy, folded=folded)
    uris = [l.uri for l in lines]
    assert BASE + "Top" in uris
    assert BASE + "Child1" not in uris
    top_line = next(l for l in lines if l.uri == BASE + "Top")
    assert top_line.is_folded is True


# ── _flatten_taxonomy ─────────────────────────────────────────────────────────


def test_flatten_taxonomy_with_depth_offset(simple_taxonomy, tmp_path):
    fp = tmp_path / "a.ttl"
    lines = _flatten_taxonomy(
        simple_taxonomy,
        file_path=fp,
        scheme_depth=1,
        scheme_prefix="    ",
        concept_base_depth=1,
    )
    scheme_line = next(l for l in lines if l.is_scheme)
    assert scheme_line.depth == 1
    assert scheme_line.prefix == "    "
    assert scheme_line.file_path == fp


# ── flatten_tree (workspace) ──────────────────────────────────────────────────


def test_flatten_tree_single_file_workspace(simple_taxonomy, tmp_path):
    fp = tmp_path / "a.ttl"
    ws = TaxonomyWorkspace({fp: simple_taxonomy})
    lines = flatten_tree(ws)
    # Single-file workspace: no file node
    assert not any(l.is_file for l in lines)
    assert any(l.is_scheme for l in lines)


def test_flatten_tree_multi_file_workspace(simple_taxonomy, tmp_path):
    fp1 = tmp_path / "a.ttl"
    fp2 = tmp_path / "b.ttl"

    # Build a second minimal taxonomy
    t2 = Taxonomy()
    s2 = ConceptScheme(uri=BASE + "S2", labels=[Label("en", "Second")])
    c2 = Concept(uri=BASE + "X", labels=[Label("en", "X", LabelType.PREF)])
    t2.schemes[s2.uri] = s2
    t2.concepts[c2.uri] = c2
    s2.top_concepts = [c2.uri]
    assign_handles(t2)

    ws = TaxonomyWorkspace({fp1: simple_taxonomy, fp2: t2})
    lines = flatten_tree(ws)
    file_lines = [l for l in lines if l.is_file]
    assert len(file_lines) == 2
    assert file_lines[0].file_path == fp1
    assert file_lines[1].file_path == fp2


def test_flatten_tree_multi_file_folded_file(simple_taxonomy, tmp_path):
    fp1 = tmp_path / "a.ttl"
    fp2 = tmp_path / "b.ttl"

    t2 = Taxonomy()
    s2 = ConceptScheme(uri=BASE + "S2", labels=[Label("en", "Second")])
    t2.schemes[s2.uri] = s2
    assign_handles(t2)

    from ster.nav.logic import _file_sentinel

    ws = TaxonomyWorkspace({fp1: simple_taxonomy, fp2: t2})
    folded = {_file_sentinel(fp1)}
    lines = flatten_tree(ws, folded=folded)
    file_line = next(l for l in lines if l.is_file and l.file_path == fp1)
    assert file_line.is_folded is True
    # No scheme/concept rows from fp1 should appear
    assert not any(l.file_path == fp1 and not l.is_file for l in lines)


# ── _children ─────────────────────────────────────────────────────────────────


def test_children_root(simple_taxonomy):
    kids = _children(simple_taxonomy, None)
    assert BASE + "Top" in kids


def test_children_concept(simple_taxonomy):
    kids = _children(simple_taxonomy, BASE + "Top")
    assert BASE + "Child1" in kids
    assert BASE + "Child2" in kids


def test_children_leaf(simple_taxonomy):
    assert _children(simple_taxonomy, BASE + "Child2") == []


def test_children_missing_uri(simple_taxonomy):
    assert _children(simple_taxonomy, BASE + "Nonexistent") == []


# ── _parent_uri ───────────────────────────────────────────────────────────────


def test_parent_uri_at_root(simple_taxonomy):
    assert _parent_uri(simple_taxonomy, None) is None


def test_parent_uri_top_concept(simple_taxonomy):
    assert _parent_uri(simple_taxonomy, BASE + "Top") is None


def test_parent_uri_child(simple_taxonomy):
    assert _parent_uri(simple_taxonomy, BASE + "Child1") == BASE + "Top"


def test_parent_uri_grandchild(simple_taxonomy):
    assert _parent_uri(simple_taxonomy, BASE + "Grandchild") == BASE + "Child1"


# ── _breadcrumb ───────────────────────────────────────────────────────────────


def test_breadcrumb_root(simple_taxonomy):
    assert _breadcrumb(simple_taxonomy, None) == "/"


def test_breadcrumb_top(simple_taxonomy):
    bc = _breadcrumb(simple_taxonomy, BASE + "Top")
    assert bc.startswith("/")
    assert "[" in bc  # handle notation


def test_breadcrumb_grandchild(simple_taxonomy):
    bc = _breadcrumb(simple_taxonomy, BASE + "Grandchild")
    # Should contain multiple path segments
    assert bc.count("[") >= 3


# ── build_detail_fields ───────────────────────────────────────────────────────


def test_build_detail_fields_missing_uri(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Nonexistent", "en")
    assert fields == []


def test_build_detail_fields_has_uri_field(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    uri_fields = [f for f in fields if f.key == "uri"]
    assert len(uri_fields) == 1
    assert uri_fields[0].value == BASE + "Top"
    assert uri_fields[0].editable is False


def test_build_detail_fields_pref_labels(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    pref_fields = [f for f in fields if f.key.startswith("pref:")]
    assert len(pref_fields) >= 1
    en_field = next(f for f in pref_fields if f.key == "pref:en")
    assert en_field.value == "Top Concept"
    assert en_field.editable is True


def test_build_detail_fields_alt_labels(taxonomy):
    """Use the disk-loaded taxonomy which has altLabel on Child2."""
    fields = build_detail_fields(taxonomy, BASE + "Child2", "en")
    alt_fields = [f for f in fields if f.key.startswith("alt:")]
    assert len(alt_fields) >= 1
    assert alt_fields[0].value == "Second child"


def test_build_detail_fields_definition(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    def_fields = [f for f in fields if f.key.startswith("def:")]
    assert len(def_fields) == 1
    assert def_fields[0].value == "The root."


def test_build_detail_fields_hierarchy_narrower(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    narrower_fields = [f for f in fields if f.key.startswith("narrower:")]
    assert len(narrower_fields) == 2  # Child1, Child2


def test_build_detail_fields_hierarchy_broader(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Child1", "en")
    broader_fields = [f for f in fields if f.key.startswith("broader:")]
    assert len(broader_fields) == 1
    assert BASE + "Top" in broader_fields[0].key


def test_build_detail_fields_actions_present(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    action_fields = [f for f in fields if f.meta.get("type") == "action"]
    action_names = [f.meta.get("action") for f in action_fields]
    assert "add_narrower" in action_names
    assert "delete" in action_names


def test_build_detail_fields_show_mappings(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en", show_mappings=True)
    map_actions = [f for f in fields if f.meta.get("action", "").startswith("map:")]
    assert len(map_actions) >= 1


def test_build_detail_fields_no_mappings_by_default(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en", show_mappings=False)
    map_actions = [f for f in fields if f.meta.get("action", "").startswith("map:")]
    assert len(map_actions) == 0


def test_build_detail_fields_separators(simple_taxonomy):
    fields = build_detail_fields(simple_taxonomy, BASE + "Top", "en")
    sep_fields = [f for f in fields if f.meta.get("type") == "separator"]
    labels = [f.display for f in sep_fields]
    assert "Identity" in labels
    assert "Labels" in labels


# ── build_scheme_fields ───────────────────────────────────────────────────────


def test_build_scheme_fields_no_scheme():
    t = Taxonomy()
    fields = build_scheme_fields(t, "en")
    assert fields == []


def test_build_scheme_fields_has_uri(simple_taxonomy):
    fields = build_scheme_fields(simple_taxonomy, "en")
    uri_fields = [f for f in fields if f.key == "scheme_uri"]
    assert len(uri_fields) == 1
    assert uri_fields[0].value == BASE + "Scheme"


def test_build_scheme_fields_display_lang(simple_taxonomy):
    fields = build_scheme_fields(simple_taxonomy, "fr")
    lang_field = next(f for f in fields if f.key == "display_lang")
    assert lang_field.value == "fr"


def test_build_scheme_fields_title(simple_taxonomy):
    fields = build_scheme_fields(simple_taxonomy, "en")
    title_fields = [f for f in fields if f.key.startswith("title:")]
    assert len(title_fields) >= 1


def test_build_scheme_fields_creator(simple_taxonomy):
    fields = build_scheme_fields(simple_taxonomy, "en")
    creator_fields = [f for f in fields if f.key == "creator"]
    assert len(creator_fields) == 1
    assert creator_fields[0].editable is True


def test_build_scheme_fields_explicit_scheme_uri(simple_taxonomy):
    fields = build_scheme_fields(simple_taxonomy, "en", scheme_uri=BASE + "Scheme")
    assert fields  # Should return fields for the specified scheme


def test_build_scheme_fields_missing_scheme_uri(simple_taxonomy):
    fields = build_scheme_fields(simple_taxonomy, "en", scheme_uri=BASE + "Nonexistent")
    assert fields == []


# ── _available_langs ──────────────────────────────────────────────────────────


def test_available_langs_basic(simple_taxonomy):
    langs = _available_langs(simple_taxonomy)
    assert "en" in langs
    assert "fr" in langs
    assert langs == sorted(langs)


def test_available_langs_empty_taxonomy():
    t = Taxonomy()
    langs = _available_langs(t)
    assert langs == []


# ── flatten_ontology_tree ─────────────────────────────────────────────────────


def _owl_taxonomy() -> Taxonomy:
    """Build a small OWL taxonomy: Animal > Dog, Animal > Cat (Cat disjoint Dog)."""
    from ster.model import RDFClass

    BASE_O = "https://example.org/onto/"
    t = Taxonomy()
    animal = RDFClass(uri=BASE_O + "Animal", labels=[Label(lang="en", value="Animal")])
    dog = RDFClass(
        uri=BASE_O + "Dog",
        labels=[Label(lang="en", value="Dog")],
        sub_class_of=[BASE_O + "Animal"],
    )
    cat = RDFClass(
        uri=BASE_O + "Cat",
        labels=[Label(lang="en", value="Cat")],
        sub_class_of=[BASE_O + "Animal"],
        disjoint_with=[BASE_O + "Dog"],
    )
    for cls in (animal, dog, cat):
        t.owl_classes[cls.uri] = cls
    assign_handles(t)
    return t


def test_flatten_ontology_tree_roots():
    from ster.nav.logic import flatten_ontology_tree

    t = _owl_taxonomy()
    lines = flatten_ontology_tree(t)
    uris = [l.uri for l in lines]
    assert "https://example.org/onto/Animal" in uris


def test_flatten_ontology_tree_children_depth():
    from ster.nav.logic import flatten_ontology_tree

    t = _owl_taxonomy()
    lines = flatten_ontology_tree(t)
    animal_line = next(l for l in lines if l.uri.endswith("Animal"))
    dog_line = next(l for l in lines if l.uri.endswith("Dog"))
    assert dog_line.depth == animal_line.depth + 1


def test_flatten_ontology_tree_node_type_class():
    from ster.nav.logic import _is_ontology_sentinel, flatten_ontology_tree

    t = _owl_taxonomy()
    lines = flatten_ontology_tree(t)
    class_lines = [l for l in lines if not _is_ontology_sentinel(l.uri)]
    for line in class_lines:
        assert line.node_type == "class"


def test_flatten_ontology_tree_node_type_promoted():
    from ster.model import Concept, RDFClass
    from ster.nav.logic import _is_ontology_sentinel, flatten_ontology_tree

    BASE_O = "https://example.org/onto/"
    t = Taxonomy()
    t.concepts[BASE_O + "Dog"] = Concept(uri=BASE_O + "Dog")
    t.owl_classes[BASE_O + "Dog"] = RDFClass(uri=BASE_O + "Dog")
    lines = flatten_ontology_tree(t)
    class_lines = [l for l in lines if not _is_ontology_sentinel(l.uri)]
    assert class_lines[0].node_type == "promoted"


def test_flatten_ontology_tree_empty():
    from ster.nav.logic import flatten_ontology_tree

    t = Taxonomy()
    assert flatten_ontology_tree(t) == []


# ── node_type on taxonomy TreeLines ──────────────────────────────────────────


def test_taxonomy_treeline_node_type_concept(simple_taxonomy):
    lines = flatten_tree(simple_taxonomy)
    concept_lines = [l for l in lines if not l.is_scheme]
    assert all(l.node_type == "concept" for l in concept_lines)


def test_taxonomy_treeline_node_type_promoted(simple_taxonomy):
    from ster.model import RDFClass

    top_uri = BASE + "Top"
    simple_taxonomy.owl_classes[top_uri] = RDFClass(uri=top_uri)
    lines = flatten_tree(simple_taxonomy)
    top_line = next(l for l in lines if l.uri == top_uri)
    assert top_line.node_type == "promoted"


# ── build_rdf_class_detail ────────────────────────────────────────────────────


def test_build_rdf_class_detail_identity():
    from ster.model import Definition, RDFClass
    from ster.nav.logic import build_rdf_class_detail

    BASE_O = "https://example.org/onto/"
    t = Taxonomy()
    t.owl_classes[BASE_O + "Dog"] = RDFClass(
        uri=BASE_O + "Dog",
        labels=[Label(lang="en", value="Dog")],
        comments=[Definition(lang="en", value="A domestic canine.")],
    )
    fields = build_rdf_class_detail(t, BASE_O + "Dog", "en")
    keys = [f.key for f in fields]
    assert "uri" in keys
    assert "node_type" in keys


def test_build_rdf_class_detail_subclassof():
    from ster.model import RDFClass
    from ster.nav.logic import build_rdf_class_detail

    BASE_O = "https://example.org/onto/"
    t = Taxonomy()
    t.owl_classes[BASE_O + "Animal"] = RDFClass(uri=BASE_O + "Animal")
    t.owl_classes[BASE_O + "Dog"] = RDFClass(uri=BASE_O + "Dog", sub_class_of=[BASE_O + "Animal"])
    fields = build_rdf_class_detail(t, BASE_O + "Dog", "en")
    keys = [f.key for f in fields]
    assert f"subclassof:{BASE_O}Animal" in keys


def test_build_rdf_class_detail_missing():
    from ster.nav.logic import build_rdf_class_detail

    t = Taxonomy()
    assert build_rdf_class_detail(t, "https://x.org/Missing", "en") == []


# ── flatten_mixed_tree ────────────────────────────────────────────────────────


def _mixed_taxonomy() -> Taxonomy:
    """Taxonomy with one SKOS scheme + two pure OWL classes."""
    from ster.model import ConceptScheme, RDFClass

    BASE_M = "https://example.org/mix/"
    t = Taxonomy()
    scheme = ConceptScheme(uri=BASE_M + "Scheme")
    concept = Concept(uri=BASE_M + "Concept", top_concept_of=BASE_M + "Scheme")
    scheme.top_concepts = [BASE_M + "Concept"]
    t.schemes[scheme.uri] = scheme
    t.concepts[concept.uri] = concept
    cls_a = RDFClass(uri=BASE_M + "ClassA", labels=[Label(lang="en", value="ClassA")])
    cls_b = RDFClass(
        uri=BASE_M + "ClassB",
        labels=[Label(lang="en", value="ClassB")],
        sub_class_of=[BASE_M + "ClassA"],
    )
    for cls in (cls_a, cls_b):
        t.owl_classes[cls.uri] = cls
    assign_handles(t)
    return t


def test_flatten_mixed_tree_includes_skos():
    from ster.nav.logic import flatten_mixed_tree

    t = _mixed_taxonomy()
    lines = flatten_mixed_tree(t)
    uris = [l.uri for l in lines]
    assert "https://example.org/mix/Concept" in uris


def test_flatten_mixed_tree_includes_owl_section_header():
    from ster.nav.logic import _is_ontology_sentinel, flatten_mixed_tree

    t = _mixed_taxonomy()
    lines = flatten_mixed_tree(t)
    assert any(_is_ontology_sentinel(l.uri) for l in lines)


def test_flatten_mixed_tree_header_has_label():
    from ster.nav.logic import _is_ontology_sentinel, flatten_mixed_tree

    t = _mixed_taxonomy()
    lines = flatten_mixed_tree(t)
    header = next(l for l in lines if _is_ontology_sentinel(l.uri))
    assert header.label  # ontology name should be non-empty


def test_flatten_mixed_tree_owl_classes_after_skos():
    from ster.nav.logic import _is_ontology_sentinel, flatten_mixed_tree

    t = _mixed_taxonomy()
    lines = flatten_mixed_tree(t)
    scheme_idx = next(
        i for i, l in enumerate(lines) if l.is_scheme and not _is_ontology_sentinel(l.uri)
    )
    owl_header_idx = next(i for i, l in enumerate(lines) if _is_ontology_sentinel(l.uri))
    assert owl_header_idx > scheme_idx


def test_flatten_mixed_tree_pure_classes_node_type():
    from ster.nav.logic import _is_ontology_sentinel, flatten_mixed_tree

    t = _mixed_taxonomy()
    lines = flatten_mixed_tree(t)
    owl_lines = [
        l
        for l in lines
        if not l.is_scheme and not _is_ontology_sentinel(l.uri) and l.uri not in t.concepts
    ]
    assert all(l.node_type == "class" for l in owl_lines)


def test_flatten_mixed_tree_owl_only_no_header():
    from ster.model import RDFClass
    from ster.nav.logic import _is_ontology_sentinel, flatten_mixed_tree

    t = Taxonomy()
    t.owl_classes["https://x.org/A"] = RDFClass(uri="https://x.org/A")
    lines = flatten_mixed_tree(t)
    # OWL-only taxonomy: ontology root + the class itself
    assert any(_is_ontology_sentinel(l.uri) for l in lines)
    assert any(l.uri == "https://x.org/A" for l in lines)


def test_flatten_mixed_tree_no_owl_no_header():
    from ster.nav.logic import _is_ontology_sentinel, flatten_mixed_tree

    lines = flatten_mixed_tree(simple_taxonomy())
    assert not any(_is_ontology_sentinel(l.uri) for l in lines)


def simple_taxonomy() -> Taxonomy:
    """Reusable simple SKOS-only taxonomy."""
    BASE_S = "https://example.org/s/"
    t = Taxonomy()
    scheme = ConceptScheme(uri=BASE_S + "Scheme")
    top = Concept(uri=BASE_S + "Top", top_concept_of=BASE_S + "Scheme")
    scheme.top_concepts = [BASE_S + "Top"]
    t.schemes[scheme.uri] = scheme
    t.concepts[top.uri] = top
    assign_handles(t)
    return t


# ── build_promoted_detail ─────────────────────────────────────────────────────


def _promoted_taxonomy() -> Taxonomy:
    from ster.model import Definition, RDFClass

    BASE_P = "https://example.org/promo/"
    t = Taxonomy()
    scheme = ConceptScheme(uri=BASE_P + "Scheme")
    concept = Concept(
        uri=BASE_P + "Dog",
        top_concept_of=BASE_P + "Scheme",
        labels=[Label(lang="en", value="Dog")],
        definitions=[Definition(lang="en", value="A domestic canine.")],
    )
    scheme.top_concepts = [BASE_P + "Dog"]
    t.schemes[scheme.uri] = scheme
    t.concepts[concept.uri] = concept
    rdf_class = RDFClass(
        uri=BASE_P + "Dog",
        labels=[Label(lang="en", value="Dog")],
        comments=[Definition(lang="en", value="Canis lupus familiaris.")],
    )
    t.owl_classes[rdf_class.uri] = rdf_class
    assign_handles(t)
    return t


def test_build_promoted_detail_has_both_sections():
    from ster.nav.logic import build_promoted_detail

    t = _promoted_taxonomy()
    uri = "https://example.org/promo/Dog"
    fields = build_promoted_detail(t, uri, "en")
    sep_displays = [f.display for f in fields if f.meta.get("type") == "separator"]
    assert "SKOS — Concept" in sep_displays
    assert "OWL — Class" in sep_displays


def test_build_promoted_detail_type_stat():
    from ster.nav.logic import build_promoted_detail

    t = _promoted_taxonomy()
    uri = "https://example.org/promo/Dog"
    fields = build_promoted_detail(t, uri, "en")
    type_field = next((f for f in fields if f.key == "node_type"), None)
    assert type_field is not None
    assert "Concept" in type_field.value and "Class" in type_field.value


def test_build_promoted_detail_fallback_concept_only():
    from ster.nav.logic import build_promoted_detail

    t = Taxonomy()
    BASE_P = "https://example.org/promo/"
    t.concepts[BASE_P + "X"] = Concept(uri=BASE_P + "X")
    fields = build_promoted_detail(t, BASE_P + "X", "en")
    # Falls back to concept detail — should still have fields
    assert len(fields) > 0


def test_build_promoted_detail_fallback_class_only():
    from ster.model import RDFClass
    from ster.nav.logic import build_promoted_detail

    t = Taxonomy()
    BASE_P = "https://example.org/promo/"
    t.owl_classes[BASE_P + "X"] = RDFClass(uri=BASE_P + "X")
    fields = build_promoted_detail(t, BASE_P + "X", "en")
    assert len(fields) > 0


# ── OWL individuals ───────────────────────────────────────────────────────────


BASE_I = "https://example.org/ind/"


def _individual_taxonomy():
    from ster.model import Definition, Label, OWLIndividual, RDFClass

    t = Taxonomy()
    t.owl_classes[BASE_I + "Animal"] = RDFClass(uri=BASE_I + "Animal")
    t.owl_classes[BASE_I + "Dog"] = RDFClass(uri=BASE_I + "Dog", sub_class_of=[BASE_I + "Animal"])
    ind = OWLIndividual(
        uri=BASE_I + "Rex",
        labels=[Label(lang="en", value="Rex")],
        comments=[Definition(lang="en", value="A dog")],
        types=[BASE_I + "Dog"],
    )
    t.owl_individuals[BASE_I + "Rex"] = ind
    assign_handles(t)
    return t


def test_individual_node_type():
    t = _individual_taxonomy()
    assert t.node_type(BASE_I + "Rex") == "individual"


def test_individual_handle_assigned():
    t = _individual_taxonomy()
    h = t.uri_to_handle(BASE_I + "Rex")
    assert h is not None


def test_individual_appears_under_class_in_ontology_tree():
    from ster.nav.logic import flatten_ontology_tree

    t = _individual_taxonomy()
    lines = flatten_ontology_tree(t)
    uris = [l.uri for l in lines]
    assert BASE_I + "Rex" in uris


def test_individual_node_type_in_tree_line():
    from ster.nav.logic import flatten_ontology_tree

    t = _individual_taxonomy()
    lines = flatten_ontology_tree(t)
    rex_line = next(l for l in lines if l.uri == BASE_I + "Rex")
    assert rex_line.node_type == "individual"


def test_individual_under_dog_not_animal():
    from ster.nav.logic import flatten_ontology_tree

    t = _individual_taxonomy()
    lines = flatten_ontology_tree(t)
    uris = [l.uri for l in lines]
    dog_idx = uris.index(BASE_I + "Dog")
    rex_idx = uris.index(BASE_I + "Rex")
    # Rex should appear after Dog (under Dog), not at top level
    assert rex_idx > dog_idx


def test_individual_appears_in_mixed_tree():
    from ster.nav.logic import flatten_mixed_tree

    t = _individual_taxonomy()
    lines = flatten_mixed_tree(t)
    uris = [l.uri for l in lines]
    assert BASE_I + "Rex" in uris


def test_individual_appears_under_multiple_classes():
    from ster.model import OWLIndividual, RDFClass

    t = Taxonomy()
    t.owl_classes[BASE_I + "Cat"] = RDFClass(uri=BASE_I + "Cat")
    t.owl_classes[BASE_I + "Pet"] = RDFClass(uri=BASE_I + "Pet")
    ind = OWLIndividual(uri=BASE_I + "Whiskers", types=[BASE_I + "Cat", BASE_I + "Pet"])
    t.owl_individuals[BASE_I + "Whiskers"] = ind
    assign_handles(t)

    from ster.nav.logic import flatten_ontology_tree

    lines = flatten_ontology_tree(t)
    uris = [l.uri for l in lines]
    # Whiskers belongs to 2 classes → should appear twice
    count = uris.count(BASE_I + "Whiskers")
    assert count == 2


def test_build_individual_detail_sections():
    from ster.nav.logic import build_individual_detail

    t = _individual_taxonomy()
    fields = build_individual_detail(t, BASE_I + "Rex", "en")
    sep_displays = [f.display for f in fields if f.meta.get("type") == "separator"]
    assert "Identity" in sep_displays
    assert "Labels" in sep_displays
    assert "Actions" in sep_displays


def test_build_individual_detail_class_membership():
    from ster.nav.logic import build_individual_detail

    t = _individual_taxonomy()
    fields = build_individual_detail(t, BASE_I + "Rex", "en")
    membership = [f for f in fields if f.meta.get("type") == "rdf_relation"]
    assert len(membership) == 1
    assert membership[0].meta["uri"] == BASE_I + "Dog"


def test_build_individual_detail_add_label_action():
    from ster.nav.logic import build_individual_detail

    t = _individual_taxonomy()
    fields = build_individual_detail(t, BASE_I + "Rex", "fr")
    actions = [f.meta.get("action") for f in fields if f.meta.get("type") == "action"]
    assert "add_ind_label" in actions
