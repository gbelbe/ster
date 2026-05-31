"""BDD step definitions for tests/features/api/global_fields_config.feature."""

from __future__ import annotations

import pytest
from pytest_bdd import given, parsers, scenarios, then

scenarios("../features/api/global_fields_config.feature")


@pytest.fixture
def ctx() -> dict:
    return {}


def _fields(ctx: dict):
    return ctx["fields"]


# ── Given ─────────────────────────────────────────────────────────────────────


@given("global fields built without a workspace")
def given_no_workspace(ctx: dict) -> None:
    from ster.nav.logic import build_global_fields

    ctx["fields"] = build_global_fields(None, None, "en")


@given(parsers.parse('global fields built with slug "{slug}" on port {port:d}'))
def given_with_slug(ctx: dict, slug: str, port: int) -> None:
    from ster.nav.logic import build_global_fields

    ctx["fields"] = build_global_fields(None, None, "en", server_port=port, ontology_slug=slug)


@given("global fields built without a slug")
def given_without_slug(ctx: dict) -> None:
    from ster.nav.logic import build_global_fields

    ctx["fields"] = build_global_fields(None, None, "en")


# ── Then ──────────────────────────────────────────────────────────────────────


@then(parsers.parse('the first separator is "{label}"'))
def then_first_sep(ctx: dict, label: str) -> None:
    seps = [f for f in _fields(ctx) if f.meta.get("type") == "separator"]
    assert seps, "no separator fields found"
    assert seps[0].display == label, f"first sep is {seps[0].display!r}"


@then(parsers.parse('a field "{fid}" exists with value "{value}"'))
def then_field_value(ctx: dict, fid: str, value: str) -> None:
    found = {f.key: f for f in _fields(ctx)}
    assert fid in found, f"{fid!r} not in {list(found)}"
    assert found[fid].value == value, f"got {found[fid].value!r}"


@then(parsers.parse('no field "{fid}" exists'))
def then_field_absent(ctx: dict, fid: str) -> None:
    found = {f.key for f in _fields(ctx)}
    assert fid not in found, f"{fid!r} unexpectedly present"
