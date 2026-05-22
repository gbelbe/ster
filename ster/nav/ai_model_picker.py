"""AI model picker — local / external split.

Top level offers three paths:
  copypaste  — build the prompt and paste it into any LLM manually
  local      — Ollama auto-detected models, LM Studio, or any local server
  external   — OpenAI, Anthropic, or any remote OpenAI-compatible API
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from dataclasses import field as dc_field


@dataclass
class AiModelPickState:
    level: str = "top"  # "top" | "local" | "external" | "endpoint"
    items: list[tuple[str, str]] = dc_field(default_factory=list)
    cursor: int = 0
    scroll: int = 0
    # Shared text-input prompt (endpoint field edit OR provider API-key entry)
    key_prompt: bool = False
    key_buffer: str = ""
    key_pos: int = 0
    key_name: str = ""  # label shown in the prompt
    key_model_id: str = ""  # provider model id being configured
    error: str = ""
    # Endpoint form fields
    ep_url: str = ""
    ep_key: str = ""
    ep_model: str = ""
    ep_field: str = ""  # which field is being edited: "url"|"key"|"model"|""
    ep_return_level: str = ""  # "local"|"external" — where Esc returns to
    ep_return_items: list[tuple[str, str]] = dc_field(default_factory=list)


def build_top_items() -> list[tuple[str, str]]:
    return [
        ("copypaste", "📋  Copy-paste  — paste the prompt into any AI"),
        ("local", "🖥  Local model  — Ollama, LM Studio, or any local server"),
        ("external", "☁   External model  — OpenAI, Anthropic, or any remote API"),
    ]


def build_local_items(
    ollama_models: list[str],
    offline_providers: list[tuple[str, str, list[tuple[str, str]]]],
) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for m in ollama_models:
        items.append((f"ollama:{m}", f"Ollama  —  {m}"))
    for _pid, plabel, models in offline_providers:
        pname = plabel.split("  ")[0]
        for mid, mlabel in models:
            items.append((mid, f"{pname}  —  {mlabel}"))
    items.append(("__local_custom__", "Custom local server…"))
    return items


def build_external_items(
    online_providers: list[tuple[str, str, list[tuple[str, str]]]],
) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for _pid, plabel, models in online_providers:
        pname = plabel.split("  ")[0]
        for mid, mlabel in models:
            items.append((mid, f"{pname}  —  {mlabel}"))
    items.append(("__external_custom__", "Custom remote endpoint…"))
    return items


def build_endpoint_items(url: str, key: str, model: str) -> list[tuple[str, str]]:
    url_label = url if url else "(not set)"
    key_label = "***" if key else "(optional)"
    model_label = model if model else "(not set)"
    return [
        ("ep:url", f"Endpoint URL    {url_label}"),
        ("ep:key", f"API key         {key_label}"),
        ("ep:model", f"Model name      {model_label}"),
        ("__save__", "Save"),
    ]


def on_key(st: AiModelPickState, key: int) -> tuple[AiModelPickState, bool]:  # noqa: C901
    """Process a key press. Return (new_state, done). done=True closes the picker."""
    from .. import ai

    def _s(**kw: object) -> AiModelPickState:
        return dataclasses.replace(st, **kw)  # type: ignore[arg-type]

    # ── Shared text-input prompt ───────────────────────────────────────────────
    if st.key_prompt:
        if key == 27:  # Esc → discard, stay in current level
            return _s(
                key_prompt=False, key_buffer="", key_pos=0, key_name="", ep_field="", error=""
            ), False

        if key in (ord("\n"), ord("\r"), 343):  # Enter → confirm
            value = st.key_buffer.strip()
            if st.ep_field:  # editing an endpoint field
                if st.ep_field == "url":
                    new = _s(
                        ep_url=value,
                        key_prompt=False,
                        key_buffer="",
                        key_pos=0,
                        ep_field="",
                        error="",
                    )
                elif st.ep_field == "key":
                    new = _s(
                        ep_key=value,
                        key_prompt=False,
                        key_buffer="",
                        key_pos=0,
                        ep_field="",
                        error="",
                    )
                else:  # "model"
                    new = _s(
                        ep_model=value,
                        key_prompt=False,
                        key_buffer="",
                        key_pos=0,
                        ep_field="",
                        error="",
                    )
                rebuilt = build_endpoint_items(new.ep_url, new.ep_key, new.ep_model)
                return dataclasses.replace(new, items=rebuilt), False

            # provider API key
            if not value:
                return _s(error="Enter a key value or press Esc to go back"), False
            ai.save_key(st.key_name, value)
            ai.save_model(st.key_model_id)
            return st, True

        if key in (263, 127, 8):  # Backspace variants
            buf = st.key_buffer[: st.key_pos - 1] + st.key_buffer[st.key_pos :]
            return _s(key_buffer=buf, key_pos=max(0, st.key_pos - 1), error=""), False
        if key == 260:  # KEY_LEFT
            return _s(key_pos=max(0, st.key_pos - 1)), False
        if key == 261:  # KEY_RIGHT
            return _s(key_pos=min(len(st.key_buffer), st.key_pos + 1)), False
        if 32 <= key < 256:
            buf = st.key_buffer[: st.key_pos] + chr(key) + st.key_buffer[st.key_pos :]
            return _s(key_buffer=buf, key_pos=st.key_pos + 1, error=""), False
        return st, False

    n = len(st.items)

    # ── Common navigation ──────────────────────────────────────────────────────
    if key in (259, ord("k")):  # KEY_UP
        c = max(0, st.cursor - 1)
        return _s(cursor=c, scroll=min(st.scroll, c), error=""), False
    if key in (258, ord("j")):  # KEY_DOWN
        c = min(n - 1, st.cursor + 1)
        return _s(cursor=c, scroll=max(st.scroll, c - 8), error=""), False

    # ── Top level ──────────────────────────────────────────────────────────────
    if st.level == "top":
        if key == 27:
            return st, True

        if key in (ord("\n"), ord("\r"), 343):
            if not st.items:
                return st, False
            mid, _ = st.items[st.cursor]

            if mid == "copypaste":
                ai.save_copypaste(True)
                return st, True

            if mid == "local":
                ollama = ai.detect_ollama_models()
                _, offline = ai.discover_models() if ai.is_available() else ([], [])
                items = build_local_items(ollama, offline)
                return _s(
                    level="local", items=items, cursor=0, scroll=0, ep_return_items=items, error=""
                ), False

            if mid == "external":
                online, _ = ai.discover_models() if ai.is_available() else ([], [])
                items = build_external_items(online)
                return _s(
                    level="external",
                    items=items,
                    cursor=0,
                    scroll=0,
                    ep_return_items=items,
                    error="",
                ), False

        return st, False

    # ── Local level ────────────────────────────────────────────────────────────
    if st.level == "local":
        if key == 27:  # Esc → back to top, highlight "local"
            top_items = build_top_items()
            local_idx = next(i for i, (mid, _) in enumerate(top_items) if mid == "local")
            return _s(level="top", items=top_items, cursor=local_idx, scroll=0, error=""), False

        if key in (ord("\n"), ord("\r"), 343):
            if not st.items:
                return st, False
            mid, _ = st.items[st.cursor]

            if mid.startswith("ollama:"):
                model_name = mid[7:]
                ai.save_endpoint("http://localhost:11434/v1", "", model_name)
                return st, True

            if mid == "__local_custom__":
                ep = ai.get_endpoint_config()
                url, k, m = ep.get("url", ""), ep.get("key", ""), ep.get("model", "")
                return _s(
                    level="endpoint",
                    items=build_endpoint_items(url, k, m),
                    cursor=0,
                    ep_url=url,
                    ep_key=k,
                    ep_model=m,
                    ep_return_level="local",
                    ep_return_items=st.items,
                    error="",
                ), False

            if mid == "__install__":
                ollama = ai.detect_ollama_models()
                _, offline = ai.discover_models() if ai.is_available() else ([], [])
                items = build_local_items(ollama, offline)
                return _s(items=items, cursor=0, scroll=0, ep_return_items=items, error=""), False

            # llm plugin local model
            ai.save_copypaste(False)
            key_name = ai.model_needs_key(mid)
            if key_name:
                return _s(
                    key_prompt=True,
                    key_buffer="",
                    key_pos=0,
                    key_name=key_name,
                    key_model_id=mid,
                    ep_field="",
                    error="",
                ), False
            ai.save_model(mid)
            return st, True

        return st, False

    # ── External level ─────────────────────────────────────────────────────────
    if st.level == "external":
        if key == 27:  # Esc → back to top, highlight "external"
            top_items = build_top_items()
            ext_idx = next(i for i, (mid, _) in enumerate(top_items) if mid == "external")
            return _s(level="top", items=top_items, cursor=ext_idx, scroll=0, error=""), False

        if key in (ord("\n"), ord("\r"), 343):
            if not st.items:
                return st, False
            mid, _ = st.items[st.cursor]

            if mid == "__external_custom__":
                ep = ai.get_endpoint_config()
                url, k, m = ep.get("url", ""), ep.get("key", ""), ep.get("model", "")
                return _s(
                    level="endpoint",
                    items=build_endpoint_items(url, k, m),
                    cursor=0,
                    ep_url=url,
                    ep_key=k,
                    ep_model=m,
                    ep_return_level="external",
                    ep_return_items=st.items,
                    error="",
                ), False

            if mid == "__install__":
                online, _ = ai.discover_models() if ai.is_available() else ([], [])
                items = build_external_items(online)
                return _s(items=items, cursor=0, scroll=0, ep_return_items=items, error=""), False

            # llm plugin cloud model
            ai.save_copypaste(False)
            key_name = ai.model_needs_key(mid)
            if key_name:
                return _s(
                    key_prompt=True,
                    key_buffer="",
                    key_pos=0,
                    key_name=key_name,
                    key_model_id=mid,
                    ep_field="",
                    error="",
                ), False
            ai.save_model(mid)
            return st, True

        return st, False

    # ── Endpoint form ──────────────────────────────────────────────────────────
    if st.level == "endpoint":
        if key == 27:  # Esc → back to whichever sub-level opened the form
            return _s(
                level=st.ep_return_level or "top",
                items=st.ep_return_items if st.ep_return_items else build_top_items(),
                cursor=0,
                scroll=0,
                ep_return_level="",
                error="",
            ), False

        if key in (ord("\n"), ord("\r"), 343):
            if not st.items:
                return st, False
            mid, _ = st.items[st.cursor]

            if mid in ("ep:url", "ep:key", "ep:model"):
                field = mid.split(":")[1]
                cur_val = {"url": st.ep_url, "key": st.ep_key, "model": st.ep_model}[field]
                return _s(
                    key_prompt=True,
                    ep_field=field,
                    key_name=field.capitalize(),
                    key_buffer=cur_val,
                    key_pos=len(cur_val),
                    error="",
                ), False

            if mid == "__save__":
                if not st.ep_url.strip() or not st.ep_model.strip():
                    return _s(error="Endpoint URL and model name are required"), False
                ai.save_endpoint(st.ep_url.strip(), st.ep_key.strip(), st.ep_model.strip())
                return st, True

        return st, False

    return st, False
