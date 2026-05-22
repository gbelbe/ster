"""Unit tests for the local/external AI model picker."""

from __future__ import annotations

from unittest.mock import patch

from ster.nav.ai_model_picker import (
    AiModelPickState,
    build_endpoint_items,
    build_external_items,
    build_local_items,
    build_top_items,
    on_key,
)

_ONLINE = [("openai", "OpenAI  (cloud)", [("gpt-4o", "GPT-4o")])]
_OFFLINE = [("llm_ollama", "Ollama  (local)", [("ollama/llama3", "llama3")])]
_OLLAMA_MODELS = ["llama3", "mistral"]


# ── build_top_items ───────────────────────────────────────────────────────────


def test_build_top_items_returns_3():
    assert len(build_top_items()) == 3


def test_build_top_items_copypaste_first():
    assert build_top_items()[0][0] == "copypaste"


def test_build_top_items_has_local():
    assert any(i[0] == "local" for i in build_top_items())


def test_build_top_items_has_external():
    assert any(i[0] == "external" for i in build_top_items())


# ── build_local_items ─────────────────────────────────────────────────────────


def test_build_local_items_includes_ollama_models():
    items = build_local_items(["llama3", "mistral"], [])
    ids = [mid for mid, _ in items]
    assert "ollama:llama3" in ids
    assert "ollama:mistral" in ids


def test_build_local_items_has_custom_option():
    items = build_local_items([], [])
    assert any(mid == "__local_custom__" for mid, _ in items)


def test_build_local_items_custom_is_last_non_install():
    items = build_local_items([], [])
    assert items[-1][0] == "__local_custom__"


def test_build_local_items_flattens_offline_providers():
    items = build_local_items([], _OFFLINE)
    ids = [mid for mid, _ in items]
    assert "ollama/llama3" in ids


def test_build_local_items_label_includes_ollama_prefix():
    items = build_local_items(["llama3"], [])
    item = next(i for i in items if i[0] == "ollama:llama3")
    assert "Ollama" in item[1]
    assert "llama3" in item[1]


# ── build_external_items ──────────────────────────────────────────────────────


def test_build_external_items_includes_provider_models():
    items = build_external_items(_ONLINE)
    ids = [mid for mid, _ in items]
    assert "gpt-4o" in ids


def test_build_external_items_has_custom_option():
    items = build_external_items([])
    assert any(mid == "__external_custom__" for mid, _ in items)


def test_build_external_items_custom_is_last():
    items = build_external_items([])
    assert items[-1][0] == "__external_custom__"


def test_build_external_items_custom_last_when_providers_exist():
    items = build_external_items(_ONLINE)
    assert items[-1][0] == "__external_custom__"


# ── Top level ─────────────────────────────────────────────────────────────────


def _top() -> AiModelPickState:
    return AiModelPickState(items=build_top_items(), level="top", cursor=0)


def test_top_esc_closes():
    _, done = on_key(_top(), 27)
    assert done


def test_top_enter_copypaste_saves_and_closes():
    with patch("ster.ai.save_copypaste") as mock_cp:
        _, done = on_key(_top(), ord("\n"))
    mock_cp.assert_called_once_with(True)
    assert done


def test_top_enter_local_switches_level():
    items = build_top_items()
    idx = next(i for i, (mid, _) in enumerate(items) if mid == "local")
    st = AiModelPickState(items=items, level="top", cursor=idx)
    with (
        patch("ster.ai.detect_ollama_models", return_value=[]),
        patch("ster.ai.is_available", return_value=False),
    ):
        new_st, done = on_key(st, ord("\n"))
    assert not done
    assert new_st.level == "local"


def test_top_enter_external_switches_level():
    items = build_top_items()
    idx = next(i for i, (mid, _) in enumerate(items) if mid == "external")
    st = AiModelPickState(items=items, level="top", cursor=idx)
    with (
        patch("ster.ai.is_available", return_value=False),
    ):
        new_st, done = on_key(st, ord("\n"))
    assert not done
    assert new_st.level == "external"


# ── Local level ───────────────────────────────────────────────────────────────


def _local(cursor: int = 0, ollama: list[str] | None = None) -> AiModelPickState:
    models = ollama or []
    return AiModelPickState(
        level="local",
        items=build_local_items(models, []),
        cursor=cursor,
        ep_return_items=build_local_items(models, []),
    )


def test_local_esc_returns_to_top():
    new_st, done = on_key(_local(), 27)
    assert not done
    assert new_st.level == "top"


def test_local_select_ollama_model_saves_endpoint_and_closes():
    items = build_local_items(["llama3"], [])
    idx = next(i for i, (mid, _) in enumerate(items) if mid == "ollama:llama3")
    st = AiModelPickState(level="local", items=items, cursor=idx)
    with patch("ster.ai.save_endpoint") as mock_save:
        _, done = on_key(st, ord("\n"))
    mock_save.assert_called_once_with("http://localhost:11434/v1", "", "llama3")
    assert done


def test_local_select_custom_opens_endpoint_form():
    items = build_local_items([], [])
    idx = next(i for i, (mid, _) in enumerate(items) if mid == "__local_custom__")
    st = AiModelPickState(level="local", items=items, cursor=idx)
    with patch("ster.ai.get_endpoint_config", return_value={}):
        new_st, done = on_key(st, ord("\n"))
    assert not done
    assert new_st.level == "endpoint"
    assert new_st.ep_return_level == "local"


