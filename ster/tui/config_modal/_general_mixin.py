"""``ConfigModal`` mixin: the General tab (display language, theme, local-server
fields, configured languages) and its auto-save handlers.

Handlers use Textual's naming-convention dispatch (``on_input_changed``, …)
rather than the ``@on(...)`` decorator: the decorator only registers a handler
via a metaclass hook that runs when *this* class is defined, and a plain mixin
(not itself a ``Widget``/``MessagePump`` subclass) never goes through that
metaclass — see ``ster.tui.app``'s mixins, which use the same convention for
the same reason. Each handler filters by widget id/class itself, and several
mixins may each define an ``on_x_changed`` of their own — Textual dispatches
every matching handler found anywhere in the MRO, not just the first.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Select, Static

from ster.tui.check import Check

from ._general_widgets import _LangGroup, _SecretInput, _ServerGroup
from ._state import _ModalState

_SERVER_INPUT_IDS = {"cfg-server-url", "cfg-server-port", "cfg-server-token"}


class _GeneralMixin(_ModalState):
    """General tab: display language/theme, the local-server block, and the
    configured-languages block."""

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
                    placeholder="Server URL — http://127.0.0.1",  # NOSONAR - local-only address, not a network destination
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
                    yield Check(code, value=True, id=f"cfg-chk-{code}")
            with Horizontal(id="cfg-add-row"):
                yield Input(
                    placeholder="add languages, comma-separated — e.g. en, fr, es, de, zh, ar",
                    id="cfg-extra",
                )
                yield Button("+", id="cfg-add")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Persist the local-server URL / port / bearer token (auto-save)."""
        if event.input.id not in _SERVER_INPUT_IDS or not self._ready:
            return
        from ster.api_server import save_server_config, save_token

        url = self.query_one("#cfg-server-url", Input).value.strip()
        port_raw = self.query_one("#cfg-server-port", Input).value.strip()
        if url and port_raw.isdigit():
            save_server_config(url, int(port_raw))
        token = self.query_one("#cfg-server-token", Input).value.strip()
        if token:
            save_token(token)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cfg-add":
            await self._add_typed_languages()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "cfg-extra":
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
