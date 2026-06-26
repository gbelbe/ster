"""Global configuration modal for the Textual TUI.

Opened with a shortcut. Everything auto-saves — there is no Save button; each
change (display language, theme, a toggled/added language) posts a
:class:`ConfigModal.Changed` message that the app applies and persists. Esc closes.

The configured-languages block is a single Tab stop: Tab from it jumps to
"Configure LLM"; inside, the arrow keys move between the checkboxes, the narrow
"add" field and its button. The theme dropdown applies live.
"""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Select,
    Static,
    TabbedContent,
    TabPane,
    Tabs,
)

from .focus_group import FocusGroup
from .llm_group import LlmSetup
from .modal import ModalBase

# Common namespaces → prefix, for suggesting a label when registering a predicate.
_KNOWN_PREFIXES: tuple[tuple[str, str], ...] = (
    ("http://purl.org/dc/terms/", "dcterms"),
    ("http://www.w3.org/2002/07/owl#", "owl"),
    ("http://www.w3.org/2000/01/rdf-schema#", "rdfs"),
    ("http://www.w3.org/2004/02/skos/core#", "skos"),
    ("http://purl.org/vocab/vann/", "vann"),
    ("http://xmlns.com/foaf/0.1/", "foaf"),
    ("http://schema.org/", "schema"),
)


def suggest_label(predicate: str) -> str:
    """A friendly ``prefix:local`` label for *predicate*, or its local name."""
    for namespace, prefix in _KNOWN_PREFIXES:
        if predicate.startswith(namespace):
            return f"{prefix}:{predicate[len(namespace) :]}"
    return predicate.rsplit("/", 1)[-1].rsplit("#", 1)[-1] or predicate


class _MetaCheckbox(Checkbox):
    """A registered ontology-metadata predicate as a checkbox (ticked = offered in
    "Add metadata"). Carries its predicate URI + display label."""

    def __init__(self, predicate: str, label: str) -> None:
        self.label_text = label or suggest_label(predicate)
        super().__init__(self.label_text, value=True, classes="cfg-mp-box")
        self.predicate = predicate


class _SecretInput(Input):
    """An ``Input`` that masks its text, revealing it only while focused."""

    def on_focus(self) -> None:
        self.password = False

    def on_blur(self) -> None:
        self.password = True


class _ServerGroup(FocusGroup):
    """The local-server URL / port / bearer-token fields as one Tab stop."""

    exit_next = "#cfg-langs"
    exit_prev = "#cfg-theme"

    def _items(self) -> list:  # type: ignore[type-arg]
        return list(self.query(Input))


class _LangGroup(FocusGroup):
    """The configured-languages block: the checkboxes *and* the add field/+ button as
    one Tab stop. Space/enter toggles the current checkbox (the rest is inherited)."""

    exit_next = "#llm-mode-select"
    exit_prev = "#cfg-server"

    def _items(self) -> list:  # type: ignore[type-arg]
        # query (never query_one) so a not-yet-mounted child can't raise.
        return [*self.query(Checkbox), *self.query("#cfg-extra"), *self.query("#cfg-add")]

    def _focus_item(self, item) -> None:  # type: ignore[no-untyped-def]
        for box in self.query(Checkbox):
            box.set_class(box is item, "lang-current")
        # Checkbox → keep focus on the group (so space toggles); field/+ → focus it.
        self.focus() if isinstance(item, Checkbox) else item.focus()

    def _extra_key(self, event) -> bool:  # type: ignore[no-untyped-def]
        return event.key in ("space", "enter") and self._toggle_current()

    def _toggle_current(self) -> bool:
        item = self.current_item()
        if isinstance(item, Checkbox):
            item.value = not item.value
            return True
        return False

    def _clear(self) -> None:
        for box in self.query(Checkbox):
            box.remove_class("lang-current")