def test_local_esc_from_endpoint_returns_to_local():
    local_items = build_local_items([], [])
    st = AiModelPickState(
        level="endpoint",
        items=build_endpoint_items("", "", ""),
        ep_return_level="local",
        ep_return_items=local_items,
    )
    new_st, done = on_key(st, 27)
    assert not done
    assert new_st.level == "local"
    assert new_st.items == local_items


# ── External level ────────────────────────────────────────────────────────────


def _external(cursor: int = 0, providers: list | None = None) -> AiModelPickState:
    prov = providers or []
    items = build_external_items(prov)
    return AiModelPickState(
        level="external",
        items=items,
        cursor=cursor,
        ep_return_items=items,
    )


def test_external_esc_returns_to_top():
    new_st, done = on_key(_external(), 27)
    assert not done
    assert new_st.level == "top"


def test_external_select_keyless_model_saves_and_closes():
    items = build_external_items(_ONLINE)
    idx = next(i for i, (mid, _) in enumerate(items) if mid == "gpt-4o")
    st = AiModelPickState(level="external", items=items, cursor=idx)
    with (
        patch("ster.ai.model_needs_key", return_value=None),
        patch("ster.ai.save_copypaste"),
        patch("ster.ai.save_model") as mock_save,
    ):
        _, done = on_key(st, ord("\n"))
    mock_save.assert_called_once_with("gpt-4o")
    assert done


def test_external_select_key_required_opens_prompt():
    items = build_external_items(_ONLINE)
    idx = next(i for i, (mid, _) in enumerate(items) if mid == "gpt-4o")
    st = AiModelPickState(level="external", items=items, cursor=idx)
    with (
        patch("ster.ai.model_needs_key", return_value="OPENAI_API_KEY"),
        patch("ster.ai.save_copypaste"),
    ):
        new_st, done = on_key(st, ord("\n"))
    assert not done
    assert new_st.key_prompt is True
    assert new_st.level == "external"


def test_external_select_custom_opens_endpoint_form():
    items = build_external_items([])
    idx = next(i for i, (mid, _) in enumerate(items) if mid == "__external_custom__")
    st = AiModelPickState(level="external", items=items, cursor=idx)
    with patch("ster.ai.get_endpoint_config", return_value={}):
        new_st, done = on_key(st, ord("\n"))
    assert not done
    assert new_st.level == "endpoint"
    assert new_st.ep_return_level == "external"


def test_external_esc_from_endpoint_returns_to_external():
    ext_items = build_external_items([])
    st = AiModelPickState(
        level="endpoint",
        items=build_endpoint_items("", "", ""),
        ep_return_level="external",
        ep_return_items=ext_items,
    )
    new_st, done = on_key(st, 27)
    assert not done
    assert new_st.level == "external"
    assert new_st.items == ext_items


# ── Endpoint form ─────────────────────────────────────────────────────────────


def _endpoint(url: str = "", key: str = "", model: str = "", cursor: int = 0) -> AiModelPickState:
    return AiModelPickState(
        level="endpoint",
        items=build_endpoint_items(url, key, model),
        cursor=cursor,
        ep_url=url,
        ep_key=key,
        ep_model=model,
        ep_return_level="local",
        ep_return_items=build_local_items([], []),
    )


def test_endpoint_save_valid_closes():
    save_idx = next(
        i
        for i, (mid, _) in enumerate(build_endpoint_items("http://x", "", "llama3"))
        if mid == "__save__"
    )
    st = _endpoint(url="http://x", model="llama3", cursor=save_idx)
    with patch("ster.ai.save_endpoint") as mock_save:
        _, done = on_key(st, ord("\n"))
    mock_save.assert_called_once_with("http://x", "", "llama3")
    assert done


def test_endpoint_save_without_url_shows_error():
    save_idx = next(
        i for i, (mid, _) in enumerate(build_endpoint_items("", "", "")) if mid == "__save__"
    )
    new_st, done = on_key(_endpoint(cursor=save_idx), ord("\n"))
    assert not done
    assert new_st.error != ""


# ── Key prompt ────────────────────────────────────────────────────────────────


def _key_prompt(level: str = "external") -> AiModelPickState:
    return AiModelPickState(
        level=level,
        items=build_external_items(_ONLINE),
        key_prompt=True,
        key_buffer="",
        key_name="OPENAI_API_KEY",
        key_model_id="gpt-4o",
        ep_field="",
    )


def test_key_prompt_empty_shows_error():
    new_st, done = on_key(_key_prompt(), ord("\n"))
    assert not done
    assert new_st.error != ""


def test_key_prompt_valid_saves_and_closes():
    st = AiModelPickState(
        level="external",
        items=build_external_items(_ONLINE),
        key_prompt=True,
        key_buffer="sk-secret",
        key_pos=9,
        key_name="OPENAI_API_KEY",
        key_model_id="gpt-4o",
        ep_field="",
    )
    with (
        patch("ster.ai.save_key") as mock_key,
        patch("ster.ai.save_model") as mock_model,
    ):
        _, done = on_key(st, ord("\n"))
    mock_key.assert_called_once_with("OPENAI_API_KEY", "sk-secret")
    mock_model.assert_called_once_with("gpt-4o")
    assert done


def test_key_prompt_esc_returns_to_list():
    new_st, done = on_key(_key_prompt(), 27)
    assert not done
    assert new_st.key_prompt is False
    assert new_st.level == "external"


# ── Navigation ────────────────────────────────────────────────────────────────


def test_down_increments_cursor():
    new_st, done = on_key(_top(), 258)
    assert not done
    assert new_st.cursor == 1


def test_up_clamps_at_zero():
    new_st, done = on_key(_top(), 259)
    assert not done
    assert new_st.cursor == 0
