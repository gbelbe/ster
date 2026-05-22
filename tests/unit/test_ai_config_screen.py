"""Unit tests for the standalone AI configuration wizard."""

from __future__ import annotations

from unittest.mock import patch

from ster.nav.state import AiInstallState, AiSetupState


def _wizard(state: AiSetupState | AiInstallState):
    """Create an AiConfigWizard bypassing __init__ with a known state."""
    from ster.ai_config_screen import AiConfigWizard

    w = AiConfigWizard.__new__(AiConfigWizard)
    w._state = state
    w._install_thread = None
    w._install_output = []
    w._install_returncode = None
    w._install_spinner = 0
    w._install_package = "llm"
    w._install_command = None
    return w


_PROVIDER = ("openai", "OpenAI  (cloud)", [("gpt-4o", "GPT-4o")])
_OFFLINE_PROVIDER = ("llm_ollama", "Ollama  (local)", [("llama3", "llama3")])


# ── Constructor ───────────────────────────────────────────────────────────────


def test_initial_state_mode_when_llm_available():
    with (
        patch("ster.ai.is_available", return_value=True),
        patch("ster.ai.discover_models", return_value=([_PROVIDER], [])),
        patch("ster.ai.is_copypaste", return_value=False),
    ):
        from ster.ai_config_screen import AiConfigWizard

        w = AiConfigWizard()
    assert isinstance(w._state, AiSetupState)
    assert w._state.step == "mode"


def test_initial_state_install_when_llm_unavailable():
    with patch("ster.ai.is_available", return_value=False):
        from ster.ai_config_screen import AiConfigWizard

        w = AiConfigWizard()
    assert isinstance(w._state, AiInstallState)


# ── Install state ─────────────────────────────────────────────────────────────


def test_install_esc_when_not_installing_signals_done():
    w = _wizard(AiInstallState())
    assert w.on_key(27) is True


def test_install_esc_on_error_signals_done():
    w = _wizard(AiInstallState(error="pip failed"))
    assert w.on_key(27) is True


def test_install_enter_starts_installing():
    w = _wizard(AiInstallState())
    w.on_key(ord("\n"))
    assert isinstance(w._state, AiInstallState)
    assert w._state.installing is True


def test_install_done_any_key_advances_to_setup():
    with (
        patch("ster.ai.discover_models", return_value=([_PROVIDER], [])),
    ):
        w = _wizard(AiInstallState(done=True))
        w.on_key(ord("\n"))
    assert isinstance(w._state, AiSetupState)
    assert w._state.step == "mode"


# ── Mode step ─────────────────────────────────────────────────────────────────


def test_mode_esc_signals_done():
    w = _wizard(AiSetupState(step="mode"))
    assert w.on_key(27) is True


def test_mode_down_increments_cursor():
    st = AiSetupState(step="mode", online_providers=[_PROVIDER], provider_cursor=0)
    w = _wizard(st)
    w.on_key(258)  # KEY_DOWN
    assert isinstance(w._state, AiSetupState)
    assert w._state.provider_cursor == 1


def test_mode_up_wraps_around():
    # mode cursor is modular: pressing up at 0 wraps to last option
    st = AiSetupState(step="mode", online_providers=[_PROVIDER], provider_cursor=0)
    w = _wizard(st)
    w.on_key(259)  # KEY_UP
    assert isinstance(w._state, AiSetupState)
    # avail = ["online", "copypaste"] (n=2), cursor wraps: (0-1)%2 = 1
    assert w._state.provider_cursor == 1


def test_mode_enter_copypaste_sets_done():
    # copypaste is the only option when no online/offline providers
    st = AiSetupState(step="mode", provider_cursor=0)
    w = _wizard(st)
    with patch("ster.ai.save_copypaste") as mock_save:
        w.on_key(ord("\n"))
    mock_save.assert_called_once_with(True)
    assert isinstance(w._state, AiSetupState)
    assert w._state.step == "done"
    assert w._state.mode == "copypaste"


def test_mode_enter_online_advances_to_provider():
    st = AiSetupState(
        step="mode",
        online_providers=[_PROVIDER],
        provider_cursor=0,
    )
    w = _wizard(st)
    with patch("ster.ai.save_copypaste"):
        w.on_key(ord("\n"))
    assert isinstance(w._state, AiSetupState)
    assert w._state.step == "provider"
    assert w._state.mode == "online"


