"""Search ranks before it caps, and says when it cut the list.

The scan stopped at the limit and *then* sorted those matches alphabetically,
so on an ontology where 7,888 things match "person" the first four results were
numeric ids that matched on URI and sort before the letter P. The class actually
called Person was in there, indistinguishable from them.

Ranking first fixes the order; reporting the total fixes the other half — fifty
results with no total implies fifty is all there is.
"""

from __future__ import annotations

import pytest

from ster.model import Concept, ConceptScheme, Label, LabelType, RDFClass, Taxonomy
from ster.viz_vowl import build_search_results


def _lbl(text: str) -> Label:
    return Label(lang="en", value=text, type=LabelType.PREF)


@pytest.fixture
def tax() -> Taxonomy:
    t = Taxonomy()
    for uri, label in [
        ("https://x/Person", "Person"),
        ("https://x/PersonalAccount", "Personal Account"),
        ("https://x/Employee", "Staff Person Record"),
        ("https://x/10182088", "10182088"),  # matches only via… nothing
    ]:
        t.owl_classes[uri] = RDFClass(uri=uri, labels=[_lbl(label)])
    # a URI-only match: the label says nothing about persons
    t.owl_classes["https://x/person-coded-9911"] = RDFClass(
        uri="https://x/person-coded-9911", labels=[_lbl("9911")]
    )
    return t


def test_an_exact_label_comes_first(tax):
    results = build_search_results(tax, "person")["results"]

    assert results[0]["label"] == "Person"


def test_a_prefix_beats_a_mid_word_match(tax):
    labels = [r["label"] for r in build_search_results(tax, "person")["results"]]

    assert labels.index("Personal Account") < labels.index("Staff Person Record")


def test_a_uri_only_match_comes_last(tax):
    """A term that appears in an opaque id by coincidence must never outrank
    the thing you actually named."""
    labels = [r["label"] for r in build_search_results(tax, "person")["results"]]

    assert labels[-1] == "9911"


def test_the_total_counts_every_match_not_just_the_returned_ones(tax):
    d = build_search_results(tax, "person", limit=2)

    assert len(d["results"]) == 2
    assert d["total"] == 4
    assert d["truncated"] is True


def test_nothing_is_marked_truncated_when_it_all_fits(tax):
    d = build_search_results(tax, "person")

    assert d["truncated"] is False
    assert d["total"] == len(d["results"])


def test_ranking_happens_before_the_cut(tax):
    """The point of the fix: with a limit of 1 you get the best match, not
    whichever match the scan reached first."""
    d = build_search_results(tax, "person", limit=1)

    assert d["results"][0]["label"] == "Person"


def test_an_empty_query_returns_an_empty_shape_not_a_missing_one(tax):
    d = build_search_results(tax, "   ")

    assert d == {"results": [], "total": 0, "truncated": False}


def test_schemes_are_searchable(tax):
    tax.schemes["https://x/scheme"] = ConceptScheme(uri="https://x/scheme")
    tax.concepts["https://x/c"] = Concept(uri="https://x/c", labels=[_lbl("Person Concept")])

    found = {r["type"] for r in build_search_results(tax, "person")["results"]}

    assert "concept" in found
