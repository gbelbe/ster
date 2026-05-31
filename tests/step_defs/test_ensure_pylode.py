"""BDD step definitions for the _ensure_pylode installation guard."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios("../features/ci/ensure_pylode.feature")


# ── fixture ───────────────────────────────────────────────────────────────────


@pytest.fixture
def ctx():
    return {}


# ── Given ─────────────────────────────────────────────────────────────────────


def _set_pylode(ctx, request, value):
    saved = sys.modules.get("pylode", ...)
    sys.modules["pylode"] = value  # type: ignore[assignment]

    def _restore():
        if saved is ...:
            sys.modules.pop("pylode", None)
        else:
            sys.modules["pylode"] = saved

    request.addfinalizer(_restore)


@given("pyLODE is importable")
def given_pylode_importable(ctx, request):
    _set_pylode(ctx, request, MagicMock())


@given("pyLODE is not installed")
def given_pylode_missing(ctx, request):
    _set_pylode(ctx, request, None)


@given("the user agrees to install")
def given_user_agrees(ctx):
    ctx["prompt_answer"] = "y"


@given('uv is available on PATH at "/usr/local/bin/uv"')
def given_uv_available(ctx):
    ctx["uv_path"] = "/usr/local/bin/uv"


@given("uv is not available on PATH")
def given_uv_missing(ctx):
    ctx["uv_path"] = None


# ── When ──────────────────────────────────────────────────────────────────────


def _run_guard(ctx, returncode: int = 0):
    """Execute _ensure_pylode with all side-effects mocked."""
    fake_result = MagicMock()
    fake_result.returncode = returncode
    fake_result.stderr = b""

    run_mock = MagicMock(return_value=fake_result)
    invalidate_mock = MagicMock()
    ctx["run_mock"] = run_mock
    ctx["invalidate_mock"] = invalidate_mock

    prompt_answer = ctx.get("prompt_answer", "n")
    uv_path = ctx.get("uv_path", None)

    with (
        patch("ster.cli.Prompt.ask", return_value=prompt_answer),
        patch("subprocess.run", run_mock),
        patch("importlib.invalidate_caches", invalidate_mock),
        patch("shutil.which", return_value=uv_path),
    ):
        from ster.cli import _ensure_pylode

        ctx["result"] = _ensure_pylode()


@when("the pylode guard runs")
def when_guard_runs(ctx):
    prompt_mock = MagicMock()
    ctx["prompt_mock"] = prompt_mock
    with patch("ster.cli.Prompt.ask", prompt_mock):
        from ster.cli import _ensure_pylode

        ctx["result"] = _ensure_pylode()


@when("the user is asked to install and declines")
def when_user_declines(ctx):
    with patch("ster.cli.Prompt.ask", return_value="n"):
        from ster.cli import _ensure_pylode

        ctx["result"] = _ensure_pylode()


@when("the user interrupts the install prompt with Ctrl+C")
def when_user_ctrl_c(ctx):
    with patch("ster.cli.Prompt.ask", side_effect=KeyboardInterrupt):
        from ster.cli import _ensure_pylode

        ctx["result"] = _ensure_pylode()


@when("the installer runs and succeeds")
def when_installer_succeeds(ctx):
    _run_guard(ctx, returncode=0)


@when("the installer runs and fails")
def when_installer_fails(ctx):
    _run_guard(ctx, returncode=1)


@when("the installer runs")
def when_installer_runs(ctx):
    _run_guard(ctx, returncode=ctx.get("_returncode", 0))


# ── Then ──────────────────────────────────────────────────────────────────────


@then("it returns True without showing any prompt")
def then_returns_true_no_prompt(ctx):
    assert ctx["result"] is True
    assert not ctx.get("prompt_mock", MagicMock()).called


@then("the guard returns True")
def then_returns_true(ctx):
    assert ctx["result"] is True


@then("the guard returns False")
def then_returns_false(ctx):
    assert ctx["result"] is False


@then("the Python import cache is invalidated regardless of outcome")
def then_cache_invalidated(ctx):
    assert ctx["invalidate_mock"].called


@then('the command uses uv with "--python" targeting the current interpreter')
def then_uses_uv(ctx):
    cmd = ctx["run_mock"].call_args[0][0]
    assert cmd[0] == "/usr/local/bin/uv"
    assert "--python" in cmd
    assert cmd[cmd.index("--python") + 1] == sys.executable
    assert "pylode" in cmd


@then('the command uses the current interpreter with "-m" "pip"')
def then_uses_pip(ctx):
    cmd = ctx["run_mock"].call_args[0][0]
    assert cmd[0] == sys.executable
    assert cmd[1] == "-m"
    assert cmd[2] == "pip"
    assert "pylode" in cmd


@then("the subprocess is called with capture_output=True")
def then_capture_output(ctx):
    _, kwargs = ctx["run_mock"].call_args
    assert kwargs.get("capture_output") is True