class _MetaGroup(FocusGroup):
    """The ontology-metadata checklist + add row as one Tab stop: the arrow keys
    rove the property checkboxes and the add fields, space toggles the current
    checkbox, and Tab/Shift+Tab return to the tab bar."""

    exit_next = "Tabs"
    exit_prev = "Tabs"

    def _items(self) -> list:  # type: ignore[type-arg]
        return [
            *self.query(_MetaCheckbox),
            *self.query("#cfg-mp-uri"),
            *self.query("#cfg-mp-label"),
            *self.query("#cfg-mp-add"),
        ]

    def _focus_item(self, item) -> None:  # type: ignore[no-untyped-def]
        for box in self.query(_MetaCheckbox):
            box.set_class(box is item, "mp-current")
        if isinstance(item, _MetaCheckbox):
            item.scroll_visible()  # keep the current property in view while roving
            self.focus()  # keep focus on the group so space toggles
        else:
            item.focus()  # the add field / + button

    def _move(self, delta: int) -> None:
        # Up from the top of the list returns to the tab headers instead of wrapping.
        if delta < 0 and (not self._active or self._cursor == 0):
            self._exit("Tabs")
            return
        super()._move(delta)

    def _extra_key(self, event) -> bool:  # type: ignore[no-untyped-def]
        return event.key in ("space", "enter") and self._toggle_current()

    def _toggle_current(self) -> bool:
        item = self.current_item()
        if isinstance(item, _MetaCheckbox):
            item.value = not item.value
            return True
        return False

    def _clear(self) -> None:
        for box in self.query(_MetaCheckbox):
            box.remove_class("mp-current")


