"""BDD step definitions for API schema introspection scenarios."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, scenarios, then, when

scenarios("../features/api/schema.feature")

NS = "https://example.org/onto#"
TOKEN = "test-token"


def uri(name: str) -> str:
    return NS + name


def _make_app():
    from ster.api import SSEBroadcaster, create_app
    from ster.model import Label, LabelType, OWLProperty, RDFClass, Taxonomy

    t = Taxonomy()
    t.namespace_bindings[""] = NS
    for name in ("Animal", "Dog", "Cat", "Tool", "Hammer"):
        t.owl_classes[uri(name)] = RDFClass(
            uri=uri(name), labels=[Label(lang="en", value=name, type=LabelType.PREF)]
        )
    t.owl_classes[uri("Dog")].sub_class_of = [uri("Animal")]
    t.owl_classes[uri("Cat")].sub_class_of = [uri("Animal")]
    t.owl_classes[uri("Hammer")].sub_class_of = [uri("Tool")]
    t.owl_properties[uri("uses")] = OWLProperty(
        uri=uri("uses"),
        prop_type="ObjectProperty",
        labels=[Label(lang="en", value="uses", type=LabelType.PREF)],
        domains=[uri("Dog")],
        ranges=[uri("Hammer")],
    )
    return create_app(t, TOKEN, SSEBroadcaster(), lambda _: None)


@pytest.fixture
def ctx():
    return {"client": None, "response": None}


@given("the API server is running with the Animal/Dog/Tool ontology")
def given_server(ctx):
    ctx["client"] = TestClient(_make_app())


@when("I GET /api/classes")
def when_get_classes(ctx):
    ctx["response"] = ctx["client"].get(
        "/api/classes", headers={"Authorization": f"Bearer {TOKEN}"}
    )


@when('I GET /api/classes with uri "Dog"')
def when_get_classes_dog(ctx):
    ctx["response"] = ctx["client"].get(
        "/api/classes",
        headers={"Authorization": f"Bearer {TOKEN}"},
        params={"uri": uri("Dog")},
    )


@when('I GET /api/classes with uri "NonExistent"')
def when_get_classes_nonexistent(ctx):
    ctx["response"] = ctx["client"].get(
        "/api/classes",
        headers={"Authorization": f"Bearer {TOKEN}"},
        params={"uri": uri("NonExistent")},
    )


@when("I GET /api/classes without Authorization header")
def when_get_classes_no_auth(ctx):
    ctx["response"] = ctx["client"].get("/api/classes")


@when("I GET /api/classes with wrong token")
def when_get_classes_wrong_token(ctx):
    ctx["response"] = ctx["client"].get(
        "/api/classes", headers={"Authorization": "Bearer wrong-token"}
    )


@then("the response status is 200")
def then_200(ctx):
    assert ctx["response"].status_code == 200


@then("the response status is 401")
def then_401(ctx):
    assert ctx["response"].status_code == 401


@then("the response status is 404")
def then_404(ctx):
    assert ctx["response"].status_code == 404


@then('the response contains classes "Animal", "Dog", "Cat", "Tool", "Hammer"')
def then_all_classes(ctx):
    uris = {c["uri"] for c in ctx["response"].json()["classes"]}
    for name in ("Animal", "Dog", "Cat", "Tool", "Hammer"):
        assert uri(name) in uris


@then('"Dog" has "Animal" in its sub_class_of list')
def then_dog_parent(ctx):
    by_uri = {c["uri"]: c for c in ctx["response"].json()["classes"]}
    assert uri("Animal") in by_uri[uri("Dog")]["sub_class_of"]


@then('"Animal" has "Dog" and "Cat" in its child_classes list')
def then_animal_children(ctx):
    by_uri = {c["uri"]: c for c in ctx["response"].json()["classes"]}
    children = by_uri[uri("Animal")]["child_classes"]
    assert uri("Dog") in children
    assert uri("Cat") in children


@then('the class detail includes property "uses" with range "Hammer"')
def then_uses_property(ctx):
    props = {p["uri"]: p for p in ctx["response"].json()["classes"][0]["applicable_properties"]}
    assert uri("uses") in props
    assert props[uri("uses")]["range_uri"] == uri("Hammer")
