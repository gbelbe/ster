"""BDD step definitions for the local/external AI model picker."""

from __future__ import annotations

import dataclasses
from unittest.mock import patch

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios("../features/ui/ai_model_picker.feature")

_ONLINE = [("openai", "OpenAI  (cloud)", [("gpt-4o", "GPT-4o")])]


@pytest.fixture
def ctx():
    return {"state": None, "done": None}


# ── Given ──────────────────────────────────────────────────────────────────────


@given("the picker starts at the top level")
def given_top(ctx):
    from ster.nav.ai_model_picker import AiModelPickState, build_top_items

    ctx["state"] = AiModelPickState(items=build_top_items(), level="top", cursor=0)


@given('the cursor is on "copypaste"')
def given_cursor_copypaste(ctx):
    items = ctx["state"].items
    idx = next(i for i, (mid, _) in enumerate(items) if mid == "copypaste")
    ctx["state"] = dataclasses.replace(ctx["state"], cursor=idx)


@given('the cursor is on "local"')
def given_cursor_local(ctx):
    items = ctx["state"].items
    idx = next(i for i, (mid, _) in enumerate(items) if mid == "local")
    ctx["state"] = dataclasses.replace(ctx["state"], cursor=idx)


@given('the cursor is on "external"')
def given_cursor_external(ctx):
    items = ctx["state"].items
    idx = next(i for i, (mid, _) in enumerate(items) if mid == "external")
    ctx["state"] = dataclasses.replace(ctx["state"], cursor=idx)


@given("the picker is at local level")
def given_local_level(ctx):
    from ster.nav.ai_model_picker import AiModelPickState, build_local_items

    items = build_local_items([], [])
    ctx["state"] = AiModelPickState(level="local", items=items, cursor=0, ep_return_items=items)


@given("the picker is at local level with a detected Ollama model")
def given_local_ollama(ctx):
    from ster.nav.ai_model_picker import AiModelPickState, build_local_items

    items = build_local_items(["llama3"], [])
    idx = next(i for i, (mid, _) in enumerate(items) if mid == "ollama:llama3")
    ctx["state"] = AiModelPickState(level="local", items=items, cursor=idx, ep_return_items=items)


@given("the picker is at local level with cursor on custom local")
def given_local_custom(ctx):
    from ster.nav.ai_model_picker import AiModelPickState, build_local_items

    items = build_local_items([], [])
    idx = next(i for i, (mid, _) in enumerate(items) if mid == "__local_custom__")
    ctx["state"] = AiModelPickState(level="local", items=items, cursor=idx, ep_return_items=items)


@given("the picker is at external level")
def given_external_level(ctx):
    from ster.nav.ai_model_picker import AiModelPickState, build_external_items

    items = build_external_items([])
    ctx["state"] = AiModelPickState(level="external", items=items, cursor=0, ep_return_items=items)


@given("the picker is at external level with cursor on a keyless model")
def given_external_keyless(ctx):
    from ster.nav.ai_model_picker import AiModelPickState, build_external_items

    items = build_external_items(_ONLINE)
    idx = next(i for i, (mid, _) in enumerate(items) if mid == "gpt-4o")
    ctx["state"] = AiModelPickState(
        level="external", items=items, cursor=idx, ep_return_items=items
    )
    ctx["model_needs_key"] = None


@given("the picker is at external level with cursor on a key-required model")
def given_external_key_required(ctx):
    from ster.nav.ai_model_picker import AiModelPickState, build_external_items

    items = build_external_items(_ONLINE)
    idx = next(i for i, (mid, _) in enumerate(items) if mid == "gpt-4o")
    ctx["state"] = AiModelPickState(
        level="external", items=items, cursor=idx, ep_return_items=items
    )
    ctx["model_needs_key"] = "OPENAI_API_KEY"


@given("the picker is at external level with cursor on custom external")
def given_external_custom(ctx):
    from ster.nav.ai_model_picker import AiModelPickState, build_external_items

    items = build_external_items([])
    idx = next(i for i, (mid, _) in enumerate(items) if mid == "__external_custom__")
    ctx["state"] = AiModelPickState(
        level="external", items=items, cursor=idx, ep_return_items=items
    )


@given("the picker is at endpoint level entered from local")
def given_endpoint_from_local(ctx):
    from ster.nav.ai_model_picker import AiModelPickState, build_endpoint_items, build_local_items

    local_items = build_local_items([], [])
    ctx["state"] = AiModelPickState(
        level="endpoint",
        items=build_endpoint_items("", "", ""),
        cursor=0,
        ep_return_level="local",
        ep_return_items=local_items,
    )


