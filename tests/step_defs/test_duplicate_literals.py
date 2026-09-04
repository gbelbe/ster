"""BDD step definitions for tests/features/ci/duplicate_literals.feature."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then

from scripts.check_complexity_ratchet import DUPLICATE_LITERAL_THRESHOLD, find_violations

scenarios("../features/ci/duplicate_literals.feature")

# A single fixed literal identity is enough to exercise the ratchet rule.
NAME = "mod.py::'a duplicated literal'"


@pytest.fixture
def ctx() -> dict[str, dict[str, int]]:
    return {"base": {}, "head": {}}


@given("a literal absent from the base")
def _absent(ctx: dict[str, Any]) -> None:
    ctx["base"].pop(NAME, None)


@given(parsers.parse("a literal with base occurrence count {count:d}"))
def _base(ctx: dict[str, Any], count: int) -> None:
    ctx["base"][NAME] = count


@given(parsers.parse("its occurrence count in the change is {count:d}"))
def _head(ctx: dict[str, Any], count: int) -> None:
    ctx["head"][NAME] = count


def _check(ctx: dict[str, Any]) -> list[str]:
    return find_violations(
        ctx["base"],
        ctx["head"],
        threshold=DUPLICATE_LITERAL_THRESHOLD - 1,
        metric="duplicated string literal",
    )


@then("the duplicate-literal check reports a violation")
def _violation(ctx: dict[str, Any]) -> None:
    assert _check(ctx)


@then("the duplicate-literal check reports no violation")
def _no_violation(ctx: dict[str, Any]) -> None:
    assert _check(ctx) == []