class ConfigModal(ModalBase[None]):
    """Display language + theme + configured languages + an LLM entry (auto-saving)."""

    DEFAULT_CSS = """
    /* A fixed modal size so it doesn't resize when switching tabs. The tabs fill
       it; each pane scrolls if its content is taller than the box. */
    #cfg-box { width: 72%; height: 90%; }
    #cfg-box TabbedContent, #cfg-box ContentSwitcher { height: 1fr; }
    #cfg-box TabPane { height: 1fr; overflow-y: auto; }
    #cfg-box .cfg-mp-title { margin-bottom: 1; }   /* space below the section title */
    #cfg-box .cfg-label { color: $text-muted; }
    #cfg-box .cfg-hint { color: $text-muted; }
    /* Narrow dropdowns with clean rounded borders (override the dashed `tall`). */
    #cfg-theme { width: 24; margin-bottom: 1; }
    #cfg-display { width: 16; margin-bottom: 1; }
    #cfg-display > SelectCurrent, #cfg-theme > SelectCurrent { border: round $primary; }
    #cfg-display:focus > SelectCurrent, #cfg-theme:focus > SelectCurrent { border: round $primary; }
    #cfg-display SelectOverlay, #cfg-theme SelectOverlay { border: round $primary; }
    /* The configured-languages block: one titled box holding the checkbox group and
       the add-language row; its border lights up while focus is anywhere inside. */
    #cfg-langs {
        height: auto;
        border: round $foreground 40%;
        border-title-color: $foreground 70%;
        padding: 0 1;
        margin-bottom: 1;
    }
    #cfg-langs:focus-within { border: round $primary; border-title-color: $primary; }
    #cfg-boxes { layout: grid; grid-size: 4; grid-rows: auto; height: auto; }
    #cfg-boxes Checkbox { border: none; background: transparent; width: 100%; }
    #cfg-boxes Checkbox.lang-current { background: $secondary 30%; text-style: bold; }
    /* Add-language row (inside the block): a wide field + a tiny + button. */
    #cfg-add-row { height: auto; margin-top: 1; }
    #cfg-extra { width: 1fr; border: round $primary; }
    #cfg-add { width: auto; min-width: 5; margin-left: 1; }
    /* Ontology-metadata predicate catalog (Default properties tab): a checklist
       of predicates (ticked = offered in "Add metadata"), spaced for readability. */
    /* The group fills the pane; the list takes the full remaining height (the add
       row sits below it) and scrolls when there are more properties than fit. */
    #cfg-mp-group { height: 1fr; }
    #cfg-mprops { height: 1fr; }
    #cfg-mprops .cfg-mp-box { height: auto; margin-bottom: 1; border: none; background: transparent; }
    #cfg-mprops .cfg-mp-box.mp-current { background: $secondary 30%; text-style: bold; }
    #cfg-mp-add-row { height: auto; margin-top: 1; }
    #cfg-mp-uri { width: 2fr; border: round $primary; }
    #cfg-mp-label { width: 1fr; border: round $primary; margin-left: 1; }
    #cfg-mp-add { width: auto; min-width: 5; margin-left: 1; }
    /* Local server (ster serve) block: URL / port / bearer token, one Tab stop. */
    #cfg-server {
        height: auto;
        border: round $foreground 40%;
        border-title-color: $foreground 70%;
        padding: 0 1;
        margin-bottom: 1;
    }
    #cfg-server:focus-within { border: round $primary; border-title-color: $primary; }
    #cfg-server Input { border: round $primary; margin-bottom: 1; }
    #cfg-server-line { height: auto; }
    #cfg-server-url { width: 3fr; }      /* URL takes the lion's share */
    #cfg-server-port { width: 1fr; margin-left: 1; }
    #cfg-server-token { width: 1fr; }
    /* Inline LLM setup block (its own FocusGroup). */
    #cfg-llm {
        border: round $foreground 40%;
        border-title-color: $foreground 70%;
        padding: 0 1;
        margin-bottom: 1;
    }
    #cfg-llm:focus-within { border: round $primary; border-title-color: $primary; }
    """

    BINDINGS = [Binding("escape", "cancel", "Close")]

    class Changed(Message):
        """Posted whenever a setting changes (the modal auto-saves)."""

        def __init__(self, result: dict) -> None:
            super().__init__()
            self.result = result

    def __init__(
        self,
        display_lang: str,
        configured_langs: list[str],
        available_langs: list[str],
        themes: list[str] | None = None,
        current_theme: str = "ster",
        metadata_props: list[tuple[str, str]] | None = None,
    ) -> None:
        super().__init__()
        self._display = display_lang
        self._available = sorted({*available_langs, display_lang} - {""}) or [display_lang]
        self._themes = sorted({*(themes or []), current_theme} - {""}) or [current_theme]
        self._theme = current_theme
        self._configured = list(dict.fromkeys(configured_langs))
        self._metadata = list(metadata_props or [])  # ontology-metadata predicate catalog
        from ster.api_server import load_server_config, load_token

        self._server_url, self._server_port = load_server_config()
        self._server_token = load_token()
        self._ready = False  # suppress Changed until fully composed

    def compose(self) -> ComposeResult:
        with Vertical(id="cfg-box", classes="modal-box"):
            with TabbedContent():
                with TabPane("General", id="cfg-tab-general"):
                    yield from self._general_tab()
                with TabPane("Default properties", id="cfg-tab-props"):
                    yield from self._props_tab()
            yield Static(
                "arrows  move     esc  close     (changes save automatically)",
                classes="modal-footer",
            )

    def _general_tab(self) -> ComposeResult:
        yield Static("Display language", classes="cfg-label")
        yield Select(
            [(code, code) for code in self._available],
            value=self._display if self._display in self._available else self._available[0],
            allow_blank=False,
            id="cfg-display",
        )
        yield Static("Display theme", classes="cfg-label")
        yield Select(
            [(name, name) for name in self._themes],
            value=self._theme if self._theme in self._themes else self._themes[0],
            allow_blank=False,
            id="cfg-theme",
        )
        with _ServerGroup(id="cfg-server"):
            with Horizontal(id="cfg-server-line"):
                yield Input(
                    value=self._server_url,
                    placeholder="Server URL — http://127.0.0.1",
                    id="cfg-server-url",
                )
                yield Input(
                    value=str(self._server_port), placeholder="Port — 8765", id="cfg-server-port"
                )
            yield _SecretInput(
                value=self._server_token,
                password=True,
                placeholder="Bearer token (hidden — shown while editing)",
                id="cfg-server-token",
            )
        yield Static(
            "(configured languages — used to add labels & language-dependent properties)",
            classes="cfg-hint",
        )
        with _LangGroup(id="cfg-langs"):
            with Vertical(id="cfg-boxes"):
                for code in self._configured:
                    yield Checkbox(code, value=True, id=f"cfg-chk-{code}")
            with Horizontal(id="cfg-add-row"):
                yield Input(
                    placeholder="add languages, comma-separated — e.g. en, fr, es, de, zh, ar",
                    id="cfg-extra",
                )
                yield Button("+", id="cfg-add")
        yield Static("Configure LLM", classes="cfg-label")
        yield LlmSetup(id="cfg-llm")

    def _props_tab(self) -> ComposeResult:
        yield Static("Ontology metadata properties", classes="cfg-label cfg-mp-title")
        with _MetaGroup(id="cfg-mp-group"):
            with VerticalScroll(id="cfg-mprops"):
                for pred, label in self._metadata:
                    yield _MetaCheckbox(pred, label)
            with Horizontal(id="cfg-mp-add-row"):
                yield Input(placeholder="predicate URI — http://…", id="cfg-mp-uri")
                yield Input(placeholder="label (optional)", id="cfg-mp-label")
                yield Button("+", id="cfg-mp-add")

    _TAB_ORDER = ("cfg-tab-general", "cfg-tab-props")

    def on_mount(self) -> None:
        self.query_one("#cfg-box").border_title = "Configuration"
        self.query_one("#cfg-server").border_title = "Local server (ster serve)"
        self.query_one("#cfg-langs").border_title = "Configured languages"
        self.query_one("#cfg-llm").border_title = "LLM"
        # Land on the tab bar: space switches tabs, then Tab/arrows enter the items.
        self.query_one(Tabs).focus()
        self._ready = True

    def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        """On the tab bar: space cycles tabs, down enters the tab's items. Text
        inputs / language checkboxes consume these keys, so this only fires while
        focus is on the tab bar / chrome."""
        if event.key == "space" and isinstance(self.focused, Tabs):
            tabs = self.query_one(TabbedContent)
            if tabs.active in self._TAB_ORDER:
                nxt = self._TAB_ORDER[
                    (self._TAB_ORDER.index(tabs.active) + 1) % len(self._TAB_ORDER)
                ]
                tabs.active = nxt
                event.stop()
        elif event.key == "down" and isinstance(self.focused, Tabs):
            self.focus_next()  # tab bar → first item of the active tab
            event.stop()

    # ── current state + auto-save ───────────────────────────────────────────────

    def _result(self) -> dict:
        configured = [
            box.id.removeprefix("cfg-chk-")  # type: ignore[union-attr]
            for box in self.query("#cfg-boxes Checkbox").results(Checkbox)
            if box.value
        ]
        return {
            "display": str(self.query_one("#cfg-display", Select).value),
            "theme": str(self.query_one("#cfg-theme", Select).value),
            "configured": configured,
            "metadata_props": [
                (cb.predicate, cb.label_text)
                for cb in self.query(_MetaCheckbox)
                if cb.value  # ticked → offered in "Add metadata"
            ],
        }

    def _save(self) -> None:
        if self._ready:
            self.post_message(self.Changed(self._result()))

    @on(Select.Changed)
    def _on_select(self, event: Select.Changed) -> None:
        self._save()  # display or theme changed → apply live + persist

    @on(Checkbox.Changed)
    def _on_checkbox(self, event: Checkbox.Changed) -> None:
        self._save()

    @on(Input.Changed, "#cfg-server-url")
    @on(Input.Changed, "#cfg-server-port")
    @on(Input.Changed, "#cfg-server-token")
    def _on_server(self, event: Input.Changed) -> None:
        """Persist the local-server URL / port / bearer token (auto-save)."""
        if not self._ready:
            return
        from ster.api_server import save_server_config, save_token

        url = self.query_one("#cfg-server-url", Input).value.strip()
        port_raw = self.query_one("#cfg-server-port", Input).value.strip()
        if url and port_raw.isdigit():
            save_server_config(url, int(port_raw))
        token = self.query_one("#cfg-server-token", Input).value.strip()
        if token:
            save_token(token)

    @on(Button.Pressed, "#cfg-add")
    async def _on_add(self, event: Button.Pressed) -> None:
        await self._add_typed_languages()

    @on(Input.Submitted, "#cfg-extra")
    async def _on_extra_submit(self, event: Input.Submitted) -> None:
        await self._add_typed_languages()

    async def _add_typed_languages(self) -> None:
        field = self.query_one("#cfg-extra", Input)
        codes = [code.strip() for code in field.value.split(",") if code.strip()]
        container = self.query_one("#cfg-boxes")
        for code in codes:
            if not self.query(f"#cfg-chk-{code}"):
                await container.mount(Checkbox(code, value=True, id=f"cfg-chk-{code}"))
        field.value = ""
        self._save()

    # ── ontology-metadata properties ────────────────────────────────────────────
    @on(Button.Pressed, "#cfg-mp-add")
    async def _on_add_prop(self, event: Button.Pressed) -> None:
        await self._add_metadata_prop()

    @on(Input.Submitted, "#cfg-mp-uri")
    @on(Input.Submitted, "#cfg-mp-label")
    async def _on_prop_submit(self, event: Input.Submitted) -> None:
        await self._add_metadata_prop()

    async def _add_metadata_prop(self) -> None:
        uri = self.query_one("#cfg-mp-uri", Input).value.strip()
        label = self.query_one("#cfg-mp-label", Input).value.strip()
        present = {cb.predicate for cb in self.query(_MetaCheckbox)}
        if not uri or uri in present:
            return
        await self.query_one("#cfg-mprops").mount(_MetaCheckbox(uri, label))
        self.query_one("#cfg-mp-uri", Input).value = ""
        self.query_one("#cfg-mp-label", Input).value = ""
        self._save()  # toggling an existing checkbox is handled by _on_checkbox

    def action_cancel(self) -> None:
        self.dismiss(None)