@given("the picker is at endpoint level entered from external")
def given_endpoint_from_external(ctx):
    from ster.nav.ai_model_picker import (
        AiModelPickState,
        build_endpoint_items,
        build_external_items,
    )

    ext_items = build_external_items([])
    ctx["state"] = AiModelPickState(
        level="endpoint",
        items=build_endpoint_items("", "", ""),
        cursor=0,
        ep_return_level="external",
        ep_return_items=ext_items,
    )


@given("the picker is at endpoint level with URL and model filled in")
def given_endpoint_filled(ctx):
    from ster.nav.ai_model_picker import AiModelPickState, build_endpoint_items, build_local_items

    items = build_endpoint_items("http://localhost:11434/v1", "", "llama3")
    save_idx = next(i for i, (mid, _) in enumerate(items) if mid == "__save__")
    ctx["state"] = AiModelPickState(
        level="endpoint",
        items=items,
        cursor=save_idx,
        ep_url="http://localhost:11434/v1",
        ep_model="llama3",
        ep_return_level="local",
        ep_return_items=build_local_items([], []),
    )


@given("the picker is at endpoint level with empty URL and model")
def given_endpoint_empty(ctx):
    from ster.nav.ai_model_picker import AiModelPickState, build_endpoint_items, build_local_items

    items = build_endpoint_items("", "", "")
    save_idx = next(i for i, (mid, _) in enumerate(items) if mid == "__save__")
    ctx["state"] = AiModelPickState(
        level="endpoint",
        items=items,
        cursor=save_idx,
        ep_return_level="local",
        ep_return_items=build_local_items([], []),
    )


@given("the picker is in key prompt mode")
def given_key_prompt(ctx):
    from ster.nav.ai_model_picker import AiModelPickState, build_external_items

    ctx["state"] = AiModelPickState(
        level="external",
        items=build_external_items(_ONLINE),
        key_prompt=True,
        key_buffer="",
        key_name="OPENAI_API_KEY",
        key_model_id="gpt-4o",
        ep_field="",
    )


@given('the picker is in key prompt mode with "sk-test" in the buffer')
def given_key_prompt_filled(ctx):
    from ster.nav.ai_model_picker import AiModelPickState, build_external_items

    ctx["state"] = AiModelPickState(
        level="external",
        items=build_external_items(_ONLINE),
        key_prompt=True,
        key_buffer="sk-test",
        key_pos=7,
        key_name="OPENAI_API_KEY",
        key_model_id="gpt-4o",
        ep_field="",
    )


# ── When ───────────────────────────────────────────────────────────────────────


@when("I press Esc on the picker")
def when_esc(ctx):
    from ster.nav.ai_model_picker import on_key

    ctx["state"], ctx["done"] = on_key(ctx["state"], 27)


@when("I press Enter on the picker")
def when_enter(ctx):
    from ster.nav.ai_model_picker import on_key

    needs_key = ctx.get("model_needs_key")

    with (
        patch("ster.ai.save_copypaste"),
        patch("ster.ai.save_model"),
        patch("ster.ai.save_key"),
        patch("ster.ai.save_endpoint"),
        patch("ster.ai.get_endpoint_config", return_value={}),
        patch("ster.ai.is_available", return_value=True),
        patch("ster.ai.detect_ollama_models", return_value=["llama3"]),
        patch("ster.ai.discover_models", return_value=(_ONLINE, [])),
        patch("ster.ai.model_needs_key", return_value=needs_key),
    ):
        ctx["state"], ctx["done"] = on_key(ctx["state"], ord("\n"))


# ── Then ───────────────────────────────────────────────────────────────────────


@then("the picker signals done")
def then_done(ctx):
    assert ctx["done"] is True


@then("the picker is not done")
def then_not_done(ctx):
    assert ctx["done"] is False


@then("the picker has 3 items")
def then_3_items(ctx):
    assert len(ctx["state"].items) == 3


@then('the first item id is "copypaste"')
def then_first_copypaste(ctx):
    assert ctx["state"].items[0][0] == "copypaste"


@then('the items include id "local"')
def then_has_local(ctx):
    assert any(mid == "local" for mid, _ in ctx["state"].items)


@then('the items include id "external"')
def then_has_external(ctx):
    assert any(mid == "external" for mid, _ in ctx["state"].items)


@then('the picker level is "top"')
def then_level_top(ctx):
    assert ctx["state"].level == "top"


@then('the picker level is "local"')
def then_level_local(ctx):
    assert ctx["state"].level == "local"


@then('the picker level is "external"')
def then_level_external(ctx):
    assert ctx["state"].level == "external"


@then('the picker level is "endpoint"')
def then_level_endpoint(ctx):
    assert ctx["state"].level == "endpoint"


@then("the picker is in key prompt mode")
def then_key_prompt(ctx):
    assert ctx["state"].key_prompt is True


@then("the picker is back in list mode")
def then_list_mode(ctx):
    assert ctx["state"].key_prompt is False


@then("the picker shows a validation error")
def then_error(ctx):
    assert ctx["state"].error != ""
