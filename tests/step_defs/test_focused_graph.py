"""BDD step definitions for focused graph from OWL class in tree view."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios("../features/owl/focused_graph.feature")

NS = "https://example.org/onto#"


def _uri(name: str) -> str:
    return NS + name


def _make_taxonomy():
    from ster.model import Label, OWLIndividual, RDFClass, Taxonomy

    t = Taxonomy()
    t.owl_classes[_uri("Animal")] = RDFClass(uri=_uri("Animal"), labels=[Label("en", "Animal")])
    t.owl_classes[_uri("Dog")] = RDFClass(
        uri=_uri("Dog"),
        labels=[Label("en", "Dog")],
        sub_class_of=[_uri("Animal")],
    )
    t.owl_classes[_uri("Cat")] = RDFClass(
        uri=_uri("Cat"),
        labels=[Label("en", "Cat")],
        sub_class_of=[_uri("Animal")],
    )
    t.owl_individuals[_uri("Simba")] = OWLIndividual(uri=_uri("Simba"), types=[_uri("Animal")])
    t.owl_individuals[_uri("Fido")] = OWLIndividual(uri=_uri("Fido"), types=[_uri("Dog")])
    t.owl_classes[_uri("Bird")] = RDFClass(uri=_uri("Bird"), labels=[Label("en", "Bird")])
    t.owl_individuals[_uri("Tweety")] = OWLIndividual(uri=_uri("Tweety"), types=[_uri("Bird")])
    return t


@pytest.fixture
def ctx():
    return {"taxonomy": None, "result": None}


# ── Background ────────────────────────────────────────────────────────────────


@given('an ontology with "Animal", "Dog" (subclass of Animal), "Cat" (subclass of Animal)')
def given_base_ontology(ctx):
    ctx["taxonomy"] = _make_taxonomy()


@given('"Animal" has individual "Simba" and "Dog" has individual "Fido"')
def given_individuals(ctx):
    pass  # already set up in _make_taxonomy


@given('"Bird" is an unrelated root class with individual "Tweety"')
def given_bird(ctx):
    pass  # already set up in _make_taxonomy


# ── Optional extra step ────────────────────────────────────────────────────────


@given('"Puppy" is a subclass of "Dog"')
def given_puppy(ctx):
    from ster.model import Label, RDFClass

    ctx["taxonomy"].owl_classes[_uri("Puppy")] = RDFClass(
        uri=_uri("Puppy"),
        labels=[Label("en", "Puppy")],
        sub_class_of=[_uri("Dog")],
    )


# ── When ──────────────────────────────────────────────────────────────────────


@when('I build a focused graph rooted at "Animal"')
def when_build_focused_animal(ctx):
    from ster.viz_vowl import build_focused_vowl_graph

    ctx["result"] = build_focused_vowl_graph(ctx["taxonomy"], _uri("Animal"))


@when('I build a focused graph rooted at "Dog"')
def when_build_focused_dog(ctx):
    from ster.viz_vowl import build_focused_vowl_graph

    ctx["result"] = build_focused_vowl_graph(ctx["taxonomy"], _uri("Dog"))


# ── Then ──────────────────────────────────────────────────────────────────────


def _node_ids(ctx) -> set[str]:
    return {n["id"] for n in ctx["result"]["nodes"]}


@then('the node for "Animal" is present')
def then_animal_present(ctx):
    assert _uri("Animal") in _node_ids(ctx)


@then('the node for "Dog" is present')
def then_dog_present(ctx):
    assert _uri("Dog") in _node_ids(ctx)


@then('the node for "Puppy" is present')
def then_puppy_present(ctx):
    assert _uri("Puppy") in _node_ids(ctx)


@then('the node for "Simba" is present')
def then_simba_present(ctx):
    assert _uri("Simba") in _node_ids(ctx)


@then('the node for "Fido" is present')
def then_fido_present(ctx):
    assert _uri("Fido") in _node_ids(ctx)


@then('the node for "Cat" is absent')
def then_cat_absent(ctx):
    assert _uri("Cat") not in _node_ids(ctx)


@then('the node for "Bird" is absent')
def then_bird_absent(ctx):
    assert _uri("Bird") not in _node_ids(ctx)


@then('the node for "Tweety" is absent')
def then_tweety_absent(ctx):
    assert _uri("Tweety") not in _node_ids(ctx)


@then('the graph layout is "cose"')
def then_layout_cose(ctx):
    assert ctx["result"]["layout"] == "cose"
