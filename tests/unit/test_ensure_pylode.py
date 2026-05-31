"""Unit tests for _ensure_pylode install helper."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

# ── already installed ─────────────────────────────────────────────────────────


def test_returns_true_when_pylode_importable():
    fake = MagicMock()
    with patch.dict(sys.modules, {"pylode": fake}):
        from ster.cli import _ensure_pylode

        assert _ensure_pylode() is True


# ── helpers ───────────────────────────────────────────────────────────────────


def _without_pylode():
    saved = sys.modules.get("pylode", ...)
    sys.modules["pylode"] = None  # type: ignore[assignment]
    return saved


def _restore_pylode(saved):
    if saved is ...:
        sys.modules.pop("pylode", None)
    else:
        sys.modules["pylode"] = saved


# ── user declines installation ────────────────────────────────────────────────


def test_returns_false_when_user_says_no():
    saved = _without_pylode()
    try:
        with patch("ster.cli.Prompt.ask", return_value="n"):
            from ster.cli import _ensure_pylode

            assert _ensure_pylode() is False
    finally:
        _restore_pylode(saved)


def test_returns_false_on_keyboard_interrupt():
    saved = _without_pylode()
    try:
        with patch("ster.cli.Prompt.ask", side_effect=KeyboardInterrupt):
            from ster.cli import _ensure_pylode

            assert _ensure_pylode() is False
    finally:
        _restore_pylode(saved)


# ── installation path ─────────────────────────────────────────────────────────


def _install_scenario(returncode: int, uv_path: str | None = None):
    """Run _ensure_pylode with pylode absent, user says yes, subprocess returns *returncode*."""
    saved = _without_pylode()

    fake_result = MagicMock()
    fake_result.returncode = returncode
    fake_result.stderr = b""

    run_mock = MagicMock(return_value=fake_result)
    invalidate_mock = MagicMock()

    try:
        with (
            patch("ster.cli.Prompt.ask", return_value="y"),
            patch("subprocess.run", run_mock),
            patch("importlib.invalidate_caches", invalidate_mock),
            patch("shutil.which", return_value=uv_path),
        ):
            from ster.cli import _ensure_pylode

            result = _ensure_pylode()
    finally:
        _restore_pylode(saved)

    return result, run_mock, invalidate_mock


def test_install_success_returns_true():
    result, _, _ = _install_scenario(returncode=0)
    assert result is True


def test_install_failure_returns_false():
    result, _, _ = _install_scenario(returncode=1)
    assert result is False


def test_subprocess_called_with_capture_output():
    _, run_mock, _ = _install_scenario(returncode=0)
    _, kwargs = run_mock.call_args
    assert kwargs.get("capture_output") is True


def test_invalidate_caches_called_after_successful_install():
    _, _, invalidate_mock = _install_scenario(returncode=0)
    assert invalidate_mock.called


def test_invalidate_caches_called_even_on_failure():
    _, _, invalidate_mock = _install_scenario(returncode=1)
    assert invalidate_mock.called


# ── uv vs pip selection ───────────────────────────────────────────────────────


def test_uses_uv_when_available():
    """When uv is in PATH, install via 'uv pip install --python <exe>'."""
    _, run_mock, _ = _install_scenario(returncode=0, uv_path="/usr/local/bin/uv")
    cmd = run_mock.call_args[0][0]
    assert cmd[0] == "/usr/local/bin/uv"
    assert "pip" in cmd
    assert "install" in cmd
    assert "pylode" in cmd


def test_uses_python_pip_when_no_uv():
    """When uv is absent, fall back to 'python -m pip install'."""
    _, run_mock, _ = _install_scenario(returncode=0, uv_path=None)
    cmd = run_mock.call_args[0][0]
    assert cmd[0] == sys.executable
    assert cmd[1:3] == ["-m", "pip"]
    assert "pylode" in cmd


def test_uv_cmd_targets_current_python():
    """uv pip install must target the running interpreter, not a random one."""
    _, run_mock, _ = _install_scenario(returncode=0, uv_path="/usr/local/bin/uv")
    cmd = run_mock.call_args[0][0]
    assert "--python" in cmd
    idx = cmd.index("--python")
    assert cmd[idx + 1] == sys.executable
