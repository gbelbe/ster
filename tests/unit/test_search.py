"""build_search_results: whole-ontology search independent of what's rendered.

See docs/architecture/graph-editor.md, Phase 2.
"""

from __future__ import annotations

from ster.model import Concept, ConceptScheme, Label, LabelType, OWLIndividual, RDFClass, Taxonomy
from ster.viz_vowl import build_search_results

NS = "https://example.org/onto#"


def uri(name: str) -> str:
    return NS + name


def _pref(value: str) -> Label:
    return Label(lang="en", value=value, type=LabelType.PREF)


def _tax() -> Taxonomy:
    t = Taxonomy()
    t.schemes[uri("Scheme")] = ConceptScheme(uri=uri("Scheme"), labels=[_pref("Main Scheme")])
    t.owl_classes[uri("Animal")] = RDFClass(uri=uri("Animal"), labels=[_pref("Animal")])
    t.owl_classes[uri("Dog")] = RDFClass(
        uri=uri("Dog"), labels=[_pref("Dog")], sub_class_of=[uri("Animal")]
    )
    t.owl_individuals[uri("Rex")] = OWLIndividual(
        uri=uri("Rex"), labels=[_pref("Rex the Dog")], types=[uri("Dog")]
    )
    t.concepts[uri("Mammal")] = Concept(
        uri=uri("Mammal"), labels=[_pref("Mammal")], top_concept_of=uri("Scheme")
    )
    t.concepts[uri("Puppy")] = Concept(
        uri=uri("Puppy"), labels=[_pref("Puppy")], broader=[uri("Mammal")]
    )
    return t


def test_empty_query_returns_no_results():
    assert build_search_results(_tax(), "") == {"results": []}


def test_whitespace_only_query_returns_no_results():
    assert build_search_results(_tax(), "   ") == {"results": []}


def test_matches_by_label_case_insensitively():
    res = build_search_results(_tax(), "dog")
    ids = {r["id"] for r in res["results"]}
    assert uri("Dog") in ids


def test_matches_are_substring_not_exact():
    res = build_search_results(_tax(), "an")
    ids = {r["id"] for r in res["results"]}
    assert uri("Animal") in ids


def test_matches_by_uri_when_label_does_not_match():
    res = build_search_results(_tax(), "Puppy")
    ids = {r["id"] for r in res["results"]}
    assert uri("Puppy") in ids


def test_no_match_returns_empty_results():
    assert build_search_results(_tax(), "nonexistent-xyz") == {"results": []}


def test_each_result_carries_id_label_and_type():
    res = build_search_results(_tax(), "Dog")
    hit = next(r for r in res["results"] if r["id"] == uri("Dog"))
    assert hit["label"] == "Dog"
    assert hit["type"] == "class"


def test_individual_type_is_reported():
    res = build_search_results(_tax(), "Rex")
    hit = next(r for r in res["results"] if r["id"] == uri("Rex"))
    assert hit["type"] == "individual"


def test_top_concept_is_distinguished_from_plain_concept():
    res = build_search_results(_tax(), "Mammal")
    hit = next(r for r in res["results"] if r["id"] == uri("Mammal"))
    assert hit["type"] == "topconcept"

    res2 = build_search_results(_tax(), "Puppy")
    hit2 = next(r for r in res2["results"] if r["id"] == uri("Puppy"))
    assert hit2["type"] == "concept"


def test_scheme_is_matched_too():
    res = build_search_results(_tax(), "Main Scheme")
    ids = {r["id"] for r in res["results"]}
    assert uri("Scheme") in ids


def test_results_are_capped_at_limit():
    t = Taxonomy()
    for i in range(10):
        u = uri(f"Thing{i}")
        t.owl_classes[u] = RDFClass(uri=u, labels=[_pref(f"Thing{i}")])
    res = build_search_results(t, "Thing", limit=3)
    assert len(res["results"]) == 3


def test_results_are_sorted_by_label():
    res = build_search_results(_tax(), "a")
    labels = [r["label"] for r in res["results"]]
    assert labels == sorted(labels, key=str.lower)


# ── Phase 4: property candidates + type filtering ───────────────────────────


def test_owl_property_is_a_search_candidate():
    from ster.model import OWLProperty

    t = _tax()
    t.owl_properties[uri("hasOwner")] = OWLProperty(
        uri=uri("hasOwner"), prop_type="ObjectProperty", labels=[_pref("has owner")]
    )
    res = build_search_results(t, "owner")
    hit = next(r for r in res["results"] if r["id"] == uri("hasOwner"))
    assert hit["type"] == "property"


def test_types_filter_restricts_the_scan():
    res = build_search_results(_tax(), "a", types={"class"})
    assert res["results"]
    assert all(r["type"] == "class" for r in res["results"])


def test_types_filter_excludes_non_matching_types():
    res = build_search_results(_tax(), "Rex", types={"class"})
    assert res["results"] == []


def test_no_types_filter_searches_everything():
    res_all = build_search_results(_tax(), "a")
    res_none_filter = build_search_results(_tax(), "a", types=None)
    assert res_all == res_none_filter
