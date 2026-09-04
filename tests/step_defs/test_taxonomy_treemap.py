"""Step definitions for taxonomy_treemap.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

from ster.model import Concept, ConceptScheme, Label, LabelType, RDFClass, Taxonomy
from ster.viz_vowl import build_detail_map, render_vowl_html

scenarios("../features/ui/taxonomy_treemap.feature")

NS = "https://ex.org/kai-taxo/"


@pytest.fixture
def ctx() -> dict:
    return {}


def _skos_only() -> Taxonomy:
    t = Taxonomy()
    scheme_uri, root_uri = NS + "Scheme", NS + "Root"
    t.concepts[root_uri] = Concept(uri=root_uri, labels=[Label("en", "Root", LabelType.PREF)])
    t.schemes[scheme_uri] = ConceptScheme(
        uri=scheme_uri, labels=[Label("en", "Scheme", LabelType.PREF)], top_concepts=[root_uri]
    )
    return t


@given("a SKOS-only taxonomy")
def given_skos_only(ctx: dict) -> None:
    ctx["tax"] = _skos_only()


@given("a mixed SKOS and OWL taxonomy")
def given_mixed(ctx: dict) -> None:
    t = _skos_only()
    t.owl_classes[NS + "Cls"] = RDFClass(uri=NS + "Cls", labels=[Label("en", "Cls")])
    ctx["tax"] = t


@given("an OWL-only taxonomy")
def given_owl_only(ctx: dict) -> None:
    t = Taxonomy()
    t.owl_classes[NS + "Cls"] = RDFClass(uri=NS + "Cls", labels=[Label("en", "Cls")])
    ctx["tax"] = t


@when("the graph view HTML is rendered")
def when_rendered(ctx: dict) -> None:
    ctx["html"] = render_vowl_html(ctx["tax"], file_path=None)


@when("the concept detail map is built")
def when_detail_map_built(ctx: dict) -> None:
    ctx["detail_map"] = build_detail_map(ctx["tax"])


@then("the rendered HTML carries a taxonomy payload")
def then_has_taxonomy_payload(ctx: dict) -> None:
    assert '"taxonomy":' in ctx["html"]


@then("the rendered HTML carries no taxonomy payload")
def then_no_taxonomy_payload(ctx: dict) -> None:
    assert '"taxonomy":' not in ctx["html"]


@then("the rendered HTML carries OWL class nodes")
def then_has_owl_nodes(ctx: dict) -> None:
    assert '"type": "class"' in ctx["html"]


@then("the tab bar markup is present")
def then_tab_bar_present(ctx: dict) -> None:
    assert 'id="view-tabs"' in ctx["html"]
    assert 'id="treemap"' in ctx["html"]


@then("the concept's detail is available for the panel")
def then_concept_detail_available(ctx: dict) -> None:
    root_uri = NS + "Root"
    assert root_uri in ctx["detail_map"]
    assert ctx["detail_map"][root_uri]["labels"]