def test_mode_enter_offline_advances_to_provider():
    st = AiSetupState(
        step="mode",
        offline_providers=[_OFFLINE_PROVIDER],
        provider_cursor=0,
    )
    w = _wizard(st)
    with patch("ster.ai.save_copypaste"):
        w.on_key(ord("\n"))
    assert isinstance(w._state, AiSetupState)
    assert w._state.step == "provider"
    assert w._state.mode == "offline"


# ── Provider step ─────────────────────────────────────────────────────────────


def test_provider_esc_returns_to_mode():
    st = AiSetupState(
        step="provider",
        mode="online",
        online_providers=[_PROVIDER],
    )
    w = _wizard(st)
    w.on_key(27)
    assert isinstance(w._state, AiSetupState)
    assert w._state.step == "mode"


def test_provider_enter_advances_to_model():
    st = AiSetupState(
        step="provider",
        mode="online",
        online_providers=[_PROVIDER],
        provider_cursor=0,
    )
    w = _wizard(st)
    w.on_key(ord("\n"))
    assert isinstance(w._state, AiSetupState)
    assert w._state.step == "model"
    assert w._state.selected_provider_id == "openai"


# ── Model step ────────────────────────────────────────────────────────────────


def test_model_enter_keyless_saves_model_and_done():
    st = AiSetupState(
        step="model",
        mode="online",
        online_providers=[_PROVIDER],
        selected_provider_id="openai",
        model_cursor=0,
    )
    w = _wizard(st)
    with (
        patch("ster.ai.model_needs_key", return_value=None),
        patch("ster.ai.save_model") as mock_save,
    ):
        w.on_key(ord("\n"))
    mock_save.assert_called_once_with("gpt-4o")
    assert isinstance(w._state, AiSetupState)
    assert w._state.step == "done"


def test_model_enter_key_required_advances_to_key():
    st = AiSetupState(
        step="model",
        mode="online",
        online_providers=[_PROVIDER],
        selected_provider_id="openai",
        model_cursor=0,
    )
    w = _wizard(st)
    with patch("ster.ai.model_needs_key", return_value="OPENAI_API_KEY"):
        w.on_key(ord("\n"))
    assert isinstance(w._state, AiSetupState)
    assert w._state.step == "key"
    assert w._state.selected_model_id == "gpt-4o"
    assert w._state.key_name == "OPENAI_API_KEY"


# ── Key step ─────────────────────────────────────────────────────────────────


def test_key_esc_saves_model_no_key_and_done():
    st = AiSetupState(
        step="key",
        selected_model_id="gpt-4o",
        key_name="OPENAI_API_KEY",
    )
    w = _wizard(st)
    with patch("ster.ai.save_model") as mock_save:
        w.on_key(27)
    mock_save.assert_called_once_with("gpt-4o")
    assert isinstance(w._state, AiSetupState)
    assert w._state.step == "done"


def test_key_enter_empty_buffer_shows_error():
    st = AiSetupState(
        step="key",
        selected_model_id="gpt-4o",
        key_name="OPENAI_API_KEY",
        buffer="",
    )
    w = _wizard(st)
    w.on_key(ord("\n"))
    assert isinstance(w._state, AiSetupState)
    assert w._state.step == "key"
    assert w._state.error != ""


def test_key_enter_value_saves_and_done():
    st = AiSetupState(
        step="key",
        selected_model_id="gpt-4o",
        key_name="OPENAI_API_KEY",
        buffer="sk-secret",
    )
    w = _wizard(st)
    with (
        patch("ster.ai.save_key") as mock_key,
        patch("ster.ai.save_model") as mock_model,
    ):
        w.on_key(ord("\n"))
    mock_key.assert_called_once_with("OPENAI_API_KEY", "sk-secret")
    mock_model.assert_called_once_with("gpt-4o")
    assert isinstance(w._state, AiSetupState)
    assert w._state.step == "done"


def test_key_typing_extends_buffer():
    st = AiSetupState(step="key", buffer="abc", pos=3)
    w = _wizard(st)
    w.on_key(ord("d"))
    assert isinstance(w._state, AiSetupState)
    assert w._state.buffer == "abcd"


# ── Done step ─────────────────────────────────────────────────────────────────


def test_done_esc_signals_done():
    w = _wizard(AiSetupState(step="done", selected_model_id="gpt-4o"))
    assert w.on_key(27) is True


def test_done_enter_signals_done():
    w = _wizard(AiSetupState(step="done", selected_model_id="gpt-4o"))
    assert w.on_key(ord("\n")) is True
