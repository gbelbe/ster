"""BDD step definitions for tests/features/api/serve_ontology.feature."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/api/serve_ontology.feature")

NS = "https://example.org/onto#"
TOKEN = "test-token"


def _minimal_taxonomy():
    from ster.model import Label, LabelType, RDFClass, Taxonomy

    t = Taxonomy()
    t.namespace_bindings[""] = NS
    t.ontology_uri = "https://example.org/onto"
    t.owl_classes[NS + "Animal"] = RDFClass(
        uri=NS + "Animal",
        labels=[Label(lang="en", value="Animal", type=LabelType.PREF)],
    )
    return t


# ── Given ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def ctx() -> dict:
    return {}


@given("a running ster API with a minimal taxonomy")
def given_api_minimal(ctx: dict) -> None:
    from ster.api import SSEBroadcaster, create_app

    app = create_app(_minimal_taxonomy(), TOKEN, SSEBroadcaster(), lambda _: None)
    ctx["client"] = TestClient(app, raise_server_exceptions=False)


@given("a running ster API with a minimal taxonomy and no file path")
def given_api_no_file(ctx: dict) -> None:
    from ster.api import SSEBroadcaster, create_app

    app = create_app(_minimal_taxonomy(), TOKEN, SSEBroadcaster(), lambda _: None, file_path=None)
    ctx["client"] = TestClient(app, raise_server_exceptions=False)


@given("a running ster API with a VOWL renderer configured")
def given_api_vowl(ctx: dict) -> None:
    from ster.api import SSEBroadcaster, create_app

    def _html_fn(_root=None) -> str:
        return "<html><body>vowl</body></html>"

    app = create_app(_minimal_taxonomy(), TOKEN, SSEBroadcaster(), lambda _: None, html_fn=_html_fn)
    ctx["client"] = TestClient(app, raise_server_exceptions=False)


@given(parsers.parse('the file path "{path}"'))
def given_file_path(ctx: dict, path: str) -> None:
    ctx["file_path"] = Path(path)


@given("no file path")
def given_no_file_path(ctx: dict) -> None:
    ctx["file_path"] = None


# ── When ──────────────────────────────────────────────────────────────────────


@when(parsers.parse('the client requests "{route}" with Accept "{accept}"'))
def when_request_accept(ctx: dict, route: str, accept: str) -> None:
    ctx["response"] = ctx["client"].get(route, headers={"Accept": accept})


@when(parsers.parse('the client requests "{route}" with no Accept header'))
def when_request_no_accept(ctx: dict, route: str) -> None:
    ctx["response"] = ctx["client"].get(route)


@when(parsers.parse('the client requests "{route}"'))
def when_request(ctx: dict, route: str) -> None:
    ctx["response"] = ctx["client"].get(route)


@when("I derive the slug")
def when_derive_slug(ctx: dict) -> None:
    from ster.api import _derive_slug

    ctx["slug"] = _derive_slug(ctx["file_path"])


# ── Then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse("the response status is {status:d}"))
def then_status(ctx: dict, status: int) -> None:
    assert ctx["response"].status_code == status, ctx["response"].text


@then(parsers.parse('the Content-Type is "{ct}"'))
def then_content_type_exact(ctx: dict, ct: str) -> None:
    assert ctx["response"].headers["content-type"].startswith(ct)


@then(parsers.parse('the Content-Type starts with "{ct}"'))
def then_content_type_starts(ctx: dict, ct: str) -> None:
    assert ctx["response"].headers["content-type"].startswith(ct)


@then(parsers.parse('the body contains "{text}"'))
def then_body_contains(ctx: dict, text: str) -> None:
    assert text in ctx["response"].text


@then(parsers.parse('the slug is "{expected}"'))
def then_slug(ctx: dict, expected: str) -> None:
    assert ctx["slug"] == expected
