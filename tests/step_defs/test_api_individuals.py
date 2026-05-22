"""BDD step definitions for individual creation and query scenarios."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, scenarios, then, when

scenarios("../features/api/individuals.feature")

NS = "https://example.org/onto#"
TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def uri(name: str) -> str:
    return NS + name


def _make_app(save_fn=None):
    from ster.api import SSEBroadcaster, create_app
    from ster.model import Label, LabelType, OWLProperty, RDFClass, Taxonomy

    t = Taxonomy()
    t.namespace_bindings[""] = NS
    for name in ("Animal", "Dog", "Cat", "Tool", "Hammer"):
        t.owl_classes[uri(name)] = RDFClass(
            uri=uri(name), labels=[Label(lang="en", value=name, type=LabelType.PREF)]
        )
    t.owl_classes[uri("Dog")].sub_class_of = [uri("Animal")]
    t.owl_classes[uri("Hammer")].sub_class_of = [uri("Tool")]
    t.owl_properties[uri("uses")] = OWLProperty(
        uri=uri("uses"),
        prop_type="ObjectProperty",
        labels=[Label(lang="en", value="uses", type=LabelType.PREF)],
        domains=[uri("Dog")],
        ranges=[uri("Hammer")],
    )
    fn = save_fn if save_fn is not None else (lambda _: None)
    return create_app(t, TOKEN, SSEBroadcaster(), fn)


@pytest.fixture
def ctx():
    app = _make_app()
    return {"client": TestClient(app), "response": None}


# ── Given ─────────────────────────────────────────────────────────────────────


@given("a tracked save function", target_fixture="ctx")
def given_tracked_save():
    from unittest.mock import MagicMock

    save_fn = MagicMock()
    app = _make_app(save_fn=save_fn)
    return {"client": TestClient(app), "response": None, "save_fn": save_fn}


@given("the API server is running with the Animal/Dog/Tool ontology")
def given_server(ctx):
    pass  # handled by fixture


@given('individual "Buddy" of class "Dog" already exists')
def given_buddy(ctx):
    ctx["client"].post(
        "/api/individuals",
        json={"class_uri": uri("Dog"), "local_name": "Buddy"},
        headers=AUTH,
    )


@given('individual "Hammer1" of class "Tool" already exists')
def given_hammer1(ctx):
    ctx["client"].post(
        "/api/individuals",
        json={"class_uri": uri("Tool"), "local_name": "Hammer1"},
        headers=AUTH,
    )


# ── When ──────────────────────────────────────────────────────────────────────


@when('I POST /api/individuals with class "Dog" and label "Fido"')
def when_post_fido(ctx):
    ctx["response"] = ctx["client"].post(
        "/api/individuals",
        json={"class_uri": uri("Dog"), "labels": [{"lang": "en", "value": "Fido"}]},
        headers=AUTH,
    )


@when('I POST /api/individuals with class "Dog", label "Rex", and local_name "RexTheDog"')
def when_post_rex_local_name(ctx):
    ctx["response"] = ctx["client"].post(
        "/api/individuals",
        json={
            "class_uri": uri("Dog"),
            "local_name": "RexTheDog",
            "labels": [{"lang": "en", "value": "Rex"}],
        },
        headers=AUTH,
    )


@when('I POST /api/individuals with class "Dog" and local_name "Buddy"')
def when_post_buddy_again(ctx):
    ctx["response"] = ctx["client"].post(
        "/api/individuals",
        json={"class_uri": uri("Dog"), "local_name": "Buddy"},
        headers=AUTH,
    )


@when("I POST /api/individuals without class_uri")
def when_post_no_class(ctx):
    ctx["response"] = ctx["client"].post(
        "/api/individuals",
        json={"labels": [{"lang": "en", "value": "X"}]},
        headers=AUTH,
    )


@when('I POST /api/individuals with class_uri "https://example.org/onto#Ghost"')
def when_post_unknown_class(ctx):
    ctx["response"] = ctx["client"].post(
        "/api/individuals",
        json={"class_uri": uri("Ghost"), "labels": [{"lang": "en", "value": "X"}]},
        headers=AUTH,
    )


@when(
    'I POST /api/individuals with class "Dog", label "Rex", and property "uses" pointing to "Hammer1"'
)
def when_post_rex_with_property(ctx):
    hammer_uri = NS + "Hammer1"
    ctx["response"] = ctx["client"].post(
        "/api/individuals",
        json={
            "class_uri": uri("Dog"),
            "local_name": "Rex",
            "labels": [{"lang": "en", "value": "Rex"}],
            "property_values": [{"property_uri": uri("uses"), "target_uri": hammer_uri}],
        },
        headers=AUTH,
    )


@when("I GET /api/individuals")
def when_get_all(ctx):
    ctx["response"] = ctx["client"].get("/api/individuals", headers=AUTH)


@when('I GET /api/individuals with type "Dog"')
def when_get_filtered(ctx):
    ctx["response"] = ctx["client"].get(
        "/api/individuals", headers=AUTH, params={"type": uri("Dog")}
    )


@when("I POST /api/individuals without Authorization header")
def when_post_no_auth(ctx):
    ctx["response"] = ctx["client"].post(
        "/api/individuals",
        json={"class_uri": uri("Dog"), "labels": [{"lang": "en", "value": "X"}]},
    )


# ── Then ──────────────────────────────────────────────────────────────────────


@then("the response status is 201")
def then_201(ctx):
    assert ctx["response"].status_code == 201


@then("the response status is 200")
def then_200(ctx):
    assert ctx["response"].status_code == 200


@then("the response status is 401")
def then_401(ctx):
    assert ctx["response"].status_code == 401


@then("the response status is 422")
def then_422(ctx):
    assert ctx["response"].status_code == 422


@then('the response contains a "uri" field')
def then_has_uri(ctx):
    assert "uri" in ctx["response"].json()


@then('the response "uri" ends with "Fido"')
def then_uri_fido(ctx):
    assert ctx["response"].json()["uri"].endswith("Fido")


@then('the response "uri" ends with "RexTheDog"')
def then_uri_rex_local(ctx):
    assert ctx["response"].json()["uri"].endswith("RexTheDog")


@then('the response "uri" ends with "Buddy_1"')
def then_uri_buddy_suffix(ctx):
    assert ctx["response"].json()["uri"].endswith("Buddy_1")


@then('the individual "Rex" has property "uses" pointing to "Hammer1"')
def then_rex_has_property(ctx):
    pv = ctx["response"].json()["property_values"]
    assert any(p["property_uri"] == uri("uses") and p["target_uri"].endswith("Hammer1") for p in pv)


@then('the response list contains "Buddy"')
def then_list_has_buddy(ctx):
    ind_uris = [i["uri"] for i in ctx["response"].json()["individuals"]]
    assert any(u.endswith("Buddy") for u in ind_uris)


@then('the response list does not contain "Hammer1"')
def then_list_no_hammer(ctx):
    ind_uris = [i["uri"] for i in ctx["response"].json()["individuals"]]
    assert not any(u.endswith("Hammer1") for u in ind_uris)


@then("the save function was called once")
def then_save_called_once(ctx):
    ctx["save_fn"].assert_called_once()
