"""BDD step definitions for the AI configuration wizard scenarios."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios("../features/ui/ai_config_screen.feature")

_PROVIDER = ("openai", "OpenAI  (cloud)", [("gpt-4o", "GPT-4o")])


def _wizard(state):
    from ster.ai_config_screen import AiConfigWizard
    from ster.nav.state import AiInstallState, AiSetupState  # noqa: F401

    w = AiConfigWizard.__new__(AiConfigWizard)
    w._state = state
    w._install_thread = None
    w._install_output = []
    w._install_returncode = None
    w._install_spinner = 0
    w._install_package = "llm"
    w._install_command = None
    return w


@pytest.fixture
def ctx():
    return {"wizard": None, "result": None}


# ── Given ─────────────────────────────────────────────────────────────────────


@given("the llm package is available")
def given_llm_available(ctx):
    ctx["llm_available"] = True


@given("the llm package is not available")
def given_llm_unavailable(ctx):
    ctx["llm_available"] = False


@given('a wizard at the "mode" step')
def given_mode_step(ctx):
    from ster.nav.state import AiSetupState

    ctx["wizard"] = _wizard(AiSetupState(step="mode"))


@given('a wizard at the "mode" step with copy-paste as only option')
def given_mode_step_copypaste_only(ctx):
    from ster.nav.state import AiSetupState

    ctx["wizard"] = _wizard(AiSetupState(step="mode", provider_cursor=0))


@given('a wizard at the "mode" step with an online provider')
def given_mode_step_online(ctx):
    from ster.nav.state import AiSetupState

    ctx["wizard"] = _wizard(
        AiSetupState(step="mode", online_providers=[_PROVIDER], provider_cursor=0)
    )


@given('a wizard at the "provider" step')
def given_provider_step(ctx):
    from ster.nav.state import AiSetupState

    ctx["wizard"] = _wizard(
        AiSetupState(step="provider", mode="online", online_providers=[_PROVIDER])
    )


@given('a wizard at the "provider" step with one provider')
def given_provider_step_one(ctx):
    from ster.nav.state import AiSetupState

    ctx["wizard"] = _wizard(
        AiSetupState(
            step="provider",
            mode="online",
            online_providers=[_PROVIDER],
            provider_cursor=0,
        )
    )


@given('a wizard at the "model" step with a keyless model')
def given_model_step_keyless(ctx):
    from ster.nav.state import AiSetupState

    ctx["wizard"] = _wizard(
        AiSetupState(
            step="model",
            mode="online",
            online_providers=[_PROVIDER],
            selected_provider_id="openai",
            model_cursor=0,
        )
    )
    ctx["model_needs_key"] = None


@given('a wizard at the "model" step with a key-required model')
def given_model_step_key_required(ctx):
    from ster.nav.state import AiSetupState

    ctx["wizard"] = _wizard(
        AiSetupState(
            step="model",
            mode="online",
            online_providers=[_PROVIDER],
            selected_provider_id="openai",
            model_cursor=0,
        )
    )
    ctx["model_needs_key"] = "OPENAI_API_KEY"


@given('a wizard at the "key" step for model "claude-3-opus"')
def given_key_step(ctx):
    from ster.nav.state import AiSetupState

    ctx["wizard"] = _wizard(
        AiSetupState(
            step="key",
            selected_model_id="claude-3-opus",
            key_name="ANTHROPIC_API_KEY",
            buffer="",
            pos=0,
        )
    )


@given('the key buffer contains "sk-test-123"')
def given_key_buffer(ctx):
    from ster.nav.state import AiSetupState

    st = ctx["wizard"]._state
    assert isinstance(st, AiSetupState)
    ctx["wizard"]._state = AiSetupState(
        step=st.step,
        selected_model_id=st.selected_model_id,
        key_name=st.key_name,
        buffer="sk-test-123",
        pos=len("sk-test-123"),
        online_providers=st.online_providers,
        offline_providers=st.offline_providers,
        mode=st.mode,
        provider_cursor=st.provider_cursor,
        provider_scroll=st.provider_scroll,
        model_cursor=st.model_cursor,
        model_scroll=st.model_scroll,
        selected_provider_id=st.selected_provider_id,
        error=st.error,
        pending_action=st.pending_action,
    )


# ── When ──────────────────────────────────────────────────────────────────────


@when("an AI config wizard is created")
def when_create_wizard(ctx):
    from ster.ai_config_screen import AiConfigWizard

    llm_available = ctx.get("llm_available", True)
    with (
        patch("ster.ai.is_available", return_value=llm_available),
        patch("ster.ai.discover_models", return_value=([_PROVIDER], [])),
        patch("ster.ai.is_copypaste", return_value=False),
    ):
        ctx["wizard"] = AiConfigWizard()


@when("I press Esc on the wizard")
def when_press_esc(ctx):
    ctx["result"] = ctx["wizard"].on_key(27)


@when("I press Enter on the wizard")
def when_press_enter(ctx):
    key_patch = ctx.get("model_needs_key")
    if key_patch is not None:
        with (
            patch("ster.ai.model_needs_key", return_value=key_patch),
            patch("ster.ai.save_model"),
        ):
            ctx["result"] = ctx["wizard"].on_key(ord("\n"))
    else:
        with (
            patch("ster.ai.save_copypaste"),
            patch("ster.ai.save_model"),
            patch("ster.ai.save_key"),
        ):
            ctx["result"] = ctx["wizard"].on_key(ord("\n"))


# ── Then ──────────────────────────────────────────────────────────────────────


@then('the wizard state step is "mode"')
def then_step_mode(ctx):
    from ster.nav.state import AiSetupState

    assert isinstance(ctx["wizard"]._state, AiSetupState)
    assert ctx["wizard"]._state.step == "mode"


@then("the wizard is in the install state")
def then_install_state(ctx):
    from ster.nav.state import AiInstallState

    assert isinstance(ctx["wizard"]._state, AiInstallState)


@then("the wizard on_key returns done")
def then_returns_done(ctx):
    assert ctx["result"] is True


@then('the wizard state step is "done"')
def then_step_done(ctx):
    from ster.nav.state import AiSetupState

    assert isinstance(ctx["wizard"]._state, AiSetupState)
    assert ctx["wizard"]._state.step == "done"


@then('the wizard mode is "copypaste"')
def then_mode_copypaste(ctx):
    from ster.nav.state import AiSetupState

    assert isinstance(ctx["wizard"]._state, AiSetupState)
    assert ctx["wizard"]._state.mode == "copypaste"


@then('the wizard state step is "provider"')
def then_step_provider(ctx):
    from ster.nav.state import AiSetupState

    assert isinstance(ctx["wizard"]._state, AiSetupState)
    assert ctx["wizard"]._state.step == "provider"


@then('the wizard mode is "online"')
def then_mode_online(ctx):
    from ster.nav.state import AiSetupState

    assert isinstance(ctx["wizard"]._state, AiSetupState)
    assert ctx["wizard"]._state.mode == "online"


@then('the wizard state step is "model"')
def then_step_model(ctx):
    from ster.nav.state import AiSetupState

    assert isinstance(ctx["wizard"]._state, AiSetupState)
    assert ctx["wizard"]._state.step == "model"


@then('the wizard state step is "key"')
def then_step_key(ctx):
    from ster.nav.state import AiSetupState

    assert isinstance(ctx["wizard"]._state, AiSetupState)
    assert ctx["wizard"]._state.step == "key"


@then("the wizard shows an error")
def then_shows_error(ctx):
    from ster.nav.state import AiSetupState

    assert isinstance(ctx["wizard"]._state, AiSetupState)
    assert ctx["wizard"]._state.error != ""
