"""BDD step definitions for tests/features/api/embedded_views.feature."""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/api/embedded_views.feature")

NS = "https://example.org/onto#"


@pytest.fixture
def ctx() -> dict[str, Any]:
    return {}


@given("a running ster API with a minimal taxonomy")
def api(ctx: dict[str, Any], api_client: TestClient) -> None:
    ctx["client"] = api_client


@when(parsers.parse('the client requests "{route}"'))
def request(ctx: dict[str, Any], route: str) -> None:
    ctx["response"] = ctx["client"].get(route)


def _embed_selectors(html: str) -> list[str] | None:
    """The selectors the page's embed <style> hides, or None when the page carries no such style."""
    match = re.search(r'<style id="ster-embed">(.*?)\{display:none !important\}</style>', html)
    return match.group(1).split(",") if match else None


@then(parsers.parse("the response status is {status:d}"))  # noqa: V103
def status_is(ctx: dict[str, Any], status: int) -> None:
    assert ctx["response"].status_code == status


@then(parsers.parse('the page hides "{selector}"'))  # noqa: V103
def hides(ctx: dict[str, Any], selector: str) -> None:
    assert selector in (_embed_selectors(ctx["response"].text) or [])


@then(parsers.parse('the page does not hide "{selector}"'))  # noqa: V103
def does_not_hide(ctx: dict[str, Any], selector: str) -> None:
    hidden = _embed_selectors(ctx["response"].text)
    assert hidden is not None, "the page is not embedded at all"
    assert selector not in hidden


@then("the page is embedded")  # noqa: V103
def is_embedded(ctx: dict[str, Any]) -> None:
    assert _embed_selectors(ctx["response"].text) is not None


@then("the page is not embedded")  # noqa: V103
def is_not_embedded(ctx: dict[str, Any]) -> None:
    assert _embed_selectors(ctx["response"].text) is None
    assert 'id="ster-embed"' not in ctx["response"].text


@then(parsers.parse('the body contains "{text}"'))  # noqa: V103
def body_contains(ctx: dict[str, Any], text: str) -> None:
    assert text in ctx["response"].text
