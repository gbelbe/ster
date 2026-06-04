"""BDD step definitions for tests/features/ci/complexity_ratchet.feature."""

from __future__ import annotations

from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then

from scripts.check_complexity_ratchet import find_violations

scenarios("../features/ci/complexity_ratchet.feature")

# A single fixed function identity is enough to exercise the ratchet rule.
NAME = "mod.py::func"


@pytest.fixture
def ctx() -> dict[str, dict[str, int]]:
    return {"base": {}, "head": {}}


@given("a function absent from the base")
def _absent(ctx: dict[str, Any]) -> None:
    ctx["base"].pop(NAME, None)


@given(parsers.parse("a function with base complexity {score:d}"))
def _base(ctx: dict[str, Any], score: int) -> None:
    ctx["base"][NAME] = score


@given(parsers.parse("its complexity in the change is {score:d}"))
def _head(ctx: dict[str, Any], score: int) -> None:
    ctx["head"][NAME] = score


@then("the ratchet check reports a violation")
def _violation(ctx: dict[str, Any]) -> None:
    assert find_violations(ctx["base"], ctx["head"])


@then("the ratchet check reports no violation")
def _no_violation(ctx: dict[str, Any]) -> None:
    assert find_violations(ctx["base"], ctx["head"]) == []


@given(parsers.parse("a god-function with base complexity {score:d}"))
def _god_base(ctx: dict[str, Any], score: int) -> None:
    ctx["base"] = {"m.py::g": score}


@given(parsers.parse("you modify it leaving complexity at {score:d}"))
def _god_flat(ctx: dict[str, Any], score: int) -> None:
    ctx["head"] = {"m.py::g": score}
    ctx["touched"] = {"m.py::g"}


@given(parsers.parse("you modify it reducing complexity to {score:d}"))
def _god_reduce(ctx: dict[str, Any], score: int) -> None:
    ctx["head"] = {"m.py::g": score}
    ctx["touched"] = {"m.py::g"}


@then("the ratchet reports a god-function violation")
def _god_violation(ctx: dict[str, Any]) -> None:
    from scripts.check_complexity_ratchet import touch_ceiling_violations

    assert touch_ceiling_violations(ctx["touched"], ctx["base"], ctx["head"])


@then("the ratchet reports no god-function violation")
def _god_no_violation(ctx: dict[str, Any]) -> None:
    from scripts.check_complexity_ratchet import touch_ceiling_violations

    assert touch_ceiling_violations(ctx["touched"], ctx["base"], ctx["head"]) == []
