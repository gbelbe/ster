"""Inline LLM setup embedded in the configuration modal.

A **Select** chooses the AI mode (no model / copy-paste / local / external); the
mode reveals contextual sub-options below — a second Select of models (with a
"Custom…" entry that opens an endpoint form), or an info line. On open the controls
are pre-selected from the saved configuration. Choices persist through ``ster.ai``.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Input, Select, Static

from ster.nav.ai_model_picker import build_external_items

from .edit_modal import EditModal

_MODES = (
    ("no_model", "No model configured"),
    ("copypaste", "Copy-Paste prompt mode"),
    ("local", "Local Model"),
    ("external", "External Model"),
)


def _current_mode() -> str:
    from ster import ai

    if ai.is_copypaste():
        return "copypaste"
    endpoint = ai.get_endpoint_config()
    if endpoint.get("url") and endpoint.get("model"):
        host = endpoint["url"]
        return "local" if ("localhost" in host or "127.0.0.1" in host) else "external"
    if ai.get_saved_model():
        return "external"
    return "no_model"


def _current_model() -> str | None:
    """The configured model id, as the value used in the secondary Select."""
    from ster import ai

    endpoint = ai.get_endpoint_config()
    if endpoint.get("model"):
        host = endpoint.get("url", "")
        if "localhost" in host or "127.0.0.1" in host:
            return f"ollama:{endpoint['model']}"
        return endpoint["model"]
    return ai.get_saved_model()


class LlmSetup(Vertical):
    """Mode Select + a contextual model Select / endpoint form for the LLM."""

    DEFAULT_CSS = """
    LlmSetup { height: auto; }
    #llm-mode-select { width: 1fr; margin-bottom: 1; }
    #llm-sub { height: auto; }
    /* Select borders — same style as the config "Display theme" dropdown. */
    #llm-mode-select > SelectCurrent, #llm-mode-select:focus > SelectCurrent,
    #llm-local-select > SelectCurrent, #llm-local-select:focus > SelectCurrent,
    #llm-ext-select > SelectCurrent, #llm-ext-select:focus > SelectCurrent { border: round $primary; }
    #llm-mode-select SelectOverlay,
    #llm-local-select SelectOverlay,
    #llm-ext-select SelectOverlay { border: round $primary; }
    #llm-sub Select { width: 1fr; margin-bottom: 1; }
    #llm-sub Input { border: round $primary; margin-bottom: 1; }
    #llm-save-ep { border: none; background: $primary; color: $background; width: auto; min-width: 16; }
    """

    def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)
        self._ready = False
        self._mode: str | None = None  # last-built mode (skip rebuilding the same one)

    def compose(self) -> ComposeResult:
        yield Static("AI mode", classes="cfg-label")
        yield Select(
            [(label, value) for value, label in _MODES],
            value=_current_mode(),
            allow_blank=False,
            id="llm-mode-select",
        )
        yield Vertical(id="llm-sub")

    def on_mount(self) -> None:
        self._build_sub(_current_mode(), preselect=_current_model())
        self._ready = True

    # ── mode selection ──────────────────────────────────────────────────────────
    @on(Select.Changed, "#llm-mode-select")
    def _on_mode(self, event: Select.Changed) -> None:
        if self._ready and str(event.value) != self._mode:
            self._build_sub(str(event.value))

    def _build_sub(self, mode: str, *, preselect: str | None = None) -> None:
        self._mode = mode
        self.query_one("#llm-sub", Vertical).remove_children()
        builder = {
            "no_model": self._build_no_model,
            "copypaste": self._build_copypaste,
            "local": self._build_local,
            "external": self._build_external,
        }[mode]
        builder(preselect)

    def _build_no_model(self, preselect: str | None) -> None:
        from ster import ai

        ai.clear_model()  # persist the "no model" choice
        self._info("No AI model configured — pick a mode above.")

    def _build_copypaste(self, preselect: str | None) -> None:
        from ster import ai

        ai.save_copypaste(True)
        self._info("The prompt is copied for you to paste into any AI.")

    def _build_local(self, preselect: str | None) -> None:
        from ster import ai

        options = [(f"Ollama — {m}", f"ollama:{m}") for m in ai.detect_ollama_models()]
        if preselect and preselect.startswith("ollama:"):  # keep the saved model selectable
            self._ensure_option(options, f"Ollama — {preselect[7:]}", preselect)
        options.append(("Custom local server…", "__custom__"))
        self._mount_model_select("llm-local-select", options, preselect)

    def _build_external(self, preselect: str | None) -> None:
        from ster import ai

        online, _offline = ai.discover_models() if ai.is_available() else ([], [])
        options = [
            (label, mid) for mid, label in build_external_items(online) if not mid.startswith("__")
        ]
        if preselect:  # keep the saved model selectable even if discovery is empty
            self._ensure_option(options, preselect, preselect)
        options.append(("Custom remote endpoint…", "__custom__"))
        self._mount_model_select("llm-ext-select", options, preselect)

    def _info(self, text: str) -> None:
        self.query_one("#llm-sub", Vertical).mount(Static(text, classes="cfg-hint"))

    @staticmethod
    def _ensure_option(options: list, label: str, value: str) -> None:
        if value not in [v for _label, v in options]:
            options.insert(0, (label, value))

    def _mount_model_select(self, select_id: str, options: list, preselect: str | None) -> None:
        # Pre-select via the constructor (reliable) — the saved model is always present.
        # Only pass ``value`` for a real selection; ``Select.BLANK`` can't be passed in.
        if preselect in [value for _label, value in options]:
            select = Select(options, prompt="Choose a model", value=preselect, id=select_id)
        else:
            select = Select(options, prompt="Choose a model", id=select_id)
        self.query_one("#llm-sub", Vertical).mount(select)

    # ── sub-option selection ────────────────────────────────────────────────────
    @on(Select.Changed, "#llm-local-select")
    def _on_local_select(self, event: Select.Changed) -> None:
        value = event.value
        if value is Select.BLANK or value == _current_model():
            return  # blank, or the already-saved pre-selection (don't re-save)
        if value == "__custom__":
            self._build_custom("local")
        elif isinstance(value, str) and value.startswith("ollama:"):
            self._save_local(value[7:])

    @on(Select.Changed, "#llm-ext-select")
    def _on_ext_select(self, event: Select.Changed) -> None:
        value = event.value
        if value is Select.BLANK or value == _current_model():
            return  # blank, or the already-saved pre-selection (don't re-prompt for a key)
        if value == "__custom__":
            self._build_custom("external")
        elif isinstance(value, str):
            self._choose_model(value)

    def _build_custom(self, mode: str) -> None:
        sub = self.query_one("#llm-sub", Vertical)
        sub.remove_children()
        from ster import ai

        endpoint = ai.get_endpoint_config()
        widgets: list = [
            Input(value=endpoint.get("url", ""), placeholder="Endpoint URL", id="ep-url")
        ]
        if mode == "external":
            widgets.append(Input(placeholder="API key (optional)", password=True, id="ep-key"))
        widgets.append(
            Input(value=endpoint.get("model", ""), placeholder="Model name", id="ep-model")
        )
        widgets.append(Button("✔ Save endpoint", id="llm-save-ep"))
        sub.mount(*widgets)

    @on(Button.Pressed, "#llm-save-ep")
    def _on_save_endpoint(self, event: Button.Pressed) -> None:
        self._save_endpoint()

    # ── persistence ─────────────────────────────────────────────────────────────
    def _save_local(self, model: str) -> None:
        from ster import ai

        ai.save_copypaste(False)
        ai.save_endpoint("http://localhost:11434/v1", "", model)
        self.notify(f"LLM: local model «{model}».")

    def _choose_model(self, model_id: str) -> None:
        from ster import ai

        ai.save_copypaste(False)
        key_name = ai.model_needs_key(model_id)
        if not key_name:
            ai.save_model(model_id)
            self.notify(f"LLM: model «{model_id}».")
            return

        def _on_key(value: str | None) -> None:
            if value:
                ai.save_key(key_name, value)
                ai.save_model(model_id)
                self.notify(f"LLM: model «{model_id}».")

        self.app.push_screen(EditModal(f"API key for {key_name}", ""), _on_key)

    def _save_endpoint(self) -> None:
        from ster import ai

        url = self.query_one("#ep-url", Input).value.strip()
        key = self.query("#ep-key").first(Input).value.strip() if self.query("#ep-key") else ""
        model = self.query_one("#ep-model", Input).value.strip()
        if not (url and model):
            self.notify("Endpoint URL and model name are required.", severity="error")
            return
        ai.save_copypaste(False)
        ai.save_endpoint(url, key, model)
        self.notify("LLM: custom endpoint saved.")
