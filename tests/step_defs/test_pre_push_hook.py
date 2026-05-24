"""BDD step definitions for tests/features/ci/pre_push_hook.feature."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios("../features/ci/pre_push_hook.feature")

_HOOK = Path(__file__).parents[2] / "scripts" / "pre-push.sh"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def ctx(tmp_path: Path) -> dict[str, Any]:
    return {"root": tmp_path, "result": None}


# ── Givens ────────────────────────────────────────────────────────────────────


@given("the CI sentinel file does not exist")
def no_sentinel(ctx: dict[str, Any]) -> None:
    pass  # tmp_path is empty by default


@given("the CI sentinel file was written less than 60 minutes ago")
def fresh_sentinel(ctx: dict[str, Any]) -> None:
    (ctx["root"] / ".ci-passed").write_text("2026-05-24T16:00:00Z\n")


@given("the CI sentinel file was written more than 60 minutes ago")
def stale_sentinel(ctx: dict[str, Any]) -> None:
    sentinel = ctx["root"] / ".ci-passed"
    sentinel.write_text("2026-05-24T16:00:00Z\n")
    stale_mtime = time.time() - 7200
    os.utime(sentinel, (stale_mtime, stale_mtime))


# ── When ──────────────────────────────────────────────────────────────────────


@when("the pre-push hook runs")
def run_hook(ctx: dict[str, Any]) -> None:
    env = {**os.environ, "CI_HOOK_ROOT": str(ctx["root"])}
    ctx["result"] = subprocess.run(
        ["bash", str(_HOOK)],
        env=env,
        capture_output=True,
        text=True,
    )


# ── Thens ─────────────────────────────────────────────────────────────────────


@then("the hook exits with code 0")
def exits_zero(ctx: dict[str, Any]) -> None:
    assert ctx["result"].returncode == 0


@then("the hook exits with code 1")
def exits_one(ctx: dict[str, Any]) -> None:
    assert ctx["result"].returncode == 1


@then('the output contains "CI has not been run"')
def output_no_sentinel(ctx: dict[str, Any]) -> None:
    assert "CI has not been run" in ctx["result"].stderr


@then('the output contains "CI result is stale"')
def output_stale(ctx: dict[str, Any]) -> None:
    assert "CI result is stale" in ctx["result"].stderr
